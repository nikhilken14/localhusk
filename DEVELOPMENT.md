# Development

## Prerequisites

- Python 3.11+
- Node.js 18+ (20+ recommended) for the UI
- Rust toolchain (optional, for the native CLI)
- Git

## Backend

```bash
cd husk
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
ruff check src tests               # optional style
```

Run the API directly (from the `husk/` directory with the venv active):

```bash
uvicorn assistant.main:app --host 127.0.0.1 --port 8000 --reload
```

Or from the repo root via the Python CLI:

```bash
python husk.py
# then /ui or /llm as needed
```

## Frontend

```bash
cd ui
npm install
npm run dev      # http://127.0.0.1:5173
npm run build    # production assets → ui/dist
```

The UI expects the backend on `http://127.0.0.1:8000` (see `src/api-base.ts`).

## Native CLI

```bash
cd cli-rs
cargo build --release
# Linux:   target/release/husk
# Windows: target/release/husk.exe
```

Copy into `builds/linux/` or `builds/windows/` if you want the installers to pick them up without a full `cli-rs/target` tree.

## Installer (local test)

```bash
# Linux – use a disposable home
HUSK_HOME=/tmp/husk-dev-test ./install.sh
/tmp/husk-dev-test/bin/husk

# Windows (PowerShell)
$env:HUSK_HOME = "$env:TEMP\husk-dev-test"
.\install.ps1
```

## Database migrations

```bash
cd husk
alembic upgrade head
alembic revision --autogenerate -m "describe change"   # only when models change
```

`Settings.auto_migrate` runs `alembic upgrade head` on backend startup for source installs.

## Tests worth running before a PR

1. `cd husk && pytest -q`
2. `cd ui && npm run build`
3. `cd cli-rs && cargo build --release`
4. Installer smoke under a clean `HUSK_HOME`

## Project conventions

- Do not commit `.env`, databases, `node_modules`, or `cli-rs/target`.
- Prefer small, reviewable PRs.
- Keep the API contract in `husk/FrontEnd-API-Required.txt` up to date when routes change.
- Public product name is **LocalHusk**; the on-disk command and package paths remain `husk` / `assistant` for compatibility.
