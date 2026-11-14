# Architecture

LocalHusk is a **local-first** personal AI assistant. All durable state stays on the user’s machine under `~/.husk` (Linux) or `%USERPROFILE%\.husk` (Windows).

## High-level layers

```
┌─────────────────────────────────────────────────────────────┐
│  CLI (husk)                                                 │
│  • Native Rust launcher (builds/linux|windows)              │
│  • Python fallback (husk.py) – chat, /llm, /ui, /help       │
└──────────────────────────┬──────────────────────────────────┘
                           │ spawns / talks to
┌──────────────────────────▼──────────────────────────────────┐
│  Backend  (husk/  →  package “assistant”)                   │
│  • FastAPI on 127.0.0.1                                     │
│  • SQLite + Alembic migrations                              │
│  • Agents, automations, MCP, mail/calendar OAuth            │
│  • Pluggable LLM providers (OpenAI-compatible, Anthropic,   │
│    Gemini, Ollama, LM Studio, …)                            │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (localhost)
┌──────────────────────────▼──────────────────────────────────┐
│  Web UI  (ui/)                                              │
│  • React + TypeScript + Vite                                │
│  • Chat, tasks, notes, calendar, mail, agents, settings     │
└─────────────────────────────────────────────────────────────┘
```

## Data layout (`$HUSK_HOME`)

| Path | Purpose |
|------|---------|
| `bin/husk` (or `husk.exe`) | Launcher on PATH |
| `venv/` | Isolated Python environment |
| `husk/` | Copy of the backend package (source installs) |
| `ui/` | UI sources (+ `dist/` after build) |
| `husk.py` | Python CLI entry |
| `data/husk.db` | SQLite database |
| `.env` | Non-secret and secondary config (mode 0600 when possible) |
| `logs/` | Application logs |

## Backend package layout

```
husk/src/assistant/
  main.py          # FastAPI app + lifespan (migrate, workers)
  core/            # config, logging, redact, secrets, middleware
  db/              # engine, session, models (via alembic)
  api/v1/          # route modules (agents, llm, tasks, …)
  services/        # business logic
  providers/       # LLM provider adapters
  mcp/             # MCP client (HTTP + stdio)
  schemas/         # Pydantic models
```

## Key design choices

- **Local by default**: bind address, CORS, and allowed hosts default to loopback.
- **Approval gates**: agents can require explicit user approval before tool side-effects.
- **Secrets**: OS keyring preferred (`localhusk` service); log redaction for residual leakage.
- **Migrations**: Alembic; `auto_migrate` on startup for source installs.
- **No cloud dependency**: remote models are opt-in via user-configured endpoints/keys.

## Version

This document describes **v1.0.0**.
