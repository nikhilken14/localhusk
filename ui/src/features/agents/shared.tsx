import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { FileText, MoreHorizontal, Paperclip, Pause, Pencil, Play, Trash2, X } from "lucide-react";

/* ---------- helpers ---------- */
export const hash = (s: string | number | null | undefined) =>
  [...String(s ?? "")].reduce((n, c) => n + c.charCodeAt(0), 0);

export function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  const rtf = new Intl.RelativeTimeFormat([], { numeric: "auto" });
  if (mins < 60) return rtf.format(-Math.max(mins, 1), "minute");
  if (mins < 1440) return rtf.format(-Math.round(mins / 60), "hour");
  return rtf.format(-Math.round(mins / 1440), "day");
}

/** “Today, 09:42” · “Yesterday, 16:18” · “Oct 20, 08:05” (also handles “Tomorrow”). */
export function when(iso: string): string {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(new Date()) - day(d)) / 86_400_000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (diff === 0) return `Today, ${time}`;
  if (diff === 1) return `Yesterday, ${time}`;
  if (diff === -1) return `Tomorrow, ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })}, ${time}`;
}

export function duration(ms: number | null | undefined): string {
  if (ms == null) return "–";
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
}

const RUN: Record<string, [label: string, tone: "ok" | "warn" | "bad" | "info"]> = {
  completed: ["Completed", "ok"],
  awaiting_approval: ["Needs approval", "warn"],
  failed: ["Failed", "bad"],
  running: ["Running", "info"],
  queued: ["Queued", "info"],
  deferred: ["Waiting for LLM", "warn"],
  cancelled: ["Cancelled", "info"],
};
export const runTone = (status: string) => RUN[status]?.[1] ?? "info";
export const runLabel = (status: string) => RUN[status]?.[0] ?? status;

export function StatusBadge({ status }: { status: string }) {
  return <span className={`ag-run ${runTone(status)}`}><i />{runLabel(status)}</span>;
}

/* ---------- dialog ---------- */
export function Modal({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return <dialog ref={ref} className="ag-dialog" onCancel={onClose} onClose={onClose}>{open && children}</dialog>;
}

export function RunDialog({
  agent,
  onClose,
  onRun,
}: {
  agent: { name: string } | null;
  onClose: () => void;
  onRun: (input: string, files: File[]) => void;
}) {
  return (
    <Modal open={!!agent} onClose={onClose}>
      {agent && <RunForm name={agent.name} onClose={onClose} onRun={onRun} />}
    </Modal>
  );
}
function RunForm({
  name,
  onClose,
  onRun,
}: {
  name: string;
  onClose: () => void;
  onRun: (input: string, files: File[]) => void;
}) {
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <h3>Run “{name}”</h3>
      <label className="ag-field">
        What should it focus on? <small>(optional if you attach files)</small>
        <textarea
          rows={3}
          maxLength={4000}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Leave empty to use its usual instructions, or attach docs"
          autoFocus
        />
      </label>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept=".pdf,.docx,.xlsx,.xlsm,.zip,.txt,.md,.csv,.json,.log"
        style={{ display: "none" }}
        onChange={(e) => {
          const list = e.target.files;
          if (!list?.length) return;
          setFiles((prev) => [...prev, ...Array.from(list)].slice(0, 8));
          e.target.value = "";
        }}
      />
      <div className="ab-attach-row">
        <button
          type="button"
          className="subtle-button"
          onClick={() => fileRef.current?.click()}
        >
          <Paperclip size={14} /> Attach docs
        </button>
        {files.length > 0 && (
          <span className="ab-attach-count">{files.length}/8 selected</span>
        )}
        {files.map((f, i) => (
          <span key={`${f.name}-${i}`} className="ab-file-chip">
            <FileText size={12} />
            {f.name}
            <button
              type="button"
              className="ab-file-remove"
              onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
              aria-label={`Remove ${f.name}`}
            >
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      {files.length > 0 && (
        <p className="ag-muted" style={{ marginTop: -4, marginBottom: 10 }}>
          Documents are uploaded when you run and passed to the agent as context.
        </p>
      )}
      <div className="ag-actions">
        <button className="subtle-button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary-button"
          disabled={!input.trim() && files.length === 0}
          onClick={() => onRun(input, files)}
        >
          <Play size={14} /> Run now
        </button>
      </div>
    </>
  );
}

export function DeleteDialog({ agent, onClose, onConfirm }: { agent: { name: string; automation_names?: string[] } | null; onClose: () => void; onConfirm: () => void }) {
  const autos = agent?.automation_names ?? [];
  return (
    <Modal open={!!agent} onClose={onClose}>
      {agent && (
        <>
          <h3>Delete “{agent.name}”?</h3>
          <p className="ag-muted">It can’t be brought back.</p>
          {autos.length > 0 && (
            <div className="ag-note warn">
              Used by {autos.map((n) => `“${n}”`).join(", ")}. {autos.length === 1 ? "That automation" : "Those automations"} will be turned off until you choose another agent.
            </div>
          )}
          <div className="ag-actions">
            <button className="subtle-button" onClick={onClose} autoFocus>Cancel</button>
            <button className="primary-button danger" onClick={onConfirm}>Delete agent</button>
          </div>
        </>
      )}
    </Modal>
  );
}

/* ---------- row menu (pass only the actions you want) ---------- */
export function RowMenu({ name, paused, onEdit, onRun, onToggle, onDelete }:
  { name: string; paused: boolean; onEdit?: () => void; onRun?: () => void; onToggle?: () => void; onDelete?: () => void }) {
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
          {onEdit && <button role="menuitem" onClick={pick(onEdit)}><Pencil size={14} /> Edit</button>}
          {onRun && <button role="menuitem" disabled={paused} title={paused ? "Resume this agent to run it" : undefined} onClick={pick(onRun)}><Play size={14} /> Run now</button>}
          {onToggle && <button role="menuitem" onClick={pick(onToggle)}>{paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}</button>}
          {onDelete && <button role="menuitem" className="danger" onClick={pick(onDelete)}><Trash2 size={14} /> Delete</button>}
        </div>
      )}
    </div>
  );
}
