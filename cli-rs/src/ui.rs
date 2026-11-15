//! Terminal presentation helpers (std-only ANSI — zero external crates).
//! Visual layout mirrors `husk.py` (Rich): two-column header, accent #2fa6f5, rounded panels.

use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

pub const ACCENT: &str = "\x1b[38;2;47;166;245m";
pub const BOLD: &str = "\x1b[1m";
pub const DIM: &str = "\x1b[38;5;245m";
pub const GREEN: &str = "\x1b[32m";
pub const RED: &str = "\x1b[31m";
pub const YELLOW: &str = "\x1b[33m";
pub const WHITE: &str = "\x1b[97m";
pub const RESET: &str = "\x1b[0m";

const LOGO: &[&str] = &[
    "██╗  ██╗██╗   ██╗███████╗██╗  ██╗",
    "██║  ██║██║   ██║██╔════╝██║ ██╔╝",
    "███████║██║   ██║███████╗█████╔╝ ",
    "██╔══██║██║   ██║╚════██║██╔═██╗ ",
    "██║  ██║╚██████╔╝███████║██║  ██╗",
    "╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝",
];
const LOGO_WIDTH: usize = 34;

// ---------------------------------------------------------------------------
// Console setup
// ---------------------------------------------------------------------------

#[cfg(windows)]
mod win {
    use std::ffi::c_void;

    type Handle = *mut c_void;

    #[repr(C)]
    #[allow(dead_code)]
    struct ConsoleInfo {
        size: [i16; 2],
        cursor: [i16; 2],
        attrs: u16,
        window: [i16; 4],
        max: [i16; 2],
    }

    extern "system" {
        fn GetStdHandle(id: u32) -> Handle;
        fn GetConsoleMode(h: Handle, mode: *mut u32) -> i32;
        fn SetConsoleMode(h: Handle, mode: u32) -> i32;
        fn SetConsoleOutputCP(cp: u32) -> i32;
        fn GetConsoleScreenBufferInfo(h: Handle, info: *mut ConsoleInfo) -> i32;
    }

    const STD_OUTPUT_HANDLE: u32 = 0xFFFF_FFF5;
    const ENABLE_VIRTUAL_TERMINAL_PROCESSING: u32 = 0x0004;

    pub fn init() {
        unsafe {
            SetConsoleOutputCP(65001);
            let h = GetStdHandle(STD_OUTPUT_HANDLE);
            let mut mode: u32 = 0;
            if GetConsoleMode(h, &mut mode) != 0 {
                SetConsoleMode(h, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING);
            }
        }
    }

    pub fn width() -> Option<usize> {
        unsafe {
            let h = GetStdHandle(STD_OUTPUT_HANDLE);
            let mut info = ConsoleInfo {
                size: [0; 2],
                cursor: [0; 2],
                attrs: 0,
                window: [0; 4],
                max: [0; 2],
            };
            if GetConsoleScreenBufferInfo(h, &mut info) != 0 {
                let w = info.window[2] as i32 - info.window[0] as i32 + 1;
                if w > 0 {
                    return Some(w as usize);
                }
            }
        }
        None
    }
}

pub fn init_terminal() {
    #[cfg(windows)]
    win::init();
}

pub fn term_width() -> usize {
    #[cfg(windows)]
    {
        if let Some(w) = win::width() {
            return w.max(40);
        }
    }
    if let Some(w) = std::env::var("COLUMNS")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
    {
        if w >= 40 {
            return w;
        }
    }
    #[cfg(not(windows))]
    {
        if let Ok(out) = std::process::Command::new("tput").arg("cols").output() {
            if let Ok(w) = String::from_utf8_lossy(&out.stdout).trim().parse::<usize>() {
                if w >= 40 {
                    return w;
                }
            }
        }
    }
    100
}

pub fn panel_width() -> usize {
    term_width().saturating_sub(1).max(60)
}

pub fn clear_screen() {
    print!("\x1b[2J\x1b[H");
    let _ = io::stdout().flush();
}

// ---------------------------------------------------------------------------
// Panels and text helpers
// ---------------------------------------------------------------------------

fn hline(width: usize, left: &str, mid: &str, right: &str) -> String {
    format!("{left}{}{right}", mid.repeat(width.saturating_sub(2)))
}

fn strip_ansi(s: &str) -> String {
    let mut out = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\x1b' {
            if chars.peek() == Some(&'[') {
                chars.next();
                while let Some(ch) = chars.next() {
                    if ch.is_ascii_alphabetic() {
                        break;
                    }
                }
            }
        } else {
            out.push(c);
        }
    }
    out
}

fn visible_len(s: &str) -> usize {
    strip_ansi(s).chars().count()
}

fn center_in(s: &str, width: usize) -> String {
    let len = visible_len(s);
    if len >= width {
        return s.to_string();
    }
    let left = (width - len) / 2;
    let right = width - len - left;
    format!("{}{}{}", " ".repeat(left), s, " ".repeat(right))
}

fn pad_right(s: &str, width: usize) -> String {
    let len = visible_len(s);
    if len >= width {
        s.to_string()
    } else {
        format!("{}{}", s, " ".repeat(width - len))
    }
}

