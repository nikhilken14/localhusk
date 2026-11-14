"""Tiny dependency-free 5-field cron matcher (minute hour day-of-month month day-of-week).

Supports ``*``, lists (``1,15``), ranges (``9-17``), steps (``*/5``, ``10-30/5``) and
``0``/``7`` as Sunday.  Day-of-month and day-of-week follow the classic cron rule: if
both are restricted, a match on either is enough.
"""
from __future__ import annotations

from datetime import datetime

_RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


class CronError(ValueError):
    pass


def _parse_field(text: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError("empty cron field")
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"invalid step '{step_text}'")
            step = int(step_text)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"invalid range '{part}'")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = int(part)
            end = hi if step > 1 else start
        else:
            raise CronError(f"invalid value '{part}'")
        if start < lo or end > hi or start > end:
            raise CronError(f"value out of range {lo}-{hi}: '{part}'")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    fields = (expr or "").split()
    if len(fields) != 5:
        raise CronError("cron expression must have 5 fields: minute hour day month weekday")
    sets = [_parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _RANGES)]
    sets[4] = {0 if v == 7 else v for v in sets[4]}
    return (*sets, not fields[2].startswith("*"), not fields[4].startswith("*"))  # type: ignore[return-value]


def validate_cron(expr: str) -> None:
    parse_cron(expr)


def cron_matches(expr: str, when: datetime) -> bool:
    minute, hour, dom, month, dow, dom_restricted, dow_restricted = parse_cron(expr)
    if when.minute not in minute or when.hour not in hour or when.month not in month:
        return False
    cron_dow = (when.weekday() + 1) % 7  # Monday=0 in Python -> Sunday=0 in cron
    dom_ok, dow_ok = when.day in dom, cron_dow in dow
    if dom_restricted and dow_restricted:
        return dom_ok or dow_ok
    return dom_ok and dow_ok
