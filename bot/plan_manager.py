"""
Plan manager: uses Claude to decompose a high-level task into a sprint + discrete tasks,
then persists everything to the DB.
"""

import json
import os

import anthropic

from bot import db

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


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
    client = _get_client()
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

    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    return json.loads(text)


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
