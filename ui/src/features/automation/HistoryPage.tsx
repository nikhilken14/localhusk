import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowLeft,
  Calendar,
  Check,
  Clock,
  Filter,
  Search,
  X,
  ChevronRight,
} from "lucide-react";
import { agentsApi } from "../agents/api";
import { automationApi } from "../automation/automation";
import { StatusBadge, duration, when } from "../agents/shared";
import "../agents/agents-page.css";

interface ActivityItem {
  id: string;
  name: string;
  type: "agent" | "automation";
  status: string;
  startedAt: string;
  durationMs: number | null;
  toolCalls: number;
  link: string;
}

export function HistoryPage({ notify }: { notify?: (m: string) => void }) {
  const [items, setItems] = useState<ActivityItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "agent" | "automation">(
    "all",
  );
  const [error, setError] = useState("");

  const loadActivity = useCallback(async () => {
    setError("");
    try {
      // Use the durable run ledger, not one fabricated row per agent/job.
      const [agentsList, automationsList, runs] = await Promise.all([
        agentsApi.list(),
        automationApi.list(),
        agentsApi.allRuns(200),
      ]);
      const agentNames = new Map(agentsList.map((a: any) => [a.id, a.name]));
      const automationNames = new Map(automationsList.map((a: any) => [a.id, a.name]));
      const allItems: ActivityItem[] = runs.map((run: any) => {
        const isAutomation = Boolean(run.job_id);
        const label = isAutomation
          ? automationNames.get(run.job_id) ?? "Automation"
          : agentNames.get(run.agent_id) ?? "Agent run";
        return {
          id: run.id,
          name: `${label} · ${String(run.goal ?? "").slice(0, 90)}`,
          type: isAutomation ? "automation" : "agent",
          status: run.status,
          startedAt: run.started_at,
          durationMs: run.duration_ms,
          toolCalls: run.tool_calls,
          link: `/agents/runs/${run.id}`,
        };
      });
      setItems(allItems);
    } catch (e: any) {
      setError(e.message || "Failed to load run history");
      setItems([]);
    }
  }, []);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  // Filter items for the current week (last 7 days) and search query
  const filteredItems = useMemo(() => {
    if (!items) return [];
    const now = new Date().getTime();
    const oneWeekMs = 7 * 24 * 60 * 60 * 1000;

    return items.filter((item) => {
      const itemTime = new Date(item.startedAt).getTime();
      const isThisWeek = now - itemTime <= oneWeekMs;
      const matchesType = typeFilter === "all" || item.type === typeFilter;
      const matchesQuery =
        !query || item.name.toLowerCase().includes(query.toLowerCase());

      return isThisWeek && matchesType && matchesQuery;
    });
  }, [items, typeFilter, query]);

  return (
    <div className="content-page ag">
      <Link className="ag-back" to="/agents">
        <ArrowLeft size={14} /> Back to dashboard
      </Link>

      <header className="ag-head">
        <div>
          <h1>Activity & Run History</h1>
          <p>Monitor agent executions and automation runs across this week.</p>
        </div>
      </header>

      <div className="ag-list-head">
        <div
          className="ag-list-tools"
          style={{ width: "100%", justifyContent: "space-between" }}
        >
          <div
            style={{
              display: "flex",
              gap: "8px",
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <label className="ag-search">
              <Search size={14} aria-hidden />
              <input
                type="search"
                placeholder="Search run activity..."
                aria-label="Search run activity"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div
              className="filter-pills"
              style={{
                display: "flex",
                background: "var(--ag-soft)",
                padding: "2px",
                borderRadius: "8px",
              }}
            >
              <button
                className={typeFilter === "all" ? "selected" : ""}
                style={{
                  background:
                    typeFilter === "all" ? "var(--ag-surface)" : "transparent",
                  border: 0,
                  padding: "6px 12px",
                  borderRadius: "6px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
                onClick={() => setTypeFilter("all")}
              >
                All Runs
              </button>
              <button
                className={typeFilter === "agent" ? "selected" : ""}
                style={{
                  background:
                    typeFilter === "agent"
                      ? "var(--ag-surface)"
                      : "transparent",
                  border: 0,
                  padding: "6px 12px",
                  borderRadius: "6px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
                onClick={() => setTypeFilter("agent")}
              >
                Agent Runs
              </button>
              <button
                className={typeFilter === "automation" ? "selected" : ""}
                style={{
                  background:
                    typeFilter === "automation"
                      ? "var(--ag-surface)"
                      : "transparent",
                  border: 0,
                  padding: "6px 12px",
                  borderRadius: "6px",
                  fontSize: "11px",
                  cursor: "pointer",
                }}
                onClick={() => setTypeFilter("automation")}
              >
                Automations
              </button>
            </div>
          </div>
          <span
            className="ag-muted"
            style={{ display: "flex", alignItems: "center", gap: "5px" }}
          >
            <Calendar size={14} /> Showing this week
          </span>
        </div>
      </div>

      {error && (
        <div className="ag-note bad">
          Couldn’t load history: {error}{" "}
          <button className="subtle-button" onClick={loadActivity}>
            Try again
          </button>
        </div>
      )}

      {items === null && <p className="ag-muted">Loading weekly history...</p>}

      {items?.length === 0 && !error && (
        <div className="ag-empty">
          <Activity size={22} />
          <h3>No run history recorded</h3>
          <p>
            Runs triggered by your agents or scheduled automations will appear
            here.
          </p>
        </div>
      )}

      {filteredItems.length === 0 && items && items.length > 0 && (
        <p className="ag-muted">
          No runs match your current filter criteria for this week.
        </p>
      )}

      {filteredItems.length > 0 && (
        <div className="ag-activity">
          {filteredItems.map((item) => (
            <Link className="ag-act" key={item.id} to={item.link}>
              <span className="ag-act-icon" aria-hidden>
                <Activity size={15} />
              </span>
              <span className="ag-act-main">
                <strong>{item.name}</strong>
                <small>
                  {when(item.startedAt)} · Type: {item.type.toUpperCase()}
                </small>
              </span>
              <StatusBadge status={item.status} />
              <ChevronRight size={16} aria-hidden />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
