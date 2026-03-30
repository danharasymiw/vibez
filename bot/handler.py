import re
import time

import discord

from bot import config
from bot import railway
from bot.claude_runner import run_claude
from bot.formatting import format_error, format_result, truncate
from bot.git_ops import commit_and_push
from bot.task_queue import TaskQueue

queue = TaskQueue()

# Maps Discord thread ID -> Claude session ID for conversation continuity
thread_sessions: dict[int, str] = {}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}", flush=True)


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


async def deploy_and_fix_loop(thread: discord.Thread, instruction: str, author_name: str):
    """After pushing, wait for deploy. If it fails, feed logs to Claude and retry."""
    if not railway.is_configured():
        return

    for attempt in range(config.MAX_FIX_ATTEMPTS):
        await thread.send("Waiting for deploy...")

        deploy_status, deployment_id = await railway.wait_for_deployment()

        if deploy_status in ("SUCCESS", "READY"):
            await thread.send("**Deploy:** successful")
            return

        if not deployment_id:
            await thread.send("**Deploy:** timed out waiting")
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

    await thread.send(f"**Deploy:** still failing after {config.MAX_FIX_ATTEMPTS} fix attempts.")


@client.event
async def on_message(message: discord.Message):
    print(f"[msg] author={message.author} bot={message.author.bot} channel={message.channel} type={message.channel.type}", flush=True)

    if message.author.bot:
        print(f"[skip] bot message", flush=True)
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
    print(f"[instruction] '{instruction}' from {message.author} in {'thread' if is_thread else 'channel'}", flush=True)

    if not instruction:
        await message.reply("Give me something to work with! Mention me with coding instructions.")
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

    if queue.pending >= config.MAX_QUEUE_SIZE:
        await thread.send("Queue is full — try again in a bit.")
        return

    position = queue.pending
    if position > 0:
        await thread.send(f"Queued — #{position + 1} in line.")

    async def process():
        await thread.send("On it...")

        last_update = 0.0
        progress_msg = None

        async def on_progress(text: str):
            nonlocal last_update, progress_msg
            now = time.time()
            if now - last_update > 5:
                last_update = now
                try:
                    if progress_msg:
                        await progress_msg.edit(content=text)
                    else:
                        progress_msg = await thread.send(text)
                except Exception:
                    pass

        print(f"[claude] starting for thread {thread.id}", flush=True)
        session_id = thread_sessions.get(thread.id)
        result = await run_claude(instruction, on_progress, session_id=session_id)
        print(f"[claude] finished success={result.success} cost=${result.cost_usd:.4f} duration={result.duration_ms:.0f}ms session={result.session_id}", flush=True)

        if result.session_id:
            thread_sessions[thread.id] = result.session_id

        if not result.success:
            await thread.send(format_result(
                success=False,
                summary=result.result,
                files_changed=[],
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                commit_hash="",
                pushed=False,
            ))
            return

        print(f"[git] committing...", flush=True)
        git_result = await commit_and_push(
            f"vibez: {instruction[:72]}\n\nRequested by: {message.author.display_name}"
        )
        print(f"[git] committed={git_result.committed} pushed={git_result.pushed} hash={git_result.commit_hash}", flush=True)

        if not git_result.committed:
            await thread.send(f"**No changes** — Claude finished but didn't modify any files.\n\n{truncate(result.result, 1500)}")
            return

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

        # Auto-fix loop if Railway is configured and we pushed
        if git_result.pushed:
            await deploy_and_fix_loop(thread, instruction, message.author.display_name)

    try:
        await queue.run(process)
    except Exception as e:
        print(f"[error] {e}", flush=True)
        try:
            await thread.send(format_error(str(e)))
        except Exception:
            pass
