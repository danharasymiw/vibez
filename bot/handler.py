import asyncio
import random
import re
import time
from datetime import datetime, timezone

import discord

from bot import config
from bot import db
from bot import plan_manager
from bot import railway
from bot.claude_runner import run_claude
from bot.formatting import format_error, format_result, truncate
from bot.git_ops import commit_and_push
from bot.task_queue import TaskQueue

queue = TaskQueue()

# Maps Discord thread ID -> Claude session ID for conversation continuity
thread_sessions: dict[int, str] = {}

# Prompt IDs that have been cancelled and should be skipped when they reach the front of the queue
_cancelled_ids: set[int] = set()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

_ready_at: datetime | None = None


@client.event
async def on_ready():
    global _ready_at
    _ready_at = datetime.now(timezone.utc)
    print(f"Logged in as {client.user}", flush=True)
    asyncio.create_task(_replay_pending_prompts())


async def _replay_pending_prompts():
    """On startup, re-queue any prompts that were pending or mid-processing when the bot last died."""
    pending = await db.get_pending_prompts()
    if not pending:
        return
    print(f"[startup] Replaying {len(pending)} pending prompt(s)", flush=True)
    for row in pending:
        try:
            channel = client.get_channel(int(row["channel_id"])) or await client.fetch_channel(int(row["channel_id"]))
            message = await channel.fetch_message(int(row["discord_message_id"]))

            # Reuse existing thread if one was already created, otherwise create a new one
            thread: discord.Thread
            if row["thread_id"]:
                thread = client.get_channel(int(row["thread_id"])) or await client.fetch_channel(int(row["thread_id"]))
            elif isinstance(message.channel, discord.Thread):
                thread = message.channel
            else:
                thread_name = row["instruction"][:97] + "..." if len(row["instruction"]) > 100 else row["instruction"]
                thread = await message.create_thread(name=thread_name)
                await db.set_thread_id(row["id"], str(thread.id))

            await thread.send("Resuming after restart...")
            await _run_prompt(message, thread, row["instruction"], row["is_bot_fix"], row["id"])
        except Exception as e:
            print(f"[startup] Failed to replay prompt id={row['id']}: {e}", flush=True)
            await db.mark_failed(row["id"], str(e))


async def handle_logs(thread: discord.Thread):
    """Fetch and display Railway logs."""
    if not railway.is_configured():
        await thread.send("Railway is not configured — set RAILWAY_API_TOKEN, RAILWAY_SERVICE_ID, and RAILWAY_ENVIRONMENT_ID.")
        return

    try:
        deployment = await railway.get_latest_deployment()
        if not deployment:
            await thread.send("No deployments found.")
            return

        logs = await railway.get_all_logs(deployment["id"])
        status = deployment["status"]
        await thread.send(
            f"**Deploy status:** {status}\n```\n{truncate(logs, 1800)}\n```"
        )
    except Exception as e:
        await thread.send(format_error(str(e)))


async def deploy_and_fix_loop(thread: discord.Thread, instruction: str, author_name: str, previous_deploy_id: str | None = None):
    """After pushing, wait for deploy. If it fails, feed logs to Claude and retry."""
    if not railway.is_configured():
        return

    for attempt in range(config.MAX_FIX_ATTEMPTS):
        deploy_status, deployment_id = await railway.wait_for_deployment(previous_deploy_id)

        if deploy_status in ("SUCCESS", "READY"):
            await thread.send("**Deploy: successful** 🚀")
            return

        if not deployment_id:
            await thread.send("**Deploy:** timed out waiting for status")
            return

        # Deploy failed — fetch logs and try to fix
        logs = await railway.get_all_logs(deployment_id)
        remaining = config.MAX_FIX_ATTEMPTS - attempt - 1

        await thread.send(
            f"**Deploy failed.** Attempting auto-fix ({remaining} attempts left)...\n```\n{truncate(logs, 800)}\n```"
        )

        fix_instruction = (
            f"The deployment failed. Here are the logs:\n\n{logs}\n\n"
            f"The original request was: {instruction}\n\n"
            f"Fix whatever is causing the deployment to fail."
        )

        result = await run_claude(fix_instruction)

        if not result.success:
            await thread.send(f"Claude failed to fix: {truncate(result.result, 500)}")
            return

        git_result = await commit_and_push(
            f"vibez: auto-fix deploy failure (attempt {attempt + 1})\n\nRequested by: {author_name}"
        )

        if not git_result.pushed:
            await thread.send("Fix committed but push failed.")
            return

        previous_deploy_id = deployment_id
        await thread.send(f"Fix pushed — waiting for deploy again...")

    await thread.send(f"**Deploy:** still failing after {config.MAX_FIX_ATTEMPTS} fix attempts. 😵")


