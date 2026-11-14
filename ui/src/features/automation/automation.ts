import { API_BASE_URL } from "../../api-base";
import type { AgentRun } from "../agents/ui-types";

export type TriggerType = "manual" | "interval" | "daily" | "weekly" | "event";
export type Automation = {
  id: string; name: string; trigger_type: TriggerType | "cron";
  trigger_config: { every_seconds?: number; time?: string; timezone?: string; days?: number[]; event?: string; expression?: string; filters?: Record<string, unknown> };
  agent_id: string | null; agent_name: string | null; agent_status: "active" | "paused" | null;
  input_template: string; skip_if_running: boolean; enabled: boolean; next_run_at: string | null;
  last_run_at: string | null; last_status: string | null;
  last_run_status: "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled" | null;
  last_run_id: string | null; flow_summary: string[]; run_count: number;
};
export type Summary = { workflows: number; success_rate: number | null; runs_7d: number; next_run: { at: string; name: string } | null };
export type AutomationDraft = Pick<Automation, "name" | "trigger_type" | "trigger_config" | "input_template" | "skip_if_running" | "enabled"> & { agent_id: string };
export type EventInfo = { name: string; label: string; fields: string[] };

const BASE = API_BASE_URL;
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type") && init?.body != null) {
    headers.set("Content-Type", "application/json");
  }
  const r = await fetch(BASE + path, { credentials: "include", ...init, headers });
  if (!r.ok) {
    const d = (await r.json().catch(() => ({}))).detail;
    throw new Error(Array.isArray(d) ? d.map((e: any) => e.msg ?? String(e)).join("; ") : typeof d === "string" ? d : r.statusText);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

function cronToUi(expression: string, timezone = "UTC") {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) return { trigger_type: "cron" as const, trigger_config: { expression, timezone } };
  const [minute, hour, dom, month, dow] = fields;
  const simpleTime = /^\d{1,2}$/.test(minute) && /^\d{1,2}$/.test(hour);
  if (simpleTime && dom === "*" && month === "*" && dow === "*")
    return { trigger_type: "daily" as const, trigger_config: { time: `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`, timezone } };
  if (simpleTime && dom === "*" && month === "*" && /^\d+(,\d+)*$/.test(dow)) {
    const cronDays = dow.split(",").map(Number);
    const days = cronDays.map((d) => (d + 6) % 7).sort((a, b) => a - b);
    return { trigger_type: "weekly" as const, trigger_config: { time: `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`, timezone, days } };
  }
  return { trigger_type: "cron" as const, trigger_config: { expression, timezone } };
}
/** Unwrap common API envelopes and accept alternate field names from list vs detail endpoints. */
function unwrapJob(raw: any): any {
  if (!raw || typeof raw !== "object") return {};
  if (raw.job && typeof raw.job === "object") return { ...raw, ...raw.job };
  if (raw.data && typeof raw.data === "object" && (raw.data.id != null || raw.data.name != null || raw.data.title != null))
    return { ...raw, ...raw.data };
  if (raw.item && typeof raw.item === "object") return { ...raw, ...raw.item };
  return raw;
}

