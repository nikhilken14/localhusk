import { API_BASE_URL } from "../../api-base";
import React, { useCallback, useEffect, useState } from "react";
import "./logs.css";
import {
  Terminal,
  RefreshCw,
  Trash2,
  Search,
  ChevronDown,
  ChevronRight,
  Download,
} from "lucide-react";

interface ApiLogEntry {
  id: number;
  created_at: string;
  level: string;
  category: string;
  logger: string;
  message: string;
  details?: Record<string, unknown> | string;
}
interface LogsPageResponse {
  items?: ApiLogEntry[];
  total?: number;
  limit?: number;
  offset?: number;
}
interface LogEntry {
  id: number;
  timestamp: string;
  category: string;
  level: string;
  source: string;
  message: string;
  details?: string;
}

export function LogsPage({ notify }: { notify?: (msg: string) => void }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [activeCategory, setActiveCategory] = useState("all");
  const [filterLevel, setFilterLevel] = useState("ALL");
  const [search, setSearch] = useState("");
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (activeCategory !== "all") params.set("category", activeCategory);
      if (filterLevel !== "ALL")
        params.set("level", filterLevel === "WARN" ? "WARNING" : filterLevel);
      params.set("limit", "200");
      const response = await fetch(`${API_BASE_URL}/logs?${params.toString()}`);
      if (!response.ok)
        throw new Error(`Logs request failed (${response.status})`);
      const payload = (await response.json()) as
        | LogsPageResponse
        | ApiLogEntry[];
      const rows = Array.isArray(payload) ? payload : (payload.items ?? []);
      setLogs(
        rows.map((row) => ({
          id: row.id,
          timestamp: row.created_at
            ? new Date(row.created_at).toLocaleString()
            : "Unknown time",
          category: row.category || "system",
          level:
            (row.level || "INFO").toUpperCase() === "WARNING"
              ? "WARN"
              : (row.level || "INFO").toUpperCase(),
          source: row.logger || row.category || "system",
          message: row.message || "",
          details:
            typeof row.details === "string"
              ? row.details
              : row.details && Object.keys(row.details).length
                ? JSON.stringify(row.details, null, 2)
                : undefined,
        })),
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch system logs";
      setError(message);
      notify?.(message);
    } finally {
      setLoading(false);
    }
  }, [activeCategory, filterLevel, notify]);

  useEffect(() => {
    void fetchLogs();
    const interval = window.setInterval(() => void fetchLogs(), 5000);
    return () => window.clearInterval(interval);
  }, [fetchLogs]);

  const clearLogs = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/logs`, {
        method: "DELETE",
      });
      if (!response.ok)
        throw new Error(`Clear logs failed (${response.status})`);
      setLogs([]);
      notify?.("Log history cleared");
    } catch (err) {
      notify?.(err instanceof Error ? err.message : "Failed to clear logs");
    }
  };

  const exportLogs = () => {
    const blob = new Blob([JSON.stringify(logs, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `husk_logs_${Date.now()}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    notify?.("Logs exported as JSON");
  };

  const needle = search.trim().toLowerCase();
  const filteredLogs = logs.filter(
    (log) =>
      !needle ||
      log.message.toLowerCase().includes(needle) ||
      log.source.toLowerCase().includes(needle),
  );

  return (
    <div className="logs-page">
      <div className="page-heading">
        <div>
          <h1>Execution Logs &amp; Diagnostics</h1>
          <p>
            Real-time telemetry traces for LLM API calls, agent tool
            invocations, and automation jobs.
          </p>
        </div>
        <div className="heading-action" style={{ display: "flex", gap: 8 }}>
          <button className="outline-button" onClick={exportLogs}>
            <Download size={14} /> Export
          </button>
          <button
            className="outline-button"
            onClick={() => void fetchLogs()}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? "spin" : ""} /> Refresh
          </button>
          <button className="subtle-button" onClick={() => void clearLogs()}>
            <Trash2 size={14} /> Clear
          </button>
        </div>
      </div>
      {error && (
        <div className="cx-note bad" role="alert">
          Could not load logs: {error}{" "}
          <button className="subtle-button" onClick={() => void fetchLogs()}>
            Retry
          </button>
        </div>
      )}
      <div className="toolbar" style={{ marginBottom: 16 }}>
        <div className="filter-pills">
          {[
            ["all", "All"],
            ["llm", "LLM"],
            ["agent", "Agents"],
            ["automation", "Automation"],
          ].map(([value, label]) => (
            <button
              key={value}
              className={activeCategory === value ? "selected" : ""}
              onClick={() => setActiveCategory(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={filterLevel}
            onChange={(e) => setFilterLevel(e.target.value)}
            style={{
              background: "var(--surface)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              padding: "6px 10px",
              fontSize: 11,
              color: "var(--text)",
            }}
          >
            <option value="ALL">All Levels</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARN">WARN</option>
            <option value="ERROR">ERROR</option>
          </select>
          <div className="search-box" style={{ width: 220 }}>
            <Search size={14} />
            <input
              placeholder="Search logs..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>
      </div>
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: 10,
          fontFamily: "monospace",
          fontSize: 11,
          overflow: "hidden",
          minHeight: 400,
        }}
      >
        {loading && logs.length === 0 ? (
          <div className="empty-state" style={{ padding: 60 }}>
            <RefreshCw size={20} className="spin" />
            <strong>Loading logs…</strong>
          </div>
        ) : filteredLogs.length === 0 ? (
          <div className="empty-state" style={{ padding: 60 }}>
            <div className="empty-icon">
              <Terminal size={20} />
            </div>
            <strong>
              {error
                ? "Logs are temporarily unavailable"
                : "No logs recorded yet"}
            </strong>
            <p>
              {error
                ? "Check that the Husk backend is running, then retry."
                : "Execute chat requests, run agent workflows, or trigger automations to see diagnostic traces here."}
            </p>
            <button className="outline-button" onClick={() => void fetchLogs()}>
              Refresh logs
            </button>
          </div>
        ) : (
          filteredLogs.map((log) => {
            const expanded = expandedLogId === log.id;
            return (
              <div
                key={log.id}
                style={{
                  padding: "12px 16px",
                  borderBottom: "1px solid var(--line)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  cursor: log.details ? "pointer" : "default",
                }}
                onClick={() =>
                  log.details && setExpandedLogId(expanded ? null : log.id)
                }
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ color: "var(--muted)", fontSize: 10 }}>
                    [{log.timestamp}]
                  </span>
                  <span
                    style={{
                      padding: "2px 6px",
                      borderRadius: 4,
                      fontSize: 9,
                      fontWeight: 700,
                      background:
                        log.level === "ERROR"
                          ? "var(--red-bg)"
                          : log.level === "WARN"
                            ? "var(--yellow-bg)"
                            : "var(--surface-2)",
                      color:
                        log.level === "ERROR"
                          ? "#b75e58"
                          : log.level === "WARN"
                            ? "#a17c25"
                            : "var(--muted)",
                    }}
                  >
                    {log.level}
                  </span>
                  <strong style={{ color: "var(--text)" }}>{log.source}</strong>
                  <span
                    style={{
                      marginLeft: "auto",
                      color: "var(--muted)",
                      fontSize: 9,
                    }}
                  >
                    {log.category.toUpperCase()}
                  </span>
                  {log.details &&
                    (expanded ? (
                      <ChevronDown size={14} />
                    ) : (
                      <ChevronRight size={14} />
                    ))}
                </div>
                <div style={{ color: "var(--text)", marginTop: 2 }}>
                  {log.message}
                </div>
                {expanded && log.details && (
                  <pre
                    style={{
                      background: "var(--surface-2)",
                      padding: 10,
                      borderRadius: 6,
                      margin: "8px 0 0",
                      overflowX: "auto",
                      color: "var(--muted)",
                      fontSize: 10,
                    }}
                  >
                    {log.details}
                  </pre>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