async def _run_prompt(
    message: discord.Message,
    thread: discord.Thread,
    instruction: str,
    is_bot_fix: bool,
    prompt_id: int | None,
    model: str | None = None,
):
    """Queue and execute a prompt, tracking status in the DB."""
    target_dir = config.BOT_DIR if is_bot_fix else config.PROJECT_DIR

    if queue.pending >= config.MAX_QUEUE_SIZE:
        await thread.send("Queue is full — try again in a bit.")
        if prompt_id is not None:
            await db.mark_failed(prompt_id, "queue full")
        return

    position = queue.pending
    if position > 0:
        await thread.send(f"Queued — #{position + 1} in line.")

    async def process():
        if prompt_id is not None and prompt_id in _cancelled_ids:
            _cancelled_ids.discard(prompt_id)
            await thread.send("Cancelled.")
            return

        if prompt_id is not None:
            await db.mark_processing(prompt_id)

        cooking = random.choice(["🍳", "🔥", "🧑‍🍳", "⚡", "🧪", "🪄", "🤖", "💅", "🫡"])
        await message.add_reaction(cooking)
        label = "bot" if is_bot_fix else "project"
        await thread.send(f"On it... (targeting {label})")

        progress_msg = None
        last_tool = "Thinking..."
        start_time = time.time()

        async def update_progress_msg(text: str):
            nonlocal progress_msg
            try:
                if progress_msg:
                    await progress_msg.edit(content=text)
                else:
                    progress_msg = await thread.send(text)
            except Exception:
                pass

        async def on_progress(text: str):
            nonlocal last_tool
            last_tool = text

        # Heartbeat task that updates Discord every 10 seconds
        heartbeat_running = True

        async def heartbeat():
            while heartbeat_running:
                await asyncio.sleep(10)
                if not heartbeat_running:
                    break
                elapsed = int(time.time() - start_time)
                await update_progress_msg(f"{last_tool} ({elapsed}s)")

        heartbeat_task = asyncio.create_task(heartbeat())

        print(f"[claude] starting for thread {thread.id} target={label}", flush=True)
        session_id = thread_sessions.get(thread.id)
        try:
            result = await run_claude(instruction, on_progress, session_id=session_id, cwd=target_dir, model=model)
        finally:
            heartbeat_running = False
            heartbeat_task.cancel()
        print(f"[claude] finished success={result.success} cost=${result.cost_usd:.4f} duration={result.duration_ms:.0f}ms session={result.session_id}", flush=True)

        if result.session_id and result.success:
            thread_sessions[thread.id] = result.session_id

        if not result.success:
            await message.add_reaction("💀")
            await thread.send(format_result(
                success=False,
                summary=result.result,
                files_changed=[],
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                commit_hash="",
                pushed=False,
            ))
            if prompt_id is not None:
                await db.mark_done(prompt_id)
            return

        # Snapshot current deployment before push so we can detect the new one
        pre_push_deploy = None
        if railway.is_configured() and not is_bot_fix:
            try:
                d = await railway.get_latest_deployment()
                pre_push_deploy = d["id"] if d else None
            except Exception:
                pass

        print(f"[git] committing...", flush=True)
        git_result = await commit_and_push(
            f"vibez: {instruction[:72]}\n\nRequested by: {message.author.display_name}",
            cwd=target_dir,
        )
        print(f"[git] committed={git_result.committed} pushed={git_result.pushed} hash={git_result.commit_hash}", flush=True)

        if not git_result.committed:
            await message.add_reaction("🤷")
            await thread.send(f"**No changes** — Claude finished but didn't modify any files.\n\n{truncate(result.result, 1500)}")
            if prompt_id is not None:
                await db.mark_done(prompt_id)
            return

        await message.add_reaction("✅")
        await thread.send(
            format_result(
                success=result.success,
                summary=result.result,
                files_changed=git_result.files_changed,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                commit_hash=git_result.commit_hash,
                pushed=git_result.pushed,
            )
        )

        if prompt_id is not None:
            await db.mark_done(prompt_id)

        if git_result.pushed:
            await thread.send("Pushed — waiting for deploy...")
            if is_bot_fix:
                await thread.send("Bot will redeploy automatically. I might go offline briefly. 👋")
            else:
                await deploy_and_fix_loop(thread, instruction, message.author.display_name, pre_push_deploy)
        elif git_result.committed:
            await thread.send("Committed but push failed — deploy won't trigger.")

    try:
        await queue.run(process)
    except Exception as e:
        print(f"[error] {e}", flush=True)
        if prompt_id is not None:
            await db.mark_failed(prompt_id, str(e))
        try:
            await message.add_reaction("💥")
            await thread.send(format_error(str(e)))
        except Exception:
            pass