function normalizeAutomation(rawIn: any): Automation {
  const raw = unwrapJob(rawIn);
  const agentObj = raw.agent && typeof raw.agent === "object" ? raw.agent : null;

  let trigger_type = (raw.trigger_type ?? raw.trigger ?? raw.schedule_type ?? "manual") as Automation["trigger_type"];
  let trigger_config: Record<string, any> =
    (raw.trigger_config && typeof raw.trigger_config === "object" ? raw.trigger_config : null)
    ?? (raw.config && typeof raw.config === "object" ? raw.config : null)
    ?? (raw.schedule && typeof raw.schedule === "object" ? raw.schedule : null)
    ?? {};

  // Flatten top-level cron / timezone if backend put them outside trigger_config
  if (raw.cron_expression || raw.expression) {
    trigger_config = {
      ...trigger_config,
      expression: String(raw.cron_expression ?? raw.expression ?? trigger_config.expression ?? ""),
      timezone: raw.timezone ?? trigger_config.timezone ?? "UTC",
    };
    if (!trigger_type || trigger_type === "manual") trigger_type = "cron";
  }
  if (raw.timezone && !trigger_config.timezone) trigger_config = { ...trigger_config, timezone: raw.timezone };
  if (raw.time && !trigger_config.time) trigger_config = { ...trigger_config, time: raw.time };
  if (raw.every_seconds != null && trigger_config.every_seconds == null && trigger_config.interval_seconds == null)
    trigger_config = { ...trigger_config, every_seconds: Number(raw.every_seconds) };

  if (trigger_type === "interval") {
    trigger_config = {
      every_seconds:
        trigger_config.every_seconds ??
        trigger_config.interval_seconds ??
        3600,
    };
  }
  if (trigger_type === "cron" || (typeof trigger_config.expression === "string" && String(trigger_config.expression).trim())) {
    const converted = cronToUi(
      String(trigger_config.expression ?? ""),
      String(trigger_config.timezone ?? raw.timezone ?? "UTC"),
    );
    trigger_type = converted.trigger_type;
    trigger_config = converted.trigger_config;
  }

  const enabledRaw = raw.enabled ?? raw.is_enabled ?? raw.active;
  const enabled =
    enabledRaw === false || enabledRaw === "false" || enabledRaw === 0 || enabledRaw === "0"
      ? false
      : enabledRaw === true || enabledRaw === "true" || enabledRaw === 1 || enabledRaw === "1"
        ? true
        : enabledRaw == null
          ? true
          : Boolean(enabledRaw);

  const name =
    raw.name ??
    raw.title ??
    raw.job_name ??
    raw.display_name ??
    (raw.id != null ? String(raw.id) : "Untitled");

  return {
    id: String(raw.id ?? raw.job_id ?? ""),
    name: String(name || "Untitled"),
    trigger_type: (trigger_type as Automation["trigger_type"]) || "manual",
    trigger_config,
    agent_id:
      raw.agent_id != null
        ? String(raw.agent_id)
        : agentObj?.id != null
          ? String(agentObj.id)
          : null,
    agent_name: raw.agent_name ?? agentObj?.name ?? null,
    agent_status: (raw.agent_status ?? agentObj?.status ?? null) as Automation["agent_status"],
    input_template: String(raw.input_template ?? raw.input ?? raw.prompt ?? raw.goal ?? ""),
    skip_if_running: raw.skip_if_running !== false && raw.skip_if_running !== "false",
    enabled,
    next_run_at: raw.next_run_at ?? raw.next_run ?? null,
    last_run_at: raw.last_run_at ?? raw.last_run?.started_at ?? raw.last_run?.created_at ?? null,
    last_status: raw.last_status ?? null,
    last_run_status: raw.last_run_status ?? raw.last_run?.status ?? null,
    last_run_id:
      raw.last_run_id != null
        ? String(raw.last_run_id)
        : raw.last_run?.id != null
          ? String(raw.last_run.id)
          : null,
    flow_summary: Array.isArray(raw.flow_summary)
      ? raw.flow_summary
      : Array.isArray(raw.steps)
        ? raw.steps.map((s: any) => (typeof s === "string" ? s : s?.name ?? s?.title ?? "Step"))
        : [],
    run_count: Number(raw.run_count ?? raw.runs_count ?? raw.total_runs ?? 0) || 0,
  };
}
function toBackend(a: AutomationDraft) {
  let trigger_type: string = a.trigger_type;
  let trigger_config: Record<string, any> = { ...a.trigger_config };
  if (a.trigger_type === "interval") trigger_config = { interval_seconds: Math.max(60, Math.round(Number(a.trigger_config.every_seconds) || 3600)) };
  if (a.trigger_type === "daily") {
    const [hour, minute] = (a.trigger_config.time ?? "08:00").split(":").map(Number);
    trigger_type = "cron"; trigger_config = { expression: `${minute} ${hour} * * *`, timezone: a.trigger_config.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC" };
  } else if (a.trigger_type === "weekly") {
    const [hour, minute] = (a.trigger_config.time ?? "09:00").split(":").map(Number);
    const days = (a.trigger_config.days ?? []).map((d) => (d + 1) % 7).sort((x, y) => x - y);
    trigger_type = "cron"; trigger_config = { expression: `${minute} ${hour} * * ${days.join(",")}`, timezone: a.trigger_config.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC" };
  }
  // Do not send description: "" — that wiped the job description on every save.
  // Backend JobIn uses `input` (not input_template).
  return {
    name: a.name,
    trigger_type,
    trigger_config,
    agent_id: a.agent_id || null,
    input: a.input_template,
    enabled: a.enabled,
    skip_if_running: a.skip_if_running,
  };
}
function normalizeRun(raw: any): AgentRun {
  return { id: raw.id, status: raw.status, started_at: raw.started_at ?? raw.created_at, duration_ms: raw.duration_ms ?? null,
    tool_calls: Array.isArray(raw.result?.completed_steps) ? raw.result.completed_steps.length : 0, tokens: typeof raw.input_tokens === "number" || typeof raw.output_tokens === "number" ? (Number(raw.input_tokens) || 0) + (Number(raw.output_tokens) || 0) : null, model: null, result: raw.result, error: raw.error ?? null, goal: raw.goal, job_id: raw.job_id, agent_id: raw.agent_id };
}

export const automationApi = {
  list: async () => {
    const r = await req<any>("/automation/jobs");
    const items = Array.isArray(r) ? r : (r?.items ?? r?.jobs ?? r?.results ?? []);
    return (Array.isArray(items) ? items : []).map(normalizeAutomation);
  },
  summary: async (): Promise<Summary> => {
    const r = await req<any>("/automation/summary");
    return { workflows: Number(r.jobs_total) || 0, success_rate: r.success_rate == null ? null : Number(r.success_rate),
      runs_7d: Number(r.runs_last_7d) || 0, next_run: r.next_run ?? null };
  },
  get: async (id: string) => {
    if (!id) throw new Error("Automation id is required");
    const r = await req<any>(`/automation/jobs/${id}`);
    let a = normalizeAutomation(r);
    // If detail payload is sparse (common when GET shape differs from list), merge from list row.
    const sparse =
      !a.name ||
      a.name === "Untitled" ||
      (!a.agent_id && !a.input_template && (!a.trigger_config || !Object.keys(a.trigger_config).length));
    if (sparse) {
      try {
        const listRaw = await req<any>("/automation/jobs");
        const items = Array.isArray(listRaw) ? listRaw : (listRaw?.items ?? listRaw?.jobs ?? listRaw?.results ?? []);
        const hit = (Array.isArray(items) ? items : [])
          .map(normalizeAutomation)
          .find((x) => String(x.id) === String(id));
        if (hit) {
          a = {
            ...hit,
            ...a,
            name: a.name && a.name !== "Untitled" ? a.name : hit.name,
            trigger_type:
              a.trigger_type && !(a.trigger_type === "manual" && hit.trigger_type !== "manual")
                ? a.trigger_type
                : hit.trigger_type,
            trigger_config: Object.keys(a.trigger_config || {}).length ? a.trigger_config : hit.trigger_config,
            agent_id: a.agent_id ?? hit.agent_id,
            agent_name: a.agent_name ?? hit.agent_name,
            agent_status: a.agent_status ?? hit.agent_status,
            input_template: a.input_template || hit.input_template,
            enabled: a.enabled,
            next_run_at: a.next_run_at ?? hit.next_run_at,
            last_run_at: a.last_run_at ?? hit.last_run_at,
            last_run_status: a.last_run_status ?? hit.last_run_status,
            last_run_id: a.last_run_id ?? hit.last_run_id,
            flow_summary: a.flow_summary?.length ? a.flow_summary : hit.flow_summary,
            run_count: a.run_count || hit.run_count,
          };
        }
      } catch {
        /* list fallback optional */
      }
    }
    return a;
  },
  runs: async (id: string) => {
    const r = await req<any>(`/automation/jobs/${id}/runs`);
    const items = Array.isArray(r) ? r : (r?.items ?? r?.results ?? r?.runs ?? []);
    return (Array.isArray(items) ? items : []).map(normalizeRun);
  },
  events: () => req<any>("/automation/triggers").then((r) => (r.events ?? []).map((e: any) => ({ name: e.name, label: e.description ?? e.name, fields: e.fields ?? [] }))),
  create: async (a: AutomationDraft) => normalizeAutomation(await req<any>("/automation/jobs", { method: "POST", body: JSON.stringify(toBackend(a)) })),
  update: async (id: string, a: AutomationDraft) => normalizeAutomation(await req<any>(`/automation/jobs/${id}`, { method: "PATCH", body: JSON.stringify(toBackend(a)) })),
  setEnabled: async (id: string, enabled: boolean) => normalizeAutomation(await req<any>(`/automation/jobs/${id}/enabled?enabled=${enabled}`, { method: "PATCH" })),
  remove: (id: string) => req<void>(`/automation/jobs/${id}`, { method: "DELETE"}),
  run: (id: string) => req<{ job_id: string; run_id: string | null; status: string }>(`/automation/jobs/${id}/run`, { method: "POST" }),
};

export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const FULL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export function clock(hhmm = ""): string {
  const [h, m] = hhmm.split(":").map(Number);
  return new Date(2000, 0, 1, h || 0, m || 0).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function dayLabel(days: number[] | null | undefined = []): string {
  const d = [...(Array.isArray(days) ? days : [])].sort((a, b) => a - b);
  if (d.length === 7) return "Every day";
  if (d.join() === "0,1,2,3,4") return "Weekdays";
  if (d.join() === "5,6") return "Weekends";
  if (d.length === 1) return `Every ${FULL_DAYS[d[0]] ?? "day"}`;
  return d.map((x) => DAYS[x] ?? String(x)).join(", ");
}
export function describeTrigger(a: Pick<Automation, "trigger_type" | "trigger_config">, events: EventInfo[] = []): string {
  const c = a.trigger_config ?? {};
  switch (a.trigger_type) {
    case "manual": return "Only when you run it";
    case "interval": {
      const s = c.every_seconds ?? 3600;
      const [n, unit] = s % 86400 === 0 ? [s / 86400, "day"] : s % 3600 === 0 ? [s / 3600, "hour"] : [Math.round(s / 60), "minute"];
      return n === 1 ? `Every ${unit}` : `Every ${n} ${unit}s`;
    }
    case "daily": return `Every day at ${clock(c.time)}`;
    case "weekly": return `${dayLabel(c.days)} at ${clock(c.time)}`;
    case "event": return `When ${(events.find((e) => e.name === c.event)?.label ?? c.event ?? "something happens").replace(/^A /, "a ")}`;
    default: return c.expression ? `Cron: ${c.expression}` : "Custom schedule";
  }
}
