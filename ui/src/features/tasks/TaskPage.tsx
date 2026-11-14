import { useCallback, useEffect, useState } from "react";
import "./tasks.css";
import {
  CalendarDays,
  Check,
  LoaderCircle,
  Plus,
  Trash2,
  X,
} from "lucide-react";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1"
).replace(/\/+$/, "");

type TaskStatus = "todo" | "in_progress" | "done";
type ColumnKey = "To Do" | "In Progress" | "Done";

type Task = {
  id: string;
  task: string;
  status: TaskStatus;
  due_at: string | null;
  position: number;
  created_at: string;
  updated_at: string;
};

type TaskInput = {
  task: string;
  status: TaskStatus;
  due_at: string | null;
  position: number;
};

const COLUMNS: {
  key: ColumnKey;
  status: TaskStatus;
  label: string;
}[] = [
  { key: "To Do", status: "todo", label: "To Do" },
  { key: "In Progress", status: "in_progress", label: "In Progress" },
  { key: "Done", status: "done", label: "Done" },
];

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
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function formatDueDate(value: string | null): string {
  if (!value) return "No due date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No due date";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year:
      date.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined,
  });
}

function toLocalDateTimeInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function getInitialColumns(tasks: Task[]) {
  const grouped: Record<ColumnKey, Task[]> = {
    "To Do": [],
    "In Progress": [],
    Done: [],
  };

  for (const task of tasks) {
    const column = COLUMNS.find((item) => item.status === task.status);
    if (column) grouped[column.key].push(task);
  }

  return grouped;
}

