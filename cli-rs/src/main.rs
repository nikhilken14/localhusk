mod chat;
mod config;
mod services;
mod ui;

use services::Services;
use std::{collections::HashMap, env, time::Duration};

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn configure(cfg: &mut HashMap<String, String>, backend_base: &str) {
    ui::info_panel("Configure LLM", &["Settings are saved locally and pushed to the shared backend model DB."]);
    println!();
    let provider = ui::ask("Provider (openai/ollama/anthropic/google)", config::get(cfg, "LLM_PROVIDER"));
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
    if !backend_base.is_empty() {
        match chat::push_to_backend(cfg, backend_base) {
            Ok(msg) => ui::ok(&msg),
            Err(e) => ui::warn(&format!("Could not sync model to backend: {e}")),
        }
    }
}

/// Shorten a long path from the left so it cannot overflow the header panel.
fn shorten(s: &str, max: usize) -> String {
    let count = s.chars().count();
    if count <= max {
        return s.to_string();
    }
    let tail: String = s.chars().skip(count - (max.saturating_sub(1))).collect();
    format!("…{tail}")
}

/// One chat round-trip with a spinner while the model thinks.
fn chat_turn(
    cfg: &HashMap<String, String>,
    history: &mut Vec<(String, String)>,
    message: &str,
    backend_url: &str,
    conversation_id: &mut Option<String>,
) {
    let spinner = ui::Spinner::start("thinking");
    let result = chat::send(cfg, history, message, backend_url, conversation_id);
    spinner.finish();
    match result {
        Ok(reply) => ui::print_reply(&reply),
        Err(e) => ui::err(&format!("Chat error: {}", e.trim())),
    }
}

fn main() {
    ui::init_terminal();
    services::install_ctrl_handler();

    let mut cfg = config::load();
    let _ = std::fs::create_dir_all(config::home().join("logs"));

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

    // Start the backend and wait (bounded) for it to answer, with a spinner instead of a dead pause.
    let mut services = Services::new();
    let mut startup_note: Option<String> = None;
    let spinner = ui::Spinner::start("starting backend");
    let backend_ready = match services.start_backend() {
        Ok(()) => match services.wait_backend_ready(Duration::from_secs(20)) {
            Ok(()) => true,
            Err(e) => {
                startup_note = Some(e);
                false
            }
        },
        Err(e) => {
            startup_note = Some(format!("Backend could not be launched: {e}"));
            false
        }
    };
    if backend_ready {
        if chat::sync_from_backend(&mut cfg, &services.backend_url).is_err() {
            let _ = chat::push_to_backend(&cfg, &services.backend_url);
        }
    }
    spinner.finish();

    let llm_ok = !config::get(&cfg, "LLM_MODEL").is_empty() && !config::get(&cfg, "LLM_ENDPOINT").is_empty();
    let oauth_ok = !config::get(&cfg, "GOOGLE_CLIENT_ID").is_empty()
        || !config::get(&cfg, "MICROSOFT_CLIENT_ID").is_empty();

    ui::header(&ui::HeaderInfo {
        version: VERSION,
        user: &user,
        provider: config::get(&cfg, "LLM_PROVIDER"),
        model: config::get(&cfg, "LLM_MODEL"),
        cwd: &shorten(&cwd, 60),
        llm_ok,
        oauth_ok,
        api_ok: backend_ready,
    });

    if let Some(note) = startup_note {
        ui::warn(&note);
        println!();
    }
    if config::get(&cfg, "LLM_ENDPOINT").is_empty() {
        ui::warn("No LLM endpoint yet — run /llm to configure.");
        println!();
    }

    let mut history: Vec<(String, String)> = Vec::new();
    let mut conversation_id: Option<String> = None;

    loop {
        // EOF (Ctrl+Z / Ctrl+D) ends the session just like /exit.
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

        // Split "/cmd rest of line" into the command and its argument.
        let (cmd, arg) = match line.split_once(char::is_whitespace) {
            Some((c, a)) => (c.to_lowercase(), a.trim().to_string()),
            None => (lower.clone(), String::new()),
        };

        if !line.starts_with('/') {
            chat_turn(&cfg, &mut history, &line, &services.backend_url, &mut conversation_id);
        } else {
            match cmd.as_str() {
                "/help" | "/?" => ui::help_table(),
                "/chat" => {
                    if arg.is_empty() {
                        ui::warn("Usage: /chat <message>");
                    } else {
                        chat_turn(&cfg, &mut history, &arg, &services.backend_url, &mut conversation_id);
                    }
                }
                "/llm" => configure(&mut cfg, &services.backend_url),
                "/sync" => match chat::sync_from_backend(&mut cfg, &services.backend_url) {
                    Ok(()) => ui::ok(&format!(
                        "Pulled default model: {} | {}",
                        config::get(&cfg, "LLM_PROVIDER"),
                        config::get(&cfg, "LLM_MODEL")
                    )),
                    Err(e) => ui::err(&format!("Sync failed: {e}")),
                },
                "/ui" => {
                    let spinner = ui::Spinner::start("starting web UI");
                    let started = services.start_ui();
                    spinner.finish();
                    match started {
                        Ok(()) => {
                            ui::ok("Web UI started");
                            ui::info_panel(
                                "Husk is running",
                                &[
                                    &format!("Web UI  {}", services.frontend_url),
                                    &format!("API     {}", services.backend_url),
                                    &format!("Docs    {}/docs", services.backend_url),
                                ],
                            );
                            services::open_url(&services.frontend_url);
                        }
                        Err(e) => ui::err(&e),
                    }
                }
                "/cli" => {
                    if services.stop_ui() {
                        ui::ok("Web UI stopped. Continuing in the terminal.");
                    } else {
                        ui::dim("The web UI is not running.");
                    }
                }
                "/new" => {
                    history.clear();
                    conversation_id = None;
                    ui::ok("Started a new conversation");
                }
                "/clear" | "/cls" => ui::clear_screen(),
                "/version" | "/v" => ui::dim(&format!("Husk v{VERSION}")),
                "/status" => ui::status_table(
                    config::get(&cfg, "LLM_PROVIDER"),
                    config::get(&cfg, "LLM_ENDPOINT"),
                    config::get(&cfg, "LLM_MODEL"),
                    if services.backend_url.is_empty() { "stopped" } else { &services.backend_url },
                    if services.frontend_url.is_empty() { "stopped" } else { &services.frontend_url },
                    conversation_id.as_deref().unwrap_or("(new)"),
                ),
                _ => ui::err(&format!("Unknown command {cmd}. Try /help")),
            }
        }
        println!();
    }

    // Shut down and say exactly what happened, so /exit never looks like it silently did nothing.
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
