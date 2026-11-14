# LocalHusk Backend (v1.0)

Local FastAPI backend for the LocalHusk assistant UI: chat with pluggable LLMs, tasks, notes, calendar,
mail (Google / Microsoft), agents with approval-gated tools, automations, MCP servers, usage and logs.
All 85 endpoints in `FrontEnd-API-Required.txt` are implemented under `/api/v1`.
See **[docs/API.md](docs/API.md)** for request/response shapes and the v0.9 → v1.0 route map.

## Run (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn assistant.main:app --reload      # migrations run automatically on startup
```

Docs UI: http://127.0.0.1:8000/docs. Run `pytest` to run the test-suite and
`python scripts/check_api_coverage.py FrontEnd-API-Required.txt` to verify spec coverage.

## Behaviour worth knowing

* **Data:** SQLite at `~/.husk/data/husk.db` (WAL mode, foreign keys enforced). Before applying a pending
  migration the database is backed up to `backups/` next to it. API keys and OAuth refresh tokens live
  in the OS keyring, never in the database or in API responses.
* **History:** `GET /history` is read-only and shows the last 5 days by default. Nothing is deleted unless you call
  `POST /history/prune` or set `HISTORY_AUTO_PRUNE=true`.
* **Agents:** runs are planned by the LLM (or you can pass a `plan`), restricted to the agent's tools, and
  executed by a background worker. Write tools and MCP tools (by default) pause for approval at
  `POST /agents/approvals/{id}/resolve`. Poll progress at `GET /agents/runs/{id}/events`.
* **Mail:** set the Google/Microsoft client IDs in `.env`, then `POST /mail/accounts/oauth/start`.
  **Calendar is local-only** (no provider sync). Local events are fully editable on this device.
* **Pre-built agents:** Mail Assistant, Task Manager, Notes Helper, and Calendar Planner are seeded on first start.
* **MCP:** HTTP(S)/loopback servers only. `stdio` servers can be registered but are reported as `unsupported`
  (spawning processes from an HTTP API is a remote-code-execution risk).
* **Security:** the API rejects non-local `Host` headers and cross-origin writes from origins not in `CORS_ORIGINS`.
  Mail HTML (`body_html`) is untrusted - sanitise it in the UI before rendering.

## Troubleshooting

* **`table provider_configs already exists` on startup** - the database was created without Alembic (for example by
  `Base.metadata.create_all`, which the pre-1.0 test-suite ran against the real database). Startup now detects this,
  backs the file up to `~/.husk/data/backups/`, records the matching schema version, and then migrates. If the existing
  tables don't match any known version you get a clear error instead; in that case move the file aside
  (`%USERPROFILE%\.husk\data\husk.db`) and restart to get a fresh database.
* **Which database is used?** `DATABASE_URL` from the environment, then `./.env`, then `~/.husk/.env`; default `~/.husk/data/husk.db`.

## Layout

```
src/assistant/
  api/v1/        one router per area (HTTP only)
  services/      business logic: chat, llm, usage, agent_runtime/, automation, mail/, calendar_sync
  providers/     LLM adapters (OpenAI-compatible, Anthropic, Gemini) + model discovery
  db/models/     SQLAlchemy models        alembic/versions/   migrations (0007 = this release)
  core/          config, errors, logging, middleware, cron, helpers
tests/           pytest suite             scripts/            spec-coverage + static checks
```


## Shared model store

LLM connections live in SQLite (`provider_configs`) + OS keyring. The native CLI reads/writes the same store when the API is running, so configuring a model in the UI or via `/llm` in the CLI is visible to both.
