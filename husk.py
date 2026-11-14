#!/usr/bin/env python3
"""Husk - Local AI Assistant. Cross-platform CLI (Windows / macOS / Linux).
 
Flow: chat in the terminal first -> after the first reply Husk offers to open the
web UI (FastAPI backend + TypeScript/Vite frontend). Pick the UI and the
localhost address is printed here; pick the terminal and nothing else starts.
"""
import atexit
import getpass
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
 
try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.exit("Husk needs the 'rich' package:  pip install rich")
 
# Make sure unicode renders on Windows terminals
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
try:
    import readline  # noqa: F401  (line editing on mac/linux)
except ImportError:
    pass
 
VERSION = "1.0"
ACCENT = "#2fa6f5"
DIM = "grey58"
HOME = Path(os.environ.get("HUSK_HOME", Path.home() / ".husk"))
ENV_FILE = HOME / ".env"
SESSION_FILE = HOME / "data" / "session.json"
LOG_DIR = HOME / "logs"
for _d in (HOME / "data", LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)
console = Console(highlight=False)
 
BACKEND_PORT = 8000
FRONTEND_PORT = 5173

# ------------------------------- Logo -------------------------------
LOGO = [
    "██╗  ██╗██╗   ██╗███████╗██╗  ██╗",
    "██║  ██║██║   ██║██╔════╝██║ ██╔╝",
    "███████║██║   ██║███████╗█████╔╝ ",
    "██╔══██║██║   ██║╚════██║██╔═██╗ ",
    "██║  ██║╚██████╔╝███████║██║  ██╗",
    "╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝",
]

# ----------------------------- Config handling -----------------------------
DEFAULTS = {
    "LLM_PROVIDER": "",
    "LLM_ENDPOINT": "",
    "LLM_MODEL": "",
    "LLM_API_KEY": "",
    "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
    "MICROSOFT_CLIENT_ID": "", "MICROSOFT_CLIENT_SECRET": "",
    "MICROSOFT_TENANT": "common",
}
 
 
def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None
 
 
def load_config():
    cfg = dict(DEFAULTS)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = "LLM_API_KEY" if k == "DEFAULT_LLM_KEY" else k
                cfg[k] = v.strip().strip('"')
    # Migrate legacy plaintext keys to the OS credential store when available.
    kr = _keyring()
    if kr:
        try:
            saved = kr.get_password("localhusk", "default-llm") or kr.get_password("husk-cli", "default-llm")
            if saved:
                cfg["LLM_API_KEY"] = saved
            elif cfg.get("LLM_API_KEY"):
                # Migrate legacy plaintext keys and remove them from the config file only
                # after the credential store confirms the write.
                kr.set_password("localhusk", "default-llm", cfg["LLM_API_KEY"])
                try:
                    remaining = [line for line in ENV_FILE.read_text(encoding="utf-8").splitlines()
                                 if line.partition("=")[0].strip() not in {"LLM_API_KEY", "DEFAULT_LLM_KEY"}]
                    ENV_FILE.write_text("\n".join(remaining) + "\n", encoding="utf-8")
                except OSError:
                    pass
        except Exception:
            pass
    return cfg
 
 