export default function TaskPage() {
  const [tasks, setTasks] = useState<Record<ColumnKey, Task[]>>({
    "To Do": [],
    "In Progress": [],
    Done: [],
  });

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<ColumnKey | null>(null);

  // Create Modal State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newTaskText, setNewTaskText] = useState("");
  const [newDueAt, setNewDueAt] = useState("");

  // Edit Modal State
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [editTask, setEditTask] = useState("");
  const [editDueAt, setEditDueAt] = useState("");

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await apiRequest<Task[]>("/tasks");
      setTasks(getInitialColumns(result));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load tasks.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    const checkDoneTasksExpiration = () => {
      const now = Date.now();
      const oneDayMs = 24 * 60 * 60 * 1000;

      tasks.Done.forEach((task) => {
        const updatedAtTime = new Date(task.updated_at).getTime();
        if (now - updatedAtTime >= oneDayMs) {
          void apiRequest(`/tasks/${task.id}`, { method: "DELETE" })
            .then(() => {
              void loadTasks();
            })
            .catch(() => {});
        }
      });
    };

    const interval = setInterval(checkDoneTasksExpiration, 60_000);
    checkDoneTasksExpiration();

    return () => clearInterval(interval);
  }, [tasks.Done, loadTasks]);

  function openCreateModal() {
    setNewTaskText("");
    setNewDueAt("");
    setIsCreateModalOpen(true);
  }

  async function handleCreateTask(event: React.FormEvent) {
    event.preventDefault();
    if (!newTaskText.trim() || saving) return;

    setSaving(true);
    setError("");

    const payload: TaskInput = {
      task: newTaskText.trim(),
      status: "todo",
      due_at: newDueAt ? new Date(newDueAt).toISOString() : null,
      position: 0,
    };

    try {
      await apiRequest<Task>("/tasks", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setNewTaskText("");
      setNewDueAt("");
      setIsCreateModalOpen(false);
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create task.");
    } finally {
      setSaving(false);
    }
  }

  function openEditModal(task: Task) {
    setEditingTask(task);
    setEditTask(task.task);
    setEditDueAt(toLocalDateTimeInput(task.due_at));
  }

  async function handleUpdateTask(event: React.FormEvent) {
    event.preventDefault();
    if (!editingTask || !editTask.trim() || saving) return;

    setSaving(true);
    setError("");

    const payload = {
      task: editTask.trim(),
      due_at: editDueAt ? new Date(editDueAt).toISOString() : null,
    };

    try {
      await apiRequest<Task>(`/tasks/${editingTask.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setEditingTask(null);
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update task.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteTask(task: Task) {
    try {
      await apiRequest<void>(`/tasks/${task.id}`, {
        method: "DELETE",
      });

      setTasks((current) => {
        const updated = { ...current };
        for (const column of COLUMNS) {
          updated[column.key] = current[column.key].filter(
            (item) => item.id !== task.id,
          );
        }
        return updated;
      });
      setEditingTask(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete task.");
    }
  }

  async function moveTask(task: Task, destination: ColumnKey) {
    const target = COLUMNS.find((item) => item.key === destination);
    if (!target || target.status === task.status || saving) return;

    setTasks((current) => {
      const sourceColumn = COLUMNS.find(
        (item) => item.status === task.status,
      )?.key;

      if (!sourceColumn) return current;

      const sourceTasks = current[sourceColumn].filter(
        (item) => item.id !== task.id,
      );

      const movedTask: Task = {
        ...task,
        status: target.status,
        updated_at: new Date().toISOString(),
        position: 0,
      };

      return {
        ...current,
        [sourceColumn]: sourceTasks,
        [destination]: [
          movedTask,
          ...current[destination].filter((item) => item.id !== task.id),
        ],
      };
    });

    setError("");

    try {
      await apiRequest<Task>(`/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: target.status,
          position: 0,
        }),
      });

      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to move task.");
      await loadTasks();
    }
  }

  return (
    <main className="task-page">
      <header className="task-page-heading">
        <div>
          <h1>Task board</h1>
          <p>Plan your work, track progress, and get things done.</p>
        </div>

        <button className="primary-button" onClick={openCreateModal}>
          <Plus size={16} />
          Add task
        </button>
      </header>

      {error && (
        <div className="task-error" role="alert">
          <span>{error}</span>
          <button
            className="bare-icon"
            onClick={() => setError("")}
            aria-label="Dismiss error"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {loading ? (
        <div className="task-status">
          <LoaderCircle className="task-spinner" size={20} />
          Loading tasks...
        </div>
      ) : (
        <section className="board" aria-label="Task board">
          {COLUMNS.map((column) => (
            <div
              className={`board-column ${
                dragOverColumn === column.key ? "drag-over" : ""
              }`}
              key={column.key}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverColumn(column.key);
              }}
              onDragLeave={(event) => {
                if (
                  !event.currentTarget.contains(
                    event.relatedTarget as Node | null,
                  )
                ) {
                  setDragOverColumn(null);
                }
              }}
              onDrop={(event) => {
                event.preventDefault();
                setDragOverColumn(null);

                const taskId = event.dataTransfer.getData("task-id");
                if (!taskId) return;

                const task = COLUMNS.flatMap((item) => tasks[item.key]).find(
                  (item) => item.id === taskId,
                );

                if (task) void moveTask(task, column.key);
                setDraggedTaskId(null);
              }}
            >
              <div className="column-heading">
                <div className="column-title">
                  <span
                    className={`column-dot ${column.status.replace("_", "-")}`}
                  />
                  {column.label}
                  {column.status === "done" && <Check size={14} />}
                </div>

                <span className="column-count">{tasks[column.key].length}</span>
              </div>

              <div className="task-list">
                {tasks[column.key].map((task) => {
                  const isDone = task.status === "done";
                  return (
                    <article
                      className={`task-card ${
                        draggedTaskId === task.id ? "is-dragging" : ""
                      }`}
                      key={task.id}
                      draggable={!saving}
                      onClick={() => openEditModal(task)}
                      style={{ cursor: "pointer" }}
                      onDragStart={(event) => {
                        event.dataTransfer.setData("task-id", task.id);
                        event.dataTransfer.effectAllowed = "move";
                        setDraggedTaskId(task.id);
                      }}
                      onDragEnd={() => {
                        setDraggedTaskId(null);
                        setDragOverColumn(null);
                      }}
                    >
                      <p
                        style={{
                          textDecoration: isDone ? "line-through" : "none",
                          opacity: isDone ? 0.7 : 1,
                          margin: 0,
                          fontWeight: 500,
                        }}
                      >
                        {task.task}
                      </p>

                      <div
                        className="task-card-bottom"
                        style={{
                          marginTop: "12px",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                        }}
                      >
                        <span
                          className="task-due"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                            fontSize: "12px",
                            color: "#64748b",
                          }}
                        >
                          <CalendarDays size={12} />
                          {formatDueDate(task.due_at)}
                        </span>
                      </div>
                    </article>
                  );
                })}

                {tasks[column.key].length === 0 && (
                  <div className="task-column-empty">
                    {column.status === "todo"
                      ? "No tasks in To Do."
                      : "Drop a task here."}
                  </div>
                )}
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Add Task Modal */}
      {isCreateModalOpen && (
        <div
          className="task-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget)
              setIsCreateModalOpen(false);
          }}
        >
          <section className="task-modal" role="dialog" aria-modal="true">
            <div className="task-modal-heading">
              <h2>Add task</h2>
              <button
                type="button"
                className="bare-icon"
                onClick={() => setIsCreateModalOpen(false)}
                disabled={saving}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateTask}>
              <label className="task-field">
                <span>Task</span>
                <input
                  autoFocus
                  required
                  maxLength={240}
                  value={newTaskText}
                  onChange={(event) => setNewTaskText(event.target.value)}
                />
              </label>

              <label className="task-field">
                <span>Due date</span>
                <input
                  type="datetime-local"
                  value={newDueAt}
                  onChange={(event) => setNewDueAt(event.target.value)}
                />
              </label>

              <div
                className="task-modal-actions"
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: "8px",
                  marginTop: "20px",
                }}
              >
                <button
                  type="button"
                  className="subtle-button"
                  onClick={() => setIsCreateModalOpen(false)}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="primary-button"
                  disabled={saving || !newTaskText.trim()}
                >
                  {saving ? "Adding..." : "Add task"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {/* Edit / Delete Task Modal */}
      {editingTask && (
        <div
          className="task-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setEditingTask(null);
          }}
        >
          <section className="task-modal" role="dialog" aria-modal="true">
            <div className="task-modal-heading">
              <h2>Edit task</h2>
              <button
                type="button"
                className="bare-icon"
                onClick={() => setEditingTask(null)}
                disabled={saving}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleUpdateTask}>
              <label className="task-field">
                <span>Task</span>
                <input
                  autoFocus
                  required
                  maxLength={240}
                  value={editTask}
                  onChange={(event) => setEditTask(event.target.value)}
                />
              </label>

              <label className="task-field">
                <span>Due date</span>
                <input
                  type="datetime-local"
                  value={editDueAt}
                  onChange={(event) => setEditDueAt(event.target.value)}
                />
              </label>

              <div
                className="task-modal-actions"
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  marginTop: "20px",
                }}
              >
                <button
                  type="button"
                  className="task-delete-button"
                  onClick={() => void deleteTask(editingTask)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    color: "#dc2626",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontWeight: 500,
                  }}
                >
                  <Trash2 size={16} />
                  Delete task
                </button>

                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    type="button"
                    className="subtle-button"
                    onClick={() => setEditingTask(null)}
                    disabled={saving}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={saving || !editTask.trim()}
                  >
                    {saving ? "Saving..." : "Save changes"}
                  </button>
                </div>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>
  );
}
