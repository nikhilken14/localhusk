from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.errors import APIError
from assistant.db.models import MCPServer
from assistant.schemas.automation import MCPIn
from assistant.services.agent_runtime.tools import mcp_tool_id
from assistant.services.mcp import cached_tools, refresh_server

router = APIRouter(prefix="/mcp", tags=["mcp"])


def server_out(server: MCPServer) -> dict:
    tools = [{"id": mcp_tool_id(server.id, t["name"]), "name": t["name"], "description": t.get("description", ""),
              "requires_approval": bool(server.require_approval),
              "input_schema": t.get("inputSchema", {"type": "object"})} for t in cached_tools(server)]
    return {"id": server.id, "name": server.name, "transport": server.transport, "command": server.command,
            "args": json.loads(server.args_json or "[]"), "url": server.url, "enabled": server.enabled,
            "require_approval": server.require_approval, "status": server.status, "last_error": server.last_error,
            "last_connected_at": server.last_connected_at, "tool_count": len(tools), "tools": tools,
            "created_at": server.created_at, "updated_at": server.updated_at}


def _get(db: Session, server_id: str) -> MCPServer:
    server = db.get(MCPServer, server_id)
    if server is None:
        raise APIError(404, "MCP server not found")
    return server


@router.get("/servers", summary="Configured servers with their discovered tools")
def list_servers(db: Session = Depends(get_db)):
    return [server_out(s) for s in db.scalars(select(MCPServer).order_by(MCPServer.created_at.desc()))]


@router.post("/servers", status_code=201, summary="Register a server and connect to it")
def create_server(payload: MCPIn, db: Session = Depends(get_db)):
    if payload.transport in ("http", "sse") and not payload.url:
        raise APIError(422, "url is required for http/sse transport")
    if payload.transport == "stdio" and not payload.command:
        raise APIError(422, "command is required for stdio transport")
    server = MCPServer(name=payload.name.strip(), transport=payload.transport, command=payload.command,
                       args_json=json.dumps(payload.args), url=payload.url, enabled=payload.enabled,
                       require_approval=payload.require_approval)
    db.add(server)
    db.commit()
    return server_out(refresh_server(db, server))  # connection problems are reported in `status`, not as an HTTP error


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, server_id))
    db.commit()


@router.patch("/servers/{server_id}/enabled", summary="Enable or disable: ?enabled=true|false")
def set_enabled(server_id: str, enabled: bool, db: Session = Depends(get_db)):
    server = _get(db, server_id)
    server.enabled = enabled
    db.commit()
    return server_out(refresh_server(db, server))


@router.post("/servers/{server_id}/refresh", summary="Reconnect and refresh discovered tools")
def refresh(server_id: str, db: Session = Depends(get_db)):
    server = _get(db, server_id)
    if not server.enabled:
        raise APIError(409, "Enable this server before refreshing", "server_disabled")
    return server_out(refresh_server(db, server))
