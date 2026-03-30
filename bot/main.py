import asyncio

from bot.config import DISCORD_TOKEN, GIT_REPO_URL
from bot.git_ops import init_repo
from bot.handler import client


async def start():
    print(f"Git repo: {GIT_REPO_URL}")
    await init_repo()
    print("Repo ready")
    await client.start(DISCORD_TOKEN)


asyncio.run(start())
