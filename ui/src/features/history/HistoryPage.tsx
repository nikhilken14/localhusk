import React, { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../../api-base";
import {
  Clock3,
  Search,
  MessageSquare,
  ChevronRight,
  RefreshCw,
  MessageSquareX,
} from "lucide-react";
import "./history.css";

interface HistoryItem {
  id: string;
  title: string;
  preview: string;
  updated_at: string;
}

interface HistoryPageProps {
  onSelectConversation: (conversationId: string) => void;
  notify?: (text: string) => void;
}

// Clean raw Markdown stars and formatting symbols out of previews
function cleanPreviewText(text: string): string {
  if (!text) return "";
  return text
    .replace(/\*\*(.*?)\*\*/g, "$1") // Remove bold **
    .replace(/\*(.*?)\*/g, "$1") // Remove italics *
    .replace(/`(.*?)`/g, "$1") // Remove code inline `
    .replace(/#+\s?/g, "") // Remove header #
    .trim();
}

export function HistoryPage({
  onSelectConversation,
  notify,
}: HistoryPageProps) {
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = () => {
    setLoading(true);
    const query = new URLSearchParams({ days: "5", limit: "100", q: search });
    fetch(`${API_BASE_URL}/history?${query.toString()}`)
      .then(async (r) => {
        if (!r.ok) throw new Error("Unable to load history");
        return r.json();
      })
      .then((data) => {
        setItems(Array.isArray(data.items) ? data.items : []);
      })
      .catch((e) => {
        notify?.(e.message || "Unable to load history");
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchHistory();
  }, [search]);

  // Group history items by relative date categories
  const groupedItems = useMemo(() => {
    const groups: { [key: string]: HistoryItem[] } = {};
    const now = new Date();

    items.forEach((item) => {
      const itemDate = new Date(item.updated_at);
      const diffDays = Math.floor(
        (now.getTime() - itemDate.getTime()) / (1000 * 3600 * 24),
      );

      let groupKey = "Earlier this week";
      if (diffDays === 0 && now.getDate() === itemDate.getDate()) {
        groupKey = "Today";
      } else if (diffDays <= 1) {
        groupKey = "Yesterday";
      }

      if (!groups[groupKey]) groups[groupKey] = [];
      groups[groupKey].push(item);
    });

    return groups;
  }, [items]);

  return (
    <div className="history-page">
      {/* Page Header */}
      <div className="page-heading">
        <div>
          <h1>History</h1>
          <p>Conversations from the last five days.</p>
        </div>
        <div className="heading-action">
          <button
            className="subtle-button"
            onClick={() =>
              notify?.("History is retained for five rolling days")
            }
          >
            <Clock3 size={14} /> Last 5 days
          </button>
        </div>
      </div>

      {/* Search Input */}
      <div className="history-search-wrap">
        <div className="search-box">
          <Search size={15} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search conversations..."
          />
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="history-loading-state">
          <RefreshCw size={20} className="spin" />
          <span>Loading conversation history…</span>
        </div>
      )}

      {/* Empty State */}
      {!loading && items.length === 0 && (
        <div className="history-empty-state">
          <div className="history-empty-icon">
            <MessageSquareX size={20} />
          </div>
          <strong>No conversations found</strong>
          <p>
            {search
              ? `No chats match "${search}". Try searching for another topic.`
              : "Start a new conversation in Ask Husk to populate your history list."}
          </p>
        </div>
      )}

      {/* Grouped History List */}
      {!loading &&
        Object.entries(groupedItems).map(([groupTitle, groupList]) => (
          <div key={groupTitle} className="history-section">
            <div className="history-section-header">
              <span>{groupTitle}</span>
              <span className="history-section-count">
                {groupList.length} chats
              </span>
            </div>

            <div className="history-list">
              {groupList.map((item) => {
                const dateObj = new Date(item.updated_at);
                const timeFormatted = dateObj.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                });
                const cleanPreview = cleanPreviewText(item.preview);

                return (
                  <button
                    key={item.id}
                    className="history-card"
                    onClick={() => onSelectConversation(item.id)}
                  >
                    <div className="history-icon-tile">
                      <MessageSquare size={16} />
                    </div>

                    <div className="history-card-body">
                      <div className="history-card-title-row">
                        <h3 className="history-card-title">
                          {item.title || "Untitled conversation"}
                        </h3>
                        <span className="history-card-time">
                          {timeFormatted}
                        </span>
                      </div>
                      <p className="history-card-preview">
                        {cleanPreview || "No preview available"}
                      </p>
                    </div>

                    <ChevronRight size={16} className="history-arrow" />
                  </button>
                );
              })}
            </div>
          </div>
        ))}
    </div>
  );
}
