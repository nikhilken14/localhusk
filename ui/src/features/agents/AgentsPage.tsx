import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  Bot,
  ChevronRight,
  CircleHelp,
  Inbox,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";
import { agentsApi } from "./api";
import type { AgentCard } from "./types";
import type { AgentCardX } from "./ui-types";
import {
  DeleteDialog,
  RowMenu,
  RunDialog,
  StatusBadge,
  ago,
  hash,
  when,
} from "./shared";
import "./agents-page.css";

const ICONS = [Sun, Inbox, Search, Sparkles, Bot];
const TILES = ["amber", "blue", "green"];
const needsAttention = (a: AgentCard) =>
  a.last_run_status === "awaiting_approval" || a.last_run_status === "failed";

function footText(a: AgentCard): string {
  if (a.runs_7d > 0)
    return `${a.runs_7d} run${a.runs_7d === 1 ? "" : "s"} this week`;
  return a.last_run_at ? `Last run ${ago(a.last_run_at)}` : "Hasn’t run yet";
}
function activityTitle(a: AgentCard): string {
  switch (a.last_run_status) {
    case "completed":
      return `${a.name} completed a run`;
    case "awaiting_approval":
      return `${a.name} is awaiting approval`;
    case "failed":
      return `${a.name} failed its last run`;
    case "running":
      return `${a.name} is running`;
    default:
      return `${a.name} ran`;
  }
}