def save_config(cfg):
    kr = _keyring()
    api_key = cfg.get("LLM_API_KEY", "")
    key_saved = not bool(api_key)
    if api_key and kr:
        try:
            kr.set_password("localhusk", "default-llm", api_key)
            key_saved = True
        except Exception as exc:
            console.print(f"[yellow]Warning: OS keyring unavailable; API key was not saved: {type(exc).__name__}[/]")
    elif api_key:
        console.print("[yellow]Warning: OS keyring is unavailable; the API key will not persist after this session.[/]")
    # Never write API keys or fake database-password settings to the .env file.
    lines = [f'{k}="{v}"' for k, v in cfg.items() if k in DEFAULTS and k != "LLM_API_KEY"]
    lines.append(f'DATABASE_URL="sqlite:///{(HOME / "data" / "husk.db").as_posix()}"')
    lines.append(f"PORT={BACKEND_PORT}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    return key_saved
 
 
def ask(label, default="", secret=False):
    hint = f" [{DIM}]({default or 'skip'})[/]" if not secret else f" [{DIM}](enter = keep)[/]"
    console.print(f"[{ACCENT}]?[/] {label}{hint}", end=" ")
    try:
        val = getpass.getpass("") if secret else input("")
    except (KeyboardInterrupt, EOFError):
        console.print()
        return default
    return val.strip() or default
 
 
# --------------------------- Web UI services ---------------------------
def find_dir(name):
    """Prefer the current checkout, then fall back to the installed ~/.husk copy."""
    # Prefer the checkout containing this launcher. An old installed copy in
    # ~/.husk must not silently override the source tree being tested.
    for base in (Path(__file__).resolve().parent, HOME):
        if (base / name).is_dir():
            return base / name
    return None
 
 
def free_port(preferred):
    for p in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred
 
 
def wait_http(url, proc, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(url, timeout=2).close()
            return True
        except Exception:
            time.sleep(0.4)
    return False
 
 
def tail(path, n=8):
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()[-n:])
    except OSError:
        return ""
 
 
def kill_tree(p):
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        p.wait(timeout=5)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
 
 
# ----------------------- CLI -> web UI model sync -----------------------
# The CLI keeps its LLM settings in ~/.husk/.env (+ OS keyring), but the web UI lists
# models from the backend's database via GET /api/v1/llm/models. Nothing connected the
# two, so a model configured with /llm never appeared in the UI. These helpers register
# the CLI model with the backend through the same API the UI's "Add model" button uses.
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
 
 
def llm_configured(cfg):
    """True when settings are complete. Hosted endpoints also need an API key."""
    if not (cfg.get("LLM_ENDPOINT") and cfg.get("LLM_MODEL")):
        return False
    local = any(h in cfg["LLM_ENDPOINT"] for h in _LOCAL_HOSTS)
    return local or bool(cfg.get("LLM_API_KEY"))
 
 
def backend_kind(cfg):
    """Map CLI provider/endpoint to a backend provider kind (see providers/registry.py)."""
    provider = cfg.get("LLM_PROVIDER", "").strip().lower()
    endpoint = cfg.get("LLM_ENDPOINT", "").lower()
    if provider == "ollama" or ":11434" in endpoint:
        return "ollama"
    if "api.openai.com" in endpoint:
        return "openai"
    return "openai_compatible"  # Groq, LM Studio, vLLM, OpenRouter... (the CLI only speaks /chat/completions)
 
 
def cli_model_name(cfg):
    return f"{cfg.get('LLM_PROVIDER') or 'LLM'} (CLI)"[:120]
 
 
def _api(base, method, path, payload=None, timeout=10):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + "/api/v1" + path, data, {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
        return json.loads(body) if body else None
 
 
def _http_detail(exc):
    try:
        d = json.loads(exc.read().decode("utf-8", "replace")).get("detail")
        return d if isinstance(d, str) else json.dumps(d)
    except Exception:
        return str(exc)
 
 
def sync_llm_to_backend(backend_url, cfg, make_default=False, force=False):
    """Make the CLI's model visible in the web UI. Returns (ok, message). Never raises.
 
    * Idempotent: the CLI entry is found by its name and updated in place, never duplicated.
    * An identical model the user already added in the UI (same endpoint + model) is reused.
    * Startup sync keeps the default the user chose in the UI; an explicit /llm
      (make_default=True) makes the new model the default, since the user just chose it.
    * The key is sent only to the local backend, which stores it in the OS keyring itself.
    """
    if not llm_configured(cfg):
        return False, "LLM settings incomplete (hosted endpoints need an API key) - nothing to sync"
    kind, name = backend_kind(cfg), cli_model_name(cfg)
    base_url, model, key = cfg["LLM_ENDPOINT"].strip(), cfg["LLM_MODEL"].strip(), cfg.get("LLM_API_KEY", "")
    try:
        rows = _api(backend_url, "GET", "/llm/models") or []
        same = lambda r: (r.get("base_url") or "").rstrip("/") == base_url.rstrip("/") and r.get("model") == model
        mine = next((r for r in rows if r.get("name") == name), None)
        twin = next((r for r in rows if same(r)), None)
        if mine is None and twin is not None:       # user already added this exact model in the UI
            if make_default and not twin.get("is_default"):
                _api(backend_url, "POST", f"/llm/models/{twin['id']}/default")
            return True, f"'{twin['name']}' is already in the web UI"
        draft = {"name": name, "kind": kind, "base_url": base_url, "model": model}
        if key:
            draft["api_key"] = key
        if mine is None:
            _api(backend_url, "POST", "/llm/models", {**draft, "is_default": bool(make_default)})
            return True, f"Added '{name}' to the web UI" + (" and set it as default" if make_default else "")
        unchanged = (mine.get("kind") == kind and (mine.get("base_url") or "").rstrip("/") == base_url.rstrip("/")
                     and mine.get("model") == model and bool(mine.get("has_api_key")) == bool(key))
        if unchanged and not force:
            if make_default and not mine.get("is_default"):
                _api(backend_url, "POST", f"/llm/models/{mine['id']}/default")
            return True, f"'{name}' is already up to date in the web UI"
        _api(backend_url, "PUT", f"/llm/models/{mine['id']}",
             {**draft, "max_output_tokens": mine.get("max_output_tokens", 2048),
              "temperature": mine.get("temperature", 0.7), "is_default": True if make_default else None})
        return True, f"Updated '{name}' in the web UI"
    except urllib.error.HTTPError as e:
        return False, f"backend rejected the model (HTTP {e.code}): {_http_detail(e)}"
    except Exception as e:  # noqa: BLE001
        return False, f"could not reach the backend: {e}"
 
 
def report_sync(ok, msg):
    console.print(f"[green]+[/] {msg}" if ok else f"[yellow]! Web UI model sync: {msg}[/]")
 
 

def sync_llm_from_backend(backend_url, cfg):
    """Pull the backend default model into local CLI config. Returns (ok, message).

    Mirrors cli-rs chat::sync_from_backend: GET /api/v1/llm/models, prefer is_default.
    Updates LLM_PROVIDER / LLM_ENDPOINT / LLM_MODEL in *cfg* and persists via save_config.
    """
    if not backend_url:
        return False, "backend is not running"
    try:
        rows = _api(backend_url, "GET", "/llm/models") or []
        if not isinstance(rows, list) or not rows:
            return False, "no models configured in backend yet"
        default = next((r for r in rows if r.get("is_default")), None) or rows[0]
        kind = (default.get("kind") or "").strip().lower()
        if kind == "ollama":
            provider = "ollama"
        elif kind == "openai":
            provider = "openai"
        elif kind in ("anthropic", "google"):
            provider = kind
        else:
            provider = "openai_compatible"
        model = (default.get("model") or "").strip()
        endpoint = (default.get("base_url") or "").strip()
        if not model:
            return False, "default model entry has no model id"
        cfg["LLM_PROVIDER"] = provider
        cfg["LLM_MODEL"] = model
        if endpoint:
            cfg["LLM_ENDPOINT"] = endpoint
        # API key is never returned by the backend list endpoint for safety.
        save_config(cfg)
        name = default.get("name") or model
        return True, f"Pulled default model: {provider} | {model} ({name})"
    except urllib.error.HTTPError as e:
        return False, f"backend rejected the request (HTTP {e.code}): {_http_detail(e)}"
    except Exception as e:  # noqa: BLE001
        return False, f"could not reach the backend: {e}"

class Services:
    """Service lifecycle aligned with cli-rs (see cli-rs/STARTUP-FLOW.md):

    1. Backend is spawned early (non-blocking) so terminal chat and /ui share it.
    2. /ui waits for backend health, then starts only the Vite frontend.
    3. /cli stops only the frontend; backend stays warm for the next /ui.
    4. /exit (or process exit) stops both.
    """

    def __init__(self):
        self.procs = {}
        self.urls = {}
        atexit.register(self.stop_all)

    def _alive(self, key):
        p = self.procs.get(key)
        return p is not None and p.poll() is None

    @property
    def backend_running(self):
        return self._alive("backend")

    @property
    def frontend_running(self):
        return self._alive("frontend")

    @property
    def running(self):
        """True when the web UI (frontend) is up. Kept for older call sites."""
        return self.frontend_running

    def _spawn(self, key, cmd, cwd, env):
        kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
            else {"start_new_session": True}
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOG_DIR / f"{key}.log", "w", encoding="utf-8")
        # npm is normally a .cmd shim on Windows; launch it through cmd.exe.
        if os.name == "nt" and isinstance(cmd, list) and cmd and str(cmd[0]).lower().endswith((".cmd", ".bat")):
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", subprocess.list2cmdline(cmd)]
        self.procs[key] = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, **kw,
        )

    def _stop_key(self, key):
        p = self.procs.pop(key, None)
        if p is not None:
            kill_tree(p)
        if key in self.urls:
            del self.urls[key]

    @staticmethod
    def _backend_interpreter(backend):
        """Choose an interpreter that actually has FastAPI and Uvicorn installed."""
        candidates = []
        if os.name == "nt":
            candidates.extend([backend / ".venv" / "Scripts" / "python.exe", HOME / "venv" / "Scripts" / "python.exe"])
        else:
            candidates.extend([backend / ".venv" / "bin" / "python", HOME / "venv" / "bin" / "python"])
        candidates.append(Path(sys.executable))
        seen = set()
        for candidate in candidates:
            candidate = candidate.resolve() if candidate.exists() else candidate
            if str(candidate) in seen or not candidate.exists():
                continue
            seen.add(str(candidate))
            try:
                check = subprocess.run(
                    [str(candidate), "-c", "import fastapi, uvicorn"],
                    capture_output=True, text=True, timeout=8,
                )
                if check.returncode == 0:
                    return str(candidate)
            except (OSError, subprocess.SubprocessError):
                continue
        return None

    def ensure_backend(self, cfg, wait=False, timeout=25):
        """Spawn the FastAPI backend if it is not already running.

        Returns the backend base URL on success, or None on failure.
        When wait=True, blocks until /api/v1/health responds (or timeout).
        """
        if self.backend_running and self.urls.get("backend"):
            return self.urls["backend"]

        self._stop_key("backend")
        backend = find_dir("husk")
        if not backend:
            console.print("[red]x[/] husk/ backend package not found - re-run the installer")
            return None
        backend_python = self._backend_interpreter(backend)
        if not backend_python:
            console.print(
                "[red]x[/] FastAPI/Uvicorn missing. Install with: "
                "python -m pip install -e . (from the husk folder), or re-run install.ps1."
            )
            return None

        bport = free_port(BACKEND_PORT)
        burl = f"http://127.0.0.1:{bport}"
        src_dir = backend / "src"
        # Ensure the assistant package is importable even if the venv was installed
        # without an editable path entry.
        existing_pp = os.environ.get("PYTHONPATH", "")
        sep = ";" if os.name == "nt" else ":"
        pythonpath = str(src_dir) if not existing_pp else f"{src_dir}{sep}{existing_pp}"
        db_url = f"sqlite:///{(HOME / 'data' / 'husk.db').as_posix()}"
        env = {
            **os.environ,
            "HUSK_HOME": str(HOME),
            "HUSK_BACKEND_URL": burl,
            "PUBLIC_BASE_URL": burl,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": pythonpath,
            "DATABASE_URL": db_url,
            "CORS_ORIGINS": "http://127.0.0.1:5173,http://localhost:5173",
        }
        # Surface keys from ~/.husk/.env into the child process
        if ENV_FILE.exists():
            try:
                for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in env:
                        env[k] = v
            except OSError:
                pass
        self._spawn(
            "backend",
            [
                backend_python, "-m", "uvicorn", "assistant.main:app",
                "--app-dir", str(src_dir),
                "--host", "127.0.0.1", "--port", str(bport),
            ],
            backend,
            env,
        )
        self.urls["backend"] = burl

        if wait:
            if not wait_http(f"{burl}/api/v1/health", self.procs["backend"], timeout):
                console.print("[red]x Backend failed to start[/]")
                console.print(f"[{DIM}]{tail(LOG_DIR / 'backend.log')}[/]")
                console.print(f"[{DIM}]Full backend log: {LOG_DIR / 'backend.log'}[/]")
                console.print(f"[{DIM}]Selected backend Python: {backend_python}[/]")
                self._stop_key("backend")
                return None
            report_sync(*sync_llm_to_backend(burl, cfg))
        return burl

    def start_frontend(self, cfg):
        """Start only the Vite frontend. Backend must already be healthy."""
        if self.frontend_running and self.urls.get("frontend"):
            return True

        self._stop_key("frontend")
        burl = self.urls.get("backend")
        if not burl or not self.backend_running:
            burl = self.ensure_backend(cfg, wait=True, timeout=45)
            if not burl:
                return False
        elif not wait_http(f"{burl}/api/v1/health", self.procs.get("backend"), 45):
            console.print("[red]x Backend is not healthy[/]")
            console.print(f"[{DIM}]{tail(LOG_DIR / 'backend.log')}[/]")
            return False

        frontend = find_dir("ui")
        node = shutil.which("node")
        npm_cli = (
            os.path.join(os.path.dirname(os.path.abspath(node)), "node_modules", "npm", "bin", "npm-cli.js")
            if node else None
        )
        problems = []
        if not frontend:
            problems.append("ui/ frontend folder not found - re-run the installer")
        if not node or not npm_cli or not os.path.isfile(npm_cli):
            problems.append("Node.js or its npm CLI is missing - repair the Node.js installation.")
        if problems:
            for p in problems:
                console.print(f"[red]x[/] {p}")
            return False

        fport = free_port(FRONTEND_PORT)
        furl = f"http://127.0.0.1:{fport}"
        env = {
            **os.environ,
            "HUSK_HOME": str(HOME),
            "HUSK_BACKEND_URL": burl,
            "VITE_API_BASE_URL": burl + "/api/v1",
            "CORS_ORIGINS": furl,
            "PUBLIC_BASE_URL": burl,
            "FRONTEND_URL": furl,
            "PYTHONUNBUFFERED": "1",
        }

        with console.status(f"[{ACCENT}]Starting web UI...[/]", spinner="dots", spinner_style=ACCENT) as st:
            if not (frontend / "node_modules").exists():
                st.update(f"[{ACCENT}]Installing frontend packages (first run only)...[/]")
                r = subprocess.run(
                    [node, npm_cli, "install", "--no-audit", "--no-fund"],
                    cwd=frontend, capture_output=True, text=True,
                )
                if r.returncode != 0:
                    console.print("[red]x npm install failed[/]")
                    console.print(f"[{DIM}]{(r.stderr or r.stdout)[-600:]}[/]")
                    return False

            st.update(f"[{ACCENT}]Starting frontend...[/]")
            self._spawn(
                "frontend",
                [node, npm_cli, "run", "dev", "--", "--host", "127.0.0.1",
                 "--port", str(fport), "--strictPort"],
                frontend,
                env,
            )
            if not wait_http(furl, self.procs["frontend"], 40):
                console.print("[red]x Frontend failed to start[/]")
                console.print(f"[{DIM}]{tail(LOG_DIR / 'frontend.log')}[/]")
                self._stop_key("frontend")
                return False

        self.urls["frontend"] = furl
        if burl:
            report_sync(*sync_llm_to_backend(burl, cfg))
        return True

    def start(self, cfg):
        """Backward-compatible: ensure backend + start frontend (used by /ui)."""
        if self.frontend_running:
            return True
        if not self.ensure_backend(cfg, wait=True, timeout=45):
            return False
        return self.start_frontend(cfg)

    def stop_ui(self):
        """Stop only the frontend; keep the backend warm (matches cli-rs /cli)."""
        self._stop_key("frontend")

    def stop(self):
        """Legacy name used by some call sites — stops only the frontend."""
        self.stop_ui()

    def stop_all(self):
        """Stop frontend and backend (exit path)."""
        self._stop_key("frontend")
        self._stop_key("backend")
        self.urls = {}


