"""Unified registry of built-in and MCP tools, plus execution.

Built-in tools are plain local CRUD (no shell, no code execution).  Tools flagged
``requires_approval`` are never run until a person approves them.  MCP tools require approval
whenever their server is configured with ``require_approval=true`` (the default).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.core.jsonschema_lite import validate_arguments
from assistant.core.textutil import like_pattern, LIKE_ESCAPE
from assistant.core.timeutil import ensure_utc
from assistant.db.models import CalendarEvent, MailAccount, MailMessage, MCPServer, Note, Task
from assistant.mcp.http_client import MCPClientError, call_tool as mcp_call_tool
from assistant.services import productivity as prod
from assistant.services.mcp import cached_tools

COLOR = {"type": "string", "enum": ["red", "yellow", "green"]}  # note importance: red > yellow > green
STATUS = {"type": "string", "enum": ["todo", "in_progress", "done"]}


def _spec(name, description, properties, required=(), *, write=False, category):
    return {
        "name": name, "description": description, "category": category, "requires_approval": write,
        "input_schema": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
    }


BUILTIN_TOOLS: list[dict] = [
    _spec("notes.list", "List local notes (optionally filtered by text)",
          {"query": {"type": "string", "maxLength": 200}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, category="notes"),
    _spec("notes.get", "Get one local note by id (includes full content)",
          {"id": {"type": "string", "maxLength": 36}},
          ["id"], category="notes"),
    _spec("notes.create", "Create a local note (colour = importance: red high, yellow normal, green low). Always put the full body in content, not only the title.",
          {"title": {"type": "string", "maxLength": 240}, "content": {"type": "string"}, "color": COLOR,
           "pinned": {"type": "boolean"}},
          ["title"], write=True, category="notes"),
    _spec("notes.update", "Update an existing note by id (title, content, colour, pinned). Use this to fill or refine content after create.",
          {"id": {"type": "string", "maxLength": 36}, "title": {"type": "string", "maxLength": 240},
           "content": {"type": "string"}, "color": COLOR, "pinned": {"type": "boolean"}},
          ["id"], write=True, category="notes"),
    _spec("tasks.list", "List local tasks",
          {"status": STATUS, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, category="tasks"),
    _spec("tasks.create", "Create a local task (a single line of text)",
          {"task": {"type": "string", "minLength": 1, "maxLength": 800}, "status": STATUS,
           "due_at": {"type": "string", "maxLength": 40}},
          ["task"], write=True, category="tasks"),
    _spec("tasks.update", "Update an existing task by id (text, due date and/or status)",
          {"id": {"type": "string", "maxLength": 36}, "task": {"type": "string", "minLength": 1, "maxLength": 800},
           "due_at": {"type": "string", "maxLength": 40}, "status": STATUS},
          ["id"], write=True, category="tasks"),
    _spec("calendar.list", "List local calendar events between two ISO-8601 datetimes",
          {"start": {"type": "string", "maxLength": 40}, "end": {"type": "string", "maxLength": 40},
           "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, category="calendar"),
    _spec("calendar.create", "Create a local calendar event (ISO-8601 datetimes). Prefer full datetime; for all-day use start_at as date midnight and set all_day true if supported.",
          {"title": {"type": "string", "minLength": 1, "maxLength": 240}, "start_at": {"type": "string", "maxLength": 40},
           "end_at": {"type": "string", "maxLength": 40}, "location": {"type": "string", "maxLength": 300},
           "description": {"type": "string"}, "all_day": {"type": "boolean"}},
          ["title", "start_at"], write=True, category="calendar"),
    # Mail tools (require a connected Google/Microsoft account; MCP can still be used for other mail systems)
    _spec("mail.list", "List recent mail messages from connected accounts (inbox by default)",
          {"folder": {"type": "string", "enum": ["inbox", "sent", "drafts", "trash", "spam"]},
           "query": {"type": "string", "maxLength": 200},
           "account_id": {"type": "string", "maxLength": 36},
           "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, category="mail"),
    _spec("mail.get", "Get one mail message by id (includes body when available)",
          {"id": {"type": "string", "maxLength": 36}},
          ["id"], category="mail"),
    _spec("mail.send", "Send a new email from a connected account",
          {"account_id": {"type": "string", "maxLength": 36},
           "to": {"type": "string", "minLength": 3, "maxLength": 500, "description": "Comma-separated recipient emails"},
           "subject": {"type": "string", "maxLength": 500},
           "body": {"type": "string", "maxLength": 20000},
           "html": {"type": "boolean"}},
          ["account_id", "to", "subject", "body"], write=True, category="mail"),
    _spec("mail.mark_read", "Mark a message as read or unread",
          {"id": {"type": "string", "maxLength": 36}, "is_read": {"type": "boolean"}},
          ["id", "is_read"], write=True, category="mail"),
]
BUILTIN_BY_NAME = {t["name"]: t for t in BUILTIN_TOOLS}
BUILTIN_NAMES = set(BUILTIN_BY_NAME)


class ToolError(ValueError):
    """The tool call was invalid or failed in a way that should be reported to the user."""


def mcp_tool_id(server_id: str, tool_name: str) -> str:
    return f"mcp:{server_id}:{tool_name}"


def parse_mcp_tool_id(tool_id: str) -> tuple[str, str] | None:
    if not tool_id.startswith("mcp:"):
        return None
    parts = tool_id.split(":", 2)
    return (parts[1], parts[2]) if len(parts) == 3 and parts[1] and parts[2] else None


def _builtin_entry(spec: dict) -> dict:
    return {"id": spec["name"], "name": spec["name"], "kind": "builtin", "category": spec["category"],
            "description": spec["description"], "input_schema": spec["input_schema"],
            "requires_approval": spec["requires_approval"], "server_id": None, "server_name": None, "available": True}


def _mcp_entries(server: MCPServer) -> list[dict]:
    entries = []
    for tool in cached_tools(server):
        entries.append({
            "id": mcp_tool_id(server.id, tool["name"]), "name": tool["name"], "kind": "mcp", "category": "mcp",
            "description": tool.get("description", ""), "input_schema": tool.get("inputSchema") or {"type": "object"},
            "requires_approval": bool(server.require_approval), "server_id": server.id, "server_name": server.name,
            "available": bool(server.enabled and server.status == "connected" and server.transport != "stdio"),
        })
    return entries


def catalog(db: Session) -> list[dict]:
    entries = [_builtin_entry(t) for t in BUILTIN_TOOLS]
    for server in db.scalars(select(MCPServer).order_by(MCPServer.name)):
        entries.extend(_mcp_entries(server))
    return entries


def get_tool(db: Session, tool_id: str) -> dict | None:
    if tool_id in BUILTIN_BY_NAME:
        return _builtin_entry(BUILTIN_BY_NAME[tool_id])
    parsed = parse_mcp_tool_id(tool_id)
    if parsed:
        server = db.get(MCPServer, parsed[0])
        if server:
            return next((e for e in _mcp_entries(server) if e["id"] == tool_id), None)
    return None


def allowed_tools(db: Session, tool_ids: list[str] | None) -> dict[str, dict]:
    """Tools a run may plan with.  ``None`` means every built-in tool (agent-less runs)."""
    if tool_ids is None:
        return {t["name"]: _builtin_entry(t) for t in BUILTIN_TOOLS}
    result = {}
    for tool_id in tool_ids:
        entry = get_tool(db, tool_id)
        if entry and entry["available"]:
            result[tool_id] = entry
    return result


def validate_tool_ids(db: Session, tool_ids: list[str]) -> None:
    for tool_id in tool_ids:
        if tool_id in BUILTIN_NAMES:
            continue
        parsed = parse_mcp_tool_id(tool_id)
        if not parsed or db.get(MCPServer, parsed[0]) is None:
            raise ValueError(f"Unknown tool: {tool_id}")


def shrink(result: Any, limit: int = 20_000) -> Any:
    text = json.dumps(result, default=str)
    if len(text) <= limit:
        return json.loads(text)
    return {"truncated": True, "preview": text[:limit]}


def _parse_dt(value: str | None, field: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(f"{field} must be an ISO-8601 datetime") from exc
    return ensure_utc(parsed)


def _execute_builtin(db: Session, name: str, args: dict) -> Any:
    limit = int(args.get("limit", 50))
    if name == "notes.list":
        stmt = select(Note).order_by(*prod.note_ordering()).limit(limit)
        if args.get("query"):
            pattern = like_pattern(args["query"])
            stmt = stmt.where(Note.title.ilike(pattern, escape=LIKE_ESCAPE) | Note.content.ilike(pattern, escape=LIKE_ESCAPE))
        return [{"id": n.id, "title": n.title, "content": n.content, "color": n.color, "pinned": n.pinned}
                for n in db.scalars(stmt)]
    if name == "notes.get":
        note = db.get(Note, args["id"])
        if note is None:
            raise ToolError("Note not found")
        return {"id": note.id, "title": note.title, "content": note.content, "color": note.color, "pinned": note.pinned}
    if name == "notes.create":
        note = prod.create_note(db, title=args["title"], content=args.get("content", ""),
                                color=args.get("color", "yellow"), pinned=args.get("pinned", False))
        return {"id": note.id, "title": note.title, "content": note.content, "color": note.color, "pinned": note.pinned}
    if name == "notes.update":
        note = db.get(Note, args["id"])
        if note is None:
            raise ToolError("Note not found")
        changes = {k: args[k] for k in ("title", "content", "color", "pinned") if k in args}
        if not changes:
            raise ToolError("Provide at least one of title, content, color, pinned")
        prod.update_note(note, changes=changes)
        db.flush()
        return {"id": note.id, "title": note.title, "content": note.content, "color": note.color, "pinned": note.pinned}
    if name == "tasks.list":
        stmt = select(Task).order_by(Task.status, Task.position, Task.created_at).limit(limit)
        if args.get("status"):
            stmt = stmt.where(Task.status == args["status"])
        return [{"id": t.id, "task": t.task, "status": t.status, "due_at": t.due_at, "position": t.position}
                for t in db.scalars(stmt)]
    if name == "tasks.create":
        task = prod.create_task(db, task=args["task"], status=args.get("status", "todo"),
                                due_at=_parse_dt(args.get("due_at"), "due_at"))
        return {"id": task.id, "task": task.task, "status": task.status}
    if name == "tasks.update":
        task = db.get(Task, args["id"])
        if task is None:
            raise ToolError("Task not found")
        changes = {k: args[k] for k in ("task",) if k in args}
        if "due_at" in args:
            changes["due_at"] = _parse_dt(args["due_at"], "due_at")
        prod.update_task(task, changes=changes)
        if "status" in args:
            prod.apply_task_status(db, task, args["status"])
        db.flush()
        return {"id": task.id, "task": task.task, "status": task.status}
    if name == "calendar.list":
        start, end = _parse_dt(args.get("start"), "start"), _parse_dt(args.get("end"), "end")
        stmt = select(CalendarEvent).order_by(CalendarEvent.start_at).limit(limit)
        if start:
            stmt = stmt.where(CalendarEvent.start_at >= start)
        if end:
            stmt = stmt.where(CalendarEvent.start_at < end)
        return [{"id": e.id, "title": e.title, "start_at": e.start_at, "end_at": e.end_at, "location": e.location}
                for e in db.scalars(stmt)]
    if name == "calendar.create":
        start, end = _parse_dt(args["start_at"], "start_at"), _parse_dt(args.get("end_at"), "end_at")
        if end and end < start:
            raise ToolError("end_at must not be before start_at")
        event = prod.create_event(
            db,
            title=args["title"].strip(),
            start_at=start,
            end_at=end,
            description=args.get("description", ""),
            location=args.get("location", ""),
            all_day=bool(args.get("all_day", False)),
        )
        return {"id": event.id, "title": event.title, "start_at": event.start_at, "all_day": event.all_day}
    if name == "mail.list":
        from assistant.services.mail import service as mail_svc
        folder = args.get("folder") or "inbox"
        limit = int(args.get("limit", 20))
        stmt = select(MailMessage).where(MailMessage.folder == folder).order_by(MailMessage.received_at.desc()).limit(limit)
        if args.get("account_id"):
            stmt = stmt.where(MailMessage.account_id == args["account_id"])
        if args.get("query"):
            pattern = like_pattern(args["query"])
            stmt = stmt.where(
                MailMessage.subject.ilike(pattern, escape=LIKE_ESCAPE)
                | MailMessage.snippet.ilike(pattern, escape=LIKE_ESCAPE)
                | MailMessage.sender_email.ilike(pattern, escape=LIKE_ESCAPE)
            )
        return [{
            "id": m.id, "account_id": m.account_id, "folder": m.folder, "subject": m.subject,
            "from": m.sender_email, "snippet": m.snippet, "is_read": m.is_read, "received_at": m.received_at,
        } for m in db.scalars(stmt)]
    if name == "mail.get":
        from assistant.services.mail import service as mail_svc
        msg = db.get(MailMessage, args["id"])
        if msg is None:
            raise ToolError("Mail message not found")
        try:
            msg = mail_svc.load_body(db, msg)
        except Exception:
            pass  # body may already be present or provider temporarily unavailable
        return {
            "id": msg.id, "account_id": msg.account_id, "folder": msg.folder, "subject": msg.subject,
            "from": msg.sender_email, "snippet": msg.snippet, "is_read": msg.is_read,
            "body_text": (msg.body_text or "")[:8000], "received_at": msg.received_at,
        }
    if name == "mail.send":
        from assistant.services.mail import service as mail_svc
        from assistant.services.mail.common import OutgoingMessage
        account = db.get(MailAccount, args["account_id"])
        if account is None:
            raise ToolError("Mail account not found — connect Google or Microsoft under Connections first")
        to_raw = args["to"]
        to_list = [e.strip() for e in to_raw.replace(";", ",").split(",") if e.strip()]
        if not to_list:
            raise ToolError("At least one recipient is required")
        outgoing = OutgoingMessage(
            to=to_list,
            subject=args.get("subject") or "(no subject)",
            body=args.get("body") or "",
            html=bool(args.get("html", False)),
        )
        mail_svc.send_new(db, account, outgoing)
        return {"ok": True, "account_id": account.id, "to": to_list, "subject": outgoing.subject}
    if name == "mail.mark_read":
        from assistant.services.mail import service as mail_svc
        msg = db.get(MailMessage, args["id"])
        if msg is None:
            raise ToolError("Mail message not found")
        mail_svc.set_read(db, msg, bool(args["is_read"]))
        return {"id": msg.id, "is_read": msg.is_read}
    raise ToolError(f"Tool is not allowlisted: {name}")


def execute_tool(db: Session, tool_id: str, arguments: dict) -> Any:
    """Run one tool.  Does not commit - the caller owns the transaction.  Blocking."""
    entry = get_tool(db, tool_id)
    if entry is None:
        raise ToolError(f"Tool is not allowlisted: {tool_id}")
    if not entry["available"]:
        raise ToolError("Tool is currently unavailable (its server is disabled or disconnected)")
    try:
        validate_arguments(entry["input_schema"], arguments, strict=entry["kind"] == "builtin")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if entry["kind"] == "builtin":
        try:
            return shrink(_execute_builtin(db, tool_id, arguments))
        except ToolError:
            raise
        except ValueError as exc:  # validation errors raised by the shared productivity helpers
            raise ToolError(str(exc)) from exc
    server = db.get(MCPServer, entry["server_id"])
    try:
        return shrink(mcp_call_tool(server.url, entry["name"], arguments))
    except MCPClientError as exc:
        raise ToolError(f"MCP call failed: {exc}") from exc
