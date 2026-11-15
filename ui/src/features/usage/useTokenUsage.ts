import { API_BASE_URL } from "../../api-base";
import { useCallback, useEffect, useState } from "react";

/**
 * Tokens used TODAY (local midnight → now).
 *
 * Backend contract (assumed – adjust the URL/field names to your API):
 *   GET /usage/today?since=<ISO timestamp of the user's local midnight>
 *   → { connected: boolean, model?: string, input_tokens: number, output_tokens: number }
 *
 * Rules:
 *  - no LLM connected (connected:false), or the request fails → both counters show 0
 *  - counters reset at local midnight without a page reload
 *  - refreshes every 30 s, when the tab regains focus, and whenever something
 *    dispatches `window.dispatchEvent(new Event("husk:usage"))` (e.g. ChatPage after a reply)
 *
 */
export type TokenUsage = { connected: boolean; hasModels: boolean; input: number; output: number; model: string | null };

const ZERO: TokenUsage = { connected: false, hasModels: false, input: 0, output: 0, model: null };
const BASE = API_BASE_URL;

const localMidnight = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };

async function fetchUsage(): Promise<TokenUsage> {
  const r = await fetch(`${BASE}/usage/today?since=${encodeURIComponent(localMidnight().toISOString())}`);
  if (!r.ok) throw new Error(r.statusText);
  const j = await r.json();
  const defaultModel = j.default_model ?? null;
  const connected = Boolean(defaultModel);
  return {
    connected,
    hasModels: Array.isArray(j.models) && j.models.length > 0,
    input: Number(j.input_tokens) || 0,
    output: Number(j.output_tokens) || 0,
    model: defaultModel ? `${defaultModel.name ?? defaultModel.kind ?? "Model"} / ${defaultModel.model ?? "default"}` : null,
  };
}

/** 0 · 842 · 2.8K · 12K · 1.2M */
export function fmtTokens(n: number): string {
  n = Math.max(0, Math.round(n));
  if (n < 1000) return String(n);
  if (n < 999_500) { const k = n / 1000; return (k < 9.95 ? k.toFixed(1) : String(Math.round(k))) + "K"; }
  const m = n / 1_000_000; return (m < 9.95 ? m.toFixed(1) : String(Math.round(m))) + "M";
}

export function useTokenUsage() {
  const [usage, setUsage] = useState<TokenUsage>(ZERO);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    try { setUsage(await fetchUsage()); setError(false); }
    catch { setUsage(ZERO); setError(true); }
  }, []);

  useEffect(() => {
    refresh();
    const poll = window.setInterval(() => { if (!document.hidden) refresh(); }, 30_000);
    const wake = () => { if (!document.hidden) refresh(); };
    const ping = () => { refresh(); };
    window.addEventListener("focus", wake);
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("husk:usage", ping);

    // new day → zero immediately, then re-fetch
    let midnight: number;
    const arm = () => {
      const ms = localMidnight().getTime() + 86_400_000 - Date.now() + 1000;
      midnight = window.setTimeout(() => { setUsage((u) => ({ ...u, input: 0, output: 0 })); refresh(); arm(); }, ms);
    };
    arm();

    return () => {
      window.clearInterval(poll); window.clearTimeout(midnight);
      window.removeEventListener("focus", wake);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("husk:usage", ping);
    };
  }, [refresh]);

  return { usage, error, refresh };
}
