import React, { useCallback, useEffect, useState } from "react";
import { API_BASE_URL } from "../../api-base";
import "./mail.css";
import {
  RefreshCw,
  Search,
  Mail,
  Send,
  X,
  Inbox,
  AlertCircle,
} from "lucide-react";

interface InboxPageProps {
  onNavigate: (page: string) => void;
  notify?: (text: string) => void;
}

type Account = {
  id: string;
  email: string;
  display_name: string;
  status: string;
};

type MailSummary = {
  id: string;
  account_id: string;
  folder: string;
  subject: string;
  sender: { name: string; email: string };
  snippet: string;
  is_read: boolean;
  received_at: string;
};

type MailDetail = MailSummary & {
  body_text: string;
  body_html: string;
  cc: { name: string; email: string }[];
};

// Decode HTML entities like &#39;, &quot;, &amp;, &lt;, &gt;
function decodeHTMLEntities(text: string): string {
  if (!text) return "";
  const textarea = document.createElement("textarea");
  textarea.innerHTML = text;
  return textarea.value;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;

    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((x: any) => x.msg ?? "Invalid request").join("; ")
          : response.statusText,
    );
  }

  return response.status === 204 ? (undefined as T) : response.json();
}

const when = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
  }

  return date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });
};

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "?";

export function InboxPage({ onNavigate, notify }: InboxPageProps) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [messages, setMessages] = useState<MailSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MailDetail | null>(null);

  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const query = new URLSearchParams({
        folder: "inbox",
        limit: "25",
        offset: "0",
      });

      if (searchTerm.trim()) {
        query.set("q", searchTerm.trim());
      }

      const [accountRows, messagePage] = await Promise.all([
        api<Account[]>("/mail/accounts"),
        api<{ items: MailSummary[] }>(`/mail/messages?${query.toString()}`),
      ]);

      const rows = (messagePage.items ?? []).slice(0, 25);

      setAccounts(accountRows);
      setMessages(rows);

      setSelectedId((current) =>
        current && rows.some((message) => message.id === current)
          ? current
          : (rows[0]?.id ?? null),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load mailbox");
    } finally {
      setLoading(false);
    }
  }, [searchTerm]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let active = true;

    setDetail(null);
    setReply("");

    if (!selectedId)
      return () => {
        active = false;
      };

    api<MailDetail>(`/mail/messages/${encodeURIComponent(selectedId)}`)
      .then(async (message) => {
        if (!active) return;

        setDetail(message);

        if (!message.is_read) {
          try {
            await api(`/mail/messages/${encodeURIComponent(message.id)}`, {
              method: "PATCH",
              body: JSON.stringify({ is_read: true }),
            });

            if (active) {
              setMessages((rows) =>
                rows.map((row) =>
                  row.id === message.id ? { ...row, is_read: true } : row,
                ),
              );
            }
          } catch {
            // Read status update non-fatal error fallback
          }
        }
      })
      .catch((e) => {
        if (active) {
          notify?.(e instanceof Error ? e.message : "Unable to open message");
        }
      });

    return () => {
      active = false;
    };
  }, [selectedId, notify]);

  const sync = async () => {
    if (syncing || accounts.length === 0) return;
    setSyncing(true);

    try {
      const result = await api<{
        synced: { error?: string }[];
      }>("/mail/sync", {
        method: "POST",
        body: JSON.stringify({}),
      });

      const failures = (result.synced ?? []).filter((row) => row.error);

      notify?.(
        failures.length
          ? `Sync finished with ${failures.length} account error(s)`
          : "Inbox synced successfully",
      );

      await load();
    } catch (e) {
      notify?.(e instanceof Error ? e.message : "Inbox sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const sendReply = async () => {
    if (!detail || !reply.trim() || sending) return;

    setSending(true);

    try {
      await api(`/mail/messages/${encodeURIComponent(detail.id)}/send-reply`, {
        method: "POST",
        body: JSON.stringify({
          body: reply.trim(),
          html: false,
          reply_all: false,
        }),
      });

      setReply("");
      notify?.("Reply sent");
    } catch (e) {
      notify?.(e instanceof Error ? e.message : "Unable to send reply");
    } finally {
      setSending(false);
    }
  };

  const selected = messages.find((message) => message.id === selectedId);
  const unreadCount = messages.filter((message) => !message.is_read).length;

  return (
    <div className="content-page mailbox-page">
      {/* Top Header Toolbar */}
      <div className="inbox-toolbar">
        <div className="inbox-toolbar-left">
          <div className="inbox-title">
            <Inbox size={18} />
            <strong>Inbox</strong>
            <span className="inbox-count">{messages.length}</span>
          </div>

          <span className="inbox-divider" />

          <span className="inbox-account-status">
            {accounts.length > 0
              ? `${accounts.length} connected account${accounts.length !== 1 ? "s" : ""}`
              : "No connected accounts"}
          </span>

          {unreadCount > 0 && (
            <span className="inbox-unread-count">{unreadCount} unread</span>
          )}
        </div>

        <div className="inbox-toolbar-right">
          <button
            className="inbox-sync-button"
            onClick={sync}
            disabled={syncing || accounts.length === 0}
          >
            <RefreshCw size={14} className={syncing ? "inbox-spinning" : ""} />
            <span>{syncing ? "Syncing..." : "Sync"}</span>
          </button>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="inbox-error-banner">
          <AlertCircle size={15} />
          <span>{error}</span>
          <button className="subtle-button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {/* Main Mail Layout */}
      {accounts.length === 0 && !loading && !error ? (
        <div className="inbox-connect-state">
          <div className="inbox-empty-icon">
            <Mail size={24} />
          </div>
          <strong>No email account connected</strong>
          <p>
            Connect Google or Microsoft to access your inbox directly inside
            Husk.
          </p>
          <button
            className="primary-button"
            onClick={() => onNavigate("connections")}
          >
            Open Connections
          </button>
        </div>
      ) : (
        <div className="mail-layout">
          {/* Left Column: Email List */}
          <section className="mail-list-pane">
            <div className="mail-toolbar">
              <div className="search-box inbox-search">
                <Search size={14} />
                <input
                  placeholder="Search your inbox..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  aria-label="Search inbox"
                />
                {searchTerm && (
                  <button
                    className="inbox-clear-search"
                    onClick={() => setSearchTerm("")}
                    aria-label="Clear search"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
            </div>

            <div className="mail-list-heading">
              <span>MESSAGES</span>
              <span>{messages.length} of 25</span>
            </div>

            <div className="mail-list-scroll">
              {loading && (
                <div className="inbox-list-message">
                  <RefreshCw size={16} className="inbox-spinning" />
                  <span>Loading messages...</span>
                </div>
              )}

              {!loading && messages.length === 0 && (
                <div className="inbox-list-message">
                  <Mail size={22} />
                  <strong>No messages found</strong>
                  <span>Try another search query or sync your inbox.</span>
                </div>
              )}

              {!loading &&
                messages.map((message) => {
                  const senderName = decodeHTMLEntities(
                    message.sender.name ||
                      message.sender.email ||
                      "Unknown sender",
                  );
                  const subjectText = decodeHTMLEntities(
                    message.subject || "(No subject)",
                  );
                  const snippetText = decodeHTMLEntities(
                    message.snippet || "No preview available.",
                  );

                  return (
                    <button
                      key={message.id}
                      className={`mail-row ${
                        selectedId === message.id ? "selected" : ""
                      } ${!message.is_read ? "unread" : ""}`}
                      onClick={() => setSelectedId(message.id)}
                    >
                      <div className="mail-row-header">
                        <span className="mail-sender">
                          {!message.is_read && (
                            <i className="mail-unread-dot" />
                          )}
                          {senderName}
                        </span>
                        <span className="mail-time">
                          {when(message.received_at)}
                        </span>
                      </div>

                      <div className="mail-row-subject">{subjectText}</div>

                      <div className="mail-row-snippet">{snippetText}</div>
                    </button>
                  );
                })}
            </div>
          </section>

          {/* Right Column: Reading Pane */}
          <section className="mail-detail">
            {detail ? (
              <div className="mail-detail-scroll">
                <div className="mail-detail-head">
                  <span className="mail-detail-label">MESSAGE</span>
                  <h2>
                    {decodeHTMLEntities(detail.subject || "(No subject)")}
                  </h2>
                </div>

                <div className="sender-card">
                  <div className="sender-avatar">
                    {initials(detail.sender.name || detail.sender.email || "?")}
                  </div>

                  <div className="sender-info">
                    <strong>
                      {decodeHTMLEntities(
                        detail.sender.name ||
                          detail.sender.email ||
                          "Unknown sender",
                      )}
                    </strong>
                    <span>
                      {detail.sender.email}
                      {accounts.find(
                        (account) => account.id === detail.account_id,
                      )?.email && (
                        <>
                          {" · "}
                          to{" "}
                          {
                            accounts.find(
                              (account) => account.id === detail.account_id,
                            )?.email
                          }
                        </>
                      )}
                    </span>
                  </div>

                  <time className="mail-time">{when(detail.received_at)}</time>
                </div>

                {detail.cc?.length > 0 && (
                  <div className="mail-cc">
                    CC:{" "}
                    {detail.cc
                      .map((person) => person.name || person.email)
                      .join(", ")}
                  </div>
                )}

                <div className="mail-body">
                  <p>
                    {decodeHTMLEntities(
                      detail.body_text ||
                        detail.snippet ||
                        "No plain-text body available.",
                    )}
                  </p>
                </div>

                {/* Reply Composer */}
                <div className="reply-box">
                  <div className="reply-box-heading">
                    <span>
                      Reply to {detail.sender.name || detail.sender.email}
                    </span>
                  </div>

                  <textarea
                    placeholder="Write your reply..."
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                  />

                  <div className="reply-box-footer">
                    <span className="reply-hint">
                      Reply will be sent via connected email provider.
                    </span>

                    <button
                      className="primary-button"
                      disabled={!reply.trim() || sending}
                      onClick={sendReply}
                    >
                      <Send size={13} />
                      {sending ? "Sending..." : "Send reply"}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="inbox-reader-empty">
                <div className="inbox-reader-icon">
                  <Mail size={24} />
                </div>
                <strong>
                  {selected ? "Loading message..." : "Select an email"}
                </strong>
                <p>
                  {selected
                    ? decodeHTMLEntities(selected.snippet)
                    : "Choose a message from your inbox to read it here."}
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
