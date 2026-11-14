import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Activity, ArrowLeft, Check, ChevronRight, Clock, Pencil, Play, ShieldCheck, Sparkles, Workflow, Wrench, X, Zap } from "lucide-react";
import { automationApi, describeTrigger } from "./automation";
import { agentsApi } from "../agents/api";
import type { Automation, EventInfo } from "./automation";
import { traceFor } from "./trace";
import type { TraceKind } from "./trace";
import { ActionMenu, Badge, DeleteAutomationDialog, jobStatus } from "./automation-shared";
import { StatusBadge, duration, hash, when } from "../agents/shared";
import type { AgentRun } from "../agents/ui-types";
import "../agents/agents-page.css";
import "./automation.css";

const TILES = ["amber", "blue", "green"];
const KIND: Record<TraceKind, { cls: string; Icon: typeof Clock }> = {
  Trigger: { cls: "amber", Icon: Clock },
  "Tool call": { cls: "blue", Icon: Wrench },
  "MCP call": { cls: "purple", Icon: Zap },
  "Agent step": { cls: "green", Icon: Sparkles },
  Approval: { cls: "amber", Icon: ShieldCheck },
  Result: { cls: "green", Icon: Check },
};
const FILTERS = [["all", "All steps"], ["calls", "Tools & MCP"], ["checks", "Approvals & results"]] as const;
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour12: false });

