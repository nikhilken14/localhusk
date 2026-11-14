import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  FileText,
  Paperclip,
  Play,
  X,
  Search,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { agentsApi } from "./api";
import type { AgentDraft, Catalog, CatalogTool } from "./types";
import { useRunEvents } from "./events";
import { RunTrace } from "./RunTrace";
import "./agent-builder.css";
import "./agents-page.css";
import "./agent-editor.css";

const EMPTY: AgentDraft = {
  name: "",
  description: "",
  instructions: "",
  model: null,
  tools: [],
};

/** /agents/new and /agents/:id/edit – define the agent, pick its tools, and watch a live test run. */
export function AgentBuilderPage({ notify }: { notify?: (m: string) => void }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const say = (m: string) => notify?.(m);

  const [d, setD] = useState<AgentDraft>(EMPTY);
  const [saved, setSaved] = useState<AgentDraft | null>(null);
  const [agentId, setAgentId] = useState<string | undefined>(id);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(!!id);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState("");
  const [testInput, setTestInput] = useState("");
  const [testFiles, setTestFiles] = useState<File[]>([]);
  const testFileRef = useRef<HTMLInputElement>(null);
  const [testing, setTesting] = useState(false);
  const [runId, setRunId] = useState<string | null>(
    (location.state as { runId?: string } | null)?.runId ?? null,
  );
  const trace = useRunEvents(runId);

  useEffect(() => {
    agentsApi
      .catalog()
      .then(setCatalog)
      .catch((e) => setError(`Couldn’t load tools: ${e.message}`));
  }, []);
  useEffect(() => {
    if (!id) return;
    agentsApi
      .get(id)
      .then((a) => {
        const draft: AgentDraft = {
          name: a.name,
          description: a.description ?? "",
          instructions: a.instructions ?? "",
          model: a.model ?? null,
          tools: (a.tools ?? []).map((t: any) =>
            typeof t === "string" ? t : t.id,
          ),
        };
        setD(draft);
        setSaved(draft);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const patch = (p: Partial<AgentDraft>) => setD((cur) => ({ ...cur, ...p }));
  const toggleTool = (tid: string) =>
    patch({
      tools: d.tools.includes(tid)
        ? d.tools.filter((x) => x !== tid)
        : [...d.tools, tid],
    });

  const allTools = catalog?.tools ?? [];
  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const m = new Map<string, CatalogTool[]>();
    allTools
      .filter(
        (t) =>
          !needle ||
          `${t.name} ${t.description} ${t.id}`.toLowerCase().includes(needle),
      )
      .forEach((t) => m.set(t.group, [...(m.get(t.group) ?? []), t]));
    return [...m];
  }, [allTools, q]);

  const picked = allTools.filter((t) => d.tools.includes(t.id));
  const asksFirst = picked.filter((t) => t.requires_approval);
  const modelName =
    catalog?.models.find((m) => m.id === d.model)?.name ??
    (d.model || "Workspace default model");
  const problems = [
    ...(d.name.trim() ? [] : ["Give the agent a name."]),
    ...(d.instructions.trim().length >= 10
      ? []
      : ["Add instructions (at least a sentence)."]),
  ];
  const dirty = !saved || JSON.stringify(d) !== JSON.stringify(saved);

  const persist = async () => {
    const payload = {
      ...d,
      name: d.name.trim(),
      description: d.description.trim(),
      instructions: d.instructions.trim(),
    };
    const a = agentId
      ? await agentsApi.update(agentId, payload)
      : await agentsApi.create(payload);
    setSaved(d);
    setAgentId(a.id);
    return a.id;
  };
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const aid = await persist();
      say(id ? "Agent updated" : "Agent created");
      navigate(`/agents/${aid}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };
  const runTest = async () => {
    setTesting(true);
    setError("");
    try {
      const aid = !agentId || dirty ? await persist() : agentId;
      const attachmentIds: string[] = [];
      for (const file of testFiles) {
        try {
          const uploaded = await agentsApi.uploadAttachment(aid, file);
          attachmentIds.push(uploaded.id);
        } catch (upErr: any) {
          throw new Error(
            `Could not attach “${file.name}”: ${upErr?.message || "upload failed"}`,
          );
        }
      }
      const r = await agentsApi.run(aid, testInput, attachmentIds);
      setRunId(r.run_id);
      setTestFiles([]);
      say(
        attachmentIds.length
          ? `Test started with ${attachmentIds.length} document${attachmentIds.length === 1 ? "" : "s"}`
          : "Test run started",
      );
      if (!id)
        navigate(`/agents/${aid}/edit`, {
          replace: true,
          state: { runId: r.run_id },
        });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setTesting(false);
    }
  };

  if (loading)
    return (
      <div className="content-page ab ag agb">
        <p className="ag-muted">Loading…</p>
      </div>
    );

  return (
    <div className="content-page ab ag agb">
      <Link className="ag-back" to={id ? `/agents/${id}` : "/agents"}>
        <ArrowLeft size={14} /> {id ? "Back to agent" : "Back to agents"}
      </Link>
      <h1 className="ab-title">{id ? "Edit agent" : "Create agent"}</h1>

      <div className="agb-grid">
        <div className="agb-main">
          <section className="ab-panel">
            <h2>Basics</h2>
            <label className="ab-field">
              Name
              <input
                value={d.name}
                maxLength={120}
                placeholder="Weekly planning assistant"
                onChange={(e) => patch({ name: e.target.value })}
              />
            </label>
            <label className="ab-field">
              Description <small>(optional)</small>
              <input
                value={d.description}
                maxLength={300}
                placeholder="Organizes priorities and prepares your week."
                onChange={(e) => patch({ description: e.target.value })}
              />
            </label>
          </section>

          <section className="ab-panel">
            <h2>Instructions</h2>
            <label className="ab-field">
              What should this agent do every time it runs?
              <textarea
                rows={7}
                maxLength={8000}
                value={d.instructions}
                onChange={(e) => patch({ instructions: e.target.value })}
                placeholder="Summarize my meetings and open tasks, then save a short brief in Notes. Never send or delete anything without asking me."
              />
              <small>{d.instructions.length.toLocaleString()} / 8,000</small>
            </label>
            <label className="ab-field">
              Model
              <select
                value={d.model ?? ""}
                onChange={(e) => patch({ model: e.target.value || null })}
              >
                <option value="">Workspace default</option>
                {catalog?.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} · {m.provider}
                  </option>
                ))}
              </select>
            </label>
          </section>

          <section className="ab-panel">
            <h2>
              Tools{" "}
              <small className="agb-count">{d.tools.length} selected</small>
            </h2>
            <p className="ab-muted">
              The model can only call tools you enable. Tools that change data
              can pause for your approval.
            </p>
            <label className="agb-search">
              <Search size={14} aria-hidden />
              <input
                type="search"
                placeholder="Search tools"
                aria-label="Search tools"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </label>
            {catalog === null && <p className="ab-muted">Loading tools…</p>}
            {catalog && groups.length === 0 && (
              <p className="ab-muted">No tools match.</p>
            )}
            {groups.map(([group, tools]) => (
              <fieldset className="ab-group" key={group}>
                <legend>{group}</legend>
                {tools.map((t) => (
                  <label className="ab-tool" key={t.id}>
                    <input
                      type="checkbox"
                      checked={d.tools.includes(t.id)}
                      onChange={() => toggleTool(t.id)}
                    />
                    <span>
                      <b>
                        {t.name}
                        <code className="agb-id">{t.id}</code>
                      </b>
                      <small>{t.description}</small>
                      <span className="agb-tags">
                        <i className={t.access === "write" ? "warn" : ""}>
                          {t.access === "write"
                            ? "Can change data"
                            : "Read only"}
                        </i>
                        {t.requires_approval && (
                          <i className="ask">
                            <ShieldCheck size={11} aria-hidden /> Asks first
                          </i>
                        )}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            ))}
          </section>

          <section className="ab-panel">
            <h2>Execution safety</h2>
            <p className="ab-muted">
              Plans are limited to five steps. The agent can only use the tools
              selected above. Every data-changing tool requires explicit
              approval before execution.
            </p>
            <div className="ag-note warn">
              Approval is enforced by the backend and cannot be bypassed by an
              agent instruction or model response.
            </div>
          </section>

          <section className="ab-panel">
            <h2>Test your agent</h2>
            <p className="ab-muted">
              Run it once and inspect the generated plan, tool execution and
              approval checkpoints.{" "}
              {(!agentId || dirty) && "Testing saves your changes first."}
            </p>
            <label className="ab-field">
              Task for this test <small>(optional if you attach files)</small>
              <textarea
                rows={2}
                maxLength={4000}
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                placeholder="Leave empty to use its usual instructions, or attach docs"
              />
            </label>
            <input
              ref={testFileRef}
              type="file"
              multiple
              accept=".pdf,.docx,.xlsx,.xlsm,.zip,.txt,.md,.csv,.json,.log"
              style={{ display: "none" }}
              onChange={(e) => {
                const list = e.target.files;
                if (!list?.length) return;
                setTestFiles((prev) =>
                  [...prev, ...Array.from(list)].slice(0, 8),
                );
                e.target.value = "";
              }}
            />
            <div className="ab-attach-row">
              <button
                type="button"
                className="subtle-button"
                onClick={() => testFileRef.current?.click()}
                disabled={testing}
              >
                <Paperclip size={14} /> Attach docs
              </button>
              {testFiles.length > 0 && (
                <span className="ab-attach-count">
                  {testFiles.length}/8 selected
                </span>
              )}
              {testFiles.map((f, i) => (
                <span key={`${f.name}-${i}`} className="ab-file-chip">
                  <FileText size={12} /> {f.name}
                  <button
                    type="button"
                    className="ab-file-remove"
                    onClick={() =>
                      setTestFiles((p) => p.filter((_, j) => j !== i))
                    }
                    aria-label={`Remove ${f.name}`}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            {testFiles.length > 0 && (
              <p
                className="ab-muted"
                style={{ marginTop: -4, marginBottom: 10 }}
              >
                Documents are uploaded when you run the test and passed to the
                agent as context.
              </p>
            )}
            <div className="ab-add">
              <button
                className="primary-button"
                disabled={testing || problems.length > 0}
                onClick={runTest}
              >
                <Play size={14} />{" "}
                {testing
                  ? "Starting…"
                  : !agentId || dirty
                    ? "Save & run test"
                    : "Run test"}
              </button>
              {runId && (
                <Link className="subtle-button" to={`/agents/runs/${runId}`}>
                  Open full run
                </Link>
              )}
            </div>
            {problems.length > 0 && (
              <p className="ab-muted">
                Fix the items on the right to enable testing.
              </p>
            )}
            {runId && (
              <div className="agb-trace">
                <RunTrace trace={trace} notify={notify} compact />
              </div>
            )}
          </section>
        </div>

        <aside className="agb-rail">
          <section className="agd-card" aria-live="polite">
            <h3>How this agent works</h3>
            <ol className="agb-flow">
              <li>
                <span className="rt-icon amber">
                  <Play size={14} />
                </span>
                <div>
                  <strong>A run starts</strong>
                  <small>You, an automation, or a test.</small>
                </div>
              </li>
              <li>
                <span className="rt-icon purple">
                  <Sparkles size={14} />
                </span>
                <div>
                  <strong>{modelName} decides</strong>
                  <small>
                    Reads the instructions and creates a bounded plan of up to
                    five steps.
                  </small>
                </div>
              </li>
              <li>
                <span className="rt-icon blue">
                  <Wrench size={14} />
                </span>
                <div>
                  <strong>
                    {d.tools.length
                      ? `Calls ${d.tools.length} enabled tool${d.tools.length === 1 ? "" : "s"}`
                      : "No tools enabled"}
                  </strong>
                  <small>
                    {picked
                      .slice(0, 3)
                      .map((t) => t.name)
                      .join(", ") || "It can only answer in text."}
                    {picked.length > 3 ? ` +${picked.length - 3}` : ""}
                  </small>
                </div>
              </li>
              <li>
                <span className="rt-icon amber">
                  <ShieldCheck size={14} />
                </span>
                <div>
                  <strong>
                    {asksFirst.length
                      ? `${asksFirst.length} write tool${asksFirst.length === 1 ? "" : "s"} require approval`
                      : "No write tools selected"}
                  </strong>
                  <small>Approval is enforced by the backend.</small>
                </div>
              </li>
              <li>
                <span className="rt-icon green">
                  <Check size={14} />
                </span>
                <div>
                  <strong>Result is saved</strong>
                  <small>Every step is logged on the run page.</small>
                </div>
              </li>
            </ol>
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
            <div className="agb-ready">
              <Check size={14} aria-hidden /> Ready to save
            </div>
          )}
          {error && <div className="ab-note bad">{error}</div>}
        </aside>
      </div>

      <footer className="ab-footer">
        <button
          className="subtle-button"
          onClick={() => navigate(id ? `/agents/${id}` : "/agents")}
        >
          Cancel
        </button>
        <span className="ab-spacer" />
        <button
          className="primary-button"
          disabled={saving || problems.length > 0}
          onClick={save}
        >
          {saving ? "Saving…" : id ? "Save changes" : "Create agent"}
        </button>
      </footer>
    </div>
  );
}
