use std::{
    env,
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicU32, Ordering},
    thread,
    time::{Duration, Instant},
};
use crate::config;

// PIDs of the child processes we own. Kept in statics so the Windows console-control handler
// (Ctrl+C / closing the window), which runs on its own thread, can still shut them down.
static BACKEND_PID: AtomicU32 = AtomicU32::new(0);
static FRONTEND_PID: AtomicU32 = AtomicU32::new(0);

/// Result of shutting everything down, so the caller can tell the person what actually happened.
pub struct StopReport {
    pub ui_stopped: bool,
    pub backend_stopped: bool,
    /// The backend was already running when Husk started, so Husk does not own it.
    pub backend_left_running: bool,
}

#[cfg(windows)]
fn kill_tree(pid: u32) {
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(windows)]
unsafe extern "system" fn console_ctrl_handler(_event: u32) -> i32 {
    // Ctrl+C, Ctrl+Break or the console window closing: take the child processes down with us,
    // then return 0 so the default handler still terminates Husk.
    for slot in [&FRONTEND_PID, &BACKEND_PID] {
        let pid = slot.swap(0, Ordering::SeqCst);
        if pid != 0 {
            kill_tree(pid);
        }
    }
    0
}

/// Make sure Ctrl+C / closing the window does not leave uvicorn or Vite running in the background.
/// (On Unix the children share the terminal's process group and receive the signal themselves.)
pub fn install_ctrl_handler() {
    #[cfg(windows)]
    {
        extern "system" {
            fn SetConsoleCtrlHandler(handler: Option<unsafe extern "system" fn(u32) -> i32>, add: i32) -> i32;
        }
        unsafe {
            SetConsoleCtrlHandler(Some(console_ctrl_handler), 1);
        }
    }
}

/// Open a URL in the default browser (best effort).
pub fn open_url(url: &str) {
    #[cfg(windows)]
    let result = Command::new("cmd").args(["/C", "start", "", url]).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
    #[cfg(target_os = "macos")]
    let result = Command::new("open").arg(url).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
    #[cfg(all(not(windows), not(target_os = "macos")))]
    let result = Command::new("xdg-open").arg(url).stdout(Stdio::null()).stderr(Stdio::null()).spawn();
    let _ = result;
}

pub struct Services {
    backend: Option<Child>,
    frontend: Option<Child>,
    /// True when a healthy backend was already running at startup (not started by this process).
    backend_external: bool,
    pub backend_url: String,
    pub frontend_url: String,
}

impl Services {
    pub fn new() -> Self {
        Self {
            backend: None,
            frontend: None,
            backend_external: false,
            backend_url: String::new(),
            frontend_url: String::new(),
        }
    }

    /// Prefer installed copy under HUSK_HOME, then paths relative to the running binary / cwd.
    fn project_dir(name: &str) -> Option<PathBuf> {
        let home = config::home();
        if home.join(name).is_dir() {
            return Some(home.join(name));
        }
        let exe = env::current_exe().ok()?;
        let mut bases = vec![
            exe.parent()?.to_path_buf(),
            env::current_dir().ok()?,
        ];
        if let Some(p) = exe.parent().and_then(|p| p.parent()) {
            bases.push(p.to_path_buf());
        }
        // Also walk up a few levels from cwd (useful when running from a checkout)
        if let Ok(cwd) = env::current_dir() {
            let mut cur = cwd;
            for _ in 0..4 {
                bases.push(cur.clone());
                if !cur.pop() {
                    break;
                }
            }
        }
        for base in bases {
            if base.join(name).is_dir() {
                return Some(base.join(name));
            }
        }
        None
    }

    fn python(backend: &Path) -> Option<String> {
        #[cfg(windows)]
        let candidates = vec![
            config::home().join("venv/Scripts/python.exe"),
            backend.join(".venv/Scripts/python.exe"),
            backend.join("venv/Scripts/python.exe"),
        ];
        #[cfg(not(windows))]
        let candidates = vec![
            config::home().join("venv/bin/python"),
            backend.join(".venv/bin/python"),
            backend.join("venv/bin/python"),
        ];
        for p in candidates {
            if p.exists()
                && Command::new(&p)
                    .args(["-c", "import fastapi, uvicorn"])
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status()
                    .map(|s| s.success())
                    .unwrap_or(false)
            {
                return Some(p.to_string_lossy().into_owned());
            }
        }
        for p in ["python3", "python"] {
            if Command::new(p)
                .args(["-c", "import fastapi, uvicorn"])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .map(|s| s.success())
                .unwrap_or(false)
            {
                return Some(p.into());
            }
        }
        None
    }

    fn port_free(preferred: u16) -> u16 {
        use std::net::TcpListener;
        if let Ok(listener) = TcpListener::bind(("127.0.0.1", preferred)) {
            return listener.local_addr().map(|a| a.port()).unwrap_or(preferred);
        }
        TcpListener::bind(("127.0.0.1", 0))
            .and_then(|l| l.local_addr())
            .map(|a| a.port())
            .unwrap_or(preferred)
    }

