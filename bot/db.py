import os

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_db():
    global _pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[db] DATABASE_URL not set — prompt persistence disabled", flush=True)
        return
    _pool = await asyncpg.create_pool(url)
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_queue (
                id SERIAL PRIMARY KEY,
                discord_message_id TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                thread_id TEXT,
                author_name TEXT NOT NULL,
                instruction TEXT NOT NULL,
                is_bot_fix BOOLEAN NOT NULL DEFAULT FALSE,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    print("[db] initialized prompt_queue table", flush=True)
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sprints (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                sprint_id INTEGER NOT NULL REFERENCES sprints(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                status_changed_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ DEFAULT NOW()
        """)
    print("[db] initialized sprints and tasks tables", flush=True)
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS thread_sessions (
                thread_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    print("[db] initialized thread_sessions table", flush=True)


def is_enabled() -> bool:
    return _pool is not None


async def add_prompt(
    discord_message_id: str,
    channel_id: str,
    author_name: str,
    instruction: str,
    is_bot_fix: bool,
) -> int | None:
    if not _pool:
        return None
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO prompt_queue (discord_message_id, channel_id, author_name, instruction, is_bot_fix)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (discord_message_id) DO NOTHING
            RETURNING id
            """,
            discord_message_id,
            channel_id,
            author_name,
            instruction,
            is_bot_fix,
        )
        return row["id"] if row else None
    except Exception as e:
        print(f"[db] add_prompt error: {e}", flush=True)
        return None


async def set_thread_id(prompt_id: int, thread_id: str):
    if not _pool:
        return
    try:
        await _pool.execute(
            "UPDATE prompt_queue SET thread_id=$1, updated_at=NOW() WHERE id=$2",
            thread_id,
            prompt_id,
        )
    except Exception as e:
        print(f"[db] set_thread_id error: {e}", flush=True)


async def mark_processing(prompt_id: int):
    if not _pool:
        return
    try:
        await _pool.execute(
            "UPDATE prompt_queue SET status='processing', updated_at=NOW() WHERE id=$1",
            prompt_id,
        )
    except Exception as e:
        print(f"[db] mark_processing error: {e}", flush=True)


async def mark_done(prompt_id: int):
    if not _pool:
        return
    try:
        await _pool.execute(
            "UPDATE prompt_queue SET status='done', updated_at=NOW() WHERE id=$1",
            prompt_id,
        )
    except Exception as e:
        print(f"[db] mark_done error: {e}", flush=True)


async def mark_failed(prompt_id: int, error: str):
    if not _pool:
        return
    try:
        await _pool.execute(
            "UPDATE prompt_queue SET status='failed', error=$1, updated_at=NOW() WHERE id=$2",
            error,
            prompt_id,
        )
    except Exception as e:
        print(f"[db] mark_failed error: {e}", flush=True)


async def get_pending_prompts() -> list[dict]:
    """Return all pending/processing prompts in order (for startup replay)."""
    if not _pool:
        return []
    try:
        rows = await _pool.fetch(
            "SELECT * FROM prompt_queue WHERE status IN ('pending', 'processing') ORDER BY created_at ASC"
        )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] get_pending_prompts error: {e}", flush=True)
        return []


async def clear_queue() -> int:
    """Delete all pending prompts (not currently processing). Returns count deleted."""
    if not _pool:
        return 0
    try:
        result = await _pool.execute(
            "DELETE FROM prompt_queue WHERE status='pending'"
        )
        return int(result.split()[-1])
    except Exception as e:
        print(f"[db] clear_queue error: {e}", flush=True)
        return 0


async def cancel_last_pending() -> dict | None:
    """Cancel the most recently added pending prompt. Returns the cancelled row or None."""
    if not _pool:
        return None
    try:
        row = await _pool.fetchrow(
            """
            UPDATE prompt_queue SET status='cancelled', updated_at=NOW()
            WHERE id = (
                SELECT id FROM prompt_queue WHERE status='pending' ORDER BY created_at DESC LIMIT 1
            )
            RETURNING *
            """
        )
        return dict(row) if row else None
    except Exception as e:
        print(f"[db] cancel_last_pending error: {e}", flush=True)
        return None


# ── Sprint / Task management ──────────────────────────────────────────────────

async def create_sprint(title: str, description: str) -> int | None:
    if not _pool:
        return None
    try:
        row = await _pool.fetchrow(
            "INSERT INTO sprints (title, description) VALUES ($1, $2) RETURNING id",
            title, description,
        )
        return row["id"] if row else None
    except Exception as e:
        print(f"[db] create_sprint error: {e}", flush=True)
        return None


async def create_task(sprint_id: int, title: str, description: str) -> int | None:
    if not _pool:
        return None
    try:
        row = await _pool.fetchrow(
            "INSERT INTO tasks (sprint_id, title, description) VALUES ($1, $2, $3) RETURNING id",
            sprint_id, title, description,
        )
        return row["id"] if row else None
    except Exception as e:
        print(f"[db] create_task error: {e}", flush=True)
        return None


async def get_sprints() -> list[dict]:
    if not _pool:
        return []
    try:
        rows = await _pool.fetch("SELECT * FROM sprints ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] get_sprints error: {e}", flush=True)
        return []


async def get_sprint(sprint_id: int) -> dict | None:
    if not _pool:
        return None
    try:
        row = await _pool.fetchrow("SELECT * FROM sprints WHERE id=$1", sprint_id)
        return dict(row) if row else None
    except Exception as e:
        print(f"[db] get_sprint error: {e}", flush=True)
        return None


async def get_tasks(sprint_id: int) -> list[dict]:
    if not _pool:
        return []
    try:
        rows = await _pool.fetch(
            "SELECT * FROM tasks WHERE sprint_id=$1 ORDER BY id ASC", sprint_id
        )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] get_tasks error: {e}", flush=True)
        return []


