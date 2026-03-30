# Vibez

A Discord bot that lets your friend group vibe-code a project together. Mention the bot with instructions and Claude Code will implement them, commit, and push.

## How It Works

1. Someone @mentions the bot in Discord with coding instructions
2. The bot queues the request and invokes Claude Code
3. Claude Code reads the project, makes changes, and finishes
4. The bot commits and pushes the changes
5. CI/CD deploys automatically

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to Bot settings
4. Enable **Message Content Intent** under Privileged Gateway Intents
5. Copy the bot token
6. Invite the bot to your server with the OAuth2 URL Generator (scopes: `bot`, permissions: `Send Messages`, `Read Message History`)

### 2. Set Up Your Target Project

Copy the `starter/` directory to a new repo — it's a Python Flask hello world ready for Railway:

```bash
cp -r starter/ /path/to/your-project/
cd /path/to/your-project
git init && git add -A && git commit -m "init"
git remote add origin <your-repo-url>
git push -u origin master
```

Deploy it to Railway and add a PostgreSQL database.

### 3. Configure the Bot

```bash
cp .env.example .env
```

Fill in your `.env` — see [Configuration](#configuration) below for all options.

### 4. Install and Run

```bash
pip install -r requirements.txt
python -m bot.main
```

Requires [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to be installed and available on `PATH`.

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | Yes | | Discord bot token |
| `ANTHROPIC_API_KEY` | Yes | | Anthropic API key for Claude Code |
| `PROJECT_DIR` | Yes | | Absolute path to the target project repo |
| `GIT_BRANCH` | No | `main` | Branch to commit and push to |
| `DISCORD_CHANNEL_IDS` | No | | Comma-separated channel IDs to restrict the bot to |
| `DATABASE_URL` | No | | PostgreSQL connection string (passed through to Claude Code) |
| `MAX_BUDGET_PER_REQUEST` | No | `5` | Max USD per Claude invocation |
| `MAX_QUEUE_SIZE` | No | `10` | Max queued requests |
| `CLAUDE_TIMEOUT_MS` | No | `600000` | Timeout per request in ms (default 10 min) |

### Git Setup

The target project (`PROJECT_DIR`) must be a git repo with a remote named `origin`. Make sure git credentials are configured for pushing (SSH key or credential helper).

```bash
# Configure git identity for commits in the target repo
cd /path/to/your-project
git config user.name "Vibez Bot"
git config user.email "vibez@bot"
```

## Starter Template

The `starter/` directory contains a minimal Python Flask app with:

- `app.py` — hello world Flask app
- `requirements.txt` — Python dependencies (Flask, gunicorn, psycopg2)
- `railway.toml` — Railway deployment config
- `CLAUDE.md` — context for Claude Code when vibe coding
