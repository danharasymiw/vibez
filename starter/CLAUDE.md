# Vibez Project

This is a collaborative vibe-coded project. A Discord bot takes instructions from users and passes them to you (Claude Code) to implement.

## Environment
- Runtime: Python
- Database: PostgreSQL (connection string in `DATABASE_URL` env var)
- Hosted on Railway.app — auto-deploys on push to main

## Rules
1. Keep things simple and fun. Working code > perfect code.
2. Add new dependencies to `requirements.txt`.
3. Use `DATABASE_URL` for any database connections.
4. Do NOT run git commands — the bot handles that.
5. Use gunicorn for production. The app entry point is `app:app` in `app.py`.
