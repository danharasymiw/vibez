# Vibez

A Discord bot that lets your friend group vibe-code a project together. Mention the bot with instructions and Claude Code will implement them, commit, and push.

## How It Works

1. Someone @mentions the bot in Discord with coding instructions
2. The bot queues the request and invokes Claude Code
3. Claude Code reads the project, makes changes, and finishes
4. The bot commits and pushes the changes
5. CI/CD deploys automatically

## Prerequisites

- Python 3.11+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed and authenticated (`claude` on PATH)
- A Discord bot token
- A GitHub personal access token with repo push access
- A target project repo (or use the included `starter/` template)

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and go to **Bot** settings
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Copy the bot token
5. Go to **OAuth2 > URL Generator**, select scopes: `bot`, permissions: `Send Messages`, `Read Message History`
6. Open the generated URL to invite the bot to your server

### 2. Create a GitHub Personal Access Token

1. Go to GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens
2. Create a token with **Contents** read/write access to your target project repo
3. Save the token for step 4

### 3. Set Up Your Target Project

Create a new repo for the project your friends will vibe-code. You can use the included starter template:

```bash
# Create a new repo on GitHub, then:
git clone https://github.com/you/your-project.git
cp -r starter/* your-project/
cd your-project
git add -A && git commit -m "init" && git push
```

The starter is a Python Flask hello world with Railway deployment config. Or use any existing repo — the bot will work with whatever's there.

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```bash
DISCORD_TOKEN=your-discord-bot-token
GIT_REPO_URL=https://github.com/you/your-project.git
GIT_TOKEN=your-github-personal-access-token
```

### 5. Install and Run

```bash
pip install -r requirements.txt
python -m bot.main
```

On startup the bot will clone the target repo into `./project/` and start listening for @mentions.

### 6. Use It

In Discord:
```
@VibezBot add a /health endpoint that returns JSON with status ok
@VibezBot check logs
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | Yes | | Discord bot token |
| `GIT_REPO_URL` | Yes | | HTTPS clone URL for the target project |
| `GIT_TOKEN` | Yes | | GitHub personal access token (push access) |
| `ANTHROPIC_API_KEY` | No | | Anthropic API key — if unset, uses Claude CLI's own auth |
| `GIT_BRANCH` | No | `master` | Branch to commit and push to |
| `GIT_USER_NAME` | No | `Vibez Bot` | Git commit author name |
| `GIT_USER_EMAIL` | No | `vibez@bot` | Git commit author email |
| `DISCORD_CHANNEL_IDS` | No | | Comma-separated channel IDs to restrict the bot to |
| `MAX_BUDGET_PER_REQUEST` | No | `5` | Max USD per Claude invocation |
| `MAX_QUEUE_SIZE` | No | `10` | Max queued requests |
| `CLAUDE_TIMEOUT_MS` | No | `600000` | Timeout per request in ms (10 min) |
| `RAILWAY_API_TOKEN` | No | | Railway API token — enables deploy checking |
| `RAILWAY_SERVICE_ID` | No | | Railway service ID |
| `RAILWAY_ENVIRONMENT_ID` | No | | Railway environment ID |
| `MAX_FIX_ATTEMPTS` | No | `3` | Auto-fix attempts on deploy failure |

## Railway Integration (Optional)

If you set the Railway env vars, the bot will:
- Wait for each deploy after pushing
- If a deploy fails, fetch the logs and feed them back to Claude to auto-fix
- Retry up to `MAX_FIX_ATTEMPTS` times

You can also manually check logs anytime: `@VibezBot check logs`

## Starter Template

The `starter/` directory contains a ready-to-deploy Python Flask app:

- `app.py` — hello world Flask app
- `requirements.txt` — Flask, gunicorn, psycopg2
- `railway.toml` — Railway deployment config
- `CLAUDE.md` — context for Claude Code when vibe coding
