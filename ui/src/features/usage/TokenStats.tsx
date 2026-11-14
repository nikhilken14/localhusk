import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { fmtTokens, useTokenUsage } from "./useTokenUsage";

/** Topbar model status + today's token counters. Shows 0 / 0 when no LLM is connected. */
export function TokenStats() {
  const { usage, error } = useTokenUsage();
  const label = error ? "Usage unavailable" : usage.connected ? usage.model ?? "Model connected" : "No model connected";
  return (
    <div className="topbar-center" title="Tokens used today · resets at midnight">
      <span className="live-dot" style={usage.connected ? undefined : { background: "#aab2ac", animation: "none" }} />
      <span>{label}</span>
      <span className="token-stat"><ArrowUpRight size={15} /> In <b>{fmtTokens(usage.input)}</b></span>
      <span className="token-stat"><ArrowDownRight size={15} /> Out <b>{fmtTokens(usage.output)}</b></span>
    </div>
  );
}
