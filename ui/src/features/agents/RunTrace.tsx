import { useState } from "react";
import { Check, Play, ShieldCheck, Sparkles, Wrench, X } from "lucide-react";
import { agentsApi } from "./api";
import type { RunTrace as Trace, Step } from "./events";
import { duration } from "./shared";
import "./agent-editor.css";

const PURPOSE: Record<string, string> = {
  plan: "Planning",
  reason: "Reasoning",
  answer: "Answering",
};
const json = (v: unknown) =>
  typeof v === "string" ? v : JSON.stringify(v, null, 2);
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour12: false });
const ms = (n?: number) =>
  n == null ? "" : n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${n} ms`;

/** The step-by-step story of a run: every model call, tool call, approval and the final result. */
export function RunTrace({
  trace,
  notify,
  compact,
}: {
  trace: Trace;
  notify?: (m: string) => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const decide = async (id: string, decision: "approved" | "rejected") => {
    setBusy(id);
    try {
      await agentsApi.resolve(id, decision);
      notify?.(decision === "approved" ? "Approved" : "Rejected");
      trace.refresh();
    } catch (e: any) {
      notify?.(e.message);
    } finally {
      setBusy(null);
    }
  };
  const { steps, status } = trace;

  return (
    <div className={`rt ${compact ? "compact" : ""}`}>
      <div className="rt-stats" aria-label="Run totals">
        <span>
          <b>{trace.toolCalls}</b> tool call{trace.toolCalls === 1 ? "" : "s"}
        </span>
        {trace.llmCalls > 0 && <span><b>{trace.llmCalls}</b> model call{trace.llmCalls === 1 ? "" : "s"}</span>}
        {(trace.tokensIn > 0 || trace.tokensOut > 0) && <span><b>{trace.tokensIn.toLocaleString()}</b> in · <b>{trace.tokensOut.toLocaleString()}</b> out tokens</span>}
        <span>
          <b>{duration(trace.durationMs || null)}</b>
        </span>
        {(status === "running" || status === "queued") && (
          <span className="rt-live">
            <i /> Live
          </span>
        )}
      </div>
      {trace.error && (
        <div className="ag-note bad">Couldn’t load events: {trace.error}</div>
      )}
      {steps.length === 0 && !trace.error && (
        <p className="ag-muted">Waiting for the first step…</p>
      )}
      <ol className="rt-list">
        {steps.map((s) => (
          <StepRow key={s.seq} s={s} busy={busy} decide={decide} />
        ))}
      </ol>
    </div>
  );
}

function Details({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <details className="rt-details">
      <summary>{label}</summary>
      <pre>{json(value)}</pre>
    </details>
  );
}

function StepRow({
  s,
  busy,
  decide,
}: {
  s: Step;
  busy: string | null;
  decide: (id: string, d: "approved" | "rejected") => void;
}) {
  const icon = (cls: string, el: React.ReactNode) => (
    <span className={`rt-icon ${cls}`} aria-hidden>
      {el}
    </span>
  );
  const meta = (kind: string, extra?: React.ReactNode) => (
    <div className="rt-meta">
      <code>{clock(s.at)}</code>
      <span>{kind}</span>
      {extra}
    </div>
  );

  switch (s.kind) {
    case "start":
      return (
        <li>
          {icon("amber", <Play size={15} />)}
          <div className="rt-card">
            {meta("Run started")}
            <h3>{s.agent_name ?? "Agent"} started</h3>
            <p>
              {s.model ? (
                <>
                  Using <code>{s.model}</code>.{" "}
                </>
              ) : null}
              {s.input ? <>Task: “{s.input}”</> : null}
            </p>
          </div>
        </li>
      );
    case "llm":
      return (
        <li>
          {icon("purple", <Sparkles size={15} />)}
          <div className="rt-card">
            {meta(
              "Model call",
              <>
                {s.model && <code className="rt-chip">{s.model}</code>}
                <em>
                  {s.tokens_in.toLocaleString()} in ·{" "}
                  {s.tokens_out.toLocaleString()} out
                  {s.duration_ms ? ` · ${ms(s.duration_ms)}` : ""}
                </em>
              </>,
            )}
            <h3>{(s.purpose && PURPOSE[s.purpose]) || "Model response"}</h3>
            {s.text && <blockquote className="rt-quote">{s.text}</blockquote>}
            {s.tool_requests.length > 0 && (
              <p className="rt-req">
                Asked to use:{" "}
                {s.tool_requests.map((t) => (
                  <code key={t}>{t}</code>
                ))}
              </p>
            )}
          </div>
        </li>
      );
    case "tool":
      return (
        <li>
          {icon(
            s.status === "error" ? "bad" : "blue",
            s.status === "error" ? <X size={15} /> : <Wrench size={15} />,
          )}
          <div className="rt-card">
            {meta(
              "Tool call",
              s.duration_ms != null && <em>{ms(s.duration_ms)}</em>,
            )}
            <h3>
              <code>{s.tool}</code>
              <span
                className={`rt-badge ${s.status === "ok" ? "ok" : s.status === "error" ? "bad" : "info"}`}
              >
                {s.status === "ok"
                  ? "Succeeded"
                  : s.status === "error"
                    ? "Failed"
                    : "Running"}
              </span>
            </h3>
            {s.error && <p className="rt-err">{s.error}</p>}
            {s.status === "ok" && typeof s.result === "string" && (
              <div className="rt-out">
                <Check size={13} aria-hidden /> {s.result}
              </div>
            )}
            <Details label="Arguments the model sent" value={s.args} />
            {typeof s.result !== "string" && (
              <Details label="Result returned to the model" value={s.result} />
            )}
          </div>
        </li>
      );
    case "approval":
      return (
        <li>
          {icon("amber", <ShieldCheck size={15} />)}
          <div className="rt-card gate">
            {meta("Approval")}
            <h3>
              {s.decision === "approved"
                ? "You approved this action"
                : s.decision === "rejected"
                  ? "You rejected this action"
                  : "Waiting for your approval"}
            </h3>
            <p>
              {s.summary ??
                (s.tool
                  ? `Use ${s.tool}`
                  : "The agent wants to make a change.")}
            </p>
            <Details label="Exactly what it will do" value={s.args} />
            {!s.decision && (
              <div className="ag-actions left">
                <button
                  className="subtle-button"
                  disabled={busy === s.approval_id}
                  onClick={() => decide(s.approval_id, "rejected")}
                >
                  Reject
                </button>
                <button
                  className="primary-button"
                  disabled={busy === s.approval_id}
                  onClick={() => decide(s.approval_id, "approved")}
                >
                  Approve
                </button>
              </div>
            )}
          </div>
        </li>
      );
    case "done":
      return (
        <li>
          {icon("green", <Check size={15} />)}
          <div className="rt-card">
            {meta("Result")}
            <h3>Run completed</h3>
            {s.output && <p>{s.output}</p>}
          </div>
        </li>
      );
    case "fail":
      return (
        <li>
          {icon("bad", <X size={15} />)}
          <div className="rt-card bad">
            {meta("Result")}
            <h3>Run failed</h3>
            {s.error && <p className="rt-err">{s.error}</p>}
          </div>
        </li>
      );
    default:
      return (
        <li>
          {icon("blue", <Wrench size={15} />)}
          <div className="rt-card">
            {meta("Note")}
            <p>{s.text}</p>
          </div>
        </li>
      );
  }
}
