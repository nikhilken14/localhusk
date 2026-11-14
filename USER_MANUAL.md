# LocalHusk Local AI — User Manual

**Version:** 1.0  
**Platforms:** Windows, Linux

LocalHusk is a local-first AI assistant. It runs entirely on your machine: a FastAPI backend, a React web UI, and a terminal CLI. Chat with pluggable LLMs, manage tasks/notes/calendar/mail, run agents with tool approval, and connect MCP servers—all without sending your data to the cloud unless you choose a remote model provider.

---

## 1. Installation

### Prerequisites

| Component | Version | Notes |
|-----------|---------|-------|
| Python    | 3.11+   | Required for backend |
| Node.js   | 18+ (20+ recommended) | Required only for the web UI |
| Optional  | Rust toolchain | To build the native CLI binary |

### Windows

1. Extract the release archive.
2. Open PowerShell in the folder that contains `install.ps1`, `husk/`, `ui/`, and `husk.py`.
3. Run:
   ```powershell
   .\install.ps1
   ```
4. Close and reopen PowerShell (or open a new terminal). Type `husk` to start.

The installer creates `%USERPROFILE%\.husk`, installs a virtualenv, copies sources, and adds `~\.husk\bin` to your user PATH.

### Linux

1. Extract the release archive.
2. Open a terminal in the folder that contains `install.sh`, `husk/`, `ui/`, and `husk.py`.
3. Run:
   ```bash
   chmod +x install.sh
   ./install.sh
   ```
4. Open a new terminal (or `source ~/.bashrc` / `source ~/.zshrc`). Type `husk` to start.

The installer creates `~/.husk`, sets up a virtualenv, and adds the launcher to your shell PATH.

### Verify

```bash
husk --help
# or
husk version
```

---

## 2. First Launch

Running `husk` (with no arguments) starts the interactive CLI:

1. You chat in the terminal first.
2. After the first reply, Husk offers to open the web UI.
3. Choosing the UI starts the FastAPI backend (port 8000 by default) and the Vite frontend (port 5173). Your browser opens to `http://127.0.0.1:5173`.

You can also start components separately:

```bash
husk serve          # backend only (API on http://127.0.0.1:8000)
husk ui             # frontend (requires backend already running)
husk chat           # pure terminal chat
```

Data lives under `~/.husk` (or `%USERPROFILE%\.husk` on Windows):

- `data/husk.db` — SQLite database
- `logs/` — application logs
- `.env` — optional configuration overrides
- `bin/husk` — launcher

---

## 3. Configuring LLM Providers

Husk supports OpenAI-compatible, Anthropic, and Gemini-style providers. API keys are stored in the **OS keyring** (never in the database or responses).

### Via the Web UI

1. Open **Settings** (sidebar) → **Models / LLM**.
2. Click **Add model** / **Add provider**.
3. Choose the provider type, enter base URL (if self-hosted), model name, and API key.
4. Save. The model appears in the chat model picker.

### Via the CLI

```bash
husk llm list
husk llm add --provider openai --model gpt-4o --api-key sk-...
# or interactive
husk llm
```

### Via API

```http
POST /api/v1/llm/models
{
  "name": "gpt-4o",
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-..."
}
```

The same store is shared between UI, CLI, and any MCP/agent tooling.

**Tips**

- For local models (Ollama, LM Studio, vLLM, etc.) set the base URL to `http://127.0.0.1:11434/v1` (or whatever your server exposes) and leave the API key blank or use a dummy value.
- Set a default model in Settings; new chats inherit it.

---

## 4. Core Features

### Chat

- Create conversations, pin/archive them, stream responses.
- Attachments are supported (see API docs).
- History view shows the last 5 days by default (configurable).

### Tasks, Notes, Calendar

- **Tasks**: Kanban-style status columns, due dates, overdue filter.
- **Notes**: Colour-coded importance (red/yellow/green), pin, full-text search.
- **Calendar**: Local-only events (no cloud sync in v1). Create/edit/delete on this device.

