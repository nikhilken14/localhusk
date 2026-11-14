import { API_BASE_URL } from "../../api-base";
import React, { useState, useEffect, useMemo } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  CalendarPlus,
  X,
  Check,
  RefreshCw,
} from "lucide-react";
import "./calendar.css";

interface CalendarEvent {
  id: string;
  title: string;
  description?: string;
  start_at: string;
  end_at?: string;
  location?: string;
  source: string;
  external_id?: string;
}

interface CalendarPageProps {
  notify?: (message: string) => void;
}

const API_BASE = API_BASE_URL;

export function CalendarPage({ notify }: CalendarPageProps) {
  const today = new Date();

  const [calendarView, setCalendarView] = useState<string>("Day");
  const [selectedDay, setSelectedDay] = useState<number>(today.getDate());

  const [currentMonthYear, setCurrentMonthYear] = useState({
    month: today.getMonth(),
    year: today.getFullYear(),
    name: today.toLocaleString("default", { month: "long", year: "numeric" }),
  });

  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  const formattedTodayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const [newEvent, setNewEvent] = useState({
    title: "",
    description: "",
    start_date: formattedTodayStr,
    start_time: "09:00",
    end_time: "10:00",
    all_day: false,
    source: "local",
  });

  const fetchEvents = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/calendar/events`);
      if (!res.ok) throw new Error("Failed to fetch calendar events");
      const data: CalendarEvent[] = await res.json();
      setEvents(data);
    } catch (err: any) {
      notify?.(err.message || "Error loading calendar");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, []);

  const handlePrevMonth = () => {
    setCurrentMonthYear((prev) => {
      const newMonth = prev.month === 0 ? 11 : prev.month - 1;
      const newYear = prev.month === 0 ? prev.year - 1 : prev.year;
      const date = new Date(newYear, newMonth, 1);
      return {
        month: newMonth,
        year: newYear,
        name: date.toLocaleString("default", {
          month: "long",
          year: "numeric",
        }),
      };
    });
    setSelectedDay(1);
  };

  const handleNextMonth = () => {
    setCurrentMonthYear((prev) => {
      const newMonth = prev.month === 11 ? 0 : prev.month + 1;
      const newYear = prev.month === 11 ? prev.year + 1 : prev.year;
      const date = new Date(newYear, newMonth, 1);
      return {
        month: newMonth,
        year: newYear,
        name: date.toLocaleString("default", {
          month: "long",
          year: "numeric",
        }),
      };
    });
    setSelectedDay(1);
  };

  const handleCreateEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      // All-day: use date at UTC midnight; timed: combine date + time.
      const startAtIso = newEvent.all_day
        ? new Date(`${newEvent.start_date}T00:00:00Z`).toISOString()
        : new Date(
            `${newEvent.start_date}T${newEvent.start_time}:00Z`,
          ).toISOString();
      const endAtIso = newEvent.all_day
        ? new Date(`${newEvent.start_date}T23:59:59Z`).toISOString()
        : new Date(
            `${newEvent.start_date}T${newEvent.end_time}:00Z`,
          ).toISOString();

      const res = await fetch(`${API_BASE}/calendar/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: newEvent.title,
          description: newEvent.description,
          start_at: startAtIso,
          end_at: endAtIso,
          all_day: newEvent.all_day,
          source: newEvent.source,
        }),
      });

      if (!res.ok) throw new Error("Failed to create event");
      notify?.("Event scheduled on your local calendar.");
      setIsModalOpen(false);
      fetchEvents();
    } catch (err: any) {
      notify?.(err.message || "Failed to create event");
    }
  };

  const selectedDayEvents = useMemo(() => {
    return events.filter((ev) => {
      if (!ev.start_at) return false;
      const evDate = new Date(ev.start_at);
      return (
        evDate.getDate() === selectedDay &&
        evDate.getMonth() === currentMonthYear.month &&
        evDate.getFullYear() === currentMonthYear.year
      );
    });
  }, [events, selectedDay, currentMonthYear]);

  const currentMonthEvents = useMemo(() => {
    return events
      .filter((ev) => {
        if (!ev.start_at) return false;
        const evDate = new Date(ev.start_at);
        return (
          evDate.getMonth() === currentMonthYear.month &&
          evDate.getFullYear() === currentMonthYear.year
        );
      })
      .sort(
        (a, b) =>
          new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
      );
  }, [events, currentMonthYear]);

  const monthDaysCount = new Date(
    currentMonthYear.year,
    currentMonthYear.month + 1,
    0,
  ).getDate();

  const firstDayOfWeek =
    (new Date(currentMonthYear.year, currentMonthYear.month, 1).getDay() + 6) %
    7;

  return (
    <div className="calendar-page">
      {/* Page Header */}
      <div className="page-heading">
        <div>
          <h1>Calendar</h1>
          <p>A clear view of your local calendar events.</p>
        </div>
        <button className="primary-button" onClick={() => setIsModalOpen(true)}>
          <CalendarPlus size={15} /> New event
        </button>
      </div>

      {/* Toolbar */}
      <div className="calendar-toolbar">
        <div className="calendar-month">
          <button
            className="icon-button bordered"
            onClick={handlePrevMonth}
            aria-label="Previous month"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            className="icon-button bordered"
            onClick={handleNextMonth}
            aria-label="Next month"
          >
            <ChevronRight size={16} />
          </button>
          <strong>{currentMonthYear.name}</strong>
          <button
            className="subtle-button"
            onClick={() => {
              const now = new Date();
              setSelectedDay(now.getDate());
              setCurrentMonthYear({
                month: now.getMonth(),
                year: now.getFullYear(),
                name: now.toLocaleString("default", {
                  month: "long",
                  year: "numeric",
                }),
              });
            }}
          >
            Today
          </button>
        </div>

        <div className="segmented">
          {["Day", "Month", "Agenda"].map((v) => (
            <button
              className={calendarView === v ? "on" : ""}
              key={v}
              onClick={() => setCalendarView(v)}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {/* Main Calendar View Rendering */}
      {calendarView === "Month" ? (
        <div className="month-grid-container">
          <div className="month-grid">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
              <div className="month-weekday" key={d}>
                {d}
              </div>
            ))}
            {/* Empty cell offsets */}
            {Array.from({ length: firstDayOfWeek }, (_, i) => (
              <div key={`empty-${i}`} className="month-cell empty-cell" />
            ))}
            {Array.from({ length: monthDaysCount }, (_, i) => {
              const d = i + 1;
              const isChosen = d === selectedDay;
              const dayHasEvents = events.some((ev) => {
                const evDate = new Date(ev.start_at);
                return (
                  evDate.getDate() === d &&
                  evDate.getMonth() === currentMonthYear.month &&
                  evDate.getFullYear() === currentMonthYear.year
                );
              });
              const isPersonal = events.some((ev) => {
                const evDate = new Date(ev.start_at);
                return (
                  evDate.getDate() === d &&
                  evDate.getMonth() === currentMonthYear.month &&
                  evDate.getFullYear() === currentMonthYear.year &&
                  (ev.source === "google" || ev.source === "outlook")
                );
              });
              return (
                <button
                  key={d}
                  className={`month-cell ${isChosen ? "chosen" : ""}`}
                  onClick={() => {
                    setSelectedDay(d);
                    setCalendarView("Day");
                  }}
                >
                  <span>{d}</span>
                  {dayHasEvents && (
                    <i className={`event-mark ${isPersonal ? "green" : ""}`} />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      ) : calendarView === "Agenda" ? (
        /* Monthly Agenda List View */
        <div className="agenda">
          <div className="agenda-date">
            <div>
              <span className="eyebrow">MONTHLY AGENDA</span>
              <h2>
                <span>{currentMonthYear.name}</span>
              </h2>
            </div>
            <span className="subtle-text">
              {currentMonthEvents.length} events this month
            </span>
          </div>

          {loading ? (
            <div className="loading-state">
              <RefreshCw size={18} className="spin" /> Loading events...
            </div>
          ) : currentMonthEvents.length === 0 ? (
            <div className="empty-day-state">
              <p>No events scheduled for {currentMonthYear.name}.</p>
              <button
                className="subtle-button"
                onClick={() => setIsModalOpen(true)}
              >
                + Add event
              </button>
            </div>
          ) : (
            <div>
              {currentMonthEvents.map((ev) => {
                const evDate = new Date(ev.start_at);
                const dateLabel = evDate.toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                });
                const timeString = evDate.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                });
                const isPersonal =
                  ev.source === "google" || ev.source === "outlook";
                return (
                  <div className="agenda-event" key={ev.id}>
                    <span className="agenda-time">
                      {dateLabel} • {timeString}
                    </span>
                    <div
                      className={`event-card ${isPersonal ? "green" : "blue"}`}
                    >
                      <strong>{ev.title}</strong>
                      <span>
                        {ev.description ||
                          ev.location ||
                          "Synced account event"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        /* Default Day View */
        <div className="calendar-layout">
          {/* Mini Sidebar Calendar */}
          <div className="mini-calendar">
            <div className="mini-month">
              {currentMonthYear.name} <ChevronDown size={14} />
            </div>
            <div
              className="mini-days"
              style={{
                marginBottom: "6px",
                fontWeight: 700,
                fontSize: "9px",
                color: "var(--muted)",
              }}
            >
              {["M", "T", "W", "T", "F", "S", "S"].map((d, idx) => (
                <div key={idx} style={{ textAlign: "center" }}>
                  {d}
                </div>
              ))}
            </div>
            <div className="mini-days">
              {Array.from({ length: firstDayOfWeek }, (_, i) => (
                <div key={`mini-empty-${i}`} />
              ))}
              {Array.from({ length: monthDaysCount }, (_, i) => i + 1).map(
                (d) => (
                  <button
                    key={d}
                    className={selectedDay === d ? "picked" : ""}
                    onClick={() => setSelectedDay(d)}
                  >
                    {d}
                  </button>
                ),
              )}
            </div>
            <div className="calendar-legend">
              <span>
                <i className="event-mark" /> Work / Local
              </span>
            </div>
          </div>

          {/* Detailed Daily View */}
          <div className="agenda">
            <div className="agenda-date">
              <div>
                <span className="eyebrow">SELECTED DAY</span>
                <h2>
                  {selectedDay} <span>{currentMonthYear.name}</span>
                </h2>
              </div>
              <span className="subtle-text">
                {selectedDayEvents.length} events
              </span>
            </div>

            {loading ? (
              <div className="loading-state">
                <RefreshCw size={18} className="spin" /> Loading events...
              </div>
            ) : selectedDayEvents.length === 0 ? (
              <div className="empty-day-state">
                <p>No events scheduled for this day.</p>
                <button
                  className="subtle-button"
                  onClick={() => setIsModalOpen(true)}
                >
                  + Add event
                </button>
              </div>
            ) : (
              selectedDayEvents.map((ev) => {
                const timeString = new Date(ev.start_at).toLocaleTimeString(
                  [],
                  {
                    hour: "2-digit",
                    minute: "2-digit",
                  },
                );
                const isPersonal =
                  ev.source === "google" || ev.source === "outlook";
                return (
                  <div className="agenda-event" key={ev.id}>
                    <span className="agenda-time">{timeString}</span>
                    <div
                      className={`event-card ${isPersonal ? "green" : "blue"}`}
                    >
                      <strong>{ev.title}</strong>
                      <span>
                        {ev.description ||
                          ev.location ||
                          "Synced account event"}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* New Event Modal */}
      {isModalOpen && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-head">
              <h2>Create Synced Event</h2>
              <button
                className="bare-icon"
                onClick={() => setIsModalOpen(false)}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateEvent}>
              <label className="field">
                <span>Event Title</span>
                <input
                  type="text"
                  required
                  placeholder="e.g. Client Sync Meeting"
                  value={newEvent.title}
                  onChange={(e) =>
                    setNewEvent({ ...newEvent, title: e.target.value })
                  }
                />
              </label>

              <label className="field">
                <span>Description / Location</span>
                <input
                  type="text"
                  placeholder="e.g. Zoom link or conference room"
                  value={newEvent.description}
                  onChange={(e) =>
                    setNewEvent({ ...newEvent, description: e.target.value })
                  }
                />
              </label>

              <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={newEvent.all_day}
                  onChange={(e) =>
                    setNewEvent({ ...newEvent, all_day: e.target.checked })
                  }
                />
                <span>All-day event (no specific time)</span>
              </label>

              <div
                className="form-row"
                style={{ display: "flex", gap: "10px" }}
              >
                <label className="field" style={{ flex: 1 }}>
                  <span>Date</span>
                  <input
                    type="date"
                    value={newEvent.start_date}
                    onChange={(e) =>
                      setNewEvent({ ...newEvent, start_date: e.target.value })
                    }
                  />
                </label>
                {!newEvent.all_day && (
                  <>
                    <label className="field" style={{ flex: 1 }}>
                      <span>Start Time</span>
                      <input
                        type="time"
                        value={newEvent.start_time}
                        onChange={(e) =>
                          setNewEvent({ ...newEvent, start_time: e.target.value })
                        }
                      />
                    </label>
                    <label className="field" style={{ flex: 1 }}>
                      <span>End Time</span>
                      <input
                        type="time"
                        value={newEvent.end_time}
                        onChange={(e) =>
                          setNewEvent({ ...newEvent, end_time: e.target.value })
                        }
                      />
                    </label>
                  </>
                )}
              </div>

              <label className="field">
                <span>Source</span>
                <select
                  value={newEvent.source}
                  onChange={(e) =>
                    setNewEvent({ ...newEvent, source: e.target.value })
                  }
                  disabled
                >
                  <option value="local">Local Workspace (calendar is local-only)</option>
                  {/* Synced Google / Outlook calendars are not available in this build */}
                </select>
              </label>

              <div className="modal-actions">
                <button
                  type="button"
                  className="subtle-button"
                  onClick={() => setIsModalOpen(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="primary-button">
                  <Check size={14} /> Save Event
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