pub fn panel(title: &str, body_lines: &[String], width: usize) {
    let inner = width.saturating_sub(2);
    let title_w = visible_len(title);
    let right_pad = inner.saturating_sub(title_w + 3);
    println!("{ACCENT}╭─ {title} {}╮{RESET}", "─".repeat(right_pad));
    for line in body_lines {
        let len = visible_len(line);
        let space = inner.saturating_sub(len);
        println!("{ACCENT}│{RESET}{}{}{ACCENT}│{RESET}", line, " ".repeat(space));
    }
    println!("{ACCENT}{}{RESET}", hline(width, "╰", "─", "╯"));
}

pub fn wrap(text: &str, width: usize) -> Vec<String> {
    let mut out = Vec::new();
    for raw in text.lines() {
        let verbatim =
            raw.starts_with("    ") || raw.starts_with('\t') || raw.trim_start().starts_with("```");
        if verbatim || raw.chars().count() <= width {
            out.push(raw.to_string());
            continue;
        }
        let mut cur = String::new();
        let mut cur_len = 0usize;
        for word in raw.split_whitespace() {
            let wl = word.chars().count();
            if cur_len > 0 && cur_len + 1 + wl > width {
                out.push(std::mem::take(&mut cur));
                cur_len = 0;
            }
            if cur_len > 0 {
                cur.push(' ');
                cur_len += 1;
            }
            cur.push_str(word);
            cur_len += wl;
        }
        if !cur.is_empty() {
            out.push(cur);
        }
    }
    out
}

fn dot(on: bool) -> String {
    if on {
        format!("{GREEN}●{RESET}")
    } else {
        format!("{RED}●{RESET}")
    }
}

// ---------------------------------------------------------------------------
// Header (2-column layout matching husk.py)
// ---------------------------------------------------------------------------

pub struct HeaderInfo<'a> {
    pub version: &'a str,
    pub user: &'a str,
    pub provider: &'a str,
    pub model: &'a str,
    pub cwd: &'a str,
    pub llm_ok: bool,
    pub oauth_ok: bool,
}

pub fn header(h: &HeaderInfo) {
    let w = panel_width().max(76);
    let inner = w.saturating_sub(2);
    let left_w = (inner.saturating_sub(1)) / 2;
    let right_w = inner.saturating_sub(left_w + 1);

    let sub_model = if h.llm_ok {
        if h.provider.is_empty() {
            h.model.to_string()
        } else {
            format!("{} - {}", h.model, h.provider)
        }
    } else {
        "not configured - run /llm".to_string()
    };

    let status_llm = if h.llm_ok {
        if h.provider.is_empty() {
            h.model.to_string()
        } else {
            format!("{} ({})", h.provider, h.model)
        }
    } else {
        "Not configured (/llm)".to_string()
    };

    let mut left_lines: Vec<String> = vec![
        String::new(),
        center_in(&format!("{BOLD}{WHITE}Welcome back, {}!{RESET}", h.user), left_w),
        String::new(),
    ];
    for line in LOGO {
        left_lines.push(center_in(&format!("{ACCENT}{line}{RESET}"), left_w));
    }
    left_lines.push(center_in(&format!("{BOLD}{DIM}Local AI Assistant{RESET}"), left_w));
    left_lines.push(String::new());
    left_lines.push(center_in(&format!("{DIM}{sub_model}{RESET}"), left_w));
    left_lines.push(center_in(&format!("{DIM}{}{RESET}", h.cwd), left_w));
    left_lines.push(String::new());

    let right_lines: Vec<String> = vec![
        String::new(),
        format!("  {BOLD}{ACCENT}Tips for getting started{RESET}"),
        format!("  {WHITE}Type a message to chat, or /help{RESET}"),
        format!("  {WHITE}'/ui' command to start Web UI.{RESET}"),
        String::new(),
        String::new(),
        format!("  {BOLD}{ACCENT}Quick status{RESET}"),
        format!("  {} {WHITE}LLM    {status_llm}{RESET}", dot(h.llm_ok)),
        format!(
            "  {} {WHITE}OAuth  {}{RESET}",
            dot(h.oauth_ok),
            if h.oauth_ok { "Configured" } else { "Not configured" }
        ),
        format!("  {} {WHITE}Store  Local SQLite{RESET}", dot(true)),
        String::new(),
        String::new(),
    ];

    let rows = left_lines.len().max(right_lines.len());
    let mut body = Vec::with_capacity(rows);
    for i in 0..rows {
        let l = left_lines.get(i).map(String::as_str).unwrap_or("");
        let r = right_lines.get(i).map(String::as_str).unwrap_or("");
        let sep = if i == 0 || i + 1 == rows {
            " ".to_string()
        } else {
            format!("{ACCENT}│{RESET}")
        };
        body.push(format!("{}{}{}", pad_right(l, left_w), sep, pad_right(r, right_w)));
    }

    let title = format!("{BOLD}Husk v{}{RESET}{ACCENT}", h.version);
    panel(&title, &body, w);
    println!();
    println!("  {DIM}/help for commands - Ctrl+C to exit{RESET}");
    println!();
}

