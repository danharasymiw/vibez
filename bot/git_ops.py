import asyncio
import os
import stat
import tempfile
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse

from bot import config


@dataclass
class GitResult:
    committed: bool = False
    commit_hash: str = ""
    files_changed: list[str] = field(default_factory=list)
    pushed: bool = False


def _auth_url(url: str, token: str) -> str:
    """Inject token into an HTTPS git URL for authentication."""
    parsed = urlparse(url)
    netloc = f"x-access-token:{token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


# Credential helper script — git calls this for auth during push/pull.
# Written to a temp file at startup so the token never touches the remote URL.
_credential_helper_path: str | None = None


def _setup_credential_helper() -> str:
    """Write a credential helper script that returns the git token."""
    global _credential_helper_path
    if _credential_helper_path:
        return _credential_helper_path

    parsed = urlparse(config.GIT_REPO_URL)
    script = (
        "#!/bin/sh\n"
        f'echo "protocol=https"\n'
        f'echo "host={parsed.hostname}"\n'
        f'echo "username=x-access-token"\n'
        f'echo "password={config.GIT_TOKEN}"\n'
    )

    fd, path = tempfile.mkstemp(prefix="vibez-git-cred-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)

    _credential_helper_path = path
    return path


async def _run_git(*args: str, cwd: str | None = None, with_auth: bool = False) -> str:
    cmd = ["git"]
    if with_auth:
        helper = _setup_credential_helper()
        cmd += ["-c", f"credential.helper={helper}"]
    cmd += list(args)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd or config.PROJECT_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {stderr.decode()}")
    return stdout.decode()


async def _clone_repo(repo_url: str, target_dir: str, branch: str) -> None:
    """Clone a repo, then strip the token from the remote URL."""
    os.makedirs(target_dir, exist_ok=True)
    auth_url = _auth_url(repo_url, config.GIT_TOKEN)
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "-b", branch, auth_url, target_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {stderr.decode()}")
    await _run_git("remote", "set-url", "origin", repo_url, cwd=target_dir)
    print(f"Cloned {repo_url} into {target_dir}", flush=True)


async def _setup_repo(repo_url: str, target_dir: str, branch: str) -> None:
    """Clone or pull a repo, configure git identity."""
    is_repo = os.path.isdir(os.path.join(target_dir, ".git"))

    if not is_repo:
        await _clone_repo(repo_url, target_dir, branch)
    else:
        await _run_git("remote", "set-url", "origin", repo_url, cwd=target_dir)
        try:
            await _run_git("pull", "origin", branch, cwd=target_dir, with_auth=True)
        except RuntimeError as e:
            print(f"Warning: pull on startup failed: {e}", flush=True)

    await _run_git("config", "user.name", config.GIT_USER_NAME, cwd=target_dir)
    await _run_git("config", "user.email", config.GIT_USER_EMAIL, cwd=target_dir)


async def init_repo() -> None:
    """Clone the project repo (and optionally the bot repo) on startup."""
    await _setup_repo(config.GIT_REPO_URL, config.PROJECT_DIR, config.GIT_BRANCH)
    print("Project repo ready", flush=True)

    if config.BOT_REPO_URL:
        await _setup_repo(config.BOT_REPO_URL, config.BOT_DIR, config.BOT_GIT_BRANCH)
        print("Bot repo ready", flush=True)


async def commit_and_push(message: str, cwd: str | None = None) -> GitResult:
    target = cwd or config.PROJECT_DIR
    status = await _run_git("status", "--porcelain", cwd=target)
    if not status.strip():
        return GitResult()

    files_changed = [line.strip() for line in status.strip().split("\n") if line.strip()]

    await _run_git("add", "-A", cwd=target)
    await _run_git("commit", "-m", message, cwd=target)
    commit_hash = (await _run_git("rev-parse", "--short", "HEAD", cwd=target)).strip()

    pushed = False
    try:
        await _run_git("push", "origin", config.GIT_BRANCH, cwd=target, with_auth=True)
        pushed = True
    except RuntimeError:
        try:
            await _run_git("pull", "--rebase", "origin", config.GIT_BRANCH, cwd=target, with_auth=True)
            await _run_git("push", "origin", config.GIT_BRANCH, cwd=target, with_auth=True)
            pushed = True
        except RuntimeError as e:
            print(f"Failed to push after rebase: {e}")

    return GitResult(
        committed=True,
        commit_hash=commit_hash,
        files_changed=files_changed,
        pushed=pushed,
    )
