import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import { ArrowLeft, CalendarDays, Clock3, Edit3, LoaderCircle, Pin } from "lucide-react";
import "./notes.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/+$/, "");
type NoteColor = "yellow" | "red" | "green";
type Note = {
  id: string; title: string; content: string; color: NoteColor; pinned: boolean;
  tags?: string[]; created_at?: string; updated_at?: string;
};

async function getNote(id: string): Promise<Note> {
  const response = await fetch(`${API_BASE}/notes/${encodeURIComponent(id)}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Unable to load note (${response.status})`);
  }
  return response.json();
}

function dateLabel(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, {
    dateStyle: "medium", timeStyle: "short",
  });
}

export function NoteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [note, setNote] = useState<Note | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) { setError("A note ID is required."); setLoading(false); return; }
    let active = true;
    setLoading(true); setError("");
    getNote(id).then((value) => { if (active) setNote(value); })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : "Unable to load note."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  if (loading) return <main className="notes-detail-page"><div className="notes-status"><LoaderCircle size={20} className="notes-spinner" /> Loading note…</div></main>;
  if (error || !note) return (
    <main className="notes-detail-page">
      <Link className="notes-back" to="/notes"><ArrowLeft size={14} /> Back to notes</Link>
      <div className="notes-error" role="alert">{error || "This note could not be found."}</div>
      <button className="outline-button" onClick={() => navigate("/notes")}>Return to notes</button>
    </main>
  );

  return (
    <main className="notes-detail-page">
      <div className="notes-detail-topbar">
        <Link className="notes-back" to="/notes"><ArrowLeft size={14} /> Back to notes</Link>
        <button className="primary-button" onClick={() => navigate(`/notes/${encodeURIComponent(note.id)}/edit`)}>
          <Edit3 size={14} /> Edit note
        </button>
      </div>
      <article className={`notes-detail-card color-${note.color || "yellow"}`}>
        <header className="notes-detail-header">
          <div className="notes-detail-eyebrow">
            <span className={`dot ${note.color || "yellow"}`} />
            <span>{(note.color || "yellow").charAt(0).toUpperCase() + (note.color || "yellow").slice(1)} priority</span>
            {note.pinned && <span className="notes-detail-pinned"><Pin size={12} /> Pinned</span>}
          </div>
          <h1>{note.title || "Untitled note"}</h1>
          <div className="notes-detail-meta">
            {note.created_at && <span><CalendarDays size={13} /> Created {dateLabel(note.created_at)}</span>}
            {note.updated_at && <span><Clock3 size={13} /> Updated {dateLabel(note.updated_at)}</span>}
          </div>
          {!!note.tags?.length && <div className="notes-detail-tags">{note.tags.map(tag => <span className="tag" key={tag}>{tag}</span>)}</div>}
        </header>
        <div className="notes-detail-content markdown-body">
          {note.content?.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex, rehypeHighlight]}>
              {note.content}
            </ReactMarkdown>
          ) : <p className="notes-detail-empty">This note is empty. Select Edit note to add content.</p>}
        </div>
      </article>
    </main>
  );
}

export default NoteDetailPage;
