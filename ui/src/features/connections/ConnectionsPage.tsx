import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";
import {
  CalendarDays,
  Command,
  ExternalLink,
  Mail,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Wrench,
} from "lucide-react";
import { connectionsApi } from "./connections-api";
import type { MailAccount, McpServer } from "./connections-api";
import type { AgentCard, CatalogTool } from "../agents/types";
import "./connections.css";

interface ConnectionsPageProps {
  notify?: (text: string) => void;
}

type Tab = "Tools" | "Accounts" | "MCP servers";

type ToolRow = Omit<CatalogTool, "access"> & {
  access: "read" | "write";
  source: "builtin" | "mcp";
};

type Access = "all" | "read" | "write" | "ask";

export function ConnectionsPage({ notify }: ConnectionsPageProps) {
  const [tab, setTab] = useState<Tab>("Tools");
  const [catalog, setCatalog] = useState<CatalogTool[] | null>(null);
  const [toolsError, setToolsError] = useState("");
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [serversError, setServersError] = useState("");
  const [accounts, setAccounts] = useState<MailAccount[]>([]);
  const [accountsError, setAccountsError] = useState("");
  const [accountBusy, setAccountBusy] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [q, setQ] = useState("");
  const [access, setAccess] = useState<Access>("all");
  const [adding, setAdding] = useState(false);
  const [toRemove, setToRemove] = useState<McpServer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setToolsError("");
    setServersError("");
    connectionsApi
      .tools()
      .then(setCatalog)
      .catch((e) => {
        setCatalog([]);
        setToolsError(e.message);
      });
    connectionsApi
      .servers()
      .then(setServers)
      .catch((e) => {
        setServers([]);
        setServersError(e.message);
      });
    connectionsApi
      .accounts()
      .then((rows) => {
        setAccounts(rows);
        setAccountsError("");
      })
      .catch((e) => {
        setAccountsError(e.message);
      });
    connectionsApi
      .agents()
      .then(setAgents)
      .catch(() => setAgents([]));
  }, []);

  useEffect(load, [load]);

  const rows: ToolRow[] = useMemo(
    () => [
      ...(catalog ?? []).map((t) => ({ ...t, source: "builtin" as const })),
      ...(servers ?? [])
        .filter((s) => s.enabled && s.status === "connected")
        .flatMap((s) =>
          s.tools.map((t) => ({
            id: t.id,
            name: t.name,
            description: t.description,
            group: s.name,
            access: t.access,
            requires_approval: false,
            source: "mcp" as const,
          })),
        ),
    ],
    [catalog, servers],
  );

  const usedBy = useMemo(() => {
    const m = new Map<string, AgentCard[]>();
    agents.forEach((a) =>
      (a.tools ?? []).forEach((t: any) => {
        const id = typeof t === "string" ? t : t.id;
        m.set(id, [...(m.get(id) ?? []), a]);
      }),
    );
    return m;
  }, [agents]);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const m = new Map<string, ToolRow[]>();
    rows
      .filter(
        (t) =>
          (!needle ||
            `${t.name} ${t.description} ${t.id} ${t.group}`
              .toLowerCase()
              .includes(needle)) &&
          (access === "all" ||
            (access === "ask" ? t.requires_approval : t.access === access)),
      )
      .forEach((t) => m.set(t.group, [...(m.get(t.group) ?? []), t]));
    return [...m];
  }, [rows, q, access]);

  const writes = rows.filter((t) => t.access === "write").length;
  const asks = rows.filter((t) => t.requires_approval).length;

  const toggle = async (s: McpServer) => {
    setBusy(s.id);
    try {
      await connectionsApi.setEnabled(s.id, !s.enabled);
      notify?.(`${s.name} ${s.enabled ? "turned off" : "turned on"}`);
      load();
    } catch (e: any) {
      notify?.(e.message);
    } finally {
      setBusy(null);
    }
  };

  const refresh = async (s: McpServer) => {
    setBusy(s.id);
    try {
      const r = await connectionsApi.refresh(s.id);
      notify?.(
        `${s.name}: ${r.tools.length} tool${r.tools.length === 1 ? "" : "s"} found`,
      );
      load();
    } catch (e: any) {
      notify?.(e.message);
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!toRemove) return;
    try {
      await connectionsApi.remove(toRemove.id);
      notify?.(`${toRemove.name} removed`);
      setToRemove(null);
      load();
    } catch (e: any) {
      notify?.(e.message);
    }
  };

  const connectAccount = async (provider: MailAccount["provider"]) => {
    const popup = window.open(
      "about:blank",
      "husk-oauth",
      "popup=yes,width=620,height=760",
    );
    if (!popup) {
      notify?.(
        "Your browser blocked the sign-in popup. Allow popups for Husk and try again.",
      );
      return;
    }
    setAccountBusy(provider);
    try {
      const result = await connectionsApi.startOAuth(provider);
      popup.location.href = result.authorization_url;
    } catch (e: any) {
      popup.close();
      notify?.(e.message || "Unable to start account connection");
    } finally {
      setAccountBusy(null);
    }
  };

  const disconnectAccount = async (account: MailAccount) => {
    setAccountBusy(account.id);
    try {
      await connectionsApi.disconnectAccount(account.id);
      notify?.(`${account.email} disconnected`);
      load();
    } catch (e: any) {
      notify?.(e.message || "Unable to disconnect account");
    } finally {
      setAccountBusy(null);
    }
  };

  useEffect(() => {
    const onOAuth = (event: MessageEvent) => {
      if (
        event.origin !== window.location.origin ||
        event.data?.type !== "husk-oauth"
      )
        return;
      if (event.data.ok) {
        notify?.(event.data.message || "Account connected");
        load();
      } else notify?.(event.data.message || "Account connection failed");
    };
    window.addEventListener("message", onOAuth);
    return () => window.removeEventListener("message", onOAuth);
  }, [load]);

  return (
    <div className="connections-page cx">
      <div className="page-heading">
        <div>
          <h1>Connections</h1>
          <p>Manage the accounts and tools Husk can access.</p>
        </div>
      </div>

      

      {/* Tabs */}
      <div className="connection-tabs" role="tablist">
        {(["Tools", "Accounts", "MCP servers"] as const).map((t) => (
          <button
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
            key={t}
          >
            {t}
            {t === "Tools" && catalog && (
              <b className="cx-count">{rows.length}</b>
            )}
            {t === "MCP servers" && servers && (
              <b className="cx-count">{servers.length}</b>
            )}
          </button>
        ))}
      </div>

      {/* Tools Tab */}
      {tab === "Tools" && (
        <>
          <div className="section-heading">
            <h2>Available tools</h2>
            <span className="subtle-text">
              {rows.length} tools · {writes} can change data · {asks} always ask
              first
            </span>
          </div>
          <p className="cx-lead">
            Agents can only use the tools you enable on them. Add more by
            connecting an MCP server.
          </p>
          <div className="cx-tools-bar">
            <label className="cx-search">
              <Search size={14} aria-hidden />
              <input
                type="search"
                placeholder="Search tools..."
                aria-label="Search tools"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </label>
            <select
              aria-label="Filter by access"
              value={access}
              onChange={(e) => setAccess(e.target.value as Access)}
            >
              <option value="all">All access</option>
              <option value="read">Read only</option>
              <option value="write">Can change data</option>
              <option value="ask">Asks first</option>
            </select>
          </div>

          {toolsError && (
            <div className="cx-note bad">
              Couldn’t load tools: {toolsError}{" "}
              <button className="subtle-button" onClick={load}>
                Try again
              </button>
            </div>
          )}

          {catalog === null && <p className="subtle-text">Loading tools…</p>}

          {catalog && !toolsError && groups.length === 0 && (
            <p className="subtle-text">No tools match your filters.</p>
          )}

          {groups.map(([group, tools]) => (
            <section className="cx-group" key={group}>
              <h3>
                {group}
                {tools[0].source === "mcp" && (
                  <span className="cx-tag mcp">MCP</span>
                )}
                <small>{tools.length}</small>
              </h3>
              {tools.map((t) => {
                const users = usedBy.get(t.id) ?? [];
                return (
                  <div className="cx-tool" key={t.id}>
                    <span className="cx-tool-icon" aria-hidden>
                      <Wrench size={15} />
                    </span>
                    <div className="cx-tool-main">
                      <div className="cx-tool-title">
                        <b>{t.name}</b>
                        <code>{t.id}</code>
                      </div>
                      <p>{t.description}</p>
                      <div className="cx-tags">
                        <span
                          className={`cx-tag ${
                            t.access === "write" ? "warn" : ""
                          }`}
                        >
                          {t.access === "write"
                            ? "Can change data"
                            : "Read only"}
                        </span>
                        {t.requires_approval && (
                          <span className="cx-tag ok">
                            <ShieldCheck size={11} aria-hidden /> Asks first
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="cx-used">
                      {users.length === 0 ? (
                        <span className="subtle-text">Not used yet</span>
                      ) : (
                        <>
                          <small>Used by</small>
                          {users.slice(0, 2).map((a) => (
                            <Link key={a.id} to={`/agents/${a.id}`}>
                              {a.name}
                            </Link>
                          ))}
                          {users.length > 2 && (
                            <span className="subtle-text">
                              +{users.length - 2} more
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </>
      )}

      {/* Accounts Tab */}
      {tab === "Accounts" && (
        <>
          <div className="section-heading">
            <h2>Email accounts</h2>
            <span className="subtle-text">
              OAuth connections stored locally
            </span>
          </div>

          {accountsError && (
            <div className="cx-note bad">
              Couldn’t load accounts: {accountsError}{" "}
              <button className="subtle-button" onClick={load}>
                Retry
              </button>
            </div>
          )}

          {accounts.length > 0 && (
            <div className="cx-accounts-list">
              {accounts.map((account) => (
                <article className="connect-card" key={account.id}>
                  <div className={`provider-logo ${account.provider}`}>
                    {account.provider === "google" ? "G" : "▦"}
                  </div>
                  <div className="connect-card-content">
                    <h3>{account.display_name || account.email}</h3>
                    <p>
                      {account.email} · {account.status}
                    </p>
                    <div className="connect-features">
                      <span>
                        <Mail size={13} /> Mail
                      </span>
                      {account.has_calendar && (
                        <span>
                          <CalendarDays size={13} /> Calendar
                        </span>
                      )}
                    </div>
                    {account.last_error && (
                      <p className="cx-note bad">{account.last_error}</p>
                    )}
                  </div>
                  <button
                    className="outline-button"
                    disabled={accountBusy === account.id}
                    onClick={() => disconnectAccount(account)}
                  >
                    {accountBusy === account.id
                      ? "Disconnecting…"
                      : "Disconnect"}
                  </button>
                </article>
              ))}
            </div>
          )}

          <div className="connect-grid">
            <article className="connect-card">
              <div className="provider-logo google">G</div>
              <div className="connect-card-content">
                <h3>Google</h3>
                <p>Connect Gmail using Google OAuth.</p>
                <div className="connect-features">
                  <span>
                    <Mail size={13} /> Gmail
                  </span>
                </div>
              </div>
              <button
                className="outline-button"
                disabled={accountBusy === "google"}
                onClick={() => connectAccount("google")}
              >
                {accountBusy === "google" ? "Opening…" : "Connect"}{" "}
                <ExternalLink size={13} />
              </button>
            </article>

            <article className="connect-card">
              <div className="provider-logo microsoft">▦</div>
              <div className="connect-card-content">
                <h3>Microsoft</h3>
                <p>Connect Outlook mail through Microsoft Graph.</p>
                <div className="connect-features">
                  <span>
                    <Mail size={13} /> Outlook Mail
                  </span>
                </div>
              </div>
              <button
                className="outline-button"
                disabled={accountBusy === "microsoft"}
                onClick={() => connectAccount("microsoft")}
              >
                {accountBusy === "microsoft" ? "Opening…" : "Connect"}{" "}
                <ExternalLink size={13} />
              </button>
            </article>
          </div>

          <div className="security-note">
            <ShieldCheck size={18} />
            <div>
              <strong>Credentials stay on your device</strong>
              <p>
                Refresh tokens are stored by the local backend in the operating
                system credential store. OAuth requires provider client IDs and
                redirect URI configuration.
              </p>
            </div>
          </div>
        </>
      )}

      {/* MCP Servers Tab */}
      {tab === "MCP servers" && (
        <>
          <div className="section-heading">
            <h2>MCP servers</h2>
            <button className="primary-button" onClick={() => setAdding(true)}>
              <Plus size={14} /> Add server
            </button>
          </div>

          {serversError && (
            <div className="cx-note bad">
              Couldn’t load MCP servers: {serversError}{" "}
              <button className="subtle-button" onClick={load}>
                Try again
              </button>
            </div>
          )}

          {servers === null && <p className="subtle-text">Loading…</p>}

          {servers?.length === 0 && !serversError && (
            <div className="mcp-card">
              <div className="mcp-symbol">
                <Command size={18} />
              </div>
              <div className="mcp-copy">
                <h3>No MCP servers connected</h3>
                <p>
                  Add a remote HTTP(S) MCP endpoint. Local stdio process
                  launching is intentionally disabled by the backend for
                  security.
                </p>
                <span className="subtle-text">
                  Their tools appear in the Tools tab and in the agent builder
                  once connected.
                </span>
              </div>
            </div>
          )}

          {servers?.map((s) => (
            <article className={`cx-server ${s.status}`} key={s.id}>
              <div className="cx-server-head">
                <span className="mcp-symbol">
                  <Command size={18} />
                </span>
                <div className="cx-server-title">
                  <h3>
                    {s.name}
                    <span className={`cx-status ${s.status}`}>
                      <i />
                      {s.status === "connected"
                        ? "Connected"
                        : s.status === "error"
                          ? "Needs attention"
                          : "Off"}
                    </span>
                  </h3>
                  <code>{s.transport === "stdio" ? s.command : s.url}</code>
                </div>
                <div className="cx-server-actions">
                  <button
                    className="bare-icon"
                    aria-label={`Refresh tools for ${s.name}`}
                    title="Refresh tools"
                    disabled={busy === s.id || !s.enabled}
                    onClick={() => refresh(s)}
                  >
                    <RefreshCw
                      size={15}
                      className={busy === s.id ? "spin" : ""}
                    />
                  </button>
                  <button
                    className="bare-icon"
                    aria-label={`Remove ${s.name}`}
                    title="Remove"
                    onClick={() => setToRemove(s)}
                  >
                    <Trash2 size={15} />
                  </button>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={s.enabled}
                    aria-label={`${s.enabled ? "Turn off" : "Turn on"} ${
                      s.name
                    }`}
                    className={`cx-switch ${s.enabled ? "on" : ""}`}
                    disabled={busy === s.id}
                    onClick={() => toggle(s)}
                  >
                    <span />
                  </button>
                </div>
              </div>
              {s.error && <p className="cx-err">{s.error}</p>}
              <details className="cx-server-tools">
                <summary>
                  {s.tools.length} tool{s.tools.length === 1 ? "" : "s"}
                </summary>
                {s.tools.length === 0 && (
                  <p className="subtle-text">No tools discovered yet.</p>
                )}
                {s.tools.map((t) => (
                  <div className="cx-mini" key={t.id}>
                    <div>
                      <b>{t.name}</b>
                      <code>{t.id}</code>
                      <p>{t.description}</p>
                    </div>
                    <span
                      className={`cx-tag ${t.access === "write" ? "warn" : ""}`}
                    >
                      {t.access === "write" ? "Can change data" : "Read only"}
                    </span>
                  </div>
                ))}
              </details>
            </article>
          ))}

          <div className="security-note">
            <ShieldCheck size={18} />
            <div>
              <strong>Review tools before enabling them</strong>
              <p>
                Local MCP commands may execute code. Review the command,
                environment, and permissions before connecting.
              </p>
            </div>
          </div>
        </>
      )}

      {/* Modal Dialogs */}
      {adding && (
        <AddServerDialog
          onClose={() => setAdding(false)}
          onAdded={(s) => {
            setAdding(false);
            notify?.(`${s.name} connected · ${s.tools.length} tools`);
            load();
          }}
        />
      )}

      <Dialog open={!!toRemove} onClose={() => setToRemove(null)}>
        {toRemove && (
          <>
            <h3>Remove “{toRemove.name}”?</h3>
            <p className="subtle-text">
              Its {toRemove.tools.length} tools will no longer be available.
              Agents that use them will skip those tools.
            </p>
            <div className="cx-actions">
              <button
                className="subtle-button"
                onClick={() => setToRemove(null)}
                autoFocus
              >
                Cancel
              </button>
              <button className="primary-button cx-danger" onClick={remove}>
                Remove server
              </button>
            </div>
          </>
        )}
      </Dialog>
    </div>
  );
}

function AddServerDialog({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: (s: McpServer) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const problem = !name.trim()
    ? "Give the server a name."
    : !/^https:\/\/.+/.test(url.trim())
      ? "Enter an HTTPS MCP URL."
      : "";

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      onAdded(
        await connectionsApi.add({
          name: name.trim(),
          transport: "http",
          url: url.trim(),
        }),
      );
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose}>
      <h3>Add MCP server</h3>
      <label className="cx-field">
        Name
        <input
          value={name}
          maxLength={120}
          placeholder="Research tools"
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </label>
      <label className="cx-field">
        HTTPS server URL
        <input
          value={url}
          placeholder="https://example.com/mcp"
          onChange={(e) => setUrl(e.target.value)}
        />
        <small>
          Local stdio commands are not executed by the backend. HTTP is
          restricted to HTTPS except for loopback URLs.
        </small>
      </label>

      {error && <div className="cx-note bad">{error}</div>}

      <div className="cx-actions">
        <button className="subtle-button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary-button"
          disabled={saving || !!problem}
          title={problem || undefined}
          onClick={submit}
        >
          {saving ? "Connecting…" : "Connect & list tools"}
        </button>
      </div>
    </Dialog>
  );
}

function Dialog({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="cx-dialog"
      onCancel={onClose}
      onClose={onClose}
    >
      {open && children}
    </dialog>
  );
}