async def handle_plan_command(message: discord.Message, thread: discord.Thread, instruction: str):
    """Handle all 'plan bot:' sub-commands."""
    # Strip the prefix  ("plan bot" or "plan bot:")
    body = instruction[len("plan bot"):].lstrip(":").strip()

    # list
    if body.lower() == "list":
        sprints = await db.get_sprints()
        await thread.send(plan_manager.format_sprint_list(sprints))
        return

    # show <id>
    if body.lower().startswith("show "):
        try:
            sprint_id = int(body.split()[1])
        except (IndexError, ValueError):
            await thread.send("Usage: `plan bot: show <sprint_id>`")
            return
        sprint = await db.get_sprint(sprint_id)
        if not sprint:
            await thread.send(f"Sprint #{sprint_id} not found.")
            return
        tasks = await db.get_tasks(sprint_id)
        await thread.send(plan_manager.format_sprint(sprint, tasks))
        return

    # done task <id>
    if body.lower().startswith("done task "):
        try:
            task_id = int(body.split()[2])
        except (IndexError, ValueError):
            await thread.send("Usage: `plan bot: done task <task_id>`")
            return
        ok = await db.mark_task_done(task_id)
        await thread.send(f"Task #{task_id} marked done." if ok else f"Task #{task_id} not found.")
        return

    # done sprint <id>
    if body.lower().startswith("done sprint "):
        try:
            sprint_id = int(body.split()[2])
        except (IndexError, ValueError):
            await thread.send("Usage: `plan bot: done sprint <sprint_id>`")
            return
        ok = await db.mark_sprint_done(sprint_id)
        await thread.send(f"Sprint #{sprint_id} marked completed." if ok else f"Sprint #{sprint_id} not found.")
        return

    # No sub-command — treat body as a high-level task to decompose
    if not body:
        await thread.send(
            "Give me a task to break down!\n"
            "Usage: `plan bot: <high-level task>`\n\n"
            "Other commands:\n"
            "• `plan bot: list` — list all sprints\n"
            "• `plan bot: show <id>` — show sprint tasks\n"
            "• `plan bot: done task <id>` — mark a task done\n"
            "• `plan bot: done sprint <id>` — mark a sprint completed"
        )
        return

    await thread.send("Breaking it down into a sprint...")
    try:
        sprint_id, plan = await plan_manager.create_sprint_from_task(body)
    except RuntimeError as e:
        await thread.send(f"Error: {e}")
        return
    except Exception as e:
        await thread.send(f"Failed to decompose task: {e}")
        return

    if sprint_id is None:
        await thread.send("Database is not available — cannot persist sprint.")
        return

    sprint = await db.get_sprint(sprint_id)
    tasks = await db.get_tasks(sprint_id)
    await thread.send(plan_manager.format_sprint(sprint, tasks))