SERVICES = Services()
HISTORY = [{"role": "system", "content": "You are Husk, a helpful local AI assistant."}]
STATE = {"offered": False}
 
 
def write_session():
    """Persist a local CLI session snapshot for diagnostics; the web UI has its own conversations."""
    try:
        SESSION_FILE.write_text(json.dumps([m for m in HISTORY if m["role"] != "system"]), encoding="utf-8")
    except OSError:
        pass
 
 
def show_ui_urls():
    u = SERVICES.urls
    body = Text.assemble(
        ("Web UI   ", DIM), (u["frontend"], f"bold {ACCENT}"), "\n",
        ("API      ", DIM), (u["backend"], ACCENT), ("   docs: ", DIM), (u["backend"] + "/docs", ACCENT), "\n\n",
        ("The web UI uses its own saved conversations. Keep chatting here; /cli stops only the UI (backend stays warm). Ctrl+C quits everything.", DIM),
    )
    console.print(Panel(body, title=f"[{ACCENT}] Husk is running [/]", title_align="left",
                        border_style=ACCENT, box=box.ROUNDED, padding=(1, 2)))
 
 
def open_ui(cfg):
    write_session()
    if SERVICES.start(cfg):
        show_ui_urls()
    else:
        console.print(f"[{DIM}]Staying in the terminal. Try again later with /ui[/]")
 
 