    fn healthy(url: &str) -> bool {
        let target = format!("{}/api/v1/health", url.trim_end_matches('/'));
        Command::new("curl")
            .args(["-fsS", "--max-time", "2", &target])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    fn tail_log(path: &Path, lines: usize) -> String {
        match fs::read_to_string(path) {
            Ok(s) => {
                let all: Vec<&str> = s.lines().collect();
                let start = all.len().saturating_sub(lines);
                all[start..].join("\n")
            }
            Err(_) => String::new(),
        }
    }

    /// Spawn Uvicorn and return immediately. Readiness is checked only when /ui is requested.
    pub fn start_backend(&mut self) -> Result<(), String> {
        let standard_url = "http://127.0.0.1:8000";
        if Self::healthy(standard_url) {
            self.backend_url = standard_url.into();
            self.backend_external = true;
            return Ok(());
        }

        if let Some(child) = self.backend.as_mut() {
            if child.try_wait().ok().flatten().is_none() && !self.backend_url.is_empty() {
                return Ok(());
            }
        }

        let backend = Self::project_dir("husk")
            .ok_or_else(|| {
                format!(
                    "Could not find the husk/ backend directory.\n\
                     Expected under {}/husk or next to the husk binary.\n\
                     Re-run the installer from a full release archive.",
                    config::home().display()
                )
            })?;

        let py = Self::python(&backend).ok_or_else(|| {
            format!(
                "Python environment with FastAPI and Uvicorn not found.\n\
                 Run the Husk installer first, or create a venv at {}/venv and:\n\
                   pip install fastapi uvicorn",
                config::home().display()
            )
        })?;

        let port = if Self::port_free(8000) == 8000 {
            8000
        } else {
            Self::port_free(0)
        };
        self.backend_url = format!("http://127.0.0.1:{port}");

        let home = config::home();
        fs::create_dir_all(home.join("logs")).map_err(|e| e.to_string())?;
        fs::create_dir_all(home.join("data")).map_err(|e| e.to_string())?;

        let log_path = home.join("logs/backend.log");
        let log = File::create(&log_path).map_err(|e| e.to_string())?;

        // Ensure the package under husk/src is importable.
        let src_dir = backend.join("src");
        let mut pythonpath = src_dir.display().to_string();
        if let Ok(existing) = env::var("PYTHONPATH") {
            if !existing.is_empty() {
                #[cfg(windows)]
                {
                    pythonpath = format!("{pythonpath};{existing}");
                }
                #[cfg(not(windows))]
                {
                    pythonpath = format!("{pythonpath}:{existing}");
                }
            }
        }

        let mut c = Command::new(&py);
        c.args(["-m", "uvicorn", "assistant.main:app", "--app-dir"])
            .arg(&src_dir)
            .args(["--host", "127.0.0.1", "--port"])
            .arg(port.to_string())
            .current_dir(&backend)
            .env("HUSK_HOME", &home)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONPATH", &pythonpath)
            .env(
                "DATABASE_URL",
                format!("sqlite:///{}", home.join("data").join("husk.db").display()),
            )
            .env("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
            .stdout(Stdio::from(log.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(log));

        // Load any .env values into the child (uvicorn / app may read them).
        if let Ok(env_text) = fs::read_to_string(config::env_path()) {
            for line in env_text.lines() {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') {
                    continue;
                }
                if let Some((k, v)) = line.split_once('=') {
                    let key = k.trim();
                    let val = v.trim().trim_matches('"').trim_matches('\'');
                    if !key.is_empty() {
                        c.env(key, val);
                    }
                }
            }
        }

        self.backend = Some(match c.spawn() {
            Ok(child) => child,
            Err(e) => {
                self.backend_url.clear();
                return Err(format!("Backend launch failed: {e}"));
            }
        });

        if let Some(child) = self.backend.as_ref() {
            BACKEND_PID.store(child.id(), Ordering::SeqCst);
        }

        // Quick sanity: if the process dies within ~1.5s, surface the log tail.
        thread::sleep(Duration::from_millis(1500));
        if let Some(child) = self.backend.as_mut() {
            if let Ok(Some(status)) = child.try_wait() {
                let tail = Self::tail_log(&log_path, 20);
                self.backend_url.clear();
                self.backend = None;
                BACKEND_PID.store(0, Ordering::SeqCst);
                return Err(format!(
                    "Backend exited immediately ({status}).\n\
                     Log: {}\n\
                     ---- last lines ----\n{tail}",
                    log_path.display()
                ));
            }
        }

        Ok(())
    }

    /// Wait for the background backend when a feature actually needs the API.
    pub fn wait_backend_ready(&mut self, timeout: Duration) -> Result<(), String> {
        let until = Instant::now() + timeout;
        let log_path = config::home().join("logs/backend.log");
        while Instant::now() < until {
            if !self.backend_url.is_empty() && Self::healthy(&self.backend_url) {
                return Ok(());
            }
            if let Some(child) = self.backend.as_mut() {
                if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                    let tail = Self::tail_log(&log_path, 25);
                    return Err(format!(
                        "Backend exited before becoming healthy ({status}).\n\
                         Check {}.\n\
                         ---- last lines ----\n{tail}",
                        log_path.display()
                    ));
                }
            }
            thread::sleep(Duration::from_millis(400));
        }
        let tail = Self::tail_log(&log_path, 25);
        Err(format!(
            "Backend is still not healthy after {}s.\n\
             Check {}.\n\
             ---- last lines ----\n{tail}",
            timeout.as_secs(),
            log_path.display()
        ))
    }

    pub fn start_ui(&mut self) -> Result<(), String> {
        if self.backend_url.is_empty() {
            self.start_backend()?;
        }
        self.wait_backend_ready(Duration::from_secs(45))?;

        if self
            .frontend
            .as_mut()
            .and_then(|p| p.try_wait().ok().flatten())
            .is_none()
            && !self.frontend_url.is_empty()
        {
            return Ok(());
        }

        let ui = Self::project_dir("ui").ok_or_else(|| {
            format!(
                "Could not find the ui/ frontend directory under {} or next to the binary.",
                config::home().display()
            )
        })?;

        let node_ok = Command::new("node")
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if !node_ok {
            return Err("Node.js 18+ is required for /ui. Install from https://nodejs.org".into());
        }

        let modules = ui.join("node_modules");
        if !modules.exists() {
            let status = npm(&ui, &["install", "--no-audit", "--no-fund"])?;
            if !status.success() {
                return Err("npm install failed — check network and Node version".into());
            }
        }

        let port = Self::port_free(5173);
        self.frontend_url = format!("http://127.0.0.1:{port}");
        let home = config::home();
        let log_path = home.join("logs/frontend.log");
        let log = File::create(&log_path).map_err(|e| e.to_string())?;

        let mut c = {
            let mut x = npm_command(&["run", "dev", "--", "--host", "127.0.0.1", "--strictPort"]);
            x.arg("--port").arg(port.to_string());
            x
        };
        c.current_dir(&ui)
            .env("HUSK_HOME", &home)
            .env(
                "VITE_API_BASE_URL",
                format!("{}/api/v1", self.backend_url.trim_end_matches('/')),
            )
            .env("CORS_ORIGINS", &self.frontend_url)
            .env("PUBLIC_BASE_URL", &self.backend_url)
            .env("FRONTEND_URL", &self.frontend_url)
            .stdout(Stdio::from(log.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(log));

        self.frontend = Some(
            c.spawn()
                .map_err(|e| format!("Frontend launch failed: {e}"))?,
        );

        if let Some(child) = self.frontend.as_ref() {
            FRONTEND_PID.store(child.id(), Ordering::SeqCst);
        }

        thread::sleep(Duration::from_secs(2));
        if self
            .frontend
            .as_mut()
            .and_then(|p| p.try_wait().ok().flatten())
            .is_some()
        {
            let tail = Self::tail_log(&log_path, 20);
            return Err(format!(
                "Frontend exited early. Check {}.\n---- last lines ----\n{tail}",
                log_path.display()
            ));
        }
        Ok(())
    }

    /// Stop the web UI only. Returns true if it was running.
    pub fn stop_ui(&mut self) -> bool {
        let was_running = self.frontend.is_some();
        stop_child(&mut self.frontend);
        FRONTEND_PID.store(0, Ordering::SeqCst);
        self.frontend_url.clear();
        was_running
    }

    /// Stop everything Husk started. A backend that was already running before Husk launched is
    /// left alone (Husk does not own it) and reported as such.
    pub fn stop_all(&mut self) -> StopReport {
        let ui_stopped = self.stop_ui();
        let backend_stopped = self.backend.is_some();
        stop_child(&mut self.backend);
        BACKEND_PID.store(0, Ordering::SeqCst);
        let backend_left_running = self.backend_external && !self.backend_url.is_empty();
        self.backend_url.clear();
        StopReport { ui_stopped, backend_stopped, backend_left_running }
    }
}

impl Drop for Services {
    fn drop(&mut self) {
        let _ = self.stop_all();
    }
}

#[cfg(windows)]
fn stop_child(child: &mut Option<Child>) {
    if let Some(mut p) = child.take() {
        kill_tree(p.id());
        let _ = p.kill(); // fallback if taskkill is unavailable
        let _ = p.wait();
    }
}

#[cfg(not(windows))]
fn stop_child(child: &mut Option<Child>) {
    if let Some(mut p) = child.take() {
        let _ = p.kill();
        let _ = p.wait();
    }
}

#[cfg(windows)]
fn npm_command(args: &[&str]) -> Command {
    let mut c = Command::new("cmd");
    c.args(["/C", "npm"]).args(args);
    c
}

#[cfg(not(windows))]
fn npm_command(args: &[&str]) -> Command {
    let mut c = Command::new("npm");
    c.args(args);
    c
}

fn npm(dir: &Path, args: &[&str]) -> Result<std::process::ExitStatus, String> {
    npm_command(args)
        .current_dir(dir)
        .status()
        .map_err(|e| format!("npm could not start: {e}"))
}