export function AgentsPage({ notify }: { notify: (m: string) => void }) {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentCard[] | null>(null);
  const [runsToday, setRunsToday] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [query, setQuery] = useState("");
  const [toRun, setToRun] = useState<AgentCard | null>(null);
  const [toDelete, setToDelete] = useState<AgentCard | null>(null);

  const load = useCallback(() => {
    setError("");
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    Promise.all([agentsApi.list(), agentsApi.overview(midnight)])
      .then(([a, o]) => {
        setAgents(a);
        setRunsToday(o.runs_today);
      })
      .catch((e) => {
        setAgents((cur) => cur ?? []);
        setError(e.message);
      });
  }, []);
  useEffect(load, [load]);

  const toggleStatus = async (a: AgentCard) => {
    const next = a.status === "active" ? "paused" : "active";
    try {
      await agentsApi.setStatus(a.id, next);
      notify(`${a.name} ${next === "paused" ? "paused" : "resumed"}`);
      load();
    } catch (e: any) {
      notify(e.message);
    }
  };
  const run = async (input: string) => {
    if (!toRun) return;
    try {
      await agentsApi.run(toRun.id, input);
      notify(`Running ${toRun.name}`);
      setToRun(null);
      setTimeout(load, 1500);
    } catch (e: any) {
      notify(e.message);
    }
  };
  const remove = async () => {
    if (!toDelete) return;
    try {
      await agentsApi.remove(toDelete.id);
      notify(`${toDelete.name} deleted`);
      setToDelete(null);
      load();
    } catch (e: any) {
      notify(e.message);
    }
  };

  const all = agents ?? [];
  const active = agents?.filter((a) => a.status === "active").length;
  const paused = agents ? agents.length - (active ?? 0) : 0;
  const attention = agents?.filter(needsAttention).length;
  const weekRuns = all.reduce((n, a) => n + (a.runs_7d || 0), 0);
  const q = query.trim().toLowerCase();
  const shown = all.filter(
    (a) =>
      (!onlyAttention || needsAttention(a)) &&
      (!q ||
        a.name.toLowerCase().includes(q) ||
        (a.description ?? "").toLowerCase().includes(q)),
  );
  const recent = all
    .filter((a) => a.last_run_at && a.last_run_id)
    .sort(
      (a, b) =>
        new Date(b.last_run_at!).getTime() - new Date(a.last_run_at!).getTime(),
    )
    .slice(0, 4);

  return (
    <div className="content-page ag">
      <header className="ag-head">
        <div>
          <h1>Agents</h1>
          <p>Purpose-built assistants for recurring work.</p>
        </div>
        <button
          className="primary-button"
          onClick={() => navigate("/agents/new")}
        >
          <Plus size={15} /> Create agent
        </button>
      </header>

      

      <section className="ag-stats" aria-label="Overview">
        <Stat
          label="Active agents"
          value={active}
          icon={<Bot size={17} />}
          detail={agents && (paused ? `${paused} paused` : "None paused")}
        />
        <Stat
          label="Runs today"
          value={runsToday}
          icon={<Activity size={17} />}
          detail={agents && `${weekRuns} this week`}
        />
        <Stat
          label="Needs attention"
          value={attention}
          icon={<CircleHelp size={17} />}
          detail={
            agents &&
            (attention
              ? onlyAttention
                ? "Showing only these"
                : "Select to filter"
              : "All clear")
          }
          tone={attention ? "warn" : undefined}
          pressed={onlyAttention}
          onClick={attention ? () => setOnlyAttention((v) => !v) : undefined}
        />
      </section>

      <div className="ag-list-head">
        <h2>Your agents</h2>
        <div className="ag-list-tools">
          {all.length > 0 && (
            <label className="ag-search">
              <Search size={14} aria-hidden />
              <input
                type="search"
                placeholder="Search agents"
                aria-label="Search agents"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
          )}
          <Link className="subtle-button" to="/automation/history">
            View activity <ArrowUpRight size={13} />
          </Link>
        </div>
      </div>
      {onlyAttention && (
        <p className="ag-muted">
          Showing agents that need attention.{" "}
          <button className="ag-link" onClick={() => setOnlyAttention(false)}>
            Show all
          </button>
        </p>
      )}

      {error && (
        <div className="ag-note bad">
          Couldn’t load agents: {error}{" "}
          <button className="subtle-button" onClick={load}>
            Try again
          </button>
        </div>
      )}
      {agents === null && <p className="ag-muted">Loading…</p>}
      {agents?.length === 0 && !error && (
        <div className="ag-empty">
          <Bot size={22} />
          <h3>You don’t have any agents yet</h3>
          <p>
            An agent is an assistant with a job: what to do, what it can use,
            and how it works.
          </p>
          <button
            className="primary-button"
            onClick={() => navigate("/agents/new")}
          >
            <Plus size={15} /> Create agent
          </button>
        </div>
      )}
      {all.length > 0 && shown.length === 0 && (
        <p className="ag-muted">
          No agents match{q ? ` “${query.trim()}”` : ""}.
        </p>
      )}

      {shown.length > 0 && (
        <div className="ag-grid">
          {shown.map((card) => {
            const a = card as AgentCardX;
            const Icon = ICONS[hash(a.id) % ICONS.length];
            const meta = [
              a.model,
              a.tool_count != null
                ? `${a.tool_count} tool${a.tool_count === 1 ? "" : "s"}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <article className="ag-card" key={a.id}>
                <div className="ag-card-top">
                  <div
                    className={`ag-tile ${TILES[hash(a.id) % 3]}`}
                    aria-hidden
                  >
                    <Icon size={19} />
                  </div>
                  <span className={`ag-pill ${a.status}`}>
                    <i />
                    {a.status === "active" ? "Active" : "Paused"}
                  </span>
                </div>
                <h3>
                  <Link to={`/agents/${a.id}`}>{a.name}</Link>
                </h3>
                <p className="ag-desc">
                  {a.description ||
                    (a.instructions.length > 110
                      ? a.instructions.slice(0, 110) + "…"
                      : a.instructions)}
                </p>
                {a.last_run_status === "awaiting_approval" && a.last_run_id && (
                  <Link
                    className="ag-badge warn"
                    to={`/agents/runs/${a.last_run_id}`}
                  >
                    Needs your approval
                  </Link>
                )}
                {a.last_run_status === "failed" && a.last_run_id && (
                  <Link
                    className="ag-badge bad"
                    to={`/agents/runs/${a.last_run_id}`}
                  >
                    Last run failed
                  </Link>
                )}
                {meta && <p className="ag-meta">{meta}</p>}
                <div className="ag-card-foot">
                  <span>{footText(a)}</span>
                  <RowMenu
                    name={a.name}
                    paused={a.status === "paused"}
                    onEdit={() => navigate(`/agents/${a.id}/edit`)}
                    onRun={() => setToRun(a)}
                    onToggle={() => toggleStatus(a)}
                    onDelete={() => setToDelete(a)}
                  />
                </div>
              </article>
            );
          })}
        </div>
      )}

      {recent.length > 0 && (
        <>
          <div className="ag-list-head">
            <h2>Recent activity</h2>
            <Link className="subtle-button" to="/automation/history">
              View all <ChevronRight size={13} />
            </Link>
          </div>
          <div className="ag-activity">
            {recent.map((a) => (
              <Link
                className="ag-act"
                key={a.id}
                to={`/agents/runs/${a.last_run_id}`}
              >
                <span className="ag-act-icon" aria-hidden>
                  <Activity size={15} />
                </span>
                <span className="ag-act-main">
                  <strong>{activityTitle(a)}</strong>
                  <small>{when(a.last_run_at!)}</small>
                </span>
                {a.last_run_status && (
                  <StatusBadge status={a.last_run_status} />
                )}
                <ChevronRight size={16} aria-hidden />
              </Link>
            ))}
          </div>
        </>
      )}

      <aside className="ag-callout">
        <ShieldCheck size={18} />
        <div>
          <strong>You stay in control</strong>
          <p>
            Agents use only enabled tools. Sending mail, deleting data and other
            sensitive actions should require approval.
          </p>
        </div>
      </aside>

      <RunDialog agent={toRun} onClose={() => setToRun(null)} onRun={run} />
      <DeleteDialog
        agent={toDelete}
        onClose={() => setToDelete(null)}
        onConfirm={remove}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  icon,
  detail,
  tone,
  onClick,
  pressed,
}: {
  label: string;
  value: number | null | undefined;
  icon: ReactNode;
  detail?: string | null;
  tone?: "warn";
  onClick?: () => void;
  pressed?: boolean;
}) {
  const body = (
    <>
      <span className="ag-stat-icon" aria-hidden>
        {icon}
      </span>
      <span>
        <small>{label}</small>
        <strong>{value ?? "–"}</strong>
        {detail && <em className={tone}>{detail}</em>}
      </span>
    </>
  );
  return onClick ? (
    <button
      className="ag-stat clickable"
      aria-pressed={pressed}
      onClick={onClick}
    >
      {body}
    </button>
  ) : (
    <div className="ag-stat">{body}</div>
  );
}