def offer_ui(cfg):
    """Shown once, right after the first terminal reply."""
    STATE["offered"] = True
    console.print()
    console.print(Panel(
        Text.assemble(("Keep going in the terminal, or switch to the web UI?\n\n", "white"),
                      ("  1  ", f"bold {ACCENT}"), "Stay in the terminal\n",
                      ("  2  ", f"bold {ACCENT}"), "Open the web UI  ", (f"(reuses warm backend when available)", DIM)),
        title=f"[{ACCENT}] Continue where? [/]", title_align="left", border_style=ACCENT, box=box.ROUNDED))
    if ask("Choose 1 or 2", "1") == "2":
        open_ui(cfg)
    else:
        console.print(f"[{DIM}]Staying in the terminal. You can open the UI any time with /ui[/]")
 
 
# --------------------------------- Header ----------------------------------
def header(cfg):
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "Developer"
    oauth = bool(cfg["GOOGLE_CLIENT_ID"] or cfg["MICROSOFT_CLIENT_ID"])
    cwd = str(Path.cwd()).replace(str(Path.home()), "~")
 
    left = Group(
        Align.center(Text(f"Welcome back, {user}!", style="bold white")),
        Text(""),
        Align.center(Text("\n".join(LOGO), style=ACCENT)),
        Align.center(Text("Local AI Assistant", style=f"bold {DIM}")),
        Text(""),
        Align.center(Text(f"{cfg['LLM_MODEL']} - {cfg['LLM_PROVIDER']}", style=DIM)),
        Align.center(Text(cwd, style=DIM)),
    )
    left_height = 2 + len(LOGO) + 1 + 1 + 2
 
    dot = lambda ok: Text("● ", style="green" if ok else "red")
    ui_on = SERVICES.running
    right = Group(
        Text("Tips for getting started", style=f"bold {ACCENT}"),
        Text("Type a message to chat, or /help"),
        Text("'/ui' command to start Web UI."),
        Text(""),
        Text(""),
        Text("Quick status", style=f"bold {ACCENT}"),
        Text.assemble(dot(llm_configured(cfg)), f"LLM    {cfg['LLM_PROVIDER']} ({cfg['LLM_MODEL']})"),
        Text.assemble(dot(oauth), f"OAuth  {'Configured' if oauth else 'Not configured'}"),
        Text.assemble(dot(True), "Store  Local SQLite"),
    )
 
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(width=1, style=ACCENT)
    grid.add_column(ratio=1)
    grid.add_row(left, "\n".join("|" for _ in range(left_height)), Padding(right, (0, 0, 0, 2)))
    console.print(Panel(grid, title=f"[{ACCENT}] Husk v{VERSION} [/]", title_align="left",
                        border_style=ACCENT, box=box.ROUNDED, padding=(1, 2)))
 
 
