import asyncio

from bot.auth import inject_claude_credentials
from bot.config import DISCORD_TOKEN, GIT_REPO_URL
from bot.git_ops import init_repo
from bot.handler import client


async def start():
    inject_claude_credentials()
    print(f"Git repo: {GIT_REPO_URL}")
    await init_repo()
    print("Repo ready")
    await client.start(DISCORD_TOKEN)


asyncio.run(start())
