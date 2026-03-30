FROM python:3.12-slim

# Install git and Node.js (needed for Claude Code CLI)
RUN apt-get update && \
    apt-get install -y git curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root user (claude CLI refuses --dangerously-skip-permissions as root)
RUN useradd -m vibez && chown -R vibez:vibez /app
USER vibez

CMD ["python", "-u", "-m", "bot.main"]
