import type { AgentCard } from "./types";

/** Optional fields the list endpoint may (or may not) return. */
export type AgentCardX = AgentCard & { model?: string | null; tool_count?: number | null };

export type RunStatus = "queued" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled";

export interface AgentRun {
  id: string;
  status: RunStatus;
  started_at: string;
  duration_ms: number | null;
  tool_calls: number;
  tokens: number | null;
  model?: string | null;
  result?: any;
  error?: string | null;
  goal?: string;
  agent_id?: string | null;
  job_id?: string | null;
}

/** Loose view of GET /agents/:id – every extra field is optional so the page works with the current backend. */
export interface AgentLike {
  id: string;
  name: string;
  description?: string;
  instructions?: string;
  status: "active" | "paused";
  model?: string | null;
  tools?: { id?: string; name: string; access: string }[];
  tool_count?: number | null;
  run_mode?: string | null;
  memory?: boolean | string | null;
  next_run_at?: string | null;
  automation_names?: string[];
  last_run_id?: string | null;
  last_run_status?: string | null;
  last_run_at?: string | null;
  runs_7d?: number;
}
