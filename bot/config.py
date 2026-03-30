import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


DISCORD_TOKEN = _required("DISCORD_TOKEN")
ANTHROPIC_API_KEY = _required("ANTHROPIC_API_KEY")
GIT_REPO_URL = _required("GIT_REPO_URL")
GIT_TOKEN = _required("GIT_TOKEN")

PROJECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "project")

GIT_BRANCH = os.environ.get("GIT_BRANCH", "main")
GIT_USER_NAME = os.environ.get("GIT_USER_NAME", "Vibez Bot")
GIT_USER_EMAIL = os.environ.get("GIT_USER_EMAIL", "vibez@bot")
CHANNEL_IDS = [
    s.strip()
    for s in os.environ.get("DISCORD_CHANNEL_IDS", "").split(",")
    if s.strip()
]
MAX_BUDGET_PER_REQUEST = float(os.environ.get("MAX_BUDGET_PER_REQUEST", "5"))
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", "10"))
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT_MS", "600000")) / 1000

# Railway (optional — enables deploy status checking and auto-fix)
RAILWAY_API_TOKEN = os.environ.get("RAILWAY_API_TOKEN")
RAILWAY_SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID")
RAILWAY_ENVIRONMENT_ID = os.environ.get("RAILWAY_ENVIRONMENT_ID")
MAX_FIX_ATTEMPTS = int(os.environ.get("MAX_FIX_ATTEMPTS", "3"))