# -------------------------------- Commands ---------------------------------
def cmd_help(cfg, _arg=""):
    t = Table(box=None, show_header=False, padding=(0, 2))
    for c, d in [
        ("/chat <msg>", "Send a message (plain text works too)"),
        ("/new", "Start a fresh conversation"),
        ("/ui", "Start the web UI and show its localhost address"),
        ("/cli", "Stop the web UI only (backend stays warm)"),
        ("/agents", "View running agents & registered tools"),
        ("/oauth", "Modify Google & Microsoft credentials"),
        ("/llm", "Modify LLM provider / model / endpoint"),
        ("/sync", "Pull default model from backend DB"),
        ("/status", "Show current configuration"),
        ("/clear", "Clear the screen"),
        ("/exit", "Quit Husk"),
    ]:
        t.add_row(Text(c, style=f"bold {ACCENT}"), d)
    console.print(t)
 
 
def cmd_chat(cfg, arg=""):
    if not arg.strip():
        console.print(f"[{DIM}]Usage: /chat <message>  (or just type your message)[/]")
        return
    handle_message(cfg, arg.strip())
 
 
def cmd_new(cfg, _arg=""):
    del HISTORY[1:]
    write_session()
    console.print(f"[green]+ Started a new conversation[/]")
 
 
def cmd_ui(cfg, _arg=""):
    if SERVICES.running:
        show_ui_urls()
    else:
        STATE["offered"] = True
        open_ui(cfg)
 
 
