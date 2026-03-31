"""
Plan manager: uses Claude to decompose a high-level task into a sprint + discrete tasks,
then persists everything to the DB.
"""

import asyncio
import json

from bot import config, db


async def decompose(high_level_task: str) -> dict:
    """
    Ask Claude to break a high-level task into a sprint with discrete tasks.
    Returns:
        {
            "sprint_title": str,
            "sprint_description": str,
            "tasks": [{"title": str, "description": str}, ...]
        }
    """
    prompt = f"""You are a technical project manager. Break the following high-level task into a sprint.

High-level task: {high_level_task}

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
{{
  "sprint_title": "<concise sprint title>",
  "sprint_description": "<1-2 sentence description of what the sprint achieves>",
  "tasks": [
    {{"title": "<short task title>", "description": "<concrete, actionable description of what to implement>"}},
    ...
  ]
}}

Rules:
- 3-8 discrete, actionable tasks
- Each task should be independently implementable
- Tasks ordered logically (dependencies first)
- Titles under 60 characters"""

    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--model",
        config.CLAUDE_MODEL,
        "--max-turns",
        "1",
        cwd=config.PROJECT_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,  # 1MB line buffer — default 64KB is too small for stream-json
    )

    # Drain stderr concurrently so it never blocks the subprocess
    stderr_task = asyncio.create_task(proc.stderr.read())

    stdout_lines: list[str] = []
    async for line_bytes in proc.stdout:
        stdout_lines.append(line_bytes.decode())
    await proc.wait()
    stderr_bytes = await stderr_task

    # Extract result text from the stream-json result event
    for line in reversed(stdout_lines):
        try:
            event = json.loads(line)
            if event.get("type") == "result" and event.get("subtype") == "success":
                text = event.get("result", "").strip()
                break
        except json.JSONDecodeError:
            pass
    else:
        stderr = stderr_bytes.decode()
        raise RuntimeError(f"Claude plan decomposition failed: {stderr[:500]}")

    # Strip markdown code fences if present (handles ```json, ``` json, plain ```)
    if text.startswith("```"):
        # Remove opening fence line, then closing fence
        lines = text.splitlines()
        # Drop first line (the fence, e.g. "```json") and any trailing closing fence
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    plan = json.loads(text)

    # Validate required schema keys
    required_keys = {"sprint_title", "sprint_description", "tasks"}
    missing = required_keys - plan.keys()
    if missing:
        raise RuntimeError(f"Claude returned invalid plan structure, missing keys: {missing}")

    if not isinstance(plan["tasks"], list) or not plan["tasks"]:
        raise RuntimeError("Claude returned a plan with no tasks")

    return plan


async def create_sprint_from_task(high_level_task: str) -> tuple[int | None, dict]:
    """
    Decompose the task, persist to DB, and return (sprint_id, plan_data).
    """
    plan = await decompose(high_level_task)

    sprint_id = await db.create_sprint(plan["sprint_title"], plan["sprint_description"])
    if sprint_id is None:
        return None, plan

    for task in plan["tasks"]:
        await db.create_task(sprint_id, task["title"], task["description"])

    return sprint_id, plan


def format_sprint(sprint: dict, tasks: list[dict]) -> str:
    status_icon = {"todo": "[ ]", "in_progress": "[~]", "done": "[x]"}.get
    lines = [
        f"**Sprint #{sprint['id']}: {sprint['title']}**",
        f"_{sprint['description']}_",
        f"Status: `{sprint['status']}`",
        "",
        "**Tasks:**",
    ]
    for t in tasks:
        icon = status_icon(t["status"], "[ ]")
        lines.append(f"{icon} `#{t['id']}` **{t['title']}** — {t['description']}")
    return "\n".join(lines)


def format_sprint_list(sprints: list[dict]) -> str:
    if not sprints:
        return "No sprints yet. Use `plan bot: <task>` to create one."
    lines = ["**Sprints:**"]
    for s in sprints:
        icon = "✅" if s["status"] == "completed" else "🔄"
        lines.append(f"{icon} `#{s['id']}` **{s['title']}** — {s['status']}")
    return "\n".join(lines)
