import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Sparkles,
  History,
  Palette,
  Clock,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  Search,
  Trash2,
  Zap,
} from "lucide-react";
import { PRESETS, llmApi, needsKey } from "./llm-api";
import type { LlmDraft, LlmModel, TestResult, Provider } from "./llm-api";
import "./settings.css";

interface SettingsPageProps {
  notify?: (text: string) => void;
  dark?: boolean;
  setDark?: (dark: boolean) => void;
}

const PROVIDERS = Object.keys(PRESETS) as Provider[];

export function SettingsPage({ notify, dark, setDark }: SettingsPageProps) {
  // Accordion state for Language Model section
  const [isModelOpen, setIsModelOpen] = useState(true);

  // Language models
  const [models, setModels] = useState<LlmModel[] | null>(null);
  const [modelsError, setModelsError] = useState("");
  const [editing, setEditing] = useState<LlmModel | "new" | null>(null);
  const [toRemove, setToRemove] = useState<LlmModel | null>(null);
  const [results, setResults] = useState<
    Record<string, TestResult | "testing">
  >({});

  // Time zone & Locale state persisted in localStorage
  const [timeZone, setTimeZone] = useState(() => {
    return localStorage.getItem("app_timezone") || "Asia/Kolkata";
  });
  const [dateFormat, setDateFormat] = useState(() => {
    return localStorage.getItem("app_date_format") || "YYYY-MM-DD";
  });

  // Persist timeZone changes
  useEffect(() => {
    localStorage.setItem("app_timezone", timeZone);
  }, [timeZone]);

  // Persist dateFormat changes
  useEffect(() => {
    localStorage.setItem("app_date_format", dateFormat);
  }, [dateFormat]);

  const load = useCallback(() => {
    setModelsError("");
    llmApi
      .list()
      .then(setModels)
      .catch((e) => {
        setModels((cur) => cur ?? []);
        setModelsError(e.message);
      });
  }, []);
  useEffect(load, [load]);

  const test = async (m: LlmModel) => {
    setResults((r) => ({ ...r, [m.id]: "testing" }));
    try {
      const res = await llmApi.test(m.id);
      setResults((r) => ({ ...r, [m.id]: res }));
      notify?.(
        res.ok
          ? `${m.name} is reachable`
          : `${m.name}: ${res.error ?? "couldn’t connect"}`,
      );
    } catch (e: any) {
      setResults((r) => ({ ...r, [m.id]: { ok: false, error: e.message } }));
    }
  };

  const makeDefault = async (m: LlmModel) => {
    try {
      await llmApi.setDefault(m.id);
      notify?.(`${m.name} is now the default model`);
      load();
    } catch (e: any) {
      notify?.(e.message);
    }
  };

  const remove = async () => {
    if (!toRemove) return;
    try {
      await llmApi.remove(toRemove.id);
      notify?.(`${toRemove.name} removed`);
      setToRemove(null);
      load();
    } catch (e: any) {
      notify?.(e.message);
    }
  };

  const def = models?.find((m) => m.is_default);

  return (
    <div className="settings-page">
      <div className="page-heading">
        <div>
          <h1>Settings</h1>
          <p>
            Configure model settings, appearance preferences, and system time
            zone.
          </p>
        </div>
      </div>

      {/* 1. Collapsible Language Models Section */}
      <div className="settings-section">
        <div className="settings-section-title-wrap">
          <div
            className="settings-section-title clickable-header"
            onClick={() => setIsModelOpen(!isModelOpen)}
            style={{
              cursor: "pointer",
              userSelect: "none",
              flex: 1,
              borderBottom: 0,
              paddingBottom: 0,
            }}
          >
            <div className="settings-icon">
              <Sparkles size={17} />
            </div>
            <div style={{ flex: 1 }}>
              <h2>Language models</h2>
              <p>
                {models
                  ? `${models.length} model${models.length === 1 ? "" : "s"} available${def ? ` · default: ${def.name}` : ""}`
                  : "Add the models Husk and your agents can use."}
              </p>
            </div>
          </div>
          <div className="settings-header-actions">
            <button
              type="button"
              className="outline-button"
              onClick={() => setEditing("new")}
            >
              <Plus size={14} /> Add model
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label="Toggle section"
              onClick={() => setIsModelOpen(!isModelOpen)}
            >
              {isModelOpen ? (
                <ChevronUp size={18} />
              ) : (
                <ChevronDown size={18} />
              )}
            </button>
          </div>
        </div>

        {isModelOpen && (
          <div
            className="settings-form llm"
            style={{
              borderTop: "1px solid var(--line)",
              marginTop: "16px",
              paddingTop: "16px",
            }}
          >
            
            {modelsError && (
              <div className="llm-note bad">
                Couldn’t load models: {modelsError}{" "}
                <button className="subtle-button" onClick={load}>
                  Try again
                </button>
              </div>
            )}
            {models === null && <p className="subtle-text">Loading models…</p>}

            {models?.length === 0 && !modelsError && (
              <div className="llm-empty">
                <Sparkles size={20} />
                <strong>No models yet</strong>
                <span>
                  Add a local model (Ollama) or connect a provider so Husk can
                  answer.
                </span>
              </div>
            )}

            <ul className="llm-list">
              {models?.map((m) => {
                const r = results[m.id];
                const status =
                  r === "testing"
                    ? "testing"
                    : r
                      ? r.ok
                        ? "ok"
                        : "bad"
                      : "idle";
                return (
                  <li
                    className={`llm-item ${m.is_default ? "default" : ""}`}
                    key={m.id}
                  >
                    <span className="llm-logo" aria-hidden>
                      {m.provider[0]}
                    </span>
                    <div className="llm-main">
                      <div className="llm-name">
                        <b>{m.name}</b>
                        {m.is_default && (
                          <span className="llm-tag">Default</span>
                        )}
                      </div>
                      <div className="llm-sub">
                        {m.provider} · <code>{m.model}</code>
                      </div>
                      <div className="llm-sub llm-endpoint">{m.endpoint}</div>
                      <div
                        className={`llm-status ${status}`}
                        aria-live="polite"
                      >
                        <i />
                        {status === "testing"
                          ? "Testing…"
                          : r && r !== "testing"
                            ? r.ok
                              ? `Connected${r.latency_ms ? ` · ${r.latency_ms} ms` : ""}`
                              : (r.error ?? "Can’t connect")
                            : needsKey(m.provider) && !m.has_key
                              ? "API key missing"
                              : "Not tested yet"}
                      </div>
                    </div>
                    <div className="llm-actions">
                      <button
                        type="button"
                        className="subtle-button"
                        disabled={r === "testing"}
                        onClick={() => test(m)}
                      >
                        <Zap size={13} /> Test
                      </button>
                      {!m.is_default && (
                        <button
                          type="button"
                          className="subtle-button"
                          onClick={() => makeDefault(m)}
                        >
                          Set default
                        </button>
                      )}
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`Edit ${m.name}`}
                        title="Edit"
                        onClick={() => setEditing(m)}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`Remove ${m.name}`}
                        title={
                          m.is_default && models.length > 1
                            ? "Choose another default first"
                            : "Remove"
                        }
                        disabled={m.is_default && models.length > 1}
                        onClick={() => setToRemove(m)}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>

      {/* 2. Appearance Section */}
      <div className="settings-section">
        <div className="settings-section-title appearance-title">
          <div className="settings-icon">
            <Palette size={17} />
          </div>
          <div style={{ flex: 1 }}>
            <h2>Appearance</h2>
            <p>Customize system visual theme.</p>
          </div>
          <div
            className="segmented"
            style={{ width: "fit-content", margin: 0 }}
          >
            <button
              type="button"
              className={!dark ? "on" : ""}
              onClick={() => {
                setDark?.(false);
                notify?.("Theme set to Light");
              }}
            >
              Light
            </button>
            <button
              type="button"
              className={dark ? "on" : ""}
              onClick={() => {
                setDark?.(true);
                notify?.("Theme set to Dark");
              }}
            >
              Dark
            </button>
          </div>
        </div>
      </div>

      {/* 3. Time Zone & Locale Section */}
      <div className="settings-section">
        <div className="settings-section-title">
          <div className="settings-icon">
            <Clock size={17} />
          </div>
          <div>
            <h2>Time zone and locale</h2>
            <p>
              Set time zone preferences for agent tasks, schedules, and logs.
            </p>
          </div>
        </div>
        <div className="settings-form">
          <label className="field">
            <span>Time Zone</span>
            <select
              value={timeZone}
              onChange={(e) => {
                setTimeZone(e.target.value);
                notify?.(`Time zone changed to ${e.target.value}`);
              }}
            >
              <option value="Asia/Kolkata">
                Asia/Kolkata (IST - Pune / India)
              </option>
              <option value="UTC">UTC (Universal Coordinated Time)</option>
              <option value="America/New_York">
                America/New_York (EST/EDT)
              </option>
              <option value="America/Los_Angeles">
                America/Los_Angeles (PST/PDT)
              </option>
              <option value="Europe/London">Europe/London (GMT/BST)</option>
              <option value="Asia/Tokyo">Asia/Tokyo (JST)</option>
            </select>
          </label>
          <label className="field">
            <span>Date Format</span>
            <select
              value={dateFormat}
              onChange={(e) => {
                setDateFormat(e.target.value);
                notify?.(`Date format updated`);
              }}
            >
              <option value="YYYY-MM-DD">YYYY-MM-DD</option>
              <option value="DD/MM/YYYY">DD/MM/YYYY</option>
              <option value="MM/DD/YYYY">MM/DD/YYYY</option>
            </select>
          </label>
        </div>
      </div>

      {/* 4. Privacy & History Section */}
      <div className="settings-section">
        <div className="settings-section-title">
          <div className="settings-icon">
            <History size={17} />
          </div>
          <div>
            <h2>Privacy and history</h2>
            <p>Manage data persistence and chat retention settings.</p>
          </div>
        </div>
        <div className="settings-row">
          <div>
            <strong>Conversation retention</strong>
            <span>
              Automatically expire chat history after five rolling days.
            </span>
          </div>
          <span className="setting-value">5 days</span>
        </div>
        <div className="settings-row">
          <div>
            <strong>Local data</strong>
            <span>
              Database and backups will live in your configured app data
              directory.
            </span>
          </div>
          <span className="setting-value green-text">On device</span>
        </div>
      </div>

      {editing && (
        <ModelDialog
          model={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(m, isNew) => {
            setEditing(null);
            notify?.(isNew ? `${m.name} added` : `${m.name} updated`);
            load();
            if (isNew) test(m);
          }}
        />
      )}
      <Dialog open={!!toRemove} onClose={() => setToRemove(null)}>
        {toRemove && (
          <>
            <h3>Remove “{toRemove.name}”?</h3>
            <p className="subtle-text">
              {models && models.length === 1
                ? "This is your only model, so Husk won’t be able to answer until you add another."
                : "Agents set to use it will fall back to the default model."}
            </p>
            <div className="llm-dialog-actions">
              <button
                className="subtle-button"
                onClick={() => setToRemove(null)}
                autoFocus
              >
                Cancel
              </button>
              <button className="primary-button llm-danger" onClick={remove}>
                Remove model
              </button>
            </div>
          </>
        )}
      </Dialog>
    </div>
  );
}

/* ---------- add / edit dialog ---------- */
function ModelDialog({
  model,
  onClose,
  onSaved,
}: {
  model: LlmModel | null;
  onClose: () => void;
  onSaved: (m: LlmModel, isNew: boolean) => void;
}) {
  const [name, setName] = useState(model?.name ?? "");
  const [provider, setProvider] = useState<Provider>(
    model?.provider ?? "Ollama",
  );
  const [endpoint, setEndpoint] = useState(model?.endpoint ?? PRESETS.Ollama);
  const [id, setId] = useState(model?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [maxTokens, setMaxTokens] = useState(model?.max_tokens ?? 4096);
  const [temperature, setTemperature] = useState(model?.temperature ?? 0.4);
  const [stream, setStream] = useState(model?.stream ?? true);
  const [found, setFound] = useState<string[] | null>(null);
  const [finding, setFinding] = useState(false);
  const [findError, setFindError] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const pickProvider = (p: Provider) => {
    setProvider(p);
    setEndpoint(PRESETS[p]);
    setFound(null);
    setFindError("");
  };

  const find = async () => {
    setFinding(true);
    setFindError("");
    try {
      const list = await llmApi.discover({
        provider,
        endpoint: endpoint.trim(),
        api_key: apiKey || undefined,
      });
      setFound(list);
      if (list.length === 0)
        setFindError(
          "This endpoint didn’t list any models. You can type the identifier instead.",
        );
    } catch (e: any) {
      setFound(null);
      setFindError(e.message);
    } finally {
      setFinding(false);
    }
  };

  const keyMissing =
    needsKey(provider) &&
    !apiKey &&
    !(model?.has_key && model.provider === provider);
  const problem = !name.trim()
    ? "Give the model a display name."
    : !/^https?:\/\/.+/.test(endpoint.trim())
      ? "Enter a full endpoint URL starting with http:// or https://."
      : !id.trim()
        ? "Enter or pick the model identifier."
        : keyMissing
          ? `${provider} needs an API key.`
          : "";

  const save = async () => {
    setSaving(true);
    setError("");
    const d: LlmDraft = {
      name: name.trim(),
      provider,
      endpoint: endpoint.trim(),
      model: id.trim(),
      api_key: apiKey || undefined,
      max_tokens: maxTokens,
      temperature,
      stream,
    };
    try {
      onSaved(
        model ? await llmApi.update(model.id, d) : await llmApi.add(d),
        !model,
      );
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onClose}>
      <h3>{model ? "Edit model" : "Add model"}</h3>
      <label className="field">
        <span>Display name</span>
        <input
          value={name}
          maxLength={80}
          placeholder="Qwen3 (local)"
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span>Provider</span>
        <select
          value={provider}
          onChange={(e) => pickProvider(e.target.value as Provider)}
        >
          {PROVIDERS.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Endpoint URL</span>
        <input
          value={endpoint}
          onChange={(e) => {
            setEndpoint(e.target.value);
            setFound(null);
          }}
          placeholder="https://api.example.com/v1"
        />
      </label>
      <label className="field">
        <span>
          API key{" "}
          <small>
            {needsKey(provider)
              ? model?.has_key
                ? "Leave blank to keep the saved key"
                : "Required"
              : "Optional for local models"}
          </small>
        </span>
        <input
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={model?.has_key ? "••••••••" : "Enter API key..."}
        />
      </label>
      <div className="field">
        <span>Model identifier</span>
        <div className="llm-find">
          <input
            list="llm-found"
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="e.g. qwen3, gpt-4o"
            aria-label="Model identifier"
          />
          <button
            type="button"
            className="subtle-button"
            disabled={finding || !/^https?:\/\//.test(endpoint)}
            onClick={find}
          >
            <Search size={13} /> {finding ? "Looking…" : "Find models"}
          </button>
        </div>
        <datalist id="llm-found">
          {found?.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
        {found && found.length > 0 && (
          <div className="llm-chips" aria-label="Models on this endpoint">
            {found.map((m) => (
              <button
                type="button"
                key={m}
                className={m === id ? "on" : ""}
                onClick={() => setId(m)}
              >
                {m}
              </button>
            ))}
          </div>
        )}
        {findError && <small className="llm-warn">{findError}</small>}
      </div>

      <details className="llm-adv">
        <summary>Generation settings</summary>
        <label className="field">
          <span>
            Maximum output tokens <b>{maxTokens.toLocaleString()}</b>
          </span>
          <input
            type="range"
            min="256"
            max="16384"
            step="256"
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
          />
          <div className="range-labels">
            <span>256</span>
            <span>16,384</span>
          </div>
        </label>
        <label className="field">
          <span>
            Temperature <b>{temperature.toFixed(1)}</b>
          </span>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={temperature}
            onChange={(e) => setTemperature(Number(e.target.value))}
          />
          <div className="range-labels">
            <span>Precise</span>
            <span>Creative</span>
          </div>
        </label>
        <label className="check-field">
          <input
            type="checkbox"
            checked={stream}
            onChange={(e) => setStream(e.target.checked)}
          />
          Stream responses as they are generated
        </label>
      </details>

      {error && <div className="llm-note bad">{error}</div>}
      <div className="llm-dialog-actions">
        <button className="subtle-button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary-button"
          disabled={saving || !!problem}
          title={problem || undefined}
          onClick={save}
        >
          {saving ? "Saving…" : model ? "Save changes" : "Add model"}
        </button>
      </div>
    </Dialog>
  );
}

function Dialog({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className="llm-dialog"
      onCancel={onClose}
      onClose={onClose}
    >
      {open && children}
    </dialog>
  );
}
