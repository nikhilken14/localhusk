import { useCallback, useEffect, useRef, useState } from "react";
import { agentsApi } from "./api";

/* A run is a stream of events: the model is called, asks for tools, tools answer, the user may be asked to approve.
   `normalizeEvent` is the ONLY place that knows the backend's raw event shape – adapt it if yours differs. */

export type RunEventType =
  | "run_started"
  | "llm_call"
  | "tool_call"
  | "tool_result"
  | "approval_requested"
  | "approval_resolved"
  | "run_completed"
  | "run_failed"
  | "run_cancelled"
  | "note";
export interface RunEvent {
  sequence: number;
  at: string;
  type: RunEventType;
  data: Record<string, any>;
}

export function normalizeEvent(raw: any, i = 0): RunEvent {
  const t = String(raw?.type ?? raw?.kind ?? raw?.event ?? "").toLowerCase();
  const source = raw?.data ?? raw?.payload ?? raw?.details ?? {};
  const data = source && typeof source === "object"
    ? { ...source, message: source.message ?? raw?.message, event_type: t }
    : { message: raw?.message, value: source, event_type: t };
  let type: RunEventType = "note";
  // Exact backend event types first — never let broad regexes swallow them.
  if (t === "run.cancelled" || t === "run.canceled") type = "run_cancelled";
  else if (t === "run.completed") type = "run_completed";
  else if (t === "run.failed") type = "run_failed";
  else if (t === "run.started" || t === "run.queued") type = "run_started";
  else if (t === "approval.required") type = "approval_requested";
  else if (t === "approval.approved" || t === "approval.rejected") type = "approval_resolved";
  else if (t.startsWith("approval.")) type = "approval_resolved";
  else if (t === "step.completed") type = "tool_result";
  else if (t === "step.started") type = "tool_call";
  else if (t === "plan.created") type = "note"; // plan is informational, not a second "run started"
  else if (/approval/.test(t))
    type = /(resolved|decision|approved|rejected)/.test(t)
      ? "approval_resolved"
      : "approval_requested";
  else if (/tool/.test(t))
    type = /(result|response|output)/.test(t) ? "tool_result" : "tool_call";
  else if (/(llm|model|completion)/.test(t)) type = "llm_call";
  else if (/(fail|error)/.test(t)) type = "run_failed";
  else if (/(^run\.start|queued)/.test(t)) type = "run_started";
  return {
    sequence: Number(raw?.sequence ?? raw?.seq ?? i + 1),
    at:
      raw?.at ?? raw?.created_at ?? raw?.timestamp ?? new Date().toISOString(),
    type,
    data,
  };
}

/* ---------- events → steps the UI draws ---------- */
export type Step =
  | {
      kind: "start";
      seq: number;
      at: string;
      agent_id?: string;
      agent_name?: string;
      model?: string;
      input?: string;
    }
  | {
      kind: "llm";
      seq: number;
      at: string;
      model?: string;
      purpose?: string;
      tokens_in: number;
      tokens_out: number;
      duration_ms?: number;
      text?: string;
      tool_requests: string[];
    }
  | {
      kind: "tool";
      seq: number;
      at: string;
      call_id?: string;
      step_index?: number;
      tool: string;
      args: unknown;
      status: "ok" | "error" | "pending";
      result?: unknown;
      error?: string;
      duration_ms?: number;
    }
  | {
      kind: "approval";
      seq: number;
      at: string;
      approval_id: string;
      tool?: string;
      args?: unknown;
      summary?: string;
      decision?: "approved" | "rejected";
    }
  | { kind: "done"; seq: number; at: string; output?: string }
  | { kind: "fail"; seq: number; at: string; error?: string }
  | { kind: "note"; seq: number; at: string; text: string };

const num = (v: unknown) => (typeof v === "number" && isFinite(v) ? v : 0);

