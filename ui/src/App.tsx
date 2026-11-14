import React, { useCallback, useState, useEffect } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  FileText,
  History,
  Inbox,
  LayoutGrid,
  Link2,
  MessageSquare,
  Moon,
  SlidersHorizontal,
  Sun,
  Workflow,
  Bot,
  X,
  Terminal,
} from "lucide-react";

// Pages
import { ChatPage } from "./features/chats/ChatPage";
import { loadConversationMessages } from "./features/chats/chatApi";
import TaskPage from "./features/tasks/TaskPage";
import NotesPage from "./features/notes/NotesPage";
import { NoteEditorPage } from "./features/notes/NoteEditorPage";
import { NoteDetailPage } from "./features/notes/NoteDetailPage";
import { CalendarPage } from "./features/calendar/CalendarPage";
import { InboxPage } from "./features/mail/InboxPage";
import { AgentsPage } from "./features/agents/AgentsPage";
import { AutomationPage } from "./features/automation/AutomationPage";
import { AutomationBuilderPage } from "./features/automation/AutomationBuilder";
import { AutomationDetailPage } from "./features/automation/AutomationDetailPage";
import { HistoryPage as AutomationActivityPage } from "./features/automation/HistoryPage";
import { HistoryPage } from "./features/history/HistoryPage";
import { ConnectionsPage } from "./features/connections/ConnectionsPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { TokenStats } from "./features/usage/TokenStats";
import { LogsPage } from "./features/logs/LogPage";
import { AgentBuilderPage } from "./features/agents/AgentBuilder";
import { AgentDetailPage } from "./features/agents/AgentDetailPage";
import { RunPage } from "./features/agents/RunPage";

class PageErrorBoundary extends React.Component<
  { page: string; children: React.ReactNode },
  { error: string | null }
> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return {
      error: error instanceof Error ? error.message : "Unexpected page error",
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`Husk page render failed (${this.props.page})`, error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="content-page">
          <div className="page-heading">
            <div>
              <h1>This page could not be displayed</h1>
              <p>Husk caught a page error instead of leaving a blank screen.</p>
            </div>
          </div>
          <div className="cx-note bad" role="alert">
            {this.state.error}
          </div>
          <button
            className="primary-button"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

type Page =
  | "chat"
  | "tasks"
  | "notes"
  | "calendar"
  | "mailbox"
  | "agents"
  | "automation"
  | "history"
  | "logs"
  | "connections"
  | "settings";

const navGroups = [
  {
    label: "WORKSPACE",
    items: [
      ["chat", "Ask Husk", MessageSquare],
      ["tasks", "Task board", LayoutGrid],
      ["notes", "Notes", FileText],
      ["calendar", "Calendar", CalendarDays],
      ["mailbox", "Inbox", Inbox],
    ],
  },
  {
    label: "PERSONAL AI",
    items: [
      ["agents", "Agents", Bot],
      ["automation", "Automation", Workflow],
    ],
  },
  {
    label: "PREFERENCES",
    items: [
      ["history", "History", History],
      ["logs", "Logs & Diagnostics", Terminal],
      ["connections", "Connections", Link2],
      ["settings", "Settings", SlidersHorizontal],
    ],
  },
] as const;

const titles: Record<Page, string> = {
  chat: "Ask Husk",
  tasks: "Task board",
  notes: "Notes",
  calendar: "Calendar",
  mailbox: "Inbox",
  agents: "Agents",
  automation: "Automation",
  history: "History",
  logs: "Logs & Diagnostics",
  connections: "Connections",
  settings: "Settings",
};

/** "/agents/new" → "New agent", "/automation/abc/edit" → "Edit automation", "/agents/abc" → "Details" … */
function subTitle(pathname: string): string | null {
  const [, section, a, b] = pathname.split("/");
  if (section === "notes") {
    if (a === "new") return "New note";
    if (b === "edit") return "Edit note";
    if (a) return "Note";
    return null;
  }
  if (section !== "agents" && section !== "automation") return null;
  const noun = section === "agents" ? "agent" : "automation";
  if (!a) return null;
  if (a === "new") return `New ${noun}`;
  if (a === "runs") return "Run";
  if (b === "edit") return `Edit ${noun}`;
  return "Details";
}

export function App() {
  const location = useLocation();
  const navigate = useNavigate();

  // 1. Permanently save & load theme from localStorage across browser restarts
  const [dark, setDark] = useState<boolean>(() => {
    const saved = localStorage.getItem("app_theme");
    return saved ? saved === "dark" : false;
  });

  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [toast, setToast] = useState<string>("");

  // 2. Persist active conversation ID and messages so they don't break on refresh or history click
  const [conversationId, setConversationId] = useState<string | null>(() => {
    return localStorage.getItem("active_conversation_id");
  });

  const [messages, setMessages] = useState<
    { role: "user" | "assistant"; text: string }[]
  >(() => {
    const saved = localStorage.getItem("active_chat_messages");
    return saved ? JSON.parse(saved) : [];
  });

  // Sync theme changes to localStorage and root HTML classes
  useEffect(() => {
    localStorage.setItem("app_theme", dark ? "dark" : "light");
    if (dark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [dark]);

  // Sync active conversation ID & messages storage
  useEffect(() => {
    if (conversationId) {
      localStorage.setItem("active_conversation_id", conversationId);
    } else {
      localStorage.removeItem("active_conversation_id");
    }
  }, [conversationId]);

  useEffect(() => {
    localStorage.setItem("active_chat_messages", JSON.stringify(messages));
  }, [messages]);

  const seg = location.pathname.split("/")[1] as Page;
  const page: Page = seg in titles ? seg : "chat";
  const sub = subTitle(location.pathname);

  const notify = useCallback((text: string) => {
    setToast(text);
    window.setTimeout(() => setToast(""), 2600);
  }, []);

  const navTo = (p: string) => navigate(`/${p}`);

  return (
    <div className={dark ? "app dark" : "app"}>
      {/* Sidebar Navigation */}
      <aside className={`sidebar ${sidebarOpen ? "" : "collapsed"}`}>
        <button
          className="brand"
          onClick={() => setSidebarOpen((open) => !open)}
          title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
        >
          <span className="brand-mark">
            <img
              src="/favicon.png"
              alt="Husk Logo"
              className="brand-logo-img"
              style={{
                width: 21,
                height: 21,
                objectFit: "contain",
              }}
            />
          </span>
          <span>
            husk<span className="brand-dot">.</span>
          </span>
        </button>
        <div className="nav-scroll">
          {navGroups.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="nav-label">{group.label}</div>
              {group.items.map(([key, label, Icon]) => (
                <button
                  key={key}
                  className={`nav-item ${page === key ? "active" : ""}`}
                  onClick={() => navTo(key)}
                >
                  <Icon size={16} />
                  <span>{label}</span>
                  {key === "connections" && <span className="status-dot" />}
                </button>
              ))}
            </div>
          ))}
        </div>
        <div className="sidebar-bottom">
          <div className="workspace-avatar">H</div>
          <div className="workspace-info">
            <strong>Your workspace</strong>
            <span>Stored on this device</span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main">
        <header className="topbar">
          <div className="breadcrumbs">
            <button className="crumb" onClick={() => navTo("chat")}>
              Workspace
            </button>
            <ChevronRight size={13} />
            {sub ? (
              <>
                <button className="crumb" onClick={() => navTo(page)}>
                  {titles[page]}
                </button>
                <ChevronRight size={13} />
                <span>{sub}</span>
              </>
            ) : (
              <span>{titles[page]}</span>
            )}
          </div>

          <TokenStats />

          <div className="topbar-actions">
            <button
              className="icon-button"
              title="Notifications"
              aria-label="Notifications"
              onClick={() => notify("You are all caught up")}
            >
              <Bell size={17} />
            </button>
          </div>
        </header>

        <section className="page-area">
          <PageErrorBoundary page={page} key={page}>
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route
                path="/chat"
                element={
                  <ChatPage
                    messages={messages}
                    setMessages={setMessages}
                    onNavigate={navTo}
                    notify={notify}
                    conversationId={conversationId}
                    setConversationId={setConversationId}
                  />
                }
              />
              <Route path="/tasks" element={<TaskPage />} />
              <Route path="/notes" element={<NotesPage notify={notify} />} />
              <Route
                path="/notes/new"
                element={<NoteEditorPage notify={notify} />}
              />
              <Route
                path="/notes/:id/edit"
                element={<NoteEditorPage notify={notify} />}
              />
              <Route
                path="/notes/:id"
                element={<NoteDetailPage notify={notify} />}
              />
              <Route
                path="/calendar"
                element={<CalendarPage notify={notify} />}
              />
              <Route
                path="/mailbox"
                element={<InboxPage onNavigate={navTo} notify={notify} />}
              />

              {/* Agents */}
              <Route path="/agents" element={<AgentsPage notify={notify} />} />
              <Route
                path="/agents/new"
                element={<AgentBuilderPage notify={notify} />}
              />
              <Route
                path="/agents/:id/edit"
                element={<AgentBuilderPage notify={notify} />}
              />
              <Route
                path="/agents/runs/:runId"
                element={<RunPage notify={notify} />}
              />
              <Route
                path="/agents/:id"
                element={<AgentDetailPage notify={notify} />}
              />
              {/* Automation */}
              <Route
                path="/automation"
                element={<AutomationPage notify={notify} />}
              />
              <Route
                path="/automation/new"
                element={<AutomationBuilderPage notify={notify} />}
              />
              <Route
                path="/automation/:id/edit"
                element={<AutomationBuilderPage notify={notify} />}
              />
              <Route
                path="/automation/:id"
                element={<AutomationDetailPage notify={notify} />}
              />
              <Route
                path="/automation/history"
                element={<AutomationActivityPage notify={notify} />}
              />

              <Route
                path="/history"
                element={
                  <HistoryPage
                    onSelectConversation={async (id) => {
                      try {
                        const stored = await loadConversationMessages(id);
                        setConversationId(id);
                        setMessages(
                          stored.map((m) => ({
                            role: m.role,
                            text: m.content,
                          })),
                        );
                        navigate("/chat");
                      } catch (e) {
                        notify(
                          e instanceof Error
                            ? e.message
                            : "Unable to open conversation",
                        );
                      }
                    }}
                    notify={notify}
                  />
                }
              />
              <Route path="/logs" element={<LogsPage notify={notify} />} />
              <Route
                path="/connections"
                element={<ConnectionsPage notify={notify} />}
              />
              <Route
                path="/settings"
                element={
                  <SettingsPage dark={dark} setDark={setDark} notify={notify} />
                }
              />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Routes>
          </PageErrorBoundary>
        </section>
      </main>

      {/* Global Notification Toast */}
      {toast && (
        <div className="toast">
          <CheckCircle2 size={16} />
          {toast}
        </div>
      )}
    </div>
  );
}

export function PageHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">WORKSPACE</div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {action && <div className="heading-action">{action}</div>}
    </div>
  );
}

export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose}>
            <X size={17} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default App;
