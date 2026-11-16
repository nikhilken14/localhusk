mod chat;
mod config;
mod services;
mod ui;

use services::Services;
use std::{collections::HashMap, env, thread};

// Version comes from the git tag: CI sets HUSK_VERSION (e.g. "1.0.4" from tag v1.0.4) at build time.
// Local builds without it fall back to the placeholder in Cargo.toml.
const PKG_VERSION: &str = match option_env!("HUSK_VERSION") {
    Some(v) => v,
    None => env!("CARGO_PKG_VERSION"),
};

fn normalize_tag(tag: &str) -> String {
    tag.trim().trim_start_matches(['v', 'V']).to_string()
}

fn configure_llm(cfg: &mut HashMap<String, String>, services: &mut Services) {
    ui::info_panel(
        "Configure LLM",
        &["Settings are saved locally (~/.husk/.env) and synced to the shared backend DB."],
    );
    println!();
    let provider = ui::ask(
        "Provider (openai/ollama/anthropic/google)",
        config::get(cfg, "LLM_PROVIDER"),
    );
    cfg.insert("LLM_PROVIDER".into(), provider);
    let endpoint = ui::ask("Endpoint URL", config::get(cfg, "LLM_ENDPOINT"));
    cfg.insert("LLM_ENDPOINT".into(), endpoint);
    let model = ui::ask("Model", config::get(cfg, "LLM_MODEL"));
    cfg.insert("LLM_MODEL".into(), model);
    let key_default = if config::get(cfg, "LLM_API_KEY").is_empty() {
        ""
    } else {
        "configured"
    };
    let key = ui::ask("API key", key_default);
    if key != "configured" && !key.is_empty() {
        cfg.insert("LLM_API_KEY".into(), key);
    }
    match config::save(cfg) {
        Ok(()) => ui::ok(&format!("Local config saved to {}", config::env_path().display())),
        Err(e) => ui::err(&format!("Could not save config: {e}")),
    }

    if !services.backend_url.is_empty() || services.ensure_backend().is_ok() {
        match chat::push_to_backend(cfg, &services.backend_url) {
            Ok(msg) => ui::ok(&msg),
            Err(e) => ui::warn(&format!("Could not sync model to backend: {e}")),
        }
    }
}

fn configure_oauth(cfg: &mut HashMap<String, String>) {
    ui::info_panel(
        "Configure OAuth",
        &["Optional credentials for Google and Microsoft mail/calendar integrations."],
    );
    println!();
    let g_id = ui::ask("Google Client ID", config::get(cfg, "GOOGLE_CLIENT_ID"));
    cfg.insert("GOOGLE_CLIENT_ID".into(), g_id.clone());
    if !g_id.is_empty() {
        let g_sec = ui::ask("Google Client Secret", "");
        if !g_sec.is_empty() {
            cfg.insert("GOOGLE_CLIENT_SECRET".into(), g_sec);
        }
    }
    let m_id = ui::ask("Microsoft Client ID", config::get(cfg, "MICROSOFT_CLIENT_ID"));
    cfg.insert("MICROSOFT_CLIENT_ID".into(), m_id.clone());
    if !m_id.is_empty() {
        let m_sec = ui::ask("Microsoft Client Secret (optional w/ PKCE)", "");
        if !m_sec.is_empty() {
            cfg.insert("MICROSOFT_CLIENT_SECRET".into(), m_sec);
        }
        let tenant = ui::ask("Microsoft Tenant", config::get(cfg, "MICROSOFT_TENANT"));
        cfg.insert("MICROSOFT_TENANT".into(), tenant);
    }
    match config::save(cfg) {
        Ok(()) => ui::ok("OAuth credentials saved"),
        Err(e) => ui::err(&format!("Could not save credentials: {e}")),
    }
}

fn shorten(s: &str, max: usize) -> String {
    let count = s.chars().count();
    if count <= max {
        return s.to_string();
    }
    let tail: String = s.chars().skip(count - (max.saturating_sub(1))).collect();
    format!("…{tail}")
}

