import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./notes.css";
import {
  LayoutGrid,
  LoaderCircle,
  MoreHorizontal,
  Pin,
  Plus,
  Search,
  X,
} from "lucide-react";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/+$/, "");

type NoteColor = "yellow" | "red" | "green";
type Filter = "all" | NoteColor | "pinned";
type SortKey = "updated" | "created" | "title";

type Note = {
  id: string;
  title: string;
  content: string;
  color: NoteColor;
  pinned: boolean;
  tags: string[];
  created_at: string;
  updated_at: string;
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

function plainPreview(markdown: string, max = 160): string {
  const text = markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[*_~>#-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  const elapsed = Date.now() - date.getTime();
  if (Number.isNaN(date.getTime())) return "";

  if (elapsed < 60_000) return "Just now";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} min ago`;
  if (elapsed < 86_400_000)
    return `${Math.floor(elapsed / 3_600_000)} hour${elapsed >= 7_200_000 ? "s" : ""} ago`;
  if (elapsed < 172_800_000) return "Yesterday";

  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

function colorLabel(c: NoteColor) {
  return c.charAt(0).toUpperCase() + c.slice(1);
}

export default function NotesPage({
  notify,
}: {
  notify?: (m: string) => void;
} = {}) {
  const navigate = useNavigate();
  const [notes, setNotes] = useState<Note[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<SortKey>("updated");
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);

  const loadNotes = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await apiRequest<Note[]>("/notes");
      setNotes(
        result.map((note) => ({
          ...note,
          tags: Array.isArray(note.tags) ? note.tags : [],
          color: note.color || "yellow",
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load notes.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadNotes();
  }, [loadNotes]);

  const counts = useMemo(() => {
    return {
      all: notes.length,
      green: notes.filter((n) => n.color === "green").length,
      yellow: notes.filter((n) => n.color === "yellow").length,
      red: notes.filter((n) => n.color === "red").length,
      pinned: notes.filter((n) => n.pinned).length,
    };
  }, [notes]);

  const filtered = useMemo(() => {
    const q = search.trim().toLocaleLowerCase();
    let list = notes.filter((note) => {
      if (filter === "pinned" && !note.pinned) return false;
      if (filter === "green" || filter === "yellow" || filter === "red") {
        if (note.color !== filter) return false;
      }
      if (!q) return true;
      const hay = [note.title, note.content, ...note.tags]
        .join(" ")
        .toLocaleLowerCase();
      return hay.includes(q);
    });

    list = [...list].sort((a, b) => {
      if (sort === "title") return a.title.localeCompare(b.title);
      const key = sort === "created" ? "created_at" : "updated_at";
      return new Date(b[key]).getTime() - new Date(a[key]).getTime();
    });

    return list;
  }, [notes, search, filter, sort]);

  const pinnedNotes = filtered.filter((n) => n.pinned);
  const otherNotes = filtered.filter((n) => !n.pinned);

  async function deleteNote(note: Note) {
    setError("");
    setDeletingId(note.id);
    setMenuId(null);
    try {
      await apiRequest<void>(`/notes/${note.id}`, { method: "DELETE" });
      setNotes((cur) => cur.filter((n) => n.id !== note.id));
      notify?.("Note deleted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete note.");
    } finally {
      setDeletingId(null);
    }
  }

  async function togglePin(note: Note) {
    setError("");
    setMenuId(null);
    try {
      await apiRequest<Note>(`/notes/${note.id}`, {
        method: "PATCH",
        body: JSON.stringify({ pinned: !note.pinned }),
      });
      await loadNotes();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to pin note.");
    }
  }

  function renderCard(note: Note) {
    const isDeleting = deletingId === note.id;
    const open = menuId === note.id;
    return (
      <article
        key={note.id}
        className={`note-card color-${note.color || "yellow"}`}
        role="link"
        aria-label={`Open note: ${note.title}`}
        tabIndex={0}
        onClick={() => navigate(`/notes/${encodeURIComponent(note.id)}`)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            navigate(`/notes/${encodeURIComponent(note.id)}`);
          }
        }}
      >
        <div className="note-card-top">
          <h3>{note.title}</h3>
          <div
            className="note-card-menu"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="bare-icon"
              aria-label="Note actions"
              aria-expanded={open}
              aria-haspopup="menu"
              onClick={(e) => {
                e.stopPropagation();
                setMenuId((cur) => (cur === note.id ? null : note.id));
              }}
            >
              <MoreHorizontal size={16} />
            </button>
            {open && (
              <div className="note-card-dropdown" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuId(null);
                    navigate(`/notes/${encodeURIComponent(note.id)}`);
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={(e) => {
                    e.stopPropagation();
                    void togglePin(note);
                  }}
                >
                  {note.pinned ? "Unpin" : "Pin to top"}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="danger"
                  disabled={isDeleting}
                  onClick={(e) => {
                    e.stopPropagation();
                    void deleteNote(note);
                  }}
                >
                  {isDeleting ? "Deleting…" : "Delete"}
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="note-card-body">
          <p>
            {note.content
              ? plainPreview(note.content)
              : "No additional details."}
          </p>
        </div>

        <div className="note-card-foot">
          <div className="note-card-tags">
            {note.tags.map((tag) => (
              <button
                type="button"
                className="tag"
                key={tag.toLocaleLowerCase()}
                onClick={(e) => {
                  e.stopPropagation();
                  setSearch(tag);
                }}
                title={`Search ${tag}`}
              >
                {tag}
              </button>
            ))}
          </div>
          <div className="note-card-meta">
            <span>{formatUpdatedAt(note.updated_at)}</span>
            {note.pinned && (
              <Pin size={12} className="pin-on" aria-label="Pinned" />
            )}
          </div>
        </div>
      </article>
    );
  }

  return (
    <main className="notes-page" onClick={() => setMenuId(null)}>
      <header className="notes-heading">
        <div>
          <h1>Notes</h1>
          <p>A little structure for your next big idea.</p>
        </div>
        <button
          className="primary-button"
          onClick={() => navigate("/notes/new")}
        >
          <Plus size={16} />
          Create note
        </button>
      </header>

      <section className="notes-toolbar">
        <label className="notes-search">
          <Search size={16} />
          <input
            aria-label="Search notes"
            placeholder="Search titles, content, or tags…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              type="button"
              className="bare-icon"
              aria-label="Clear search"
              onClick={() => setSearch("")}
            >
              <X size={14} />
            </button>
          )}
        </label>
        <div className="notes-toolbar-right">
          <select
            className="notes-sort"
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            aria-label="Sort notes"
          >
            <option value="updated">Recently updated</option>
            <option value="created">Recently created</option>
            <option value="title">Title</option>
          </select>
          <button
            type="button"
            className="notes-view-toggle"
            aria-label="Grid view"
            title="Grid view"
          >
            <LayoutGrid size={16} />
          </button>
        </div>
      </section>

      <section className="notes-filters" aria-label="Filter notes">
        {(
          [
            ["all", "All notes", counts.all],
            ["green", "Green", counts.green],
            ["yellow", "Yellow", counts.yellow],
            ["red", "Red", counts.red],
            ["pinned", "Pinned", counts.pinned],
          ] as const
        ).map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            className={`notes-chip ${filter === key ? "active" : ""}`}
            onClick={() => setFilter(key)}
          >
            {key !== "all" && key !== "pinned" && (
              <span className={`dot ${key}`} />
            )}
            {key === "pinned" && <Pin size={12} />}
            {label}
            <span className="count">{count}</span>
          </button>
        ))}
        <span className="notes-count-label">
          {filtered.length} note{filtered.length === 1 ? "" : "s"}
        </span>
      </section>

      {error && (
        <div className="notes-error" role="alert">
          <span>{error}</span>
          <button
            className="bare-icon"
            onClick={() => setError("")}
            aria-label="Dismiss"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {loading ? (
        <div className="notes-status">
          <LoaderCircle size={20} className="notes-spinner" />
          Loading notes…
        </div>
      ) : filtered.length === 0 ? (
        <div className="notes-empty">
          <h3>{notes.length === 0 ? "No notes yet" : "No notes found"}</h3>
          <p>
            {notes.length === 0
              ? "Create your first note to capture an idea."
              : "Try a different search or filter."}
          </p>
          {notes.length === 0 && (
            <button
              className="primary-button"
              onClick={() => navigate("/notes/new")}
            >
              <Plus size={15} />
              Create note
            </button>
          )}
        </div>
      ) : (
        <>
          {pinnedNotes.length > 0 && (
            <>
              <div className="notes-section-label">
                <Pin size={14} />
                Pinned
                <span>Keep the important things close.</span>
              </div>
              <section className="notes-grid" aria-label="Pinned notes">
                {pinnedNotes.map(renderCard)}
              </section>
            </>
          )}

          {otherNotes.length > 0 && (
            <>
              <div className="notes-section-label">
                All other notes
                <span>Your latest thoughts, in one place.</span>
              </div>
              <section className="notes-grid" aria-label="Notes">
                {otherNotes.map(renderCard)}
              </section>
            </>
          )}
        </>
      )}
    </main>
  );
}
