import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  Clock,
  FileText,
  Paperclip,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { agentsApi } from "../agents/api";
import type { Agent } from "../agents/types";
import { automationApi, describeTrigger, DAYS } from "./automation";
import type { AutomationDraft, EventInfo, TriggerType } from "./automation";
import "../agents/agent-builder.css"; // shares the .ab-* form styles
import "../agents/agents-page.css";
import "./automation.css";

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const EMPTY: AutomationDraft = {
  name: "",
  trigger_type: "daily",
  trigger_config: { time: "08:00", timezone: TZ },
  agent_id: "",
  input_template: "",
  skip_if_running: true,
  enabled: true,
};
const UNITS = { minute: 60, hour: 3600, day: 86400 } as const;

const OPTIONS: { type: TriggerType; title: string; hint: string }[] = [
  { type: "daily", title: "Every day", hint: "At a time you choose" },
  {
    type: "weekly",
    title: "On certain days",
    hint: "For example weekdays at 9:00",
  },
  {
    type: "interval",
    title: "Repeat regularly",
    hint: "Every few minutes, hours or days",
  },
  {
    type: "event",
    title: "When something happens",
    hint: "A new task or note is created",
  },
  { type: "manual", title: "Only when I run it", hint: "No schedule" },
];

export function AutomationBuilderPage({
  notify,
  jobId: propJobId,
  onBack,
}: {
  notify: (m: string) => void;
  jobId?: string;
  onBack?: () => void;
}) {
  // Parent routes may use :id (same as agents) or :jobId — accept either.
  const params = useParams();
  const jobId = propJobId || params.jobId || params.id;
  const navigate = useNavigate();

  const [d, setD] = useState<AutomationDraft>(EMPTY);
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [events, setEvents] = useState<EventInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [runFiles, setRunFiles] = useState<File[]>([]);
  const runFileRef = useRef<HTMLInputElement>(null);

  const patch = (p: Partial<AutomationDraft>) => setD((x) => ({ ...x, ...p }));
  const cfg = (p: object) =>
    setD((x) => ({ ...x, trigger_config: { ...x.trigger_config, ...p } }));

  const handleBack = () => {
    if (onBack) {
      onBack();
    } else {
      navigate("/automation");
    }
  };

  useEffect(() => {
    agentsApi
      .list()
      .then(setAgents)
      .catch((e) => {
        setAgents([]);
        setError(e.message);
      });
    automationApi
      .events()
      .then(setEvents)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (jobId)
      automationApi
        .get(jobId)
        .then((a) =>
          setD({
            name: a.name,
            trigger_type: a.trigger_type as TriggerType,
            trigger_config: a.trigger_config,
            agent_id: a.agent_id ?? "",
            input_template: a.input_template,
            skip_if_running: a.skip_if_running,
            enabled: a.enabled,
          }),
        )
        .catch(() => handleBack());
  }, [jobId]);

  const pickTrigger = (type: TriggerType) => {
    const base: Record<TriggerType, object> = {
      daily: { time: "08:00", timezone: TZ },
      weekly: { time: "09:00", timezone: TZ, days: [0, 1, 2, 3, 4] },
      interval: { every_seconds: 3600 },
      event: { event: events[0]?.name },
      manual: {},
    };
    patch({ trigger_type: type, trigger_config: base[type] });
  };

  const agent = agents?.find((a) => a.id === d.agent_id);
  const event = events.find((e) => e.name === d.trigger_config.event);
  const problems = useMemo(() => {
    const p: string[] = [];
    if (!d.name.trim()) p.push("Give the automation a name.");
    if (!d.agent_id) p.push("Choose which agent should run.");
    if (d.trigger_type === "weekly" && !d.trigger_config.days?.length)
      p.push("Pick at least one day.");
    if (d.trigger_type === "event" && !d.trigger_config.event)
      p.push("Choose what starts it.");
    return p;
  }, [d]);

  const secs = d.trigger_config.every_seconds ?? 3600;
  const unit = (
    secs % 86400 === 0 ? "day" : secs % 3600 === 0 ? "hour" : "minute"
  ) as keyof typeof UNITS;
  const amount = secs / UNITS[unit];

  const save = async (andRun: boolean) => {
    setSaving(true);
    setError("");
    try {
      const saved = jobId
        ? await automationApi.update(jobId, d)
        : await automationApi.create(d);
      if (andRun) {
        if (runFiles.length > 0 && d.agent_id) {
          // Upload docs to the agent, then start an agent run with them.
          // (Job-level run API does not accept attachments yet.)
          const attachmentIds: string[] = [];
          for (const file of runFiles) {
            try {
              const uploaded = await agentsApi.uploadAttachment(
                d.agent_id,
                file,
              );
              attachmentIds.push(uploaded.id);
            } catch (upErr: any) {
              throw new Error(
                `Could not attach “${file.name}”: ${upErr?.message || "upload failed"}`,
              );
            }
          }
          await agentsApi.run(
            d.agent_id,
            d.input_template || "",
            attachmentIds,
          );
          notify(
            `Saved. Running once with ${attachmentIds.length} document${attachmentIds.length === 1 ? "" : "s"}`,
          );
        } else {
          await automationApi.run(saved.id);
          notify("Saved. Running once now");
        }
        setRunFiles([]);
      } else {
        notify("Automation saved");
      }
      handleBack();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const flow = [
    {
      icon: Clock,
      tone: "amber",
      title: "Trigger",
      detail: describeTrigger(d, events),
    },
    {
      icon: Sparkles,
      tone: "green",
      title: agent ? agent.name : "Choose an agent",
      detail: d.input_template.trim()
        ? "Runs with your task"
        : "Runs with its usual instructions",
    },
    ...(agent && agent.tools.length > 0
      ? [
          {
            icon: ShieldCheck,
            tone: "amber",
            title: "Ask for approval",
            detail: "Before anything is changed",
          },
        ]
      : []),
  ];

  return (
    <div className="content-page ab ag au-b">
      <button className="ag-back as-button" onClick={handleBack}>
        <ArrowLeft size={14} /> Automation
      </button>
      <h1 className="ab-title">
        {jobId ? "Edit automation" : "New automation"}
      </h1>

      <div className="au-b-grid">
        <div className="au-b-main">
          <section className="ab-panel">
            <h2>Basics</h2>
            <label className="ab-field">
              Name
              <input
                value={d.name}
                maxLength={160}
                placeholder="Morning briefing"
                onChange={(e) => patch({ name: e.target.value })}
              />
            </label>
          </section>

          <section className="ab-panel">
            <h2>When should it run?</h2>
            {OPTIONS.map((o) => (
              <label key={o.type} className="ab-radio">
                <input
                  type="radio"
                  name="trigger"
                  checked={d.trigger_type === o.type}
                  onChange={() => pickTrigger(o.type)}
                />
                <span>
                  <b>{o.title}</b>
                  <small>{o.hint}</small>
                </span>
              </label>
            ))}

            <div className="ab-flow">
              {(d.trigger_type === "daily" || d.trigger_type === "weekly") && (
                <label className="ab-field sm">
                  Time
                  <input
                    type="time"
                    value={d.trigger_config.time ?? ""}
                    onChange={(e) => cfg({ time: e.target.value })}
                  />
                  <small>Uses your time zone ({TZ}).</small>
                </label>
              )}
              {d.trigger_type === "weekly" && (
                <div role="group" aria-label="Days" className="ab-add">
                  {DAYS.map((name, i) => {
                    const on = d.trigger_config.days?.includes(i);
                    return (
                      <button
                        key={name}
                        type="button"
                        aria-pressed={!!on}
                        className={on ? "primary-button" : "subtle-button"}
                        onClick={() =>
                          cfg({
                            days: on
                              ? d.trigger_config.days!.filter((x) => x !== i)
                              : [...(d.trigger_config.days ?? []), i],
                          })
                        }
                      >
                        {name}
                      </button>
                    );
                  })}
                </div>
              )}
              {d.trigger_type === "interval" && (
                <div className="ab-add">
                  <input
                    type="number"
                    min={1}
                    style={{ width: 90 }}
                    value={amount}
                    onChange={(e) =>
                      cfg({
                        every_seconds:
                          Math.max(1, +e.target.value || 1) * UNITS[unit],
                      })
                    }
                  />
                  <select
                    style={{ width: 130 }}
                    value={unit}
                    onChange={(e) =>
                      cfg({
                        every_seconds:
                          amount * UNITS[e.target.value as keyof typeof UNITS],
                      })
                    }
                  >
                    <option value="minute">minutes</option>
                    <option value="hour">hours</option>
                    <option value="day">days</option>
                  </select>
                </div>
              )}
              {d.trigger_type === "event" && (
                <select
                  value={d.trigger_config.event ?? ""}
                  onChange={(e) => cfg({ event: e.target.value })}
                >
                  {events.map((e) => (
                    <option key={e.name} value={e.name}>
                      {e.label}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </section>

          <section className="ab-panel">
            <h2>What should it run?</h2>
            {agents === null && <p className="ab-muted">Loading agents…</p>}
            {agents?.length === 0 && (
              <div className="ab-note">
                You don’t have an agent yet.{" "}
                <Link to="/agents/new">Create an agent</Link>, then come back to
                schedule it.
              </div>
            )}
            {!!agents?.length && (
              <label className="ab-field">
                Agent
                <select
                  value={d.agent_id}
                  onChange={(e) => patch({ agent_id: e.target.value })}
                >
                  <option value="">Choose an agent</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                      {a.status === "paused" ? " (paused)" : ""}
                    </option>
                  ))}
                </select>
                {agent?.status === "paused" && (
                  <small>
                    This agent is paused, so scheduled runs will be skipped
                    until you resume it.
                  </small>
                )}
              </label>
            )}
            <label className="ab-field">
              Task for the agent <small>(optional)</small>
              <textarea
                rows={3}
                maxLength={4000}
                value={d.input_template}
                onChange={(e) => patch({ input_template: e.target.value })}
                placeholder={
                  d.trigger_type === "event"
                    ? "Summarize this new item: {{event.title}}"
                    : "Focus on what’s due this week"
                }
              />
              {d.trigger_type === "event" && event && (
                <small>
                  Insert:{" "}
                  {event.fields.map((f) => (
                    <code
                      key={f}
                      style={{ marginRight: 6 }}
                    >{`{{event.${f}}}`}</code>
                  ))}
                </small>
              )}
            </label>
            {/* Attach docs for the one-time "Save and run once" flow */}
            <input
              ref={runFileRef}
              type="file"
              multiple
              accept=".pdf,.docx,.xlsx,.xlsm,.zip,.txt,.md,.csv,.json,.log"
              style={{ display: "none" }}
              onChange={(e) => {
                const list = e.target.files;
                if (!list?.length) return;
                setRunFiles((prev) =>
                  [...prev, ...Array.from(list)].slice(0, 8),
                );
                e.target.value = "";
              }}
            />
            <div className="ab-attach-row">
              <button
                type="button"
                className="subtle-button"
                onClick={() => runFileRef.current?.click()}
                disabled={saving || !d.agent_id}
                title={
                  !d.agent_id
                    ? "Choose an agent first"
                    : "Attach documents for the next run"
                }
              >
                <Paperclip size={14} /> Attach docs
              </button>
              {runFiles.length > 0 && (
                <span className="ab-attach-count">
                  {runFiles.length}/8 selected
                </span>
              )}
              {runFiles.map((f, i) => (
                <span key={`${f.name}-${i}`} className="ab-file-chip">
                  <FileText size={12} /> {f.name}
                  <button
                    type="button"
                    className="ab-file-remove"
                    onClick={() =>
                      setRunFiles((p) => p.filter((_, j) => j !== i))
                    }
                    aria-label={`Remove ${f.name}`}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            {runFiles.length > 0 && (
              <p className="ab-muted" style={{ marginTop: -4 }}>
                Documents are used only for the next “Save and run once”.
                Scheduled runs use the task text above.
              </p>
            )}
          </section>

          <section className="ab-panel">
            <h2>Behavior</h2>
            <label className="ab-radio">
              <input
                type="checkbox"
                checked={d.skip_if_running}
                onChange={(e) => patch({ skip_if_running: e.target.checked })}
              />
              <span>
                <b>Skip a run if the last one hasn’t finished</b>
                <small>
                  Recommended, especially with a local AI model or runs that
                  wait for your approval.
                </small>
              </span>
            </label>
            <label className="ab-radio">
              <input
                type="checkbox"
                checked={d.enabled}
                onChange={(e) => patch({ enabled: e.target.checked })}
              />
              <span>
                <b>Turn on after saving</b>
              </span>
            </label>
          </section>
        </div>

        <aside className="au-b-rail">
          <section className="agd-card" aria-live="polite">
            <div className="au-rail-head">
              <h3>Flow preview</h3>
              <span className="au-count">{flow.length} steps</span>
            </div>
            <ol className="au-fp">
              {flow.map((s, i) => {
                const Icon = s.icon;
                return (
                  <li key={i}>
                    <span className={`au-trace-icon ${s.tone}`} aria-hidden>
                      <Icon size={15} />
                    </span>
                    <div>
                      <strong>
                        {i + 1}. {s.title}
                      </strong>
                      <small>{s.detail}</small>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>

          <section className="au-promo">
            <span className="ag-stat-icon" aria-hidden>
              <ShieldCheck size={16} />
            </span>
            <h3>Guardrails</h3>
            <p>
              {agent && agent.tools.length > 0
                ? "Actions that change things will still wait for your approval."
                : "Choose an agent to see which actions will wait for your approval."}
              {d.skip_if_running ? " Overlapping runs are skipped." : ""}
            </p>
          </section>

          {problems.length > 0 ? (
            <div className="ab-note bad">
              <ul>
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="au-ready">
              <Check size={14} aria-hidden /> Ready to save
            </div>
          )}
          {error && <div className="ab-note bad">{error}</div>}
        </aside>
      </div>

      <footer className="ab-footer">
        <button className="subtle-button" onClick={handleBack}>
          Cancel
        </button>
        <span className="ab-spacer" />
        <button
          className="subtle-button"
          disabled={saving || problems.length > 0}
          onClick={() => save(true)}
        >
          Save and run once
        </button>
        <button
          className="primary-button"
          disabled={saving || problems.length > 0}
          onClick={() => save(false)}
        >
          {saving ? "Saving…" : "Save automation"}
        </button>
      </footer>
    </div>
  );
}