fn chat_turn(
    cfg: &HashMap<String, String>,
    history: &mut Vec<(String, String)>,
    message: &str,
    backend_url: &str,
    conversation_id: &mut Option<String>,
) {
    let spinner = ui::Spinner::start("Thinking...");
    let result = chat::send(cfg, history, message, backend_url, conversation_id);
    spinner.finish();
    match result {
        Ok(reply) => ui::print_reply(&reply),
        Err(e) => ui::err(&format!("Chat error: {}", e.trim())),
    }
}

fn main() {
    if let Some(arg) = env::args().nth(1) {
        match arg.as_str() {
            "--version" | "-V" | "version" => {
                println!("husk {PKG_VERSION}");
                return;
            }
            "--help" | "-h" => {
                println!("husk {PKG_VERSION} - LocalHusk local AI assistant\n\nUsage: husk [--version | --help]\n\nRun `husk` with no arguments to start the interactive CLI (type /help inside).");
                return;
            }
            _ => {}
        }
    }

    ui::init_terminal();
    services::install_ctrl_handler();

    let mut cfg = config::load();
    let _ = std::fs::create_dir_all(config::home().join("logs"));

    // Reuse an already-running backend silently if present, otherwise stay fast and lazy like husk.py.
    let mut services = Services::new();
    if Services::healthy("http://127.0.0.1:8000") {
        // ensure_backend marks it as external when we did not start the child.
        let _ = services.ensure_backend();
        let _ = chat::sync_from_backend(&mut cfg, &services.backend_url);
    }

    // Check GitHub release tag in background so startup is instantaneous.
    let tag_handle = thread::spawn(|| chat::fetch_latest_github_tag());

    let user = env::var("USER")
        .or_else(|_| env::var("USERNAME"))
        .unwrap_or_else(|_| "Developer".into());
    let cwd = env::current_dir()
        .map(|p| {
            let s = p.display().to_string();
            if let Ok(home) = env::var("HOME").or_else(|_| env::var("USERPROFILE")) {
                if !home.is_empty() && s.starts_with(&home) {
                    return format!("~{}", &s[home.len()..]);
                }
            }
            s
        })
        .unwrap_or_else(|_| ".".into());

    let llm_ok = !config::get(&cfg, "LLM_MODEL").is_empty()
        && !config::get(&cfg, "LLM_ENDPOINT").is_empty();
    let oauth_ok = !config::get(&cfg, "GOOGLE_CLIENT_ID").is_empty()
        || !config::get(&cfg, "MICROSOFT_CLIENT_ID").is_empty();

    ui::clear_screen();
    ui::header(&ui::HeaderInfo {
        version: PKG_VERSION,
        user: &user,
        provider: config::get(&cfg, "LLM_PROVIDER"),
        model: config::get(&cfg, "LLM_MODEL"),
        cwd: &shorten(&cwd, 44),
        llm_ok,
        oauth_ok,
    });

    if let Ok(Some(latest_tag)) = tag_handle.join() {
        let latest_clean = normalize_tag(&latest_tag);
        if !latest_clean.is_empty() && latest_clean != normalize_tag(PKG_VERSION) {
            ui::warn(&format!(
                "New GitHub release available: v{latest_clean} (current: v{PKG_VERSION})"
            ));
            println!();
        }
    }

    let mut history: Vec<(String, String)> = Vec::new();
    let mut conversation_id: Option<String> = None;

    loop {
        let Some(line) = ui::prompt_line() else {
            break;
        };
        if line.is_empty() {
            continue;
        }
        let lower = line.to_lowercase();
        if matches!(lower.as_str(), "/exit" | "/quit" | "/q" | "exit" | "quit") {
            break;
        }

        let (cmd, arg) = match line.split_once(char::is_whitespace) {
            Some((c, a)) => (c.to_lowercase(), a.trim().to_string()),
            None => (lower.clone(), String::new()),
        };

        if !line.starts_with('/') {
            chat_turn(
                &cfg,
                &mut history,
                &line,
                &services.backend_url,
                &mut conversation_id,
            );
        } else {
            match cmd.as_str() {
                "/help" | "/?" => ui::help_table(),
                "/chat" => {
                    if arg.is_empty() {
                        ui::warn("Usage: /chat <message>");
                    } else {
                        chat_turn(
                            &cfg,
                            &mut history,
                            &arg,
                            &services.backend_url,
                            &mut conversation_id,
                        );
                    }
                }
                "/llm" => configure_llm(&mut cfg, &mut services),
                "/oauth" => configure_oauth(&mut cfg),
                "/sync" => {
                    let spinner = ui::Spinner::start("Syncing default model...");
                    let ready = services.ensure_backend();
                    spinner.finish();
                    match ready {
                        Ok(url) => match chat::sync_from_backend(&mut cfg, &url) {
                            Ok(()) => {
                                let _ = config::save(&cfg);
                                ui::ok(&format!(
                                    "Pulled default model: {} | {}",
                                    config::get(&cfg, "LLM_PROVIDER"),
                                    config::get(&cfg, "LLM_MODEL")
                                ));
                            }
                            Err(e) => ui::err(&format!("Sync failed: {e}")),
                        },
                        Err(e) => ui::err(&format!("Backend unavailable: {e}")),
                    }
                }
                "/ui" => {
                    let spinner = ui::Spinner::start("Starting web UI...");
                    let started = services.start_ui();
                    spinner.finish();
                    match started {
                        Ok(()) => {
                            // Single unified panel (no duplicate raw URL lines above it).
                            ui::info_panel(
                                "Husk is running",
                                &[
                                    &format!("Web UI   {}", services.frontend_url),
                                    &format!("API      {}", services.backend_url),
                                    &format!("Docs     {}/docs", services.backend_url),
                                    "",
                                    "Keep chatting here; /cli stops only the UI (backend stays warm). /exit quits everything.",
                                ],
                            );
                            services::open_url(&services.frontend_url);
                        }
                        Err(e) => ui::err(&e),
                    }
                }
                "/cli" => {
                    if services.stop_ui() {
                        ui::ok("Web UI stopped. Backend remains warm. Continuing in the terminal.");
                    } else {
                        ui::dim("Web UI isn't running. You're already in the terminal.");
                    }
                }
                "/new" => {
                    history.clear();
                    conversation_id = None;
                    ui::ok("Started a new conversation");
                }
                "/clear" | "/cls" => {
                    ui::clear_screen();
                    let llm_ok = !config::get(&cfg, "LLM_MODEL").is_empty()
                        && !config::get(&cfg, "LLM_ENDPOINT").is_empty();
                    let oauth_ok = !config::get(&cfg, "GOOGLE_CLIENT_ID").is_empty()
                        || !config::get(&cfg, "MICROSOFT_CLIENT_ID").is_empty();
                    ui::header(&ui::HeaderInfo {
                        version: PKG_VERSION,
                        user: &user,
                        provider: config::get(&cfg, "LLM_PROVIDER"),
                        model: config::get(&cfg, "LLM_MODEL"),
                        cwd: &shorten(&cwd, 44),
                        llm_ok,
                        oauth_ok,
                    });
                }
                "/version" | "/v" => {
                    let latest = chat::fetch_latest_github_tag()
                        .map(|t| format!(" (GitHub latest: v{})", normalize_tag(&t)))
                        .unwrap_or_default();
                    ui::dim(&format!("Husk v{PKG_VERSION}{latest}"));
                }
                "/status" => {
                    // Own the strings: is_*_running() take &mut self, so we must not
                    // hold a borrow of services.backend_url across the second call.
                    let api_status: String = if services.is_backend_running() {
                        services.backend_url.clone()
                    } else {
                        "off (starts on /ui)".to_string()
                    };
                    let ui_status: String = if services.is_frontend_running() {
                        services.frontend_url.clone()
                    } else {
                        "off".to_string()
                    };
                    ui::status_table(
                        config::get(&cfg, "LLM_PROVIDER"),
                        config::get(&cfg, "LLM_ENDPOINT"),
                        config::get(&cfg, "LLM_MODEL"),
                        &api_status,
                        &ui_status,
                        conversation_id.as_deref().unwrap_or("(new)"),
                    );
                }
                _ => ui::err(&format!("Unknown command {cmd}. Try /help")),
            }
        }
        println!();
    }

    ui::dim("Stopping services...");
    let report = services.stop_all();
    if report.ui_stopped {
        ui::ok("Web UI stopped");
    }
    if report.backend_stopped {
        ui::ok("Backend stopped");
    }
    if report.backend_left_running {
        ui::warn("A backend that was already running was left running (Husk did not start it).");
    }
    ui::goodbye();
}