async def mark_task_in_progress(task_id: int) -> bool:
    if not _pool:
        return False
    try:
        result = await _pool.execute(
            "UPDATE tasks SET status='in_progress', updated_at=NOW(), status_changed_at=NOW() WHERE id=$1",
            task_id,
        )
        return result.split()[-1] == "1"
    except Exception as e:
        print(f"[db] mark_task_in_progress error: {e}", flush=True)
        return False


async def mark_task_done(task_id: int) -> bool:
    if not _pool:
        return False
    try:
        result = await _pool.execute(
            "UPDATE tasks SET status='done', updated_at=NOW(), status_changed_at=NOW() WHERE id=$1", task_id
        )
        return result.split()[-1] == "1"
    except Exception as e:
        print(f"[db] mark_task_done error: {e}", flush=True)
        return False


async def load_all_sessions() -> dict[int, str]:
    """Load all thread_id -> session_id mappings from DB for in-memory seeding."""
    if not _pool:
        return {}
    try:
        rows = await _pool.fetch("SELECT thread_id, session_id FROM thread_sessions")
        return {int(r["thread_id"]): r["session_id"] for r in rows}
    except Exception as e:
        print(f"[db] load_all_sessions error: {e}", flush=True)
        return {}


async def set_session_id(thread_id: str, session_id: str):
    """Persist a thread's Claude session ID so it survives restarts."""
    if not _pool:
        return
    try:
        await _pool.execute(
            """
            INSERT INTO thread_sessions (thread_id, session_id, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (thread_id) DO UPDATE SET session_id=$2, updated_at=NOW()
            """,
            thread_id,
            session_id,
        )
    except Exception as e:
        print(f"[db] set_session_id error: {e}", flush=True)


async def reset_in_progress_tasks() -> int:
    """Reset tasks stuck in 'in_progress' back to 'todo' (e.g. after a crash). Returns count reset."""
    if not _pool:
        return 0
    try:
        result = await _pool.execute(
            "UPDATE tasks SET status='todo', updated_at=NOW() WHERE status='in_progress'"
        )
        return int(result.split()[-1])
    except Exception as e:
        print(f"[db] reset_in_progress_tasks error: {e}", flush=True)
        return 0


async def get_todo_tasks(limit: int = 3) -> list[dict]:
    """Return up to `limit` tasks with status='todo', oldest first."""
    if not _pool:
        return []
    try:
        rows = await _pool.fetch(
            """
            SELECT t.*, s.title AS sprint_title
            FROM tasks t
            JOIN sprints s ON s.id = t.sprint_id
            WHERE t.status = 'todo'
            ORDER BY t.id ASC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] get_todo_tasks error: {e}", flush=True)
        return []


async def get_all_tasks() -> list[dict]:
    """Return all tasks across all sprints, joined with sprint title."""
    if not _pool:
        return []
    try:
        rows = await _pool.fetch(
            """
            SELECT t.*, s.title AS sprint_title, s.status AS sprint_status
            FROM tasks t
            JOIN sprints s ON s.id = t.sprint_id
            ORDER BY s.created_at DESC, t.id ASC
            """
        )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] get_all_tasks error: {e}", flush=True)
        return []


async def mark_sprint_done(sprint_id: int) -> bool:
    if not _pool:
        return False
    try:
        result = await _pool.execute(
            "UPDATE sprints SET status='completed', updated_at=NOW() WHERE id=$1", sprint_id
        )
        return result.split()[-1] == "1"
    except Exception as e:
        print(f"[db] mark_sprint_done error: {e}", flush=True)
        return False
