import { API_BASE_URL } from "../../api-base";
import type { Agent, AgentDraft, Catalog } from "./types";

const BASE = API_BASE_URL;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type") && init?.body != null) {
    headers.set("Content-Type", "application/json");
  }
  const r = await fetch(BASE + path, {
    credentials: "include",
    ...init,
    headers,
  });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const d = body.detail ?? body.message ?? body.error;
    const msg = Array.isArray(d)
      ? d.map((e: any) => e.msg ?? String(e)).join("; ")
      : typeof d === "string"
        ? d
        : r.statusText;
    throw new Error(msg || r.statusText);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

const toBackend = (a: AgentDraft) => ({
  name: a.name,
  description: a.description,
  system_prompt: a.instructions,
  provider_id: a.model || null,
  tools: a.tools,
  // Do not send status on create/update — use PATCH /status. Sending the
  // schema default would re-activate a paused agent on every save.
});

function normalizeAgent(raw: any): any {
  const tools = Array.isArray(raw.tools)
    ? raw.tools.map((t: any) =>
        typeof t === "string"
          ? { id: t, name: t, access: "read" }
          : {
              id: t.id ?? t.name,
              name: t.name ?? t.id,
              access: t.access ?? (t.requires_approval ? "write" : "read"),
            },
      )
    : [];
  const stats = raw.stats ?? {};
  return {
    ...raw,
    instructions: raw.system_prompt ?? "",
    model: raw.provider_id ?? null,
    tools,
    automation_names: raw.automation_names ?? [],
    last_run_id: raw.last_run_id ?? null,
    last_run_status: raw.last_run_status ?? null,
    last_run_at: stats.last_run_at ?? raw.last_run_at ?? null,
    // Prefer explicit 7-day count; fall back to total only when backend lacks it
    runs_7d: stats.runs_7d ?? raw.runs_7d ?? 0,
    tool_count: raw.tool_count ?? tools.length,
  };
}

function normalizeCatalog(raw: any): Catalog {
  return {
    tools: (raw.tools ?? []).map((t: any) => ({
      id: t.id,
      name: t.name,
      description: t.description ?? "",
      group: t.category ?? t.group ?? "Other",
      access: t.access ?? (t.requires_approval ? "write" : "read"),
      requires_approval: !!t.requires_approval,
    })),
    models: (raw.models ?? []).map((m: any) => ({
      id: m.id,
      name: m.name ?? m.model ?? m.id,
      provider: m.provider ?? m.kind ?? "unknown",
    })),
  };
}

function normalizeRun(x: any) {
  let result = x.result;
  if (typeof result === "string") {
    try {
      result = JSON.parse(result);
    } catch {
      /* keep string */
    }
  }
  const started = x.started_at ?? x.created_at ?? null;
  const finished = x.finished_at ?? x.updated_at ?? null;
  let duration_ms: number | null =
    typeof x.duration_ms === "number" ? x.duration_ms : null;
  if (
    duration_ms == null &&
    started &&
    finished &&
    ["completed", "failed", "cancelled"].includes(String(x.status))
  ) {
    const a = new Date(started).getTime();
    const b = new Date(finished).getTime();
    if (Number.isFinite(a) && Number.isFinite(b) && b >= a) duration_ms = b - a;
  }
  const steps = Array.isArray(result?.completed_steps)
    ? result.completed_steps
    : [];
  return {
    id: x.id,
    status: x.status,
    started_at: started,
    duration_ms,
    tool_calls:
      steps.length ||
      (typeof x.tool_calls === "number" ? x.tool_calls : 0),
    tokens:
      typeof x.input_tokens === "number" || typeof x.output_tokens === "number"
        ? (x.input_tokens ?? 0) + (x.output_tokens ?? 0)
        : null,
    model: x.model ?? null,
    result,
    error: x.error ?? null,
    goal: x.input ?? x.goal,
    agent_id: x.agent_id ?? null,
    job_id: x.job_id ?? null,
  };
}

export const agentsApi = {
  catalog: () =>
    req<any>("/agents/catalog").then(normalizeCatalog),
  list: () =>
    req<any[]>("/agents").then((rows) => rows.map(normalizeAgent)),
  overview: (since: Date) =>
    req<any>(
          `/agents/overview?since=${encodeURIComponent(since.toISOString())}`,
        ).then((r) => ({ runs_today: r.totals?.total ?? 0 })),
  get: (id: string) =>
     req<any>(`/agents/${id}`).then(normalizeAgent),
  runs: (id: string) =>
    req<any>(`/agents/${id}/runs`).then((r) => {
          const items = Array.isArray(r) ? r : (r.items ?? r.results ?? []);
          return items.map(normalizeRun);
        }),
  create: (a: AgentDraft) =>
     req<any>("/agents", {
          method: "POST",
          body: JSON.stringify(toBackend(a)),
        }).then(normalizeAgent),
  update: (id: string, a: AgentDraft) =>
     req<any>(`/agents/${id}`, {
          method: "PUT",
          body: JSON.stringify(toBackend(a)),
        }).then(normalizeAgent),
  remove: (id: string) =>
    req<void>(`/agents/${id}`, { method: "DELETE" }),
  setStatus: (id: string, status: "active" | "paused") =>
     req<any>(`/agents/${id}/status?status=${status}`, {
          method: "PATCH",
        }).then(normalizeAgent),
  uploadAttachment: async (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch(BASE + `/agents/${id}/attachments`, {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      const d = body.detail ?? body.message ?? r.statusText;
      throw new Error(typeof d === "string" ? d : "Upload failed");
    }
    return r.json() as Promise<{ id: string; filename: string; size_bytes: number; extracted_chars?: number }>;
  },
  run: (id: string, input = "", attachmentIds: string[] = []) =>
    req<any>(`/agents/${id}/run`, {
          method: "POST",
          body: JSON.stringify({
            input: input || (attachmentIds.length ? "" : "Run the agent"),
            attachment_ids: attachmentIds,
          }),
        }).then((r) => ({ run_id: r.run_id ?? r.id, status: r.status })),
  /** Backend: POST /agents/approvals/{id}/resolve with { decision } — worker resumes on approve. */
  resolve: (approvalId: string, decision: "approved" | "rejected") =>
    req<any>(`/agents/approvals/${approvalId}/resolve`, {
          method: "POST",
          body: JSON.stringify({ decision }),
        }),
  allRuns: async (limit = 200) => {
    try {
      const r = await req<any>(`/agents/runs?limit=${limit}`);
      const items = Array.isArray(r) ? r : (r.items ?? r.results ?? []);
      return items.map(normalizeRun);
    } catch {
      // Global list may not exist yet — return empty rather than break activity page
      return [];
    }
  },
  getRun: (runId: string) =>
     req<any>(`/agents/runs/${runId}`).then((x) =>
          x ? normalizeRun(x) : null,
        ),
  cancelRun: (runId: string) =>
     req<any>(`/agents/runs/${runId}/cancel`, { method: "POST" }),
  events: (
    runId: string,
    after = 0,
  ): Promise<{
    events: any[];
    next_sequence: number;
    done?: boolean;
    run_status?: string;
  }> =>
    req<{
          events: any[];
          next_sequence: number;
          done?: boolean;
          run_status?: string;
        }>(`/agents/runs/${runId}/events?after_sequence=${after}`),
};
