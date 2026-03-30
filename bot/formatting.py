def truncate(text: str, max_length: int = 1900) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n... (truncated)"


def format_result(
    *,
    success: bool,
    summary: str,
    files_changed: list[str],
    cost_usd: float,
    duration_ms: float,
    commit_hash: str,
    pushed: bool,
) -> str:
    status = "Done" if success else "Failed"
    duration = f"{duration_ms / 1000:.1f}"
    cost = f"{cost_usd:.4f}"

    msg = f"**{status}** ({duration}s | ${cost})\n"

    if files_changed:
        files = "\n".join(f"`{f}`" for f in files_changed[:15])
        msg += f"\n**Files changed:**\n{files}"
        if len(files_changed) > 15:
            msg += f"\n... and {len(files_changed) - 15} more"

    if commit_hash:
        msg += f"\n\n**Commit:** `{commit_hash}`"
        if not pushed:
            msg += " (push failed)"

    if summary:
        msg += f"\n\n{truncate(summary, 800)}"

    return truncate(msg)


def format_error(error: str) -> str:
    return f"**Error**\n```\n{truncate(error, 1800)}\n```"
