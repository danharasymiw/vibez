import base64
import json
import os


def inject_claude_credentials() -> None:
    """Reconstruct Claude Code credentials from CLAUDE_CREDENTIALS env var.

    The env var should contain the base64-encoded JSON credential object
    from the macOS keychain entry "Claude Code-credentials".

    To get it:
        security find-generic-password -s "Claude Code-credentials" -w | base64
    """
    creds_b64 = os.environ.get("CLAUDE_CREDENTIALS")
    if not creds_b64:
        print("No CLAUDE_CREDENTIALS set — Claude CLI will use its own auth")
        return

    try:
        creds_json = base64.b64decode(creds_b64).decode()
        json.loads(creds_json)  # validate
    except Exception as e:
        print(f"Warning: failed to decode CLAUDE_CREDENTIALS: {e}")
        return

    home = os.environ.get("HOME", "/root")
    creds_path = os.path.join(home, ".claude", ".credentials.json")
    os.makedirs(os.path.dirname(creds_path), exist_ok=True)

    with open(creds_path, "w") as f:
        f.write(creds_json)
    os.chmod(creds_path, 0o600)

    print(f"Wrote Claude credentials to {creds_path}")
