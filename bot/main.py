print("bot starting", flush=True)

import asyncio

try:
    from bot.auth import inject_claude_credentials
    from bot.config import DISCORD_TOKEN, GIT_REPO_URL
    from bot.db import init_db
    from bot.git_ops import init_repo
    from bot.handler import client
    print("imports ok", flush=True)
except Exception as e:
    print(f"import failed: {e}", flush=True)
    raise


async def start():
    inject_claude_credentials()
    print(f"Git repo: {GIT_REPO_URL}", flush=True)
    await init_repo()
    print("Repo ready", flush=True)
    await init_db()
    await client.start(DISCORD_TOKEN)


asyncio.run(start())
