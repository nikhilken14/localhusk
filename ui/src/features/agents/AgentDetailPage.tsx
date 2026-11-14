import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Activity, ArrowLeft, Bot, Check, ChevronRight, Clock, Inbox, Pencil, Play, Search, Sparkles, Sun, Wrench } from "lucide-react";
import { agentsApi } from "./api";
import type { AgentLike, AgentRun } from "./ui-types";
import { DeleteDialog, RowMenu, RunDialog, StatusBadge, ago, duration, hash, runLabel, runTone, when } from "./shared";
import "./agents-page.css";

const ICONS = [Sun, Inbox, Search, Sparkles, Bot];
const TILES = ["amber", "blue", "green"];
const FILTERS = [["all", "All runs"], ["completed", "Completed"], ["awaiting_approval", "Needs approval"], ["failed", "Failed"]] as const;
const PAGE = 5;

export function AgentDetailPage({ notify }: { notify: (m: string) => void }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [agent, setAgent] = useState<AgentLike | null>(null);
  const [runs, setRuns] = useState<AgentRun[] | null>(null);
  const [sample, setSample] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"overview" | "config">("overview");
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("all");
  const [shown, setShown] = useState(PAGE);
  const [runOpen, setRunOpen] = useState(false);
  const [delOpen, setDelOpen] = useState(false);

  const load = useCallback(async () => {
    setError("");
    let a: AgentLike;
    try { a = (await agentsApi.get(id)) as unknown as AgentLike; setAgent(a); }
    catch (e: any) { setError(e.message); return; }
    try { setRuns(await agentsApi.runs(id)); setSample(false); }
    catch (e) { setRuns([]); setSample(false); notify(e instanceof Error ? `Unable to load run history: ${e.message}` : "Unable to load run history"); }
  }, [id]);
  useEffect(() => { setAgent(null); setRuns(null); setTab("overview"); setFilter("all"); setShown(PAGE); load(); }, [load]);

  const stats = useMemo(() => {
    const r = runs ?? [];
    const done = r.filter((x) => x.status === "completed").length;
    const finished = r.filter((x) => x.status === "completed" || x.status === "failed").length;
    const calls = r.reduce((n, x) => n + x.tool_calls, 0);
    const durs = r.filter((x) => x.duration_ms != null).map((x) => x.duration_ms as number);
    return {
      total: r.length, done, calls,
      perRun: r.length ? (calls / r.length).toFixed(1) : "0",
      avg: durs.length ? durs.reduce((a, b) => a + b, 0) / durs.length : null,
      rate: finished ? Math.round((done / finished) * 1000) / 10 : null,
    };
  }, [runs]);

  const toggle = async () => {
    if (!agent) return;
    const next = agent.status === "active" ? "paused" : "active";
    try { await agentsApi.setStatus(agent.id, next); notify(`${agent.name} ${next === "paused" ? "paused" : "resumed"}`); load(); }
    catch (e: any) { notify(e.message); }
  };
  const run = async (input: string, files: File[] = []) => {
    if (!agent) return;
    try {
      const attachmentIds: string[] = [];
      for (const file of files) {
        try {
          const uploaded = await agentsApi.uploadAttachment(agent.id, file);
          attachmentIds.push(uploaded.id);
        } catch (upErr: any) {
          throw new Error(`Could not attach “${file.name}”: ${upErr?.message || "upload failed"}`);
        }
      }
      await agentsApi.run(agent.id, input, attachmentIds);
      notify(
        attachmentIds.length
          ? `Running ${agent.name} with ${attachmentIds.length} document${attachmentIds.length === 1 ? "" : "s"}`
          : `Running ${agent.name}`,
      );
      setRunOpen(false);
      setTimeout(load, 1500);
    } catch (e) {
      notify(e instanceof Error ? e.message : "Unable to start run");
    }
  };

  const remove = async () => {
    if (!agent) return;
    try { await agentsApi.remove(agent.id); notify(`${agent.name} deleted`); navigate("/agents"); }
    catch (e: any) { notify(e.message); }
  };

  if (error) return (
    <div className="content-page ag">
      <Link className="ag-back" to="/agents"><ArrowLeft size={14} /> Back to agents</Link>
      <div className="ag-note bad">Couldn’t load this agent: {error} <button className="subtle-button" onClick={load}>Try again</button></div>
    </div>
  );
  if (!agent) return <div className="content-page ag"><p className="ag-muted">Loading…</p></div>;

  const paused = agent.status === "paused";
  const Icon = ICONS[hash(agent.id) % ICONS.length];
  const latest = runs?.[0];
  const filtered = (runs ?? []).filter((r) => filter === "all" || r.status === filter);
  const toolCount = agent.tools?.length ?? agent.tool_count ?? null;

  return (
    <div className="content-page ag agd">
      <Link className="ag-back" to="/agents"><ArrowLeft size={14} /> Back to agents</Link>

      <header className="agd-head">
        <div className="agd-title">
          <div className={`ag-tile lg ${TILES[hash(agent.id) % 3]}`} aria-hidden><Icon size={22} /></div>
          <div>
            <div className="agd-title-line">
              <h1>{agent.name}</h1>
              <span className={`ag-pill ${agent.status}`}><i />{paused ? "Paused" : "Active"}</span>
            </div>
            <p>{agent.description || "No description yet."}</p>
          </div>
        </div>
        <div className="agd-actions">
          <Link className="subtle-button" to={`/agents/${agent.id}/edit`}><Pencil size={14} /> Edit agent</Link>
          <button className="primary-button" disabled={paused} title={paused ? "Resume this agent to run it" : undefined} onClick={() => setRunOpen(true)}><Play size={14} /> Run now</button>
          <RowMenu name={agent.name} paused={paused} onToggle={toggle} onDelete={() => setDelOpen(true)} />
        </div>
      </header>

      <div className="agd-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "overview"} className={tab === "overview" ? "on" : ""} onClick={() => setTab("overview")}>Overview{runs && <b>{runs.length}</b>}</button>
        <button role="tab" aria-selected={tab === "config"} className={tab === "config" ? "on" : ""} onClick={() => setTab("config")}>Configuration</button>
        {sample && <span className="agd-sample" title="Run history isn’t connected yet">Sample data</span>}
      </div>

      {tab === "overview" && (
        <>
          {latest && (latest.status === "awaiting_approval" || latest.status === "failed") && (
            <div className={`ag-note ${runTone(latest.status) === "bad" ? "bad" : "warn"}`}>
              {latest.status === "failed" ? "The last run failed." : "The last run is waiting for your approval."}{" "}
              <Link className="ag-link" to={`/agents/runs/${latest.id}`}>Open run</Link>
            </div>
          )}

          <section className="agd-metrics" aria-label="Metrics">
            <Metric icon={<Activity size={16} />} label="Runs" value={runs ? String(stats.total) : "–"} detail={`${agent.runs_7d ?? 0} in the last 7 days`} />
            <Metric icon={<Wrench size={16} />} label="Tool calls" value={runs ? stats.calls.toLocaleString() : "–"} detail={`${stats.perRun} per run`} />
            <Metric icon={<Clock size={16} />} label="Avg. duration" value={duration(stats.avg)} detail="Finished runs" />
            <Metric icon={<Check size={16} />} label="Success rate" value={stats.rate == null ? "–" : `${stats.rate}%`} detail={`${stats.done} completed`} />
          </section>

          <div className="agd-grid">
            <section className="agd-card">
              <div className="agd-card-head">
                <div><h2>Run history</h2><p>Inspect every execution, tool call, and decision.</p></div>
                <select aria-label="Filter runs" value={filter} onChange={(e) => { setFilter(e.target.value as typeof filter); setShown(PAGE); }}>
                  {FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
              {runs === null && <p className="ag-muted">Loading runs…</p>}
              {runs?.length === 0 && <div className="ag-empty slim"><h3>No runs yet</h3><p>Run it once to see the history here.</p></div>}
              {runs && runs.length > 0 && filtered.length === 0 && <p className="ag-muted">No runs match this filter.</p>}
              {filtered.length > 0 && (
                <div className="agd-table-wrap">
                  <div className="agd-table" role="table">
                    <div className="agd-row head" role="row"><span>Run</span><span>Status</span><span>Started</span><span>Duration</span><span>Tool calls</span><span /></div>
                    {filtered.slice(0, shown).map((r) => (
                      <Link className="agd-row" role="row" key={r.id} to={`/agents/runs/${r.id}`}>
                        <span><strong>{r.id.slice(-8)}</strong><small><Sparkles size={11} /> {r.model ? `${r.model} · ` : ""}{r.tokens == null ? "Usage not reported" : `${r.tokens.toLocaleString()} tokens`}</small></span>
                        <StatusBadge status={r.status} />
                        <span>{when(r.started_at)}</span>
                        <span>{duration(r.duration_ms)}</span>
                        <span>{r.tool_calls}</span>
                        <ChevronRight size={16} aria-hidden />
                      </Link>
                    ))}
                  </div>
                </div>
              )}
              {filtered.length > shown && <button className="ag-link more" onClick={() => setShown((n) => n + PAGE)}>Load more runs ({filtered.length - shown} more)</button>}
            </section>

            <aside className="agd-rail">
              <section className="agd-card">
                <h3>Agent health</h3>
                <Line label="Status" value={paused ? "Paused" : "Active"} />
                <Line label="Last run" value={latest ? when(latest.started_at) : "Never"} />
                <Line label="Next scheduled run" value={paused ? "Paused" : agent.next_run_at ? when(agent.next_run_at) : "Not scheduled"} />
                <Line label="Recent success" value={stats.rate == null ? "–" : `${stats.done} of ${stats.total} runs`} />
                <button className="ag-link" onClick={() => setTab("config")}>View configuration <ChevronRight size={13} /></button>
              </section>
              <section className="agd-card">
                <h3>Latest activity</h3>
                {!runs?.length && <p className="ag-muted">Nothing yet.</p>}
                <ol className="agd-timeline">
                  {(runs ?? []).slice(0, 3).map((r) => (
                    <li key={r.id}>
                      <span className={`agd-dot ${runTone(r.status)}`} aria-hidden />
                      <div><strong>Run {runLabel(r.status).toLowerCase()}</strong><small>{r.tool_calls} tool calls · {duration(r.duration_ms)}</small></div>
                      <time dateTime={r.started_at}>{ago(r.started_at)}</time>
                    </li>
                  ))}
                </ol>
              </section>
            </aside>
          </div>
        </>
      )}

      {tab === "config" && (
        <div className="agd-grid">
          <section className="agd-card">
            <div className="agd-card-head"><div><h2>Instructions</h2><p>What this agent does every time it runs.</p></div></div>
            <p className="agd-instructions">{agent.instructions || "No instructions set."}</p>
            <h2 className="agd-sub">Tools &amp; permissions {toolCount != null && <small>{toolCount} enabled</small>}</h2>
            {agent.tools?.length ? (
              <ul className="agd-tools">{agent.tools.map((t) => <li key={t.name}><Wrench size={14} aria-hidden /><strong>{t.name}</strong><span>{t.access}</span></li>)}</ul>
            ) : <p className="ag-muted">Open the editor to see which tools are enabled.</p>}
          </section>
          <aside className="agd-rail">
            <section className="agd-card">
              <h3>Behavior</h3>
              <Line label="Model" value={agent.model || "Workspace default"} />
              <Line label="Execution plan" value="Up to five validated steps" />
              <Line label="Write permissions" value="Approval required" />
            </section>
            <section className="agd-card">
              <h3>Used by automations</h3>
              {agent.automation_names?.length
                ? <ul className="agd-plain">{agent.automation_names.map((n) => <li key={n}>{n}</li>)}</ul>
                : <p className="ag-muted">Not used by any automation.</p>}
              <Link className="ag-link" to={`/agents/${agent.id}/edit`}>Edit configuration <ChevronRight size={13} /></Link>
            </section>
          </aside>
        </div>
      )}

      <RunDialog agent={runOpen ? agent : null} onClose={() => setRunOpen(false)} onRun={run} />
      <DeleteDialog agent={delOpen ? agent : null} onClose={() => setDelOpen(false)} onConfirm={remove} />
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return <div className="agd-metric"><span className="ag-stat-icon" aria-hidden>{icon}</span><small>{label}</small><strong>{value}</strong><em>{detail}</em></div>;
}
function Line({ label, value }: { label: string; value: string }) {
  return <div className="agd-line"><span>{label}</span><strong>{value}</strong></div>;
}
