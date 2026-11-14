from __future__ import annotations

import re

LIKE_ESCAPE = "\\"


def like_pattern(query: str) -> str:
    """Escape LIKE wildcards in user input and wrap for a contains-search.

    Use with ``column.ilike(pattern, escape=LIKE_ESCAPE)``.
    """
    escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def make_snippet(text: str, query: str | None, width: int = 80) -> str:
    """Return ``text`` shortened around the first match of ``query`` (or its start)."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) <= width * 2:
        return flat
    index = flat.lower().find(query.lower()) if query else -1
    if index < 0:
        return flat[: width * 2].rstrip() + "…"
    start = max(0, index - width // 2)
    end = min(len(flat), index + len(query) + width)
    return ("…" if start else "") + flat[start:end].strip() + ("…" if end < len(flat) else "")


def preview(text: str, length: int = 140) -> str:
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"


def estimate_tokens(text: str) -> int:
    """Rough fallback (~4 chars/token) for providers that don't report usage."""
    return max(1, len(text or "") // 4)


EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]+$")


def is_valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 320 and bool(EMAIL_RE.match(value))
