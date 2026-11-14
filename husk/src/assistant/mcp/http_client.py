"""Minimal MCP Streamable HTTP client used for explicit, user-triggered tool calls.

The client deliberately supports HTTP/SSE-style configured endpoints only through
HTTP POST JSON-RPC. It never launches local processes and applies short timeouts.
"""
from __future__ import annotations

import json
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

PROTOCOL_VERSION = "2025-03-26"


class MCPClientError(RuntimeError):
    pass


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise MCPClientError("MCP endpoint must use HTTPS or loopback HTTP")
    if not parsed.hostname or parsed.username or parsed.password:
        raise MCPClientError("MCP endpoint URL is invalid or contains embedded credentials")
    # Reject public-looking hostnames that resolve into private, link-local, or
    # reserved address space. Loopback is permitted only over HTTP above.
    try:
        addresses = {ipaddress.ip_address(item[4][0].split("%", 1)[0])
                     for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as exc:
        raise MCPClientError("MCP endpoint hostname could not be resolved") from exc
    loopback_http = parsed.scheme == "http" and parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if not addresses or (not loopback_http and any(not address.is_global for address in addresses)):
        raise MCPClientError("MCP endpoint must resolve only to public IP addresses")


def _post(url: str, payload: dict, session_id: str | None = None) -> tuple[dict, str | None]:
    _check_url(url)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    try:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise MCPClientError(f"Could not reach MCP server: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise MCPClientError(f"MCP server returned HTTP {response.status_code}")
    new_session = response.headers.get("Mcp-Session-Id") or session_id
    body = response.text.strip()
    if not body:
        if "id" not in payload and response.status_code in {200, 202, 204}:
            return {}, new_session
        raise MCPClientError("MCP server returned an empty response")
    try:
        if "text/event-stream" in response.headers.get("content-type", ""):
            candidates = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
            parsed = [json.loads(item) for item in candidates if item and item != "[DONE]"]
            if not parsed:
                raise ValueError("no event data")
            data = parsed[-1]
        else:
            data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise MCPClientError("MCP server returned an unsupported response format") from exc
    if not isinstance(data, dict):
        raise MCPClientError("MCP server returned an invalid JSON-RPC response")
    if data.get("error"):
        error = data["error"]
        message = error.get("message", "MCP request failed") if isinstance(error, dict) else "MCP request failed"
        raise MCPClientError(str(message)[:300])
    return data, new_session


def _request(url: str, method: str, params: dict | None = None) -> dict:
    initialized, session_id = _post(url, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "Husk", "version": "1.0.0"},
        },
    })
    if "result" not in initialized:
        raise MCPClientError("MCP initialize response did not include a result")
    _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)
    response, _ = _post(url, {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}}, session_id)
    if "result" not in response or not isinstance(response["result"], dict):
        raise MCPClientError("MCP response did not include a result object")
    return response["result"]


def list_tools(url: str) -> list[dict]:
    result = _request(url, "tools/list")
    tools = result.get("tools", [])
    if not isinstance(tools, list):
        raise MCPClientError("MCP tools/list returned an invalid tools list")
    cleaned = []
    for item in tools[:200]:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            cleaned.append({
                "name": item["name"][:200],
                "description": str(item.get("description", ""))[:1000],
                "inputSchema": item.get("inputSchema", {"type": "object"}),
            })
    return cleaned


def call_tool(url: str, name: str, arguments: dict) -> dict:
    if not name or len(name) > 200:
        raise MCPClientError("Invalid MCP tool name")
    if not isinstance(arguments, dict):
        raise MCPClientError("Tool arguments must be a JSON object")
    result = _request(url, "tools/call", {"name": name, "arguments": arguments})
    if result.get("isError") is True:
        content = result.get("content", [])
        message = "; ".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        raise MCPClientError((message or "MCP tool reported an error")[:500])
    return result
