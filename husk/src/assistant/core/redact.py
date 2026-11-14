"""Best-effort secret redaction for anything that ends up in logs or error messages."""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-~+/]{8,}=*"), r"\1 ***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "AIza***"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\b(\s*[=:]\s*)[\"']?[^\s\"'&,;]{4,}"), r"\1\2***"),
    (re.compile(r"(?i)([?&](?:key|code|token|access_token|refresh_token|client_secret)=)[^&\s]+"), r"\1***"),
]


def redact(text: str, secrets: list[str | None] | None = None) -> str:
    out = str(text)
    for secret in secrets or []:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "***")
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