### Mail

1. In **Mailbox** or **Connections**, start OAuth for Google or Microsoft.
2. Complete the browser consent flow.
3. Sync pulls inbox/sent into the local cache.
4. Reply and send work through the connected account.

Configure client IDs/secrets in `~/.husk/.env` (see `.env.example`).

### Agents

- Pre-seeded agents: Mail Assistant, Task Manager, Notes Helper, Calendar Planner.
- Build your own in the Agent Builder: choose tools, system prompt, model.
- Runs are planned by the LLM (or you supply a plan). Write/MCP tools pause for **approval**.
- Watch progress on the Run page / event stream.

### Automations

- Scheduled or event-triggered jobs.
- Overlap guards prevent concurrent runs of the same job.
- View run history and summary stats.

### Usage & Logs

- Token usage per model/conversation.
- Structured logs with request IDs (correlate with API responses).

---

## 5. MCP (Model Context Protocol) Servers

Husk can call tools exposed by MCP servers over HTTP(S) or loopback.

1. Go to **Connections** → **MCP**.
2. Register a server:
   - URL (e.g. `http://127.0.0.1:3000/sse` or your MCP endpoint)
   - Optional auth headers
3. Tools from that server become available to agents (subject to approval).

**Security notes**

- Only HTTP(S)/loopback is fully supported. `stdio` transport can be registered but is reported as unsupported (spawning processes from the HTTP API would be a remote-code-execution risk).
- Tools that write data or call external services require explicit user approval by default.

See `docs/MCP.md` for schema details and examples.

---

## 6. Configuration Reference

Copy `husk/.env.example` to `~/.husk/.env` (or the project `.env`).

Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` / `PORT` | 127.0.0.1 / 8000 | Backend bind |
| `CORS_ORIGINS` | http://127.0.0.1:5173,http://localhost:5173 | Allowed browser origins |
| `ALLOWED_HOSTS` | 127.0.0.1,localhost,[::1] | DNS-rebinding protection |
| `DATABASE_URL` | sqlite:///~/.husk/data/husk.db | Database |
| `FRONTEND_URL` | http://localhost:5173 | OAuth postMessage target |
| `HISTORY_RETENTION_DAYS` | 5 | Default history window |
| `GOOGLE_CLIENT_ID` / `SECRET` | (empty) | Gmail OAuth |
| `MICROSOFT_CLIENT_ID` / `SECRET` | (empty) | Outlook OAuth |

Environment variables override the files. Restart the backend after changes.

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Host not allowed` | Add the Host header value to `ALLOWED_HOSTS` |
| `Origin not allowed` | Add the frontend origin to `CORS_ORIGINS` |
| Blank page / CORS errors in browser | Ensure backend is running and CORS_ORIGINS matches the exact origin (including port) |
| `table ... already exists` on startup | Husk backs up the DB and migrates; if it fails, move `~/.husk/data/husk.db` aside and restart |
| UI not found / 404 on assets | Rebuild frontend: `cd ~/.husk/ui && npm install && npm run build` |
| Port already in use | Change `PORT` in `.env` or stop the other process |
| Keyring errors | On headless Linux you may need `python-keyring` backends or set a keyring password |

API interactive docs: http://127.0.0.1:8000/docs

---

## 8. Uninstall

**Windows**

```powershell
Remove-Item -Recurse -Force $env:USERPROFILE\.husk
# Optionally remove the PATH entry that points to .husk\bin
```

**Linux**

```bash
rm -rf ~/.husk
# Remove the export lines from ~/.bashrc / ~/.zshrc if desired
```

---

## 9. Further Reading

- `docs/API.md` — full REST reference
- `docs/LLM.md` — provider details and discovery
- `docs/MCP.md` — MCP integration guide
- Backend README: `husk/README.md`
- CLI source: `cli-rs/`

Enjoy building with Husk!