def cmd_cli(cfg, _arg=""):
    if SERVICES.frontend_running:
        SERVICES.stop_ui()
        console.print("[green]+ Web UI stopped.[/] Backend remains warm. Continuing in the terminal.")
    else:
        console.print(f"[{DIM}]Web UI isn't running. You're already in the terminal.[/]")
 
 
def cmd_agents(cfg, _arg=""):
    """Report only verified local state; do not imply integrations are active when unconfigured."""
    t = Table(title="Agent runtime", title_style=f"bold {ACCENT}", box=box.SIMPLE_HEAD,
              header_style=DIM, title_justify="left")
    t.add_column("Component"); t.add_column("Status")
    t.add_row("Web backend", "[green]* running[/]" if SERVICES.backend_running else "[dim]o stopped[/]")
    t.add_row("Agent registry", "Open the web UI to inspect configured agents")
    t.add_row("MCP connections", "Open Connections to inspect configured servers")
    t.add_row("Mail / calendar", "Configure provider accounts in Connections")
    console.print(t)
 
 
def cmd_llm(cfg, _arg=""):
    console.print(f"[bold {ACCENT}]Configure LLM[/]")
    cfg["LLM_PROVIDER"] = ask("Provider", cfg["LLM_PROVIDER"])
    cfg["LLM_ENDPOINT"] = ask("Endpoint URL", cfg["LLM_ENDPOINT"])
    cfg["LLM_MODEL"] = ask("Model", cfg["LLM_MODEL"])
    cfg["LLM_API_KEY"] = ask("API key", cfg["LLM_API_KEY"], secret=True) or cfg["LLM_API_KEY"]
    key_saved = save_config(cfg)
    if cfg.get("LLM_API_KEY") and not key_saved:
        console.print("[yellow]LLM settings saved, but the API key was not persisted. Configure an OS keyring and save again.[/]")
    else:
        console.print("[green]+ LLM settings saved[/]")
    burl = SERVICES.urls.get("backend") if SERVICES.backend_running else None
    if not burl:
        burl = SERVICES.ensure_backend(cfg, wait=True, timeout=20)
    if burl:
        report_sync(*sync_llm_to_backend(burl, cfg, make_default=True, force=True))
 
 
