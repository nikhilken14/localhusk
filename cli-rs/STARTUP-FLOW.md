# Husk startup and service lifecycle

The native CLI follows this lifecycle:

1. Load `HUSK_HOME/.env` (or `~/.husk/.env`) and initialize the terminal REPL.
2. **Lazy backend**: do **not** spawn Uvicorn on bare startup. If a healthy backend is already listening on `http://127.0.0.1:8000`, reuse it silently and mark it as external (so `/exit` will not kill it).
3. Kick off a background GitHub release-tag check so the header can show an update notice without blocking startup.
4. Accept terminal chat immediately. Chat prefers the backend conversation API when available; otherwise it falls back to a direct OpenAI-compatible `curl` call using local endpoint settings.
5. On `/ui`, `/sync`, `/llm` (when a push is needed), or any path that requires the API:
   - Call `ensure_backend()` which either reuses a healthy instance or starts a managed child process.
   - Wait (bounded) for `/api/v1/health`.
6. On `/ui`, once the backend is healthy, start only the Vite frontend and open it in the browser.
7. On `/cli`, stop only the frontend. Keep the backend child (or external instance) alive.
8. On `/exit`, `/quit`, `/q`, EOF (Ctrl+Z / Ctrl+D), Ctrl+C, or closing the console window:
   - Stop only the child processes that Husk itself started.
   - Leave an external backend running and print a clear message.
   - On Windows a console-control handler kills owned process trees even when Husk is interrupted.

Backend and frontend logs are written to `HUSK_HOME/logs/backend.log` and `HUSK_HOME/logs/frontend.log`.

## Commands that force backend start

| Command   | Behaviour |
|-----------|-----------|
| `/ui`     | ensure backend → start frontend → open browser |
| `/sync`   | ensure backend → pull default model |
| `/llm`    | save local config; if backend reachable, push model |
| chat via API | uses backend if already up; otherwise falls back to direct curl |

## Version / update check

On every interactive start the CLI queries `https://api.github.com/repos/<owner>/LocalHusk/releases/latest` (override with `HUSK_GITHUB_REPO`) in a background thread. If a newer tag is found it prints a one-line notice under the header.