// ---------------------------------------------------------------------------
// Input / output
// ---------------------------------------------------------------------------

pub fn prompt_line() -> Option<String> {
    let w = panel_width();
    println!("{DIM}{}{RESET}", "-".repeat(w));
    print!("{BOLD}{ACCENT}❯{RESET} ");
    let _ = io::stdout().flush();
    let mut line = String::new();
    match io::stdin().read_line(&mut line) {
        Ok(0) | Err(_) => {
            println!();
            None
        }
        Ok(_) => {
            println!("{DIM}{}{RESET}", "-".repeat(w));
            Some(line.trim().to_string())
        }
    }
}

pub fn ok(msg: &str) {
    println!("{GREEN}+{RESET} {msg}");
}

pub fn warn(msg: &str) {
    println!("{YELLOW}!{RESET} {msg}");
}

pub fn err(msg: &str) {
    println!("{RED}x{RESET} {msg}");
}

pub fn dim(msg: &str) {
    println!("{DIM}{msg}{RESET}");
}

pub fn print_reply(reply: &str) {
    let width = term_width().saturating_sub(5).max(40);
    println!();
    println!("  {BOLD}{ACCENT}Husk{RESET}");
    for line in wrap(reply.trim_end(), width) {
        println!("  {line}");
    }
}

pub struct Spinner {
    stop: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
}

impl Spinner {
    pub fn start(label: &str) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&stop);
        let label = label.to_string();
        let handle = thread::spawn(move || {
            let frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
            let started = Instant::now();
            let mut i = 0usize;
            while !flag.load(Ordering::Relaxed) {
                print!(
                    "\r{ACCENT}{}{RESET} {DIM}{} ({}s){RESET}  ",
                    frames[i % frames.len()],
                    label,
                    started.elapsed().as_secs()
                );
                let _ = io::stdout().flush();
                i += 1;
                thread::sleep(Duration::from_millis(90));
            }
            print!("\r\x1b[2K");
            let _ = io::stdout().flush();
        });
        Self {
            stop,
            handle: Some(handle),
        }
    }

    pub fn finish(mut self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}

pub fn info_panel(title: &str, lines: &[&str]) {
    let w = panel_width();
    let mut body: Vec<String> = Vec::with_capacity(lines.len() + 2);
    body.push(String::new());
    for s in lines {
        body.push(format!("  {s}"));
    }
    body.push(String::new());
    let t = format!("{BOLD}{title}{RESET}{ACCENT}");
    panel(&t, &body, w);
}

pub fn help_table() {
    let rows = [
        ("/help", "Show this help"),
        ("/chat <msg>", "Send a message (plain text works too)"),
        ("/new", "Start a fresh conversation"),
        ("/llm", "Configure the LLM (synced to the shared backend DB)"),
        ("/oauth", "Configure Google & Microsoft OAuth credentials"),
        ("/sync", "Pull the default model from the backend DB"),
        ("/ui", "Start the web UI and open it in your browser"),
        ("/cli", "Stop the web UI only (backend stays warm)"),
        ("/status", "Show model and service status"),
        ("/clear", "Clear the screen"),
        ("/version", "Show the Husk version & check GitHub tag"),
        ("/exit", "Stop services and quit (also /quit, /q)"),
    ];
    let w = panel_width();
    let mut body = Vec::new();
    body.push(String::new());
    for (cmd, desc) in rows {
        body.push(format!("  {BOLD}{ACCENT}{cmd:<13}{RESET} {desc}"));
    }
    body.push(String::new());
    let t = format!("{BOLD}Commands{RESET}{ACCENT}");
    panel(&t, &body, w);
}

pub fn status_table(provider: &str, endpoint: &str, model: &str, api: &str, ui: &str, conv: &str) {
    let show = |v: &str| {
        if v.is_empty() {
            "—".to_string()
        } else {
            v.to_string()
        }
    };
    let w = panel_width();
    let body = vec![
        String::new(),
        format!("  {DIM}Provider    {RESET} {}", show(provider)),
        format!("  {DIM}Endpoint    {RESET} {}", show(endpoint)),
        format!("  {DIM}Model       {RESET} {}", show(model)),
        format!("  {DIM}API         {RESET} {api}"),
        format!("  {DIM}Web UI      {RESET} {ui}"),
        format!("  {DIM}Conversation{RESET} {conv}"),
        String::new(),
    ];
    let t = format!("{BOLD}Status{RESET}{ACCENT}");
    panel(&t, &body, w);
}

pub fn ask(label: &str, default: &str) -> String {
    if default.is_empty() {
        print!("{ACCENT}?{RESET} {label} {DIM}(skip){RESET}: ");
    } else {
        print!("{ACCENT}?{RESET} {label} {DIM}[{default}]{RESET}: ");
    }
    let _ = io::stdout().flush();
    let mut value = String::new();
    if io::stdin().read_line(&mut value).is_err() {
        return default.to_string();
    }
    let value = value.trim();
    if value.is_empty() {
        default.to_string()
    } else {
        value.to_string()
    }
}

pub fn goodbye() {
    println!("{DIM}Goodbye!{RESET}");
}
