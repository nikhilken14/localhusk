import { describeTrigger } from "./automation";
import type { Automation, EventInfo } from "./automation";
import type { AgentRun } from "../agents/ui-types";

export type TraceKind = "Trigger" | "Tool call" | "MCP call" | "Agent step" | "Approval" | "Result";
export interface TraceStep { at: string; kind: TraceKind; title: string; detail: string; duration_ms?: number; output?: string; tone?: "ok" | "warn" | "bad" }

/** Convert the durable backend event log into a truthful timeline; never fabricate tool calls/results. */
export function traceFor(a: Automation, run: AgentRun, events: any[] = [], triggerEvents: EventInfo[] = []): TraceStep[] {
  const steps: TraceStep[] = [];
  const started = run.started_at || new Date().toISOString();
  if (!events.length) {
    return [{ at: started, kind: "Trigger", title: "Run queued", detail: `${a.name} · ${describeTrigger(a, triggerEvents)}` }];
  }
  for (const event of events) {
    const type = String(event.type ?? event.kind ?? "");
    const details = event.details ?? event.data ?? event.payload ?? {};
    const detail =
      details && typeof details === "object" && Object.keys(details).length
        ? JSON.stringify(details)
        : event.message ?? "";
    let kind: TraceKind = "Agent step";
    let tone: TraceStep["tone"] = "ok";
    const toolName =
      details?.tool ?? details?.tool_name ?? details?.name ?? details?.mcp_tool_name;
    const isMcp =
      type.includes("mcp") ||
      (typeof toolName === "string" && toolName.startsWith("mcp::"));

    if (type.includes("approval")) {
      kind = "Approval";
      tone = type.includes("rejected") ? "bad" : "warn";
    } else if (isMcp) {
      kind = "MCP call";
    } else if (type.includes("tool") || type.includes("step.")) {
      kind = "Tool call";
    } else if (
      type.startsWith("run.queued") ||
      type.startsWith("run.started") ||
      type.startsWith("run.resumed") ||
      type === "plan.created"
    ) {
      kind = "Trigger";
    } else if (type === "run.failed") {
      kind = "Result";
      tone = "bad";
    } else if (type === "run.completed" || type === "run.cancelled") {
      kind = "Result";
      if (type === "run.cancelled") tone = "warn";
    }

    const title =
      toolName && (kind === "Tool call" || kind === "MCP call")
        ? String(toolName)
        : String(event.message ?? type ?? "Activity");

    steps.push({
      at: event.created_at ?? event.at ?? started,
      kind,
      title,
      detail,
      tone,
      output:
        type === "run.completed"
          ? "Run completed"
          : type === "run.failed"
            ? "Run failed"
            : type === "run.cancelled"
              ? "Run cancelled"
              : undefined,
    });
  }

  // Structured results from the run record (prefer over generic "Run completed")
  let result = run.result as any;
  if (typeof result === "string") {
    try { result = JSON.parse(result); } catch { /* keep string */ }
  }
  if (result && typeof result === "object") {
    if (Array.isArray(result.completed_steps)) {
      for (const item of result.completed_steps) {
        const value = item.result;
        const output = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        const tool = String(item.tool ?? "Tool");
        steps.push({
          at: run.started_at,
          kind: tool.startsWith("mcp::") ? "MCP call" : "Result",
          title: `${tool} result`,
          detail: `Step ${Number(item.step ?? 0) + 1} completed`,
          output: output?.slice(0, 1600),
          tone: "ok",
        });
      }
    } else if (typeof result.message === "string" && result.message) {
      steps.push({
        at: run.started_at,
        kind: "Result",
        title: "Agent response",
        detail: "Text response generated",
        output: result.message.slice(0, 1600),
        tone: "ok",
      });
    }
  }
  if (run.status === "failed" && run.error) {
    steps.push({ at: run.started_at, kind: "Result", title: "Run failed", detail: run.error, tone: "bad" });
  }
  return steps;
}
