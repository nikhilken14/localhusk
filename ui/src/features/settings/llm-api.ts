import { API_BASE_URL } from "../../api-base";
/* Backend contract (assumed – adapt here; the page doesn't care how it's served):
     GET    /llm/models                 → LlmModel[]          (never includes the API key – only has_key)
     POST   /llm/models                 → LlmModel
     PUT    /llm/models/:id             → LlmModel            (api_key omitted/empty = keep the saved key)
     DELETE /llm/models/:id
     POST   /llm/models/:id/default     → LlmModel
     POST   /llm/models/:id/test        → { ok: boolean; latency_ms?: number; error?: string }
     POST   /llm/discover               → { models: string[] } (asks the endpoint which models it serves, e.g. GET {endpoint}/models)
   The same list should feed /agents/catalog (`models`) so agents can pick any of them. */

export type Provider = "Ollama" | "OpenAI" | "Anthropic" | "Google Gemini" | "OpenAI-compatible";
const toKind = (p: Provider) => ({ "Ollama": "openai_compatible", "OpenAI": "openai", "Anthropic": "anthropic", "Google Gemini": "gemini", "OpenAI-compatible": "openai_compatible" } as const)[p];
const fromKind = (k: string): Provider => ({ openai: "OpenAI", anthropic: "Anthropic", gemini: "Google Gemini", openai_compatible: "OpenAI-compatible", ollama: "Ollama" } as Record<string, Provider>)[k] ?? "OpenAI-compatible";
function normalizeModel(raw: any): LlmModel {
  return { id: raw.id, name: raw.name, provider: fromKind(raw.kind), endpoint: raw.base_url ?? "", model: raw.model,
    has_key: !!raw.has_api_key, max_tokens: raw.max_output_tokens ?? 2048, temperature: raw.temperature ?? 0.7,
    stream: true, is_default: !!raw.is_default, connectivity: raw.connectivity } as LlmModel;
}
function backendDraft(d: LlmDraft) {
  const payload: Record<string, unknown> = { name: d.name, kind: toKind(d.provider), base_url: d.endpoint || null, model: d.model,
    max_output_tokens: d.max_tokens, temperature: d.temperature };
  // The backend treats an explicit empty string as a request to delete a stored key.
  // An untouched/blank form field must therefore be omitted, not serialized as "".
  if (d.api_key?.trim()) payload.api_key = d.api_key.trim();
  return payload;
}
export const PRESETS: Record<Provider, string> = {
  Ollama: "http://127.0.0.1:11434/v1",
  OpenAI: "https://api.openai.com/v1",
  Anthropic: "https://api.anthropic.com",
  "Google Gemini": "https://generativelanguage.googleapis.com/v1beta",
  "OpenAI-compatible": "",
};
export const needsKey = (p: Provider) => p === "OpenAI" || p === "Anthropic" || p === "Google Gemini";

export interface LlmModel {
  id: string; name: string; provider: Provider; endpoint: string; model: string;
  has_key: boolean; max_tokens: number; temperature: number; stream: boolean; is_default: boolean; connectivity?: {status:string; latency_ms?:number|null; checked_at?:string|null; error?:string|null};
}
export interface LlmDraft {
  name: string; provider: Provider; endpoint: string; model: string; api_key?: string;
  max_tokens: number; temperature: number; stream: boolean;
}
export interface TestResult { ok: boolean; latency_ms?: number; error?: string }

const BASE = API_BASE_URL;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const d = body.detail;
    throw new Error((Array.isArray(d) ? d.map((e: any) => e.msg).join("; ") : d) ?? r.statusText);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

export const llmApi = {
  list: () =>
    req<any[]>("/llm/models").then((rows) => rows.map(normalizeModel)),
  add: (d: LlmDraft) =>
    req<any>("/llm/models", {
      method: "POST",
      body: JSON.stringify(backendDraft(d)),
    }).then(normalizeModel),
  update: (id: string, d: LlmDraft) =>
    req<any>(`/llm/models/${id}`, {
      method: "PUT",
      body: JSON.stringify(backendDraft(d)),
    }).then(normalizeModel),
  remove: (id: string) =>
    req<void>(`/llm/models/${id}`, { method: "DELETE" }),
  setDefault: (id: string) =>
    req<LlmModel>(`/llm/models/${id}/default`, { method: "POST" }),
  test: (id: string): Promise<TestResult> =>
    req<TestResult>(`/llm/models/${id}/test`, { method: "POST" }),
  discover: (p: {
    provider: Provider;
    endpoint: string;
    api_key?: string;
  }): Promise<string[]> =>
    req<{ models: string[] }>("/llm/discover", {
      method: "POST",
      body: JSON.stringify({
        kind: toKind(p.provider),
        base_url: p.endpoint,
        api_key: p.api_key,
      }),
    }).then((r) => r.models),
};