@client.event
async def on_message(message: discord.Message):
    print(f"[msg] author={message.author} bot={message.author.bot} channel={message.channel} type={message.channel.type}", flush=True)

    if message.author.bot:
        print(f"[skip] bot message", flush=True)
        return
    if _ready_at and message.created_at < _ready_at:
        print(f"[skip] old message from before ready", flush=True)
        return
    if not client.user or client.user not in message.mentions:
        print(f"[skip] not mentioned (mentions={[u.name for u in message.mentions]})", flush=True)
        return

    # If the message is in a thread, use that thread. Otherwise create one.
    is_thread = isinstance(message.channel, discord.Thread)

    if not is_thread:
        if config.CHANNEL_IDS and str(message.channel.id) not in config.CHANNEL_IDS:
            print(f"[skip] channel {message.channel.id} not in allowed list {config.CHANNEL_IDS}", flush=True)
            return

    instruction = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()

    # Parse optional --model <name> flag
    model: str | None = None
    model_match = re.search(r"--model\s+(\S+)", instruction, re.IGNORECASE)
    if model_match:
        model = model_match.group(1)
        instruction = (instruction[: model_match.start()] + instruction[model_match.end() :]).strip()

    print(f"[instruction] '{instruction}' model={model or 'default'} from {message.author} in {'thread' if is_thread else 'channel'}", flush=True)

    await message.add_reaction("👀")

    if not instruction:
        await message.add_reaction("❓")
        await message.reply("Give me something to work with! Mention me with coding instructions.")
        return

    # Clear queue command
    if instruction.lower() == "clear":
        count = await db.clear_queue()
        await message.reply(f"Cleared {count} pending prompt(s) from the queue.")
        return

    # Cancel last queued request
    if instruction.lower() == "cancel":
        cancelled = await db.cancel_last_pending()
        if cancelled:
            _cancelled_ids.add(cancelled["id"])
            short = cancelled["instruction"][:80]
            await message.reply(f"Cancelled: *{short}*")
        else:
            await message.reply("Nothing pending to cancel.")
        return

    if is_thread:
        thread = message.channel
    else:
        thread_name = instruction[:97] + "..." if len(instruction) > 100 else instruction
        thread = await message.create_thread(name=thread_name)

    # Manual log check
    if instruction.lower() in ("logs", "check logs", "show logs", "get logs"):
        await handle_logs(thread)
        return

    # Detect "plan bot" prefix
    if instruction.lower().startswith("plan bot"):
        await handle_plan_command(message, thread, instruction)
        return

    # Detect "fix bot" prefix
    is_bot_fix = False
    if instruction.lower().startswith("fix bot"):
        if not config.BOT_REPO_URL:
            await thread.send("BOT_REPO_URL is not configured.")
            return
        is_bot_fix = True
        instruction = instruction[7:].lstrip(":").strip()
        if not instruction:
            await thread.send("What should I fix? e.g. `fix bot: the heartbeat isn't updating`")
            return

    # Persist to DB queue
    prompt_id = await db.add_prompt(
        str(message.id),
        str(message.channel.id),
        message.author.display_name,
        instruction,
        is_bot_fix,
    )
    if prompt_id is not None:
        await db.set_thread_id(prompt_id, str(thread.id))

    await _run_prompt(message, thread, instruction, is_bot_fix, prompt_id, model)
