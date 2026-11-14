import React, { useState, useRef, useEffect } from "react";
import "./chat.css";
import {
  Sparkles,
  ArrowUpRight,
  ArrowDownRight,
  Plus,
  Send,
  Paperclip,
  X,
  FileText,
} from "lucide-react";
import {
  createConversation,
  streamMessage,
  uploadAttachment,
  type UploadedAttachment,
} from "./chatApi";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";

interface Message {
  role: "user" | "assistant";
  text: string;
}

interface ChatPageProps {
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  conversationId: string | null;
  setConversationId: (id: string | null) => void;
  onNavigate: (page: string) => void;
  notify?: (text: string) => void;
}

export function ChatPage({
  messages,
  setMessages,
  conversationId,
  setConversationId,
  onNavigate,
  notify,
}: ChatPageProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const conversationEndRef = useRef<HTMLDivElement>(null);

  // 1. Load conversation messages when conversationId changes (e.g. user clicked from History)
  useEffect(() => {
    if (conversationId && messages.length === 0) {
      // Fetch messages for this specific conversation ID from backend API or local storage
      // Example: fetch(`http://127.0.0.1:5173/api/conversations/${conversationId}`)
      const savedChats = localStorage.getItem(
        `chat_messages_${conversationId}`,
      );
      if (savedChats) {
        try {
          setMessages(JSON.parse(savedChats));
        } catch (e) {
          console.error("Failed to parse history messages", e);
        }
      }
    }
  }, [conversationId]);

  // 2. Save messages locally per conversation ID so history clicks instantly display them
  useEffect(() => {
    if (conversationId && messages.length > 0) {
      localStorage.setItem(
        `chat_messages_${conversationId}`,
        JSON.stringify(messages),
      );
    }
  }, [conversationId, messages]);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const startNewChat = () => {
    setConversationId(null);
    setMessages([]);
    localStorage.removeItem("active_conversation_id");
  };

  const sendMessage = async () => {
    const value = input.trim();
    if ((!value && pendingFiles.length === 0) || loading || uploading) return;

    const filesToSend = [...pendingFiles];
    const label =
      value ||
      (filesToSend.length
        ? `[Attached: ${filesToSend.map((f) => f.name).join(", ")}]`
        : "");

    const newMessages: Message[] = [...messages, { role: "user", text: label }];
    setMessages(newMessages);
    setInput("");
    setPendingFiles([]);
    setLoading(true);

    try {
      const activeId =
        conversationId ??
        (await createConversation((value || label).slice(0, 30)));
      if (!conversationId) {
        setConversationId(activeId);
        localStorage.setItem("active_conversation_id", activeId);
      }

      const attachmentIds: string[] = [];
      if (filesToSend.length) {
        setUploading(true);
        for (const file of filesToSend) {
          const uploaded: UploadedAttachment = await uploadAttachment(
            activeId,
            file,
          );
          attachmentIds.push(uploaded.id);
        }
        setUploading(false);
      }

      setMessages((old) => [...old, { role: "assistant", text: "" }]);

      await streamMessage(
        activeId,
        value,
        (currentText) => {
          setMessages((old) => {
            const updated = [...old];
            updated[updated.length - 1] = {
              role: "assistant",
              text: currentText,
            };
            return updated;
          });
        },
        attachmentIds,
      );
    } catch (err) {
      setUploading(false);
      setMessages((old) => {
        const next = [...old];
        if (
          next[next.length - 1]?.role === "assistant" &&
          next[next.length - 1]?.text === ""
        )
          next.pop();
        return [
          ...next,
          {
            role: "assistant",
            text: `Error: ${err instanceof Error ? err.message : "Could not connect to the backend."}`,
          },
        ];
      });
      notify?.(err instanceof Error ? err.message : "Chat request failed");
    } finally {
      setLoading(false);
      setUploading(false);
    }
  };

  const onPickFiles = (event: React.ChangeEvent<HTMLInputElement>) => {
    const list = event.target.files;
    if (!list?.length) return;
    const next = [...pendingFiles];
    for (const file of Array.from(list)) {
      if (next.length >= 8) break;
      next.push(file);
    }
    setPendingFiles(next);
    event.target.value = "";
  };

  return (
    <div className="chat-page">
      {messages.length > 0 && (
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            padding: "12px 40px 0",
          }}
        >
          <button
            className="outline-button"
            type="button"
            style={{ fontSize: "11px", padding: "6px 12px" }}
            onClick={startNewChat}
            disabled={loading}
          >
            <Plus size={14} /> New chat
          </button>
        </div>
      )}

      {messages.length === 0 ? (
        <div className="chat-page-empty">
          <div className="welcome">
            <div className="welcome-icon">
              <Sparkles size={18} />
            </div>
            <h1>What’s on your mind?</h1>
            <p>
              A little help to organize your day, make sense of your inbox,
              <br className="desktop-break" /> or get that next thing moving.
            </p>
            <div className="suggestions">
              {["Plan my day", "Clear my head", "Catch me up"].map((s, i) => (
                <button
                  key={s}
                  className="suggestion"
                  onClick={() => {
                    setInput(
                      [
                        "Help me plan my day using my tasks and calendar.",
                        "Help me organize my thoughts and turn them into notes and tasks.",
                        "Summarize what needs my attention in my inbox and tasks.",
                      ][i],
                    );
                  }}
                >
                  {s}
                  <ArrowUpRight size={14} />
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className="conversation-container">
          <div className="conversation">
            {messages.map((m, i) => (
              <div key={i} className={`message-row ${m.role}`}>
                <div className="message-label">
                  {m.role === "user" ? "You" : "Husk"}
                </div>
                <div className={`message-bubble ${m.role}`}>
                  {m.role === "user" ? (
                    m.text
                  ) : (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex, rehypeHighlight]}
                    >
                      {m.text ||
                        (loading && i === messages.length - 1
                          ? "Thinking..."
                          : "")}
                    </ReactMarkdown>
                  )}
                </div>
              </div>
            ))}
            <div ref={conversationEndRef} />
          </div>
        </div>
      )}

      <div className="composer-wrap">
        {pendingFiles.length > 0 && (
          <div className="composer-attachments">
            {pendingFiles.map((file, index) => (
              <span className="attachment-chip" key={`${file.name}-${index}`}>
                <FileText size={12} />
                <span className="attachment-name">{file.name}</span>
                <button
                  type="button"
                  className="attachment-remove"
                  aria-label={`Remove ${file.name}`}
                  onClick={() =>
                    setPendingFiles((files) =>
                      files.filter((_, i) => i !== index),
                    )
                  }
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="composer">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.xlsx,.xlsm,.zip,.txt,.md,.csv,.json,.log"
            style={{ display: "none" }}
            onChange={onPickFiles}
          />
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder="Ask anything, attach a PDF/DOCX/XLSX/ZIP, or tell me what you need..."
            rows={1}
          />
          <div className="composer-actions">
            <button
              type="button"
              className="attach-button"
              title="Attach documents (pdf, docx, xlsx, zip, txt)"
              disabled={loading || uploading || pendingFiles.length >= 8}
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip size={16} />
            </button>
            <span className="composer-hint">
              {uploading
                ? "Uploading…"
                : "Shift + Enter for a new line · files → LLM context"}
            </span>
            <button
              className="send-button"
              onClick={sendMessage}
              title="Send message"
              disabled={loading || !input.trim()}
            >
              <Send size={14} />
            </button>
          </div>
        </div>
        <div className="composer-foot">
          <span>Conversations saved by day. A fresh start every morning.</span>
          <button onClick={() => onNavigate("history")}>
            Daily report <ArrowDownRight size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
