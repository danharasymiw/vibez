# Vibez

A Discord bot that lets your friend group vibe-code a project together. Mention the bot with instructions and Claude Code will implement them, commit, and push.

## How It Works

1. Someone @mentions the bot in Discord with coding instructions
2. The bot creates a thread and starts working
3. Claude Code reads the project, makes changes autonomously
4. The bot commits and pushes the changes
5. If Railway is configured, the bot waits for the deploy and auto-fixes failures
6. Progress updates and emoji reactions keep you in the loop

## Prerequisites

- A Discord bot token
- A GitHub personal access token with **Contents** (read/write) permission
- A target project repo (or use the included `starter/` template)
- Claude Code CLI authenticated — either via `ANTHROPIC_API_KEY` or `CLAUDE_CREDENTIALS`

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and go to **Bot** settings
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Copy the bot token
5. Go to **OAuth2 > URL Generator**, select scope: `bot` only
6. Under Bot Permissions, check: `Send Messages`, `Read Message History`, `Create Public Threads`, `Send Messages in Threads`, `Add Reactions`
7. Open the generated URL to invite the bot to your server

### 2. Create a GitHub Personal Access Token

1. Go to GitHub > Settings > Developer settings > Personal access tokens
2. Create a classic token with the **repo** scope
3. Save the token for step 4

### 3. Set Up Your Target Project

Create a new repo for the project your friends will vibe-code. You can use the included starter template:

```bash
git clone https://github.com/you/your-project.git
cp -r starter/* your-project/
cd your-project
git add -A && git commit -m "init" && git push
```

The starter is a Python Flask hello world with Railway deployment config. Or use any existing repo.

### 4. Configure

```bash
cp .env.example .env
```

Fill in the required values:

```bash
DISCORD_TOKEN=your-discord-bot-token
GIT_REPO_URL=https://github.com/you/your-project.git
GIT_TOKEN=your-github-personal-access-token
```

#### Claude Auth (one of these)

**Option A:** Set `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com)

**Option B:** Export your Claude Code credentials (uses your existing subscription):

```bash
security find-generic-password -s "Claude Code-credentials" -w | base64
```

Set the output as `CLAUDE_CREDENTIALS`.

### 5. Deploy with Docker

The bot includes a `Dockerfile` and `railway.toml` for easy deployment:

```bash
docker build -t vibez .
docker run --env-file .env vibez
```

Or deploy directly to Railway by connecting the repo.

### 6. Run Locally (alternative)

```bash
pip install -r requirements.txt
python -m bot.main
```

Requires [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed and on `PATH`.

On startup the bot clones the target repo into `./project/` and starts listening for @mentions.

### 7. Use It

In Discord:

```
@VibezBot add a /health endpoint that returns JSON with status ok
```

The bot will:
- React with 👀 then a random emoji (🍳🔥🪄🤖💅 etc.)
- Create a thread with progress updates and a heartbeat timer
- Post the result with files changed, cost, and commit hash
- React ✅ on success, 💀 on failure, 🤷 if no changes

Reply in the thread to give follow-up instructions — each thread maintains its own Claude session.

You can also check deploy logs anytime:

```
@VibezBot check logs
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | Yes | | Discord bot token |
| `GIT_REPO_URL` | Yes | | HTTPS clone URL for the target project |
| `GIT_TOKEN` | Yes | | GitHub personal access token (repo scope) |
| `ANTHROPIC_API_KEY` | No | | Anthropic API key for Claude Code |
| `CLAUDE_CREDENTIALS` | No | | Base64-encoded Claude Code credentials from macOS keychain |
| `CLAUDE_MODEL` | No | `sonnet` | Claude model to use (e.g. `sonnet`, `opus`, `haiku`) |
| `GIT_BRANCH` | No | `master` | Branch to commit and push to |
| `GIT_USER_NAME` | No | `Vibez Bot` | Git commit author name |
| `GIT_USER_EMAIL` | No | `vibez@bot` | Git commit author email |
| `DISCORD_CHANNEL_IDS` | No | | Comma-separated channel IDs to restrict the bot to |
| `MAX_BUDGET_PER_REQUEST` | No | `5` | Max USD per Claude invocation |
| `MAX_QUEUE_SIZE` | No | `10` | Max queued requests |
| `CLAUDE_TIMEOUT_MS` | No | `600000` | Timeout per request in ms (10 min) |
| `DEPLOY_RAILWAY_TOKEN` | No | | Railway API token — enables deploy status checking |
| `DEPLOY_RAILWAY_SERVICE` | No | | Target project's Railway service ID |
| `DEPLOY_RAILWAY_ENVIRONMENT` | No | | Target project's Railway environment ID |
| `MAX_FIX_ATTEMPTS` | No | `3` | Auto-fix attempts on deploy failure |

## Railway Integration (Optional)

If you set the Railway env vars, the bot will after each push:

1. Wait for the deployment to finish
2. If it fails, fetch build + deploy logs
3. Feed the logs back to Claude to auto-fix
4. Commit, push, and wait for deploy again
5. Retry up to `MAX_FIX_ATTEMPTS` times

## Starter Template

The `starter/` directory contains a ready-to-deploy Python Flask app:

- `app.py` — hello world Flask app
- `requirements.txt` — Flask, gunicorn, psycopg2
- `railway.toml` — Railway deployment config
- `CLAUDE.md` — context for Claude Code when vibe coding
