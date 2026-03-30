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

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


async def handle_logs(message: discord.Message):
    """Fetch and display Railway logs."""
    if not railway.is_configured():
        await message.reply("Railway is not configured — set RAILWAY_API_TOKEN, RAILWAY_SERVICE_ID, and RAILWAY_ENVIRONMENT_ID.")
        return

    status_msg = await message.reply("Fetching logs...")

    try:
        deployment = await railway.get_latest_deployment()
        if not deployment:
            await status_msg.edit(content="No deployments found.")
            return

        logs = await railway.get_all_logs(deployment["id"])
        status = deployment["status"]
        await status_msg.edit(
            content=f"**Deploy status:** {status}\n```\n{truncate(logs, 1800)}\n```"
        )
    except Exception as e:
        await status_msg.edit(content=format_error(str(e)))


async def deploy_and_fix_loop(status_msg: discord.Message, instruction: str, author_name: str):
    """After pushing, wait for deploy. If it fails, feed logs to Claude and retry."""
    if not railway.is_configured():
        return

    for attempt in range(config.MAX_FIX_ATTEMPTS):
        await status_msg.edit(content="Waiting for deploy...")

        deploy_status, deployment_id = await railway.wait_for_deployment()

        if deploy_status in ("SUCCESS", "READY"):
            await status_msg.edit(content=f"{status_msg.content}\n\n**Deploy:** successful")
            return

        if not deployment_id:
            await status_msg.edit(content=f"{status_msg.content}\n\n**Deploy:** timed out waiting")
            return

        # Deploy failed — fetch logs and try to fix
        logs = await railway.get_all_logs(deployment_id)
        remaining = config.MAX_FIX_ATTEMPTS - attempt - 1

        await status_msg.edit(
            content=f"**Deploy failed.** Attempting auto-fix ({remaining} attempts left)...\n```\n{truncate(logs, 800)}\n```"
        )

        fix_instruction = (
            f"The deployment failed. Here are the logs:\n\n{logs}\n\n"
            f"The original request was: {instruction}\n\n"
            f"Fix whatever is causing the deployment to fail."
        )

        result = await run_claude(fix_instruction)

        if not result.success:
            await status_msg.edit(content=f"{status_msg.content}\n\nClaude failed to fix: {truncate(result.result, 500)}")
            return

        git_result = await commit_and_push(
            f"vibez: auto-fix deploy failure (attempt {attempt + 1})\n\nRequested by: {author_name}"
        )

        if not git_result.pushed:
            await status_msg.edit(content=f"{status_msg.content}\n\nFix committed but push failed.")
            return

    await status_msg.edit(content=f"{status_msg.content}\n\n**Deploy:** still failing after {config.MAX_FIX_ATTEMPTS} fix attempts.")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not client.user or client.user not in message.mentions:
        return
    if config.CHANNEL_IDS and str(message.channel.id) not in config.CHANNEL_IDS:
        return

    instruction = re.sub(rf"<@!?{client.user.id}>", "", message.content).strip()

    if not instruction:
        await message.reply("Give me something to work with! Mention me with coding instructions.")
        return

    # Manual log check
    if instruction.lower() in ("logs", "check logs", "show logs", "get logs"):
        await handle_logs(message)
        return

    if queue.pending >= config.MAX_QUEUE_SIZE:
        await message.reply("Queue is full — try again in a bit.")
        return

    position = queue.pending
    status_msg = await message.reply(
        f"Queued — #{position + 1} in line." if position > 0 else "On it..."
    )

    async def process():
        if position > 0:
            try:
                await status_msg.edit(content="On it...")
            except Exception:
                pass

        last_update = 0.0

        async def on_progress(text: str):
            nonlocal last_update
            now = time.time()
            if now - last_update > 5:
                last_update = now
                try:
                    await status_msg.edit(content=text)
                except Exception:
                    pass

        result = await run_claude(instruction, on_progress)

        git_result = await commit_and_push(
            f"vibez: {instruction[:72]}\n\nRequested by: {message.author.display_name}"
        )

        await status_msg.edit(
            content=format_result(
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
            await deploy_and_fix_loop(status_msg, instruction, message.author.display_name)

    try:
        await queue.run(process)
    except Exception as e:
        try:
            await status_msg.edit(content=format_error(str(e)))
        except Exception:
            pass
