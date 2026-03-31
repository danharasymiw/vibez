import asyncio
import json
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from bot import config


@dataclass
class ClaudeResult:
    success: bool
    result: str
    cost_usd: float
    duration_ms: float
    num_turns: int
    session_id: str


async def run_claude(
    instruction: str,
    on_progress: Optional[Callable[[str], Awaitable[None]]] = None,
    session_id: Optional[str] = None,
    cwd: Optional[str] = None,
) -> ClaudeResult:
    env = os.environ.copy()

    args = [
        "claude",
        "-p",
        instruction,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--model",
        config.CLAUDE_MODEL,
        "--max-turns",
        "50",
    ]

    if session_id:
        args += ["--resume", session_id]

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd or config.PROJECT_DIR,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,  # 1MB line buffer (default 64KB is too small for stream-json)
    )

    stdout_lines: list[str] = []
    last_progress = ""

    try:
        async with asyncio.timeout(config.CLAUDE_TIMEOUT):
            async for line_bytes in proc.stdout:
                line = line_bytes.decode()
                stdout_lines.append(line)

                try:
                    event = json.loads(line)
                    if event.get("type") == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "tool_use":
                                progress = f"Using tool: {block['name']}"
                                if progress != last_progress and on_progress:
                                    last_progress = progress
                                    await on_progress(progress)
                except (json.JSONDecodeError, KeyError):
                    pass

            await proc.wait()
    except TimeoutError:
        proc.kill()
        raise RuntimeError("Claude Code timed out")

    stderr = (await proc.stderr.read()).decode() if proc.stderr else ""
    if stderr:
        print(f"[claude stderr] {stderr[:500]}", flush=True)

    # Parse result from the last stream-json event
    for line in reversed(stdout_lines):
        try:
            event = json.loads(line)
            if event.get("type") == "result":
                result_text = event.get("result", "")
                is_success = not event.get("is_error") and event.get("subtype") == "success"
                # If Claude failed with no result text, include stderr so the error is visible
                if not is_success and not result_text and stderr:
                    result_text = stderr[:500]
                return ClaudeResult(
                    success=is_success,
                    result=result_text,
                    cost_usd=event.get("total_cost_usd", 0),
                    duration_ms=event.get("duration_ms", 0),
                    num_turns=event.get("num_turns", 0),
                    session_id=event.get("session_id", ""),
                )
        except json.JSONDecodeError:
            pass

    # Try to find session_id from any system event
    found_session_id = ""
    for line in stdout_lines:
        try:
            event = json.loads(line)
            if event.get("session_id"):
                found_session_id = event["session_id"]
                break
        except json.JSONDecodeError:
            pass

    stdout_text = "".join(stdout_lines)
    if proc.returncode == 0:
        return ClaudeResult(True, stdout_text[-500:], 0, 0, 0, found_session_id)

    raise RuntimeError(
        f"Claude exited with code {proc.returncode}: {stderr[-500:]}"
    )
