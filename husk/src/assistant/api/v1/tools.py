from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.errors import APIError
from assistant.services.agent_runtime import tools

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", summary="Unified registry of built-in and MCP tools")
def list_tools(kind: Literal["builtin", "mcp"] | None = None, q: str | None = None, available: bool | None = None,
               db: Session = Depends(get_db)):
    items = tools.catalog(db)
    if kind:
        items = [t for t in items if t["kind"] == kind]
    if available is not None:
        items = [t for t in items if t["available"] is available]
    if q and q.strip():
        needle = q.lower()
        items = [t for t in items if needle in t["name"].lower() or needle in (t["description"] or "").lower()]
    return items


@router.get("/{tool_id:path}", summary="Tool metadata and permission details")
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    tool = tools.get_tool(db, tool_id)
    if tool is None:
        raise APIError(404, "Tool not found")
    return {**tool, "permission": {
        "requires_approval": tool["requires_approval"],
        "access": "read" if tool["kind"] == "builtin" and not tool["requires_approval"] else "write_or_external",
        "note": "A person must approve each use before it runs" if tool["requires_approval"] else "Runs without approval",
    }}
