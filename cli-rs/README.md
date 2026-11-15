# Husk native CLI

The Rust executable is the terminal launcher for LocalHusk. The FastAPI backend remains Python and the web UI remains the existing Node/Vite application. The crate uses **only Rust's standard library** (`std`-only, zero external dependencies); terminal chat and GitHub tag checks call endpoints via `curl`.

## Source layout

```text
cli-rs/
├── Cargo.toml
├── Cargo.lock
├── build.ps1
├── build.sh
├── README.md
├── STARTUP-FLOW.md
└── src/
    ├── main.rs       # REPL, commands, GitHub release tag check
    ├── ui.rs         # 2-column Rich-parity terminal UI & panels
    ├── config.rs     # ~/.husk/.env persistence (LLM + OAuth)
    ├── services.rs   # Lazy backend/frontend process lifecycle & cleanup
    └── chat.rs       # Backend & curl-based LLM chat + model sync
```

## Build

Install Rust only on the machine that builds/releases Husk:

```bash
cd cli-rs
cargo build --release
```

- Windows output: `target\release\husk.exe`
- Linux / macOS output: `target/release/husk`

> **Note:** After rebuilding, copy the new binary into `~/.husk/bin/husk[.exe]` (or `builds/windows/husk.exe` / `builds/linux/husk`) so your global `husk` command uses the updated build rather than an older cached binary.

Helper scripts:

```bash
./build.sh          # Linux / macOS
.\build.ps1         # Windows PowerShell
```

## Runtime behavior

- **Lazy backend**: Does **not** spawn Uvicorn on bare startup. Reuses an already-running instance if healthy; otherwise starts it on demand (`/ui`, `/sync`, `/llm` push, etc.).
- **GitHub update notice**: Background check against the latest release tag; shows a warning when a newer version exists.
- **OAuth wizard**: `/oauth` configures Google / Microsoft client credentials (stored in `~/.husk/.env`).
- **Clean `/exit`**: Stops only the processes that Husk itself spawned. An external backend is left running and the user is told so.
- **Windows Ctrl+C safety**: Console-control handler kills owned process trees so Uvicorn/Vite are never left behind.
- **Shared model DB**: CLI, backend and UI all use the same SQLite database under `~/.husk/data/husk.db`.

## Commands

| Command     | Description |
|-------------|-------------|
| `/help`     | Show command table |
| `/llm`      | Configure LLM provider / endpoint / model / key |
| `/oauth`    | Configure Google & Microsoft OAuth credentials |
| `/sync`     | Pull the default model from the backend |
| `/ui`       | Start web UI (and backend if needed) and open browser |
| `/cli`      | Stop only the web UI; keep backend warm |
| `/new`      | Start a new conversation |
| `/clear`    | Clear screen and redraw header |
| `/status`   | Show LLM, API and UI status |
| `/version`  | Show version + GitHub latest tag |
| `/exit`     | Stop owned services and quit |

Plain text (no leading `/`) is sent as a chat message.

## Runtime layout

```text
.husk/
├── bin/husk[.exe]    # native CLI launcher
├── husk/             # Python backend package
├── ui/               # frontend
├── venv/             # Python environment with backend dependencies
├── .env
├── data/
└── logs/
```

`HUSK_HOME` can override `~/.husk`.

## Runtime prerequisites

- Python environment with `fastapi` and `uvicorn` for the backend.
- Node.js 18+ and npm for `/ui`.
- `curl` on PATH for health checks, chat and GitHub tag lookup.
- A reachable OpenAI-compatible LLM endpoint (or Ollama, Anthropic, Google via the configured provider).

## Security note

This standard-library-only version stores `LLM_API_KEY` (and OAuth secrets) in `~/.husk/.env`. On Unix it sets file permissions to `0600`. On Windows protect the `.husk` directory with the current user's filesystem permissions.

## Version

Current crate version: **1.0.1** (kept in sync with GitHub release tags of the form `v1.0.1`).
