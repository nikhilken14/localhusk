import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, Check, ChevronRight, Clock, Plus, Search, Sparkles, Workflow, X } from "lucide-react";
import { automationApi, describeTrigger } from "./automation";
import type { Automation, EventInfo, Summary } from "./automation";
import { ActionMenu, Badge, DeleteAutomationDialog, Switch, jobStatus, needsAttention, pct } from "./automation-shared";
import { hash, when } from "../agents/shared";
import "../agents/agents-page.css"; // shared tokens, menu, dialog styles
import "./automation.css";

const TILES = ["amber", "blue", "green"];
type Filter = "all" | "active" | "paused" | "attention";

function nextRunText(a: Automation): string {
  if (!a.enabled) return "Paused";
  if (a.next_run_at) return when(a.next_run_at);
  if (a.trigger_type === "event") return "When it happens";
  if (a.trigger_type === "manual") return "Only when run";
  return "–";
}
function flowText(a: Automation): string {
  const f = a.flow_summary ?? [];
  return f.length > 3 ? `${f.slice(0, 3).join(" → ")} +${f.length - 3}` : f.join(" → ");
}
const ACT: Record<string, [text: string, tone: "ok" | "warn" | "bad" | "off"]> = {
  completed: ["Completed successfully", "ok"],
  awaiting_approval: ["Waiting for your approval", "warn"],
  failed: ["Run failed", "bad"],
  running: ["Running now", "off"],
  queued: ["Queued", "off"],
  cancelled: ["Cancelled", "off"],
};

