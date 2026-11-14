"""A deliberately small JSON-schema subset validator for tool arguments.

Strict mode (built-in tools) rejects unknown properties.  Lenient mode (remote MCP tools,
whose schemas can use arbitrary keywords) only checks ``required`` and simple types.
"""
from __future__ import annotations

from typing import Any

_TYPES = {
    "string": str,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = _TYPES.get(expected)
    return True if py is None else isinstance(value, py)


def validate_arguments(schema: dict, arguments: Any, *, strict: bool = True) -> None:
    """Raise ``ValueError`` describing the first problem found."""
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be a JSON object")
    props: dict = schema.get("properties", {}) if isinstance(schema, dict) else {}
    missing = [name for name in (schema.get("required") or []) if name not in arguments]
    if missing:
        raise ValueError(f"missing required arguments: {', '.join(sorted(missing))}")
    if strict:
        extra = sorted(set(arguments) - set(props))
        if extra:
            raise ValueError(f"unexpected arguments: {', '.join(extra)}")
    for key, value in arguments.items():
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if isinstance(expected, str) and not _type_ok(expected, value):
            raise ValueError(f"argument '{key}' must be of type {expected}")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"argument '{key}' must be one of {spec['enum']}")
        if isinstance(value, str):
            if len(value) > spec.get("maxLength", 100_000):
                raise ValueError(f"argument '{key}' is too long")
            if len(value) < spec.get("minLength", 0):
                raise ValueError(f"argument '{key}' is too short")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                raise ValueError(f"argument '{key}' must be >= {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise ValueError(f"argument '{key}' must be <= {spec['maximum']}")
