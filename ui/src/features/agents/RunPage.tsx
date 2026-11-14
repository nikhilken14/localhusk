import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useRunEvents } from "./events";
import { agentsApi } from "./api";
import { RunTrace } from "./RunTrace";
import { StatusBadge, duration, when } from "./shared";
import "./agents-page.css";
import "./agent-editor.css";

function parseResult(raw: unknown): { completed_steps?: Array<{ step?: number; tool?: string; result?: unknown }>; total_steps?: number; message?: string } | null {
  if (raw == null) return null;
  if (typeof raw === "string") {
    try { return JSON.parse(raw); } catch { return { message: raw }; }
  }
  if (typeof raw === "object") return raw as any;
  return null;
}

/** /agents/runs/:runId – shows how the agent used the model and its tools, step by step. */
export function RunPage({ notify }: { notify?: (m: string) => void }) {
  const { runId = "" } = useParams();
  const trace = useRunEvents(runId);
  const [run, setRun] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const value = await agentsApi.getRun(runId); if (active) setRun(value); }
      catch (e: any) { if (active) setActionError(e.message); }
    };
    void load();
    const timer = window.setInterval(load, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId]);
  const cancel = async () => {
    setBusy(true); setActionError("");
    try { await agentsApi.cancelRun(runId); const value = await agentsApi.getRun(runId); setRun(value); trace.refresh(); }
    catch (e: any) { setActionError(e.message); }
    finally { setBusy(false); }
  };
  const start = trace.steps.find((s) => s.kind === "start");
  const info = start && start.kind === "start" ? start : null;
  // Backend only allows cancel for queued / awaiting_approval (running steps are not interruptible).
  const canCancel = ["queued", "awaiting_approval", "deferred"].includes(
    String(run?.status ?? trace.status),
  );
  const parsed = parseResult(run?.result);
  const completedSteps = Array.isArray(parsed?.completed_steps) ? parsed!.completed_steps! : [];

  return (
    <div className="content-page ag">
      <Link className="ag-back" to={(run?.agent_id ?? info?.agent_id) ? `/agents/${run?.agent_id ?? info?.agent_id}` : "/agents"}><ArrowLeft size={14} /> {info?.agent_name ?? "Back to agents"}</Link>
      <header className="agd-head">
        <div>
          <div className="agd-title-line"><h1>Run {runId.slice(-8)}</h1><StatusBadge status={trace.status} /></div>
          <p className="ag-muted">{info?.agent_name ?? (run?.agent_id ? "Agent run" : "Execution")}{info?.model ? ` · ${info.model}` : ""}{run?.created_at ? ` · ${when(run.created_at)}` : start ? ` · ${when(start.at)}` : ""}</p>
        </div>
        {canCancel ? <button className="subtle-button" disabled={busy} onClick={cancel}>{busy ? "Cancelling…" : "Cancel run"}</button> : null}
      </header>
      {actionError && <div className="ag-note bad">{actionError}</div>}
      {run?.error && <div className="ag-note bad">{run.error}</div>}

      {/* Prefer structured per-step results over a raw JSON dump */}
      {(completedSteps.length > 0 || parsed?.message) && (
        <section className="agd-card" style={{ marginBottom: 16 }}>
          <h2>Execution result</h2>
          {parsed?.message && <p style={{ marginBottom: 12 }}>{parsed.message}</p>}
          {completedSteps.length > 0 && (
            <ol className="agd-plain" style={{ listStyle: "decimal", paddingLeft: 20 }}>
              {completedSteps.map((item, i) => {
                const value = item.result;
                const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
                return (
                  <li key={i} style={{ marginBottom: 10 }}>
                    <strong>{item.tool ?? `Step ${(item.step ?? i) + 1}`}</strong>
                    {text != null && text !== "" && (
                      <pre className="rt-details" style={{ marginTop: 4, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {String(text).slice(0, 4000)}
                      </pre>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
          {parsed?.total_steps != null && (
            <p className="ag-muted" style={{ marginTop: 8 }}>
              {completedSteps.length} of {parsed.total_steps} step{parsed.total_steps === 1 ? "" : "s"} completed
            </p>
          )}
        </section>
      )}
      {/* Fallback if result exists but is not the expected shape */}
      {run?.result && completedSteps.length === 0 && !parsed?.message && (
        <section className="agd-card" style={{ marginBottom: 16 }}>
          <h2>Execution result</h2>
          <pre className="rt-details">{typeof run.result === "string" ? run.result : JSON.stringify(run.result, null, 2)}</pre>
        </section>
      )}

      {trace.status === "awaiting_approval" && <div className="ag-note warn">This run is paused. Approve or reject the action below to continue.</div>}

      <div className="agd-grid">
        <section className="agd-card">
          <div className="agd-card-head"><div><h2>What happened</h2><p>Every plan step, tool execution and approval, in order.</p></div></div>
          <RunTrace trace={trace} notify={notify} />
        </section>
        <aside className="agd-rail">
          <section className="agd-card">
            <h3>Run summary</h3>
            <div className="agd-line"><span>Agent</span><strong>{(run?.agent_id ?? info?.agent_id) ? <Link className="ag-link" to={`/agents/${run?.agent_id ?? info?.agent_id}`}>{info?.agent_name ?? "Open agent"}</Link> : info?.agent_name ?? "–"}</strong></div>
            <div className="agd-line"><span>Model</span><strong>{info?.model ?? "–"}</strong></div>
            <div className="agd-line"><span>Duration</span><strong>{duration(trace.durationMs || null)}</strong></div>
            <div className="agd-line"><span>Tool calls</span><strong>{trace.toolCalls}</strong></div>
            <div className="agd-line"><span>Usage metrics</span><strong>{trace.tokensIn || trace.tokensOut ? `${trace.tokensIn.toLocaleString()} / ${trace.tokensOut.toLocaleString()} tokens` : "Not reported by provider"}</strong></div>
          </section>
          <section className="agd-card">
            <h3>Tools used</h3>
            {trace.toolsUsed.length === 0 && <p className="ag-muted">None yet.</p>}
            <ul className="agd-plain">{trace.toolsUsed.map(([t, n]) => <li key={t}><code>{t}</code> × {n}</li>)}</ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