export function AutomationPage({ notify, onNewAutomation, onEditAutomation }: {
  notify?: (m: string) => void; onNewAutomation?: () => void; onEditAutomation?: (id: string) => void;
}) {
  const navigate = useNavigate();
  const say = (m: string) => notify?.(m);
  const [jobs, setJobs] = useState<Automation[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [events, setEvents] = useState<EventInfo[]>([]);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Automation | null>(null);

  const load = useCallback(() => {
    setError("");
    Promise.all([automationApi.list(), automationApi.summary().catch(() => null), automationApi.events().catch(() => [] as EventInfo[])])
      .then(([j, s, e]) => { setJobs(j); setSummary(s); setEvents(e); })
      .catch((e) => { setJobs((cur) => cur ?? []); setError(e.message); });
  }, []);
  useEffect(load, [load]);

  const create = () => (onNewAutomation ? onNewAutomation() : navigate("/automation/new"));
  const edit = (id: string) => (onEditAutomation ? onEditAutomation(id) : navigate(`/automation/${id}/edit`));

  const toggle = async (a: Automation) => {
    const next = !a.enabled;
    setJobs((cur) => cur && cur.map((j) => (j.id === a.id ? { ...j, enabled: next } : j)));
    try { await automationApi.setEnabled(a.id, next); say(`${a.name} ${next ? "turned on" : "paused"}`); load(); }
    catch (e: any) { setJobs((cur) => cur && cur.map((j) => (j.id === a.id ? { ...j, enabled: !next } : j))); say(e.message); }
  };
  const run = async (a: Automation) => {
    setBusy(a.id);
    try { const result = await automationApi.run(a.id); say(result.status === "skipped" ? `${a.name} already has a run in progress` : `Running ${a.name}`); setTimeout(load, 1200); }
    catch (e: any) { say(e.message); }
    finally { setBusy(null); }
  };
  const remove = async () => {
    if (!toDelete) return;
    try { await automationApi.remove(toDelete.id); say(`${toDelete.name} deleted`); setToDelete(null); load(); }
    catch (e: any) { say(e.message); }
  };

  const all = jobs ?? [];
  const active = all.filter((a) => a.enabled).length;
  const attention = all.filter(needsAttention).length;
  const q = query.trim().toLowerCase();
  const shown = all.filter((a) =>
    (filter === "all" || (filter === "active" && a.enabled) || (filter === "paused" && !a.enabled) || (filter === "attention" && needsAttention(a))) &&
    (!q || a.name.toLowerCase().includes(q) || (a.agent_name ?? "").toLowerCase().includes(q)));
  const recent = all.filter((a) => a.last_run_at && a.last_run_id)
    .sort((a, b) => new Date(b.last_run_at!).getTime() - new Date(a.last_run_at!).getTime()).slice(0, 4);

  return (
    <div className="content-page ag au">
      <header className="ag-head">
        <div>
          <h1>Automation</h1>
          <p>Connect triggers, tools, and agents so work happens on its own.</p>
        </div>
        <button className="primary-button" onClick={create}><Plus size={15} /> New automation</button>
      </header>

      

      <section className="au-stats" aria-label="Overview">
        <Stat label="Automations" value={jobs ? summary?.workflows ?? all.length : null} detail={jobs && `${active} active`} />
        <Stat label="Runs this week" value={summary?.runs_7d ?? null}
          detail={summary && (summary.success_rate != null ? `${pct(summary.success_rate)} succeeded` : "No runs yet")} />
        <Stat label="Next run" text value={summary ? (summary.next_run ? when(summary.next_run.at) : "None scheduled") : null}
          detail={summary?.next_run?.name} />
        <Stat label="Needs attention" value={jobs ? attention : null} tone={attention ? "warn" : undefined}
          detail={jobs && (attention ? (filter === "attention" ? "Showing only these" : "Select to filter") : "All clear")}
          pressed={filter === "attention"} onClick={attention ? () => setFilter((f) => (f === "attention" ? "all" : "attention")) : undefined} />
      </section>

      <div className="ag-list-head">
        <h2>Your automations</h2>
        <div className="ag-list-tools">
          {all.length > 0 && (
            <>
              <label className="ag-search"><Search size={14} aria-hidden />
                <input type="search" placeholder="Search automations" aria-label="Search automations" value={query} onChange={(e) => setQuery(e.target.value)} />
              </label>
              <select className="au-select" aria-label="Filter automations" value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
                <option value="all">All</option><option value="active">Active</option><option value="paused">Paused</option><option value="attention">Needs attention</option>
              </select>
            </>
          )}
          <Link className="subtle-button" to="/automation/history">View activity <ArrowUpRight size={13} /></Link>
        </div>
      </div>

      {error && <div className="ag-note bad">Couldn’t load automations: {error} <button className="subtle-button" onClick={load}>Try again</button></div>}
      {jobs === null && <p className="ag-muted">Loading…</p>}
      {jobs?.length === 0 && !error && (
        <div className="ag-empty">
          <Workflow size={22} />
          <h3>No automations yet</h3>
          <p>An automation runs an agent for you on a schedule, or when something happens.</p>
          <button className="primary-button" onClick={create}><Plus size={15} /> Create your first automation</button>
        </div>
      )}
      {all.length > 0 && shown.length === 0 && <p className="ag-muted">No automations match.{" "}<button className="ag-link" onClick={() => { setQuery(""); setFilter("all"); }}>Clear filters</button></p>}

      {shown.length > 0 && (
        <section className="au-table" aria-label="Automations">
          <div className="au-row head" aria-hidden>
            <span>Automation</span><span>Agent</span><span>Schedule</span><span>Next run</span><span>Last run</span><span>Status</span><span />
          </div>
          {shown.map((a) => {
            const st = jobStatus(a);
            return (
              <div className="au-row" key={a.id}>
                <div className="au-job">
                  <div className={`ag-tile ${TILES[hash(a.id) % 3]}`} aria-hidden><Workflow size={17} /></div>
                  <div>
                    <Link className="au-name" to={`/automation/${a.id}`}>{a.name}</Link>
                    {flowText(a) && <small>{flowText(a)}</small>}
                  </div>
                </div>
                <div data-label="Agent">
                  <span>{a.agent_name ?? "No agent"}</span>
                  {a.enabled && a.agent_status === "paused" && <small className="warn">Agent is paused</small>}
                </div>
                <div data-label="Schedule"><span>{describeTrigger(a, events)}</span>{a.trigger_config?.timezone && a.trigger_type !== "event" && a.trigger_type !== "manual" && <small>{a.trigger_config.timezone.replace("_", " ")}</small>}</div>
                <div data-label="Next run"><span>{nextRunText(a)}</span></div>
                <div data-label="Last run">
                  <span>{a.last_run_at ? when(a.last_run_at) : "Never"}</span>
                  <small>{a.run_count} run{a.run_count === 1 ? "" : "s"} total</small>
                </div>
                <div data-label="Status"><Badge label={st.label} tone={st.tone} /></div>
                <div className="au-actions">
                  <Switch on={a.enabled} label={`${a.enabled ? "Pause" : "Turn on"} ${a.name}`} onChange={() => toggle(a)} />
                  <ActionMenu name={a.name} enabled={a.enabled} onRun={busy === a.id ? undefined : () => run(a)} onEdit={() => edit(a.id)} onToggle={() => toggle(a)} onDelete={() => setToDelete(a)} />
                </div>
              </div>
            );
          })}
        </section>
      )}

      <div className="au-bottom">
        <section className="agd-card">
          <div className="agd-card-head"><div><h2>Recent activity</h2><p>Latest automation runs</p></div><Link className="ag-link" to="/automation/history">View all <ChevronRight size={13} /></Link></div>
          {recent.length === 0 && <p className="ag-muted">Nothing has run yet.</p>}
          <div className="au-feed">
            {recent.map((a) => {
              const [text, tone] = ACT[a.last_run_status ?? "completed"] ?? ACT.completed;
              // Prefer the automation detail page so the user lands on the job, not the agent run shell.
              const href = `/automation/${a.id}`;
              return (
                <Link className="au-feed-row" key={a.id} to={href}>
                  <span className={`au-feed-icon ${tone}`} aria-hidden>{tone === "ok" ? <Check size={14} /> : tone === "bad" ? <X size={14} /> : <Clock size={14} />}</span>
                  <span className="au-feed-main"><strong>{a.name}</strong><small>{text}</small></span>
                  <time dateTime={a.last_run_at!}>{when(a.last_run_at!)}</time>
                </Link>
              );
            })}
          </div>
        </section>
        <aside className="au-promo">
          <span className="ag-stat-icon" aria-hidden><Sparkles size={17} /></span>
          <h2>Make work predictable</h2>
          <p>Automations run with your permissions, respect approval rules, and keep a clear record of every result.</p>
          <button className="subtle-button" onClick={create}>{all.length ? "Create another automation" : "Create your first automation"} <ArrowUpRight size={13} /></button>
        </aside>
      </div>

      <DeleteAutomationDialog name={toDelete?.name ?? null} onClose={() => setToDelete(null)} onConfirm={remove} />
    </div>
  );
}

function Stat({ label, value, detail, tone, text, onClick, pressed }:
  { label: string; value: ReactNode; detail?: string | null; tone?: "warn"; text?: boolean; onClick?: () => void; pressed?: boolean }) {
  const body = (
    <>
      <small>{label}</small>
      <strong className={text ? "text" : ""}>{value ?? "–"}</strong>
      {detail && <em className={tone}>{detail}</em>}
    </>
  );
  return onClick
    ? <button className="au-stat clickable" aria-pressed={pressed} onClick={onClick}>{body}</button>
    : <div className="au-stat">{body}</div>;
}