def cmd_sync(cfg, _arg=""):
    """Pull the default model from the shared backend DB into local CLI config (cli-rs /sync)."""
    burl = SERVICES.urls.get("backend") if SERVICES.backend_running else None
    if not burl:
        burl = SERVICES.ensure_backend(cfg, wait=True, timeout=20)
    if not burl:
        console.print(f"[{DIM}]Backend is not available. Start it with /ui or wait for startup.[/]")
        return
    ok, msg = sync_llm_from_backend(burl, cfg)
    if ok:
        console.print(f"[green]+[/] {msg}")
    else:
        console.print(f"[red]x Sync failed:[/] {msg}")


def cmd_oauth(cfg, _arg=""):
    console.print(f"[bold {ACCENT}]Configure OAuth[/]")
    cfg["GOOGLE_CLIENT_ID"] = ask("Google Client ID", cfg["GOOGLE_CLIENT_ID"])
    if cfg["GOOGLE_CLIENT_ID"]:
        cfg["GOOGLE_CLIENT_SECRET"] = ask("Google Client Secret", secret=True) or cfg["GOOGLE_CLIENT_SECRET"]
    cfg["MICROSOFT_CLIENT_ID"] = ask("Microsoft Client ID", cfg["MICROSOFT_CLIENT_ID"])
    if cfg["MICROSOFT_CLIENT_ID"]:
        cfg["MICROSOFT_CLIENT_SECRET"] = ask("Microsoft Client Secret (optional w/ PKCE)", secret=True) or cfg["MICROSOFT_CLIENT_SECRET"]
        cfg["MICROSOFT_TENANT"] = ask("Microsoft Tenant", cfg["MICROSOFT_TENANT"])
    save_config(cfg)
    console.print("[green]+ Credentials saved[/]")
 
 
def cmd_status(cfg, _arg=""):
    t = Table(box=None, show_header=False, padding=(0, 2))
    for k in ("LLM_PROVIDER", "LLM_ENDPOINT", "LLM_MODEL", "MICROSOFT_TENANT"):
        t.add_row(Text(k, style=DIM), cfg[k])
    t.add_row(Text("CONFIG", style=DIM), str(ENV_FILE))
    t.add_row(Text("WEB UI", style=DIM), SERVICES.urls.get("frontend", "off") if SERVICES.frontend_running else "off")
    t.add_row(Text("BACKEND", style=DIM), SERVICES.urls.get("backend", "off") if SERVICES.backend_running else "off")
    console.print(t)
 
 
def cmd_clear(cfg, _arg=""):
    console.clear()
    header(cfg)
 
 
def chat(cfg, history, message):
    """Stream a reply from any OpenAI-compatible endpoint (Ollama, LM Studio, OpenAI...).
    Returns True if a reply was received."""
    history.append({"role": "user", "content": message})
    url = cfg["LLM_ENDPOINT"].rstrip("/") + "/chat/completions"
    headers = { "Content-Type": "application/json", "User-Agent": "Husk/1.2 (local AI assistant)",}
    if cfg["LLM_API_KEY"]:
        headers["Authorization"] = f"Bearer {cfg['LLM_API_KEY']}"
    body = json.dumps({"model": cfg["LLM_MODEL"], "messages": history, "stream": True}).encode()
    reply = ""
    try:
        with console.status(f"[{ACCENT}]Thinking...[/]", spinner="dots", spinner_style=ACCENT) as status:
            req = urllib.request.Request(url, body, headers)
            with urllib.request.urlopen(req, timeout=300) as r:
                started = False
                for raw in r:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:") or line.endswith("[DONE]"):
                        continue
                    delta = json.loads(line[5:])["choices"][0].get("delta", {}).get("content") or ""
                    if delta:
                        if not started:
                            status.stop()
                            console.print(f"[{ACCENT}]*[/] ", end="")
                            started = True
                        reply += delta
                        console.print(delta, end="", markup=False, soft_wrap=True)
        console.print()
    except urllib.error.HTTPError as e:
        history.pop()
        detail = e.read().decode("utf-8", "replace")
        console.print(f"[red]x HTTP {e.code} from {cfg['LLM_PROVIDER']}[/]")
        if detail:
            console.print(detail)
        return False
    except Exception as e:  # noqa: BLE001
        history.pop()
        console.print(f"[red]x {e}[/]")
        return False
    history.append({"role": "assistant", "content": reply})
    return True
 
 
