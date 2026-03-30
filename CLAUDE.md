# Vibez Bot

A Discord bot for collaborative vibe coding with Claude Code.

## Stack
- Python 3.11+, discord.py
- Run with `python -m bot.main`

## Development
- `pip install -r requirements.txt`
- `python -m bot.main`

## Architecture
- `bot/main.py` — entry point
- `bot/config.py` — environment variable loading
- `bot/handler.py` — Discord message handling and orchestration
- `bot/task_queue.py` — sequential request processing (asyncio lock)
- `bot/claude_runner.py` — Claude Code CLI invocation
- `bot/git_ops.py` — git commit and push
- `bot/formatting.py` — Discord message formatting
