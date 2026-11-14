// Contract between the Agents UI and the FastAPI backend.
export type AgentStatus = "active" | "paused";
// Retained only for the opt-in demo mock implementation. Not part of the backend contract.
export type RunMode = "ask" | "plan" | "auto";

export interface CatalogTool {
  id: string;
  name: string;
  description: string;
  group: string;
  access: "read" | "write";
  requires_approval: boolean;
}
export interface ModelInfo { id: string; name: string; provider: string }
export interface Catalog { tools: CatalogTool[]; models: ModelInfo[] }

export interface AgentDraft {
  name: string;
  description: string;
  instructions: string;
  model: string | null;
  tools: string[];
}
export interface ToolGrant { id: string; name: string; access: string }
export interface Agent extends Omit<AgentDraft, "tools"> {
  id: string;
  status: AgentStatus;
  tools: ToolGrant[];
  automation_names: string[];
  next_run_at?: string | null;
}
export interface AgentCard extends Agent {
  last_run_id: string | null;
  last_run_status: string | null;
  last_run_at: string | null;
  runs_7d: number;
  tool_count?: number | null;
}
