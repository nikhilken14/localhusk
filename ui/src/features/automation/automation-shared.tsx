import { useEffect, useRef, useState } from "react";
import { MoreHorizontal, Pause, Pencil, Play, Trash2 } from "lucide-react";
import { Modal } from "../agents/shared";
import type { Automation } from "./automation";

export type Tone = "ok" | "warn" | "bad" | "off";

/** Paused wins; otherwise the last run decides. */
export function jobStatus(a: Pick<Automation, "enabled" | "last_run_status">): { label: string; tone: Tone } {
  if (!a.enabled) return { label: "Paused", tone: "off" };
  if (a.last_run_status === "failed") return { label: "Failed", tone: "bad" };
  if (a.last_run_status === "awaiting_approval") return { label: "Awaiting approval", tone: "warn" };
  return { label: "Active", tone: "ok" };
}
export const needsAttention = (a: Pick<Automation, "last_run_status">) => a.last_run_status === "failed" || a.last_run_status === "awaiting_approval";

/** Accepts 0–1 or 0–100 so it works whichever the backend returns. */
export const pct = (n: number) => `${Math.round(n <= 1 ? n * 100 : n)}%`;

export function Badge({ label, tone }: { label: string; tone: Tone }) {
  return <span className={`au-badge ${tone}`}><i />{label}</span>;
}

export function Switch({ on, label, onChange }: { on: boolean; label: string; onChange: () => void }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className={`au-switch ${on ? "on" : ""}`} onClick={onChange}><span /></button>;
}

export function ActionMenu({ name, enabled, onEdit, onRun, onToggle, onDelete }:
  { name: string; enabled: boolean; onEdit?: () => void; onRun?: () => void; onToggle?: () => void; onDelete?: () => void }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    document.addEventListener("mousedown", away); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  const pick = (fn: () => void) => () => { setOpen(false); fn(); };
  return (
    <div className="ag-menu" ref={wrap}>
      <button ref={btn} className="bare-icon" aria-label={`More actions for ${name}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}><MoreHorizontal size={18} /></button>
      {open && (
        <div role="menu" className="ag-popover">
          {onRun && <button role="menuitem" onClick={pick(onRun)}><Play size={14} /> Run now</button>}
          {onEdit && <button role="menuitem" onClick={pick(onEdit)}><Pencil size={14} /> Edit</button>}
          {onToggle && <button role="menuitem" onClick={pick(onToggle)}>{enabled ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}</button>}
          {onDelete && <button role="menuitem" className="danger" onClick={pick(onDelete)}><Trash2 size={14} /> Delete</button>}
        </div>
      )}
    </div>
  );
}

export function DeleteAutomationDialog({ name, onClose, onConfirm }: { name: string | null; onClose: () => void; onConfirm: () => void }) {
  return (
    <Modal open={!!name} onClose={onClose}>
      {name && (
        <>
          <h3>Delete “{name}”?</h3>
          <p className="ag-muted">It will stop running and can’t be brought back. Past runs stay in History.</p>
          <div className="ag-actions">
            <button className="subtle-button" onClick={onClose} autoFocus>Cancel</button>
            <button className="primary-button danger" onClick={onConfirm}>Delete automation</button>
          </div>
        </>
      )}
    </Modal>
  );
}