export function AutomationDetailPage({ notify }: { notify?: (m: string) => void }) {
  // Parent routes may use :id (same as agents) or :jobId — accept either.
  const params = useParams();
  const jobId = String(params.jobId ?? params.id ?? "").trim();
  const navigate = useNavigate();
  const say = (m: string) => notify?.(m);
  const [job, setJob] = useState<Automation | null>(null);
  const [events, setEvents] = useState<EventInfo[]>([]);
  const [runEvents, setRunEvents] = useState<any[]>([]);
  const [runs, setRuns] = useState<AgentRun[] | null>(null);
  const [runsSample, setRunsSample] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("all");
  const [error, setError] = useState("");
  const [delOpen, setDelOpen] = useState(false);

  const load = useCallback(async () => {
    setError("");
    if (!jobId) {
      setError("Missing automation id in the URL");
      return;
    }
    let a: Automation;
    try { a = await automationApi.get(jobId); setJob(a); }
    catch (e: any) { setError(e.message); return; }
    automationApi.events().then((e) => setEvents(Array.isArray(e) ? e : [])).catch(() => setEvents([]));
    try {
      const list = await automationApi.runs(jobId);
      setRuns(Array.isArray(list) ? list : []);
      setRunsSample(false);
    } catch (e) {
      setRuns([]);
      setRunsSample(false);
      say(e instanceof Error ? `Unable to load run history: ${e.message}` : "Unable to load run history");
    }
  }, [jobId]);
  useEffect(() => { setJob(null); setRuns(null); setSelected(null); setFilter("all"); load(); }, [load]);

  const run = runs?.find((r) => r.id === selected) ?? runs?.[0];
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    setRunEvents([]);
    if (!run || false) return () => { active = false; };
    const poll = async () => {
      try {
        const result = await agentsApi.events(run.id);
        if (!active) return;
        setRunEvents(result.events ?? []);
        if (!result.done) timer = window.setTimeout(poll, 1200);
      } catch {
        if (active) timer = window.setTimeout(poll, 2500);
      }
    };
    void poll();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [run?.id]);
  const steps = useMemo(() => {
    if (!job || !run) return [];
    try {
      const t = traceFor(job, run, runEvents, events);
      return Array.isArray(t) ? t : [];
    } catch {
      return [];
    }
  }, [job, run, runEvents, events]);
  const shownSteps = steps.filter((s) =>
    filter === "all" || (filter === "calls" && (s.kind === "Tool call" || s.kind === "MCP call")) || (filter === "checks" && (s.kind === "Approval" || s.kind === "Result")));

  const toggle = async () => {
    if (!job) return;
    try { await automationApi.setEnabled(job.id, !job.enabled); say(`${job.name} ${job.enabled ? "paused" : "turned on"}`); load(); }
    catch (e: any) { say(e.message); }
  };
  const runNow = async () => {
    if (!job) return;
    try { const result = await automationApi.run(job.id); say(result.status === "skipped" ? `${job.name} already has a run in progress` : `Running ${job.name}`); setTimeout(load, 1200); }
    catch (e: any) { say(e.message); }
  };
  const remove = async () => {
    if (!job) return;
    try { await automationApi.remove(job.id); say(`${job.name} deleted`); navigate("/automation"); }
    catch (e: any) { say(e.message); }
  };

  if (error) return (
    <div className="content-page ag au">
      <Link className="ag-back" to="/automation"><ArrowLeft size={14} /> Back to automation</Link>
      <div className="ag-note bad">Couldn’t load this automation: {error} <button className="subtle-button" onClick={load}>Try again</button></div>
    </div>
  );
  if (!job) return <div className="content-page ag au"><p className="ag-muted">Loading…</p></div>;

  const st = jobStatus(job);
  const calls = steps.filter((s) => s.kind === "Tool call").length;
  const mcp = steps.filter((s) => s.kind === "MCP call").length;
  const when_ = (iso: string) => when(iso);

  return (
    <div className="content-page ag au">
      <Link className="ag-back" to="/automation"><ArrowLeft size={14} /> Back to automation</Link>

      <header className="agd-head">
        <div className="agd-title">
          <div className={`ag-tile lg ${TILES[hash(job.id) % 3]}`} aria-hidden><Workflow size={22} /></div>
          <div>
            <div className="agd-title-line"><h1>{job.name}</h1><Badge label={st.label} tone={st.tone} /></div>
            <p>{describeTrigger(job, events)}{job.agent_name ? ` · ${job.agent_name}` : ""}</p>
          </div>
        </div>
        <div className="agd-actions">
          <Link className="subtle-button" to={`/automation/${job.id}/edit`}><Pencil size={14} /> Edit automation</Link>
          <button className="primary-button" onClick={runNow}><Play size={14} /> Run now</button>
          <ActionMenu name={job.name} enabled={job.enabled} onToggle={toggle} onDelete={() => setDelOpen(true)} />
        </div>
      </header>

      {run && (run.status === "awaiting_approval" || run.status === "failed") && (
        <div className={`ag-note ${run.status === "failed" ? "bad" : "warn"}`}>
          {run.status === "failed" ? "This run failed." : "This run is waiting for your approval."}{" "}
          <Link className="ag-link" to={`/agents/runs/${run.id}`}>Open run</Link>
        </div>
      )}
      {job.enabled && job.agent_status === "paused" && <div className="ag-note warn">The assigned agent is paused, so scheduled runs are skipped until you resume it. {job.agent_id && <Link className="ag-link" to={`/agents/${job.agent_id}`}>Open agent</Link>}</div>}

      <section className="agd-metrics" aria-label="Latest run">
        <Metric icon={<Clock size={16} />} label="Duration" value={run ? duration(run.duration_ms) : "–"} detail={run ? `Started ${when_(run.started_at)}` : "No runs yet"} />
        <Metric icon={<Wrench size={16} />} label="Tool calls" value={run ? String(calls) : "–"} detail="In the selected run" />
        <Metric icon={<Zap size={16} />} label="MCP calls" value={run ? String(mcp) : "–"} detail="External connections" />
        <Metric icon={<Activity size={16} />} label="Tokens" value={run?.tokens == null ? "Not reported" : run.tokens.toLocaleString()} detail={run?.model ?? "Usage metrics unavailable"} />
      </section>

      <div className="agd-grid">
        <section className="agd-card">
          <div className="agd-card-head">
            <div><h2>Execution timeline {run && <StatusBadge status={run.status} />}</h2><p>Every trigger, tool call and approval, in order.</p></div>
            <div className="au-head-tools">
              <select aria-label="Filter steps" value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}>{FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            </div>
          </div>
          {runs === null && <p className="ag-muted">Loading…</p>}
          {runs?.length === 0 && <div className="ag-empty slim"><h3>No runs yet</h3><p>Run it once to see the timeline here.</p></div>}
          {run && shownSteps.length === 0 && <p className="ag-muted">No steps match this filter.</p>}
          <ol className="au-trace">
            {shownSteps.map((s, i) => {
              const { cls, Icon } = KIND[s.kind];
              const tone = s.tone === "bad" ? "bad" : s.tone === "warn" ? "amber" : cls;
              return (
                <li key={i}>
                  <span className={`au-trace-icon ${tone}`} aria-hidden>{s.tone === "bad" ? <X size={15} /> : <Icon size={15} />}</span>
                  <div className="au-trace-card">
                    <div className="au-trace-meta"><code>{clock(s.at)}</code><span>{s.kind}</span>{s.duration_ms != null && <em>{s.duration_ms >= 1000 ? `${(s.duration_ms / 1000).toFixed(1)} s` : `${s.duration_ms} ms`}</em>}</div>
                    <h3>{s.title}</h3>
                    <p>{s.detail}</p>
                    {s.output && <div className={`au-trace-out ${s.tone ?? "ok"}`}><Check size={13} aria-hidden /> {s.output}</div>}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>

        <aside className="agd-rail">
          <section className="agd-card">
            <h3>Run context</h3>
            <div className="agd-line"><span>Assigned agent</span><strong>{job.agent_id ? <Link className="ag-link" to={`/agents/${job.agent_id}`}>{job.agent_name ?? "Open agent"}</Link> : "None"}</strong></div>
            <div className="agd-line"><span>Trigger</span><strong>{describeTrigger(job, events)}</strong></div>
            <div className="agd-line"><span>Next run</span><strong>{!job.enabled ? "Paused" : job.next_run_at ? when_(job.next_run_at) : job.trigger_type === "event" ? "When it happens" : "Not scheduled"}</strong></div>
            <div className="agd-line"><span>Overlapping runs</span><strong>{job.skip_if_running ? "Skipped" : "Allowed"}</strong></div>
            <div className="agd-line"><span>Total runs</span><strong>{job.run_count}</strong></div>
          </section>

          {run?.status === "awaiting_approval" && (
            <section className="au-promo">
              <span className="ag-stat-icon" aria-hidden><ShieldCheck size={16} /></span>
              <h3>Approval checkpoint</h3>
              <p>This run paused before delivery because it needs your approval.</p>
              <Link className="primary-button" to={`/agents/runs/${run.id}`}>Review draft</Link>
            </section>
          )}

          <section className="agd-card">
            <div className="au-rail-head"><h3>Recent runs</h3>{runsSample && <span className="agd-sample">Sample</span>}</div>
            {!runs?.length && <p className="ag-muted">No runs yet.</p>}
            <ul className="au-runs">
              {(runs ?? []).slice(0, 6).map((r) => (
                <li key={r.id}>
                  <button className={r.id === run?.id ? "on" : ""} aria-pressed={r.id === run?.id} onClick={() => setSelected(r.id)}>
                    <span><strong>{when_(r.started_at)}</strong><small>{duration(r.duration_ms)} · {r.tool_calls} tool calls</small></span>
                    <StatusBadge status={r.status} />
                  </button>
                </li>
              ))}
            </ul>
            {run && <Link className="ag-link" to={`/agents/runs/${run.id}`}>Open full run <ChevronRight size={13} /></Link>}
          </section>
        </aside>
      </div>

      <DeleteAutomationDialog name={delOpen ? job.name : null} onClose={() => setDelOpen(false)} onConfirm={remove} />
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail: string }) {
  return <div className="agd-metric"><span className="ag-stat-icon" aria-hidden>{icon}</span><small>{label}</small><strong>{value}</strong><em>{detail}</em></div>;
}
