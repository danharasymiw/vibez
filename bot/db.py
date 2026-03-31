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