def handle_message(cfg, text):
    ok = chat(cfg, HISTORY, text)
    if ok:
        write_session()
        if not STATE["offered"] and not SERVICES.running:
            offer_ui(cfg)
 
 
COMMANDS = {"help": cmd_help, "chat": cmd_chat, "new": cmd_new, "ui": cmd_ui, "cli": cmd_cli,
            "agents": cmd_agents, "oauth": cmd_oauth, "llm": cmd_llm, "sync": cmd_sync,
            "status": cmd_status, "clear": cmd_clear}
 
# -------------------------------- Setup wizard -----------------------------
def first_run(cfg):
    """Optional first-run setup — ask before collecting LLM / OAuth credentials.
    Mirrors the lighter Claude Code experience: get into the CLI quickly,
    configure later with /llm and /oauth if preferred.
    """
    console.print(Panel(
        Text.assemble(
            ("Welcome to Husk.\n\n", "white"),
            ("You can configure your LLM and optional OAuth credentials now,\n", "white"),
            ("or skip and do it later with ", "white"),
            ("/llm", f"bold {ACCENT}"),
            (" and ", "white"),
            ("/oauth", f"bold {ACCENT}"),
            (".\n\n", "white"),
            ("  1  ", f"bold {ACCENT}"), "Set up now (recommended for first chat)\n",
            ("  2  ", f"bold {ACCENT}"), "Skip for now — use defaults / configure later",
        ),
        title=f"[{ACCENT}] Setup [/]",
        border_style=ACCENT,
        box=box.ROUNDED,
        title_align="left",
    ))
    choice = ask("Choose 1 or 2", "1").strip().lower()
    if choice in ("1", "y", "yes", "setup", "now"):
        cmd_llm(cfg)
        # OAuth is optional even during guided setup
        console.print()
        console.print(f"[{DIM}]OAuth (Google / Microsoft) is optional — needed only for mail/calendar integrations.[/]")
        do_oauth = ask("Configure OAuth now? (y/N)", "n").strip().lower()
        if do_oauth in ("y", "yes", "1"):
            cmd_oauth(cfg)
        else:
            console.print(f"[{DIM}]Skipped OAuth. Run /oauth any time later.[/]")
        save_config(cfg)
        console.print(f"[green]+ Saved to {ENV_FILE}[/]\n")
    else:
        # Still write defaults so ENV_FILE exists and subsequent runs are not "first"
        save_config(cfg)
        console.print(Panel(
            Text.assemble(
                ("Setup skipped. No LLM is configured yet.\n\n", "white"),
                ("Configure with ", "white"),
                ("/llm", f"bold {ACCENT}"),
                (" (and optionally ", "white"),
                ("/oauth", f"bold {ACCENT}"),
                (") before chatting.\n", "white"),
                ("Chat will work once a provider endpoint and model are set.", "white"),
            ),
            title=f"[{ACCENT}] Ready [/]",
            border_style=ACCENT,
            box=box.ROUNDED,
            title_align="left",
        ))
        console.print()
 
 
# ----------------------------------- Main ----------------------------------
def prompt():
    width = shutil.get_terminal_size((80, 24)).columns
    console.print(f"[{DIM}]{'-' * width}[/]")
    try:
        text = input("\x01\x1b[1;38;2;47;166;245m\x02❯\x01\x1b[0m\x02 " if os.name != "nt" else "> ")
    except (KeyboardInterrupt, EOFError):
        console.print()
        return None
    console.print(f"[{DIM}]{'-' * width}[/]")
    return text.strip()
 
 
def main():
    first = not ENV_FILE.exists()
    cfg = load_config()
    console.clear()
    if first:
        first_run(cfg)
    header(cfg)
    console.print(f"[{DIM}]  /help for commands - Ctrl+C to exit[/]\n")
    write_session()  # fresh terminal session -> UI starts empty
    # Match cli-rs: spawn backend early (non-blocking) so /ui and API chat are ready sooner.
    SERVICES.ensure_backend(cfg, wait=False)
    try:
        while True:
            text = prompt()
            if text is None or text.lower() in ("/exit", "/quit", "exit", "quit"):
                console.print(f"[{DIM}]Goodbye![/]")
                return
            if not text:
                continue
            if text.startswith("/"):
                name, _, arg = text[1:].partition(" ")
                if name in COMMANDS:
                    COMMANDS[name](cfg, arg)
                else:
                    console.print(f"[red]Unknown command[/] /{name} [{DIM}](try /help)[/]")
            else:
                handle_message(cfg, text)
            console.print()
    finally:
        SERVICES.stop_all()
 
 
if __name__ == "__main__":
    main()