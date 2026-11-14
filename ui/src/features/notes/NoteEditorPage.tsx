import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import {
  ArrowLeft,
  Check,
  LoaderCircle,
  Pin,
  Plus,
  ShieldCheck,
  X,
} from "lucide-react";
import "./notes.css";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/+$/, "");

type NoteColor = "yellow" | "red" | "green";

type Note = {
  id: string;
  title: string;
  content: string;
  color: NoteColor;
  pinned: boolean;
  tags: string[];
};

type NotePayload = {
  title: string;
  content: string;
  color: NoteColor;
  pinned: boolean;
  tags: string[];
};

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(result?.detail || `Request failed (${response.status})`);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function plainPreview(markdown: string, max = 100): string {
  const text = markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*_~>#-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

export function NoteEditorPage({
  notify,
}: {
  notify?: (m: string) => void;
}) {
  const { id } = useParams();
  const navigate = useNavigate();
  const isEdit = Boolean(id && id !== "new");
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"write" | "preview">("write");

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [color, setColor] = useState<NoteColor>("yellow");
  const [tags, setTags] = useState<string[]>([]);
  const [tagDraft, setTagDraft] = useState("");
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    if (!id || id === "new") return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const note = await apiRequest<Note>(`/notes/${id}`);
        if (cancelled) return;
        setTitle(note.title || "");
        setContent(note.content || "");
        setColor((note.color as NoteColor) || "yellow");
        setTags(Array.isArray(note.tags) ? note.tags : []);
        setPinned(Boolean(note.pinned));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to load note.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  function addTag() {
    const raw = tagDraft.trim().replace(/\s+/g, " ");
    if (!raw) return;
    const key = raw.toLocaleLowerCase();
    if (tags.some((t) => t.toLocaleLowerCase() === key)) {
      setTagDraft("");
      return;
    }
    setTags((cur) => [...cur, raw]);
    setTagDraft("");
  }

  function removeTag(tag: string) {
    setTags((cur) => cur.filter((t) => t !== tag));
  }

  /** Apply a content change and restore the caret in the textarea. */
  function applyEdit(next: string, selectStart: number, selectEnd: number = selectStart) {
    setContent(next);
    setMode("write");
    requestAnimationFrame(() => {
      const el = bodyRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(selectStart, selectEnd);
    });
  }

  function getSelection() {
    const el = bodyRef.current;
    if (!el) {
      return { start: content.length, end: content.length, selected: "" };
    }
    const start = el.selectionStart ?? 0;
    const end = el.selectionEnd ?? 0;
    return { start, end, selected: content.slice(start, end) };
  }

  /** Inline wrap/toggle: bold **, italic *, inline code ` */
  function toggleInline(marker: string) {
    const { start, end, selected } = getSelection();
    const before = content.slice(0, start);
    const after = content.slice(end);
    const m = marker;
    const mLen = m.length;

    // Already wrapped → unwrap
    if (
      selected &&
      before.endsWith(m) &&
      after.startsWith(m)
    ) {
      const next = before.slice(0, -mLen) + selected + after.slice(mLen);
      applyEdit(next, start - mLen, start - mLen + selected.length);
      return;
    }
    // Selection itself includes markers → unwrap
    if (
      selected.startsWith(m) &&
      selected.endsWith(m) &&
      selected.length > mLen * 2
    ) {
      const inner = selected.slice(mLen, selected.length - mLen);
      const next = before + inner + after;
      applyEdit(next, start, start + inner.length);
      return;
    }

    const inner = selected || "text";
    const next = before + m + inner + m + after;
    const selStart = start + mLen;
    applyEdit(next, selStart, selStart + inner.length);
  }

  /** Prefix current line(s) for headings / lists. */
  function prefixLines(prefix: string, ordered = false) {
    const { start, end } = getSelection();
    // Expand to full lines
    const lineStart = content.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    let lineEnd = content.indexOf("\n", end);
    if (lineEnd === -1) lineEnd = content.length;

    const block = content.slice(lineStart, lineEnd);
    const lines = block.length ? block.split("\n") : [""];

    const strip = (line: string) =>
      line
        .replace(/^#{1,6}\s+/, "")
        .replace(/^[-*+]\s+/, "")
        .replace(/^\d+\.\s+/, "");

    const isMatch = (line: string) => {
      if (!line.trim()) return true;
      if (ordered) return /^\d+\.\s+/.test(line);
      if (prefix.startsWith("#")) return /^#{1,6}\s+/.test(line);
      return line.startsWith(prefix);
    };

    const allPrefixed = lines.every(isMatch);
    const nextLines = lines.map((line, i) => {
      const core = strip(line) || (allPrefixed ? "" : "text");
      if (!line.trim() && allPrefixed) return line;
      if (allPrefixed) return core;
      if (ordered) return `${i + 1}. ${core}`;
      return `${prefix}${core}`;
    });

    const replacement = nextLines.join("\n");
    const next =
      content.slice(0, lineStart) + replacement + content.slice(lineEnd);
    applyEdit(next, lineStart, lineStart + replacement.length);
  }

  function insertLink() {
    const { start, end, selected } = getSelection();
    const label = selected || "link text";
    const snippet = `[${label}](https://)`;
    const next = content.slice(0, start) + snippet + content.slice(end);
    // Select the URL part for easy overwrite
    const urlStart = start + label.length + 3; // [label](
    applyEdit(next, urlStart, urlStart + "https://".length);
  }

  function insertCode() {
    const { start, end, selected } = getSelection();
    // Multi-line or empty → fenced block; else inline
    if (!selected || selected.includes("\n")) {
      const body = selected || "code";
      const snippet = `\`\`\`\n${body}\n\`\`\``;
      const next = content.slice(0, start) + snippet + content.slice(end);
      const selStart = start + 4; // after ```\n
      applyEdit(next, selStart, selStart + body.length);
      return;
    }
    toggleInline("`");
  }

  function format(action: "h2" | "bold" | "italic" | "bullet" | "link" | "code") {
    // Ensure we're in write mode so the textarea exists
    if (mode !== "write") {
      setMode("write");
      // Defer so the textarea mounts, then retry once
      requestAnimationFrame(() => {
        requestAnimationFrame(() => format(action));
      });
      return;
    }
    switch (action) {
      case "h2":
        prefixLines("## ");
        break;
      case "bold":
        toggleInline("**");
        break;
      case "italic":
        toggleInline("*");
        break;
      case "bullet":
        prefixLines("- ");
        break;
      case "link":
        insertLink();
        break;
      case "code":
        insertCode();
        break;
    }
  }

  async function saveNote() {
    if (!title.trim() || saving) return;
    setSaving(true);
    setError("");

    // tags are shown in the UI; backend NoteIn does not persist tags yet
    const payload: NotePayload = {
      title: title.trim(),
      content: content.trim(),
      color,
      pinned,
      tags: [],
    };

    try {
      if (isEdit && id) {
        await apiRequest<Note>(`/notes/${id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        notify?.("Note updated");
      } else {
        await apiRequest<Note>("/notes", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        notify?.("Note created");
      }
      navigate(isEdit && id ? `/notes/${encodeURIComponent(id)}` : "/notes");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save note.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <main className="notes-editor-page">
        <div className="notes-status">
          <LoaderCircle size={20} className="notes-spinner" />
          Loading note…
        </div>
      </main>
    );
  }

  return (
    <main className="notes-editor-page">
      <Link className="notes-back" to={isEdit && id ? `/notes/${encodeURIComponent(id)}` : "/notes"}>
        <ArrowLeft size={14} /> Back to notes
      </Link>

      <header className="notes-heading">
        <div>
          <h1>{isEdit ? "Edit note" : "Create note"}</h1>
          <p>
            {isEdit
              ? "Update this idea and keep it easy to find."
              : "Capture an idea. Make it easy to find later."}
          </p>
        </div>
      </header>

      {error && (
        <div className="notes-error" role="alert">
          <span>{error}</span>
        </div>
      )}

      <div className="notes-editor-layout">
        <div className="notes-editor-main">
          <label className="sr-only" htmlFor="note-title">
            Title
          </label>
          <input
            id="note-title"
            className="notes-title-input"
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Note title"
          />

          <div className="notes-md-toolbar" role="toolbar" aria-label="Formatting">
            <button
              type="button"
              className={mode === "write" ? "active" : ""}
              onClick={() => setMode("write")}
            >
              Write
            </button>
            <button
              type="button"
              className={mode === "preview" ? "active" : ""}
              onClick={() => setMode("preview")}
            >
              Preview
            </button>
            <span className="sep" />
            <button type="button" title="Heading" onClick={() => format("h2")}>
              H2
            </button>
            <button type="button" title="Bold" onClick={() => format("bold")}>
              <strong>B</strong>
            </button>
            <button type="button" title="Italic" onClick={() => format("italic")}>
              <em>I</em>
            </button>
            <button type="button" title="Bullet list" onClick={() => format("bullet")}>
              • List
            </button>
            <button type="button" title="Link" onClick={() => format("link")}>
              Link
            </button>
            <button type="button" title="Code" onClick={() => format("code")}>
              {"</>"}
            </button>
          </div>

          {mode === "write" ? (
            <textarea
              ref={bodyRef}
              className="notes-body-area"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Add a thought, paste a link, or keep writing…"
            />
          ) : (
            <div className="notes-md-preview markdown-body">
              {content.trim() ? (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex, rehypeHighlight]}
                >
                  {content}
                </ReactMarkdown>
              ) : (
                <p style={{ color: "var(--muted)" }}>Nothing to preview yet.</p>
              )}
            </div>
          )}

          <div className="notes-editor-foot">
            <span>Markdown supported · headings, lists, code, tables & math</span>
            <span>{content.trim() ? "Draft" : "Empty"}</span>
          </div>
        </div>

        <aside className="notes-editor-side">
          <section className="notes-side-card">
            <h4>Note color</h4>
            <p>Choose a color to recognize it at a glance.</p>
            <div className="notes-color-swatches">
              {(["green", "yellow", "red"] as NoteColor[]).map((c) => (
                <button
                  key={c}
                  type="button"
                  className={`notes-swatch ${c} ${color === c ? "selected" : ""}`}
                  aria-label={c}
                  aria-pressed={color === c}
                  onClick={() => setColor(c)}
                >
                  {color === c && (
                    <span className="check">
                      <Check size={16} strokeWidth={3} />
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="notes-swatch-labels">
              <span>Green</span>
              <span>Yellow</span>
              <span>Red</span>
            </div>
          </section>

          <section className="notes-side-card">
            <h4>Tags</h4>
            <p>Group related ideas for easy retrieval.</p>
            {tags.length > 0 && (
              <div className="notes-tag-chips">
                {tags.map((tag) => (
                  <span className="chip" key={tag.toLocaleLowerCase()}>
                    {tag}
                    <button
                      type="button"
                      aria-label={`Remove ${tag}`}
                      onClick={() => removeTag(tag)}
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="notes-tag-input-row">
              <input
                value={tagDraft}
                onChange={(e) => setTagDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTag();
                  }
                }}
                placeholder="Add a tag…"
              />
            </div>
            <p style={{ margin: "8px 0 0", fontSize: 11, color: "var(--muted)" }}>
              Press Enter to add
            </p>
          </section>

          <section className="notes-side-card">
            <div className="notes-pin-row">
              <div className="label">
                <strong>
                  <Pin size={14} /> Pin to top
                </strong>
                <span>Keep it above other notes.</span>
              </div>
              <button
                type="button"
                className={`notes-switch ${pinned ? "on" : ""}`}
                role="switch"
                aria-checked={pinned}
                onClick={() => setPinned((v) => !v)}
              >
                <span />
              </button>
            </div>
          </section>

          <section className="notes-side-card">
            <h4 style={{ marginBottom: 10, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--muted)" }}>
              Card preview
            </h4>
            <div className={`notes-preview-card color-${color}`}>
              <h5>{title.trim() || "Untitled note"}</h5>
              <p>
                {content.trim()
                  ? plainPreview(content)
                  : "Your note preview will appear here."}
              </p>
              <div className="notes-preview-meta">
                <span className={`dot ${color}`} style={{ background: color === "green" ? "#5c9272" : color === "red" ? "#c46b66" : "#c4a35a" }} />
                <span>{color.charAt(0).toUpperCase() + color.slice(1)}</span>
                {tags.length > 0 && <span>· {tags.join(" · ")}</span>}
              </div>
            </div>
          </section>
        </aside>
      </div>

      <div className="notes-editor-bar">
        <span className="stored">
          <ShieldCheck size={14} />
          Stored on this device
        </span>
        <div className="actions">
          <button
            type="button"
            className="subtle-button"
            onClick={() => navigate(isEdit && id ? `/notes/${encodeURIComponent(id)}` : "/notes")}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={saving || !title.trim()}
            onClick={() => void saveNote()}
          >
            {saving ? (
              <>
                <LoaderCircle size={15} className="notes-spinner" />
                Saving…
              </>
            ) : isEdit ? (
              "Save changes"
            ) : (
              <>
                <Plus size={15} /> Create note
              </>
            )}
          </button>
        </div>
      </div>
    </main>
  );
}

export default NoteEditorPage;
