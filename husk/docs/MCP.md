# MCP (Model Context Protocol) Integration

Husk can register remote MCP servers and expose their tools to agents. Agents that use MCP tools pause for user approval by default before executing them.

## Supported transports

| Transport | Status | Notes |
|-----------|--------|-------|
| HTTP / HTTPS / SSE | Fully supported | Preferred for local and remote servers |
| Loopback | Fully supported | Same-machine only |
| stdio | Registered but unsupported | Spawning processes from the HTTP API is treated as an RCE risk; tools are reported as unavailable |

## Registering a server

### UI

**Connections → MCP → Add server**

Provide:

- Name
- URL (e.g. `http://127.0.0.1:3000/sse` or the MCP HTTP endpoint your server publishes)
- Optional headers (Authorization, etc.)

### API

```http
POST /api/v1/mcp/servers
{
  "name": "my-tools",
  "url": "http://127.0.0.1:3000/sse",
  "headers": {
    "Authorization": "Bearer ..."
  }
}
```

```http
GET /api/v1/mcp/servers
GET /api/v1/mcp/servers/{id}
DELETE /api/v1/mcp/servers/{id}
```

After registration Husk discovers the tools the server advertises. Those tools appear in the agent tool catalog (subject to the agent’s allowed-tool list).

## Using MCP tools in agents

1. Create or edit an agent.
2. Enable the desired MCP tools (or the whole server).
3. When a run reaches an MCP tool call, the agent pauses and an approval request is created.
4. Resolve it via the UI or:

```http
POST /api/v1/agents/approvals/{id}/resolve
{
  "approved": true
}
```

5. Poll progress:

```http
GET /api/v1/agents/runs/{id}/events
```

## Security considerations

- Only allow MCP servers you trust. Tools can perform arbitrary side effects on the machine or network that hosts the MCP server.
- Keep the Husk backend on localhost and restrict `CORS_ORIGINS` / `ALLOWED_HOSTS`.
- Prefer short-lived tokens in headers when the MCP server requires authentication.
- Approval gating is the primary human-in-the-loop control for write / external tools.

## Example local MCP server

Any MCP-compatible HTTP/SSE server can be used. A minimal pattern is a small process that speaks the MCP protocol over SSE and exposes tools such as “read file”, “run command” (carefully), or domain-specific actions.

Once the server is running and reachable at a loopback URL, register it in Husk and assign selected tools to an agent.

## Related endpoints

See `docs/API.md` sections for `/mcp/*` and the agents approval / run event streams for the exact request/response shapes.