export function buildSteps(events: RunEvent[]): Step[] {
  const steps: Step[] = [];
  for (const e of events) {
    const d = e.data,
      base = { seq: e.sequence, at: e.at };
    switch (e.type) {
      case "run_started":
        steps.push({
          kind: "start",
          ...base,
          agent_id: d.agent_id,
          agent_name: d.agent_name,
          model: d.model,
          input: d.input,
        });
        break;
      case "llm_call":
        steps.push({
          kind: "llm",
          ...base,
          model: d.model,
          purpose: d.purpose,
          tokens_in: num(
            d.prompt_tokens ?? d.usage?.input_tokens ?? d.input_tokens,
          ),
          tokens_out: num(
            d.completion_tokens ?? d.usage?.output_tokens ?? d.output_tokens,
          ),
          duration_ms: d.duration_ms,
          text: d.text ?? d.content ?? d.output,
          tool_requests:
            d.tool_requests ?? d.tool_calls?.map((c: any) => c.name ?? c) ?? [],
        });
        break;
      case "tool_call":
        steps.push({
          kind: "tool",
          ...base,
          call_id: d.call_id ?? d.id,
          step_index: typeof d.step === "number" ? d.step : undefined,
          tool: d.tool ?? d.name ?? d.tool_name ?? "tool",
          args: d.arguments ?? d.args ?? d.input ?? {},
          status:
            d.status === "error" || d.error
              ? "error"
              : d.status === "pending" || (d.result === undefined && !d.status)
                ? "pending"
                : "ok",
          result: d.result ?? d.output,
          error: d.error,
          duration_ms: d.duration_ms,
        });
        break;
      case "tool_result": {
        const id = d.call_id ?? d.id;
        const target = [...steps]
          .reverse()
          .find(
            (s): s is Extract<Step, { kind: "tool" }> =>
              s.kind === "tool" &&
              (id ? s.call_id === id : typeof d.step === "number" ? s.step_index === d.step : s.status === "pending"),
          );
        if (!target && d.tool) {
          steps.push({ kind: "tool", ...base, step_index: typeof d.step === "number" ? d.step : undefined, tool: d.tool, args: d.arguments ?? {}, status: "ok", result: d.result ?? d.output });
          break;
        }
        if (target) {
          target.result = d.result ?? d.output;
          target.error = d.error;
          target.status = d.error ? "error" : "ok";
          target.duration_ms = d.duration_ms ?? target.duration_ms;
        }
        break;
      }
      case "approval_requested":
        steps.push({
          kind: "approval",
          ...base,
          approval_id: d.approval_id ?? d.id,
          tool: d.tool ?? d.tool_name,
          args: d.arguments ?? d.args,
          summary: d.summary ?? d.description,
        });
        break;
      case "approval_resolved": {
        const id = d.approval_id ?? d.id;
        const target = [...steps]
          .reverse()
          .find(
            (s): s is Extract<Step, { kind: "approval" }> =>
              s.kind === "approval" && (!id || s.approval_id === id),
          );
        if (target)
          target.decision =
            d.decision === "rejected" || d.approved === false
              ? "rejected"
              : "approved";
        break;
      }
      case "run_completed":
        steps.push({
          kind: "done",
          ...base,
          output: d.output ?? d.result ?? d.text,
        });
        break;
      case "run_failed":
        steps.push({ kind: "fail", ...base, error: d.error ?? d.message });
        break;
      case "run_cancelled":
        steps.push({ kind: "note", ...base, text: d.message ?? "Run cancelled" });
        break;
      default: {
        const msg =
          typeof d === "string"
            ? d
            : (d.message ??
              (d.event_type === "plan.created"
                ? `Plan created${typeof d.steps === "number" ? ` (${d.steps} steps)` : ""}`
                : JSON.stringify(d)));
        steps.push({ kind: "note", ...base, text: msg });
      }
    }
  }
  return steps;
}

export type TraceStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";
export function summarize(steps: Step[]) {
  const llm = steps.filter(
    (s): s is Extract<Step, { kind: "llm" }> => s.kind === "llm",
  );
  const tools = steps.filter(
    (s): s is Extract<Step, { kind: "tool" }> => s.kind === "tool",
  );
  const first = steps[0] && new Date(steps[0].at).getTime();
  const last = steps.length
    ? new Date(steps[steps.length - 1].at).getTime()
    : 0;
  // Derive status only from steps — never reference the free variable `events`.
  let status: TraceStatus = steps.some((s) => s.kind === "start")
    ? "running"
    : "queued";
  if (steps.some((s) => s.kind === "fail")) status = "failed";
  else if (steps.some((s) => s.kind === "done")) status = "completed";
  else if (
    steps.some(
      (s) =>
        s.kind === "note" &&
        /cancell?ed/i.test((s as Extract<Step, { kind: "note" }>).text ?? ""),
    )
  )
    status = "cancelled";
  else if (steps.some((s) => s.kind === "approval" && !s.decision))
    status = "awaiting_approval";
  return {
    status,
    llmCalls: llm.length,
    toolCalls: tools.length,
    tokensIn: llm.reduce((n, s) => n + s.tokens_in, 0),
    tokensOut: llm.reduce((n, s) => n + s.tokens_out, 0),
    durationMs: first && last ? last - first : 0,
    toolsUsed: [
      ...tools.reduce(
        (m, s) => m.set(s.tool, (m.get(s.tool) ?? 0) + 1),
        new Map<string, number>(),
      ),
    ],
  };
}

/** Polls the run's events until it finishes (or fails). Call refresh() after resolving an approval. */
export function useRunEvents(runId: string | null) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const cursor = useRef(0);
  const timer = useRef<number>(0);
  const live = useRef(false);

  const tick = useCallback(async (id: string) => {
    let stop = false;
    try {
      const r = await agentsApi.events(id, cursor.current);
      const fresh = (r.events ?? []).map(normalizeEvent);
      if (fresh.length) {
        cursor.current = Math.max(
          cursor.current,
          r.next_sequence ?? 0,
          ...fresh.map((e) => e.sequence),
        );
        setEvents((cur) => {
          const seen = new Set(cur.map((e) => e.sequence));
          return [...cur, ...fresh.filter((e) => !seen.has(e.sequence))];
        });
      }
      // Stop on explicit done flag, terminal event types, or terminal run_status
      // even when this poll returned no new events.
      const terminalStatus = ["completed", "failed", "cancelled", "canceled"].includes(
        String(r.run_status ?? "").toLowerCase(),
      );
      stop =
        Boolean(r.done) ||
        terminalStatus ||
        fresh.some(
          (e) =>
            e.type === "run_completed" ||
            e.type === "run_failed" ||
            e.type === "run_cancelled",
        );
      setError("");
    } catch (e: any) {
      setError(e.message);
    }
    if (!live.current || stop) {
      live.current = false;
      return;
    }
    timer.current = window.setTimeout(() => tick(id), 1500);
  }, []);

  const start = useCallback(() => {
    if (!runId) return;
    window.clearTimeout(timer.current);
    live.current = true;
    tick(runId);
  }, [runId, tick]);

  useEffect(() => {
    setEvents([]);
    setError("");
    cursor.current = 0;
    start();
    return () => {
      live.current = false;
      window.clearTimeout(timer.current);
    };
  }, [start]);

  const steps = buildSteps(events);
  return { events, steps, error, refresh: start, ...summarize(steps) };
}
export type RunTrace = ReturnType<typeof useRunEvents>;
