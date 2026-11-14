"""Connect to / refresh remote MCP servers and cache the tools they advertise."""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from assistant.core.timeutil import utcnow
from assistant.db.models import MCPServer
from assistant.mcp.http_client import MCPClientError, list_tools

log = logging.getLogger("assistant.mcp")


def cached_tools(server: MCPServer) -> list[dict]:
    try:
        tools = json.loads(server.tools_json or "[]")
    except json.JSONDecodeError:
        return []
    return tools if isinstance(tools, list) else []


def refresh_server(db: Session, server: MCPServer) -> MCPServer:
    """Blocking (HTTP) - call from sync routes or a worker thread."""
    if not server.enabled:
        server.status, server.last_error = "disabled", ""
    elif server.transport == "stdio":
        # Spawning local processes from an HTTP API is a remote-code-execution surface; keep it off.
        server.status = "unsupported"
        server.last_error = "stdio transport is not enabled; use an HTTP MCP endpoint"
    else:
        try:
            tools = list_tools(server.url)
        except MCPClientError as exc:
            server.status, server.last_error = "error", str(exc)[:500]
            log.warning("MCP server %s unreachable: %s", server.name, exc, extra={"category": "mcp"})
        else:
            server.tools_json = json.dumps(tools)
            server.status, server.last_error = "connected", ""
            server.last_connected_at = utcnow()
            log.info("MCP server %s connected (%d tools)", server.name, len(tools), extra={"category": "mcp"})
    db.commit()
    return server
