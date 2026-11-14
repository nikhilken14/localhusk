import { API_BASE_URL } from "../../api-base";
import type { AgentCard, CatalogTool } from "../agents/types";
import { agentsApi } from "../agents/api";

/* Backend contract (assumed – adapt here, the page doesn't care how it's served):
     GET    /mcp/servers                      → McpServer[]   (each with its discovered tools)
     POST   /mcp/servers                      → McpServer     (connects, then lists the server's tools)
     DELETE /mcp/servers/:id
     PATCH  /mcp/servers/:id/enabled?enabled= → McpServer
     POST   /mcp/servers/:id/refresh          → McpServer     (re-list tools)
   Built-in tools come from the existing GET /agents/catalog. */

export interface McpTool {
  id: string;
  name: string;
  description: string;
  access: "read" | "write";
  requires_approval: boolean;
}
export interface McpServer {
  id: string;
  name: string;
  transport: "stdio" | "http";
  command?: string;
  url?: string;
  enabled: boolean;
  status: "connected" | "error" | "disabled";
  error?: string | null;
  tools: McpTool[];
}
export interface McpDraft {
  name: string;
  transport: "stdio" | "http";
  command?: string;
  url?: string;
  env?: Record<string, string>;
}
export interface MailAccount {
  id: string;
  provider: "google" | "microsoft";
  email: string;
  display_name: string;
  status: string;
  has_calendar: boolean;
  last_synced_at: string | null;
  last_error: string;
  created_at: string;
}

function normalizeServer(raw: any): McpServer {
  const serverApproval = raw.require_approval !== false;
  return {
    id: raw.id,
    name: raw.name,
    transport: raw.transport === "sse" ? "http" : raw.transport,
    command: raw.command || "",
    url: raw.url || "",
    enabled: Boolean(raw.enabled),
    status:
      raw.enabled === false
        ? "disabled"
        : raw.status === "connected"
          ? "connected"
          : "error",
    error: raw.last_error || null,
    tools: Array.isArray(raw.tools)
      ? raw.tools.map((t: any) => ({
          id: t.id,
          name: t.name ?? t.id,
          description: t.description ?? "",
          access: t.access === "write" ? "write" : "read",
          requires_approval: Boolean(t.requires_approval ?? serverApproval),
        }))
      : [],
  };
}

function parseCommand(command = ""): { command: string; args: string[] } {
  // Parse a command line without invoking a shell. Quotes group arguments; shell expansion is intentionally unsupported.
  const parts: string[] = [];
  const pattern = /\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|([^\s]+))/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(command)) !== null)
    parts.push(
      (match[1] ?? match[2] ?? match[3] ?? "").replace(/\\([\\"'])/g, "$1"),
    );
  return { command: parts[0] ?? "", args: parts.slice(1) };
}

function serverDraft(draft: McpDraft) {
  const parsed =
    draft.transport === "stdio"
      ? parseCommand(draft.command)
      : { command: "", args: [] as string[] };
  return {
    name: draft.name,
    transport: draft.transport,
    command: parsed.command,
    args: parsed.args,
    url: draft.url ?? "",
    enabled: true,
    require_approval: true,
  };
}

const BASE = API_BASE_URL;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const d = body.detail;
    throw new Error(
      (Array.isArray(d) ? d.map((e: any) => e.msg).join("; ") : d) ??
        r.statusText,
    );
  }
  return r.status === 204 ? (undefined as T) : r.json();
}


export const connectionsApi = {
  accounts: () => req<MailAccount[]>("/mail/accounts"),
  startOAuth: (provider: MailAccount["provider"]) =>
    req<{ authorization_url: string }>("/mail/accounts/oauth/start", {
      method: "POST",
      body: JSON.stringify({ provider, include_calendar: true }),
    }),
  disconnectAccount: (id: string) =>
    req<{ deleted: boolean }>(`/mail/accounts/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  servers: () =>
    req<any[]>("/mcp/servers").then((rows) => rows.map(normalizeServer)),
  add: (d: McpDraft) =>
    req<any>("/mcp/servers", {
      method: "POST",
      body: JSON.stringify(serverDraft(d)),
    }).then(normalizeServer),
  remove: (id: string) =>
    req<void>(`/mcp/servers/${id}`, { method: "DELETE" }),
  setEnabled: (id: string, enabled: boolean) =>
    req<any>(`/mcp/servers/${id}/enabled?enabled=${enabled}`, {
      method: "PATCH",
    }).then(normalizeServer),
  refresh: (id: string) =>
    req<any>(`/mcp/servers/${id}/refresh`, { method: "POST" }).then(
      normalizeServer,
    ),
  /** Built-in tools agents can use. */
  tools: (): Promise<CatalogTool[]> =>
    agentsApi.catalog().then((c) => c.tools),
  /** Used to show which agents use each tool. */
  agents: (): Promise<AgentCard[]> => agentsApi.list(),
};
