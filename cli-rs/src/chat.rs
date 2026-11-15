use std::{
    collections::HashMap,
    env,
    io::Write,
    process::{Command, Stdio},
};
use crate::config;

fn json_escape(s: &str) -> String {
    let mut out = String::new();
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push(' '),
            c => out.push(c),
        }
    }
    out
}

fn curl_json(method: &str, url: &str, body: Option<&str>, timeout_secs: &str) -> Result<String, String> {
    let mut cmd = Command::new("curl");
    cmd.args([
        "-sS",
        "--fail-with-body",
        "--max-time",
        timeout_secs,
        "-X",
        method,
        url,
        "-H",
        "Content-Type: application/json",
        "-H",
        "User-Agent: Husk-CLI",
    ]);
    if body.is_some() {
        cmd.args(["--data-binary", "@-"]).stdin(Stdio::piped());
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Could not start curl (ensure curl is on PATH): {e}"))?;
    if let Some(b) = body {
        child
            .stdin
            .take()
            .ok_or("Could not open curl stdin")?
            .write_all(b.as_bytes())
            .map_err(|e| e.to_string())?;
    }
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    if !output.status.success() {
        return Err(if stderr.is_empty() {
            stdout
        } else {
            format!("{stderr}{stdout}")
        });
    }
    Ok(stdout)
}

/// Fetch the latest GitHub release tag (e.g. "v1.0.1") with a fast 2s timeout.
pub fn fetch_latest_github_tag() -> Option<String> {
    let repo = env::var("HUSK_GITHUB_REPO").unwrap_or_else(|_| "nikhil-b-2003/LocalHusk".into());
    let url = format!("https://api.github.com/repos/{}/releases/latest", repo.trim());
    let raw = curl_json("GET", &url, None, "2").ok()?;
    extract_json_string(&raw, "tag_name")
}

fn backend_healthy(base: &str) -> bool {
    let url = format!("{}/api/v1/health", base.trim_end_matches('/'));
    curl_json("GET", &url, None, "2")
        .map(|s| s.contains("\"status\""))
        .unwrap_or(false)
}

pub fn sync_from_backend(cfg: &mut HashMap<String, String>, backend_base: &str) -> Result<(), String> {
    if backend_base.is_empty() || !backend_healthy(backend_base) {
        return Err("Backend not ready".into());
    }
    let url = format!("{}/api/v1/llm/models", backend_base.trim_end_matches('/'));
    let raw = curl_json("GET", &url, None, "10")?;
    let default = raw
        .find("\"is_default\": true")
        .or_else(|| raw.find("\"is_default\":true"))
        .and_then(|pos| {
            let window = &raw[safe_start(&raw, pos.saturating_sub(400))..pos];
            let model = extract_json_string(window, "model")
                .or_else(|| extract_json_string(&raw[pos..], "model"));
            let base_url = extract_json_string(window, "base_url");
            let kind = extract_json_string(window, "kind");
            let name = extract_json_string(window, "name");
            Some((model, base_url, kind, name))
        });
    if let Some((model, base_url, kind, name)) = default {
        if let Some(m) = model {
            cfg.insert("LLM_MODEL".into(), m);
        }
        if let Some(k) = kind {
            cfg.insert("LLM_PROVIDER".into(), k);
        }
        if let Some(n) = name {
            cfg.insert("LLM_NAME".into(), n);
        }
        if let Some(b) = base_url {
            if !b.is_empty() {
                cfg.insert("LLM_ENDPOINT".into(), b);
            }
        }
        return Ok(());
    }
    if let Some(m) = extract_json_string(&raw, "model") {
        cfg.insert("LLM_MODEL".into(), m);
        return Ok(());
    }
    Err("No models configured in backend yet".into())
}

pub fn push_to_backend(cfg: &HashMap<String, String>, backend_base: &str) -> Result<String, String> {
    if backend_base.is_empty() || !backend_healthy(backend_base) {
        return Err("Backend not ready — config saved locally only".into());
    }
    let base = backend_base.trim_end_matches('/');
    let kind = map_provider_kind(config::get(cfg, "LLM_PROVIDER"));
    let model = config::get(cfg, "LLM_MODEL");
    let endpoint = config::get(cfg, "LLM_ENDPOINT");
    let key = config::get(cfg, "LLM_API_KEY");
    let name = if config::get(cfg, "LLM_NAME").is_empty() {
        format!("{} (CLI)", config::get(cfg, "LLM_PROVIDER"))
    } else {
        config::get(cfg, "LLM_NAME").to_string()
    };

    let list = curl_json("GET", &format!("{base}/api/v1/llm/models"), None, "10").unwrap_or_default();
    let body = format!(
        "{{\"name\":\"{}\",\"kind\":\"{}\",\"base_url\":{},\"model\":\"{}\",\"api_key\":{},\"is_default\":true}}",
        json_escape(&name),
        json_escape(kind),
        if endpoint.is_empty() {
            "null".into()
        } else {
            format!("\"{}\"", json_escape(endpoint))
        },
        json_escape(model),
        if key.is_empty() {
            "null".into()
        } else {
            format!("\"{}\"", json_escape(key))
        },
    );

    if let Some(id) = extract_default_id(&list) {
        let url = format!("{base}/api/v1/llm/models/{id}");
        let _ = curl_json("PUT", &url, Some(&body), "10")?;
        let _ = curl_json(
            "POST",
            &format!("{base}/api/v1/llm/models/{id}/default"),
            Some("{}"),
            "10",
        );
        return Ok(format!("Updated shared model in backend (id {id})"));
    }
    let created = curl_json("POST", &format!("{base}/api/v1/llm/models"), Some(&body), "10")?;
    let id = extract_json_string(&created, "id").unwrap_or_else(|| "?".into());
    Ok(format!("Created shared model in backend (id {id})"))
}

fn map_provider_kind(provider: &str) -> &str {
    let p = provider.to_lowercase();
    if p.contains("ollama") {
        "ollama"
    } else if p.contains("anthropic") || p.contains("claude") {
        "anthropic"
    } else if p.contains("google") || p.contains("gemini") {
        "google"
    } else {
        "openai"
    }
}

fn safe_start(s: &str, idx: usize) -> usize {
    let mut i = idx;
    while i < s.len() && !s.is_char_boundary(i) {
        i += 1;
    }
    i
}

fn read_hex4(chars: &mut std::iter::Peekable<std::str::Chars<'_>>) -> Option<u32> {
    let mut v = 0u32;
    for _ in 0..4 {
        v = v * 16 + chars.next()?.to_digit(16)?;
    }
    Some(v)
}

fn extract_json_string(s: &str, key: &str) -> Option<String> {
    let marker = format!("\"{}\":", key);
    let start = s.find(&marker)? + marker.len();
    let mut chars = s[start..].chars().peekable();
    while chars.peek().map_or(false, |c| c.is_whitespace()) {
        chars.next();
    }
    if chars.next()? != '"' {
        return None;
    }
    let mut out = String::new();
    while let Some(c) = chars.next() {
        match c {
            '"' => return Some(out),
            '\\' => match chars.next()? {
                'n' => out.push('\n'),
                'r' => out.push('\r'),
                't' => out.push('\t'),
                'b' => out.push('\u{8}'),
                'f' => out.push('\u{c}'),
                'u' => {
                    let hi = read_hex4(&mut chars)?;
                    if (0xD800..0xDC00).contains(&hi) {
                        if chars.next()? == '\\' && chars.next()? == 'u' {
                            let lo = read_hex4(&mut chars)?;
                            let cp = 0x10000
                                + ((hi - 0xD800) << 10)
                                + (lo.wrapping_sub(0xDC00) & 0x3FF);
                            out.push(char::from_u32(cp).unwrap_or('\u{FFFD}'));
                        } else {
                            out.push('\u{FFFD}');
                        }
                    } else {
                        out.push(char::from_u32(hi).unwrap_or('\u{FFFD}'));
                    }
                }
                other => out.push(other),
            },
            c => out.push(c),
        }
    }
    None
}

fn extract_default_id(list: &str) -> Option<String> {
    let pos = list
        .find("\"is_default\": true")
        .or_else(|| list.find("\"is_default\":true"))?;
    let window = &list[safe_start(list, pos.saturating_sub(500))..pos];
    let mut last = None;
    let mut search = window;
    while let Some(idx) = search.find("\"id\":") {
        let after = &search[idx..];
        if let Some(id) = extract_json_string(after, "id") {
            last = Some(id);
        }
        search = &search[idx + 5..];
    }
    last
}

fn extract_content(s: &str) -> Option<String> {
    if let Some(idx) = s.find("\"assistant_message\"") {
        if let Some(c) = extract_json_string(&s[idx..], "content") {
            return Some(c);
        }
    }
    extract_json_string(s, "content")
}

fn send_via_backend(
    backend_base: &str,
    conversation_id: &mut Option<String>,
    message: &str,
) -> Result<String, String> {
    let base = backend_base.trim_end_matches('/');
    if conversation_id.is_none() {
        let body = format!(
            "{{\"title\":\"{}\"}}",
            json_escape(&message.chars().take(60).collect::<String>())
        );
        let created = curl_json("POST", &format!("{base}/api/v1/conversations"), Some(&body), "30")?;
        let id = extract_json_string(&created, "id")
            .ok_or_else(|| format!("Could not create conversation: {created}"))?;
        *conversation_id = Some(id);
    }
    let cid = conversation_id.as_ref().unwrap();
    let body = format!("{{\"content\":\"{}\"}}", json_escape(message));
    let url = format!("{base}/api/v1/conversations/{cid}/messages");
    let raw = curl_json("POST", &url, Some(&body), "300")?;
    extract_content(&raw).ok_or_else(|| {
        format!(
            "Unexpected backend response: {}",
            raw.chars().take(400).collect::<String>()
        )
    })
}

fn send_direct(
    cfg: &HashMap<String, String>,
    history: &[(String, String)],
    message: &str,
) -> Result<String, String> {
    let endpoint = config::get(cfg, "LLM_ENDPOINT").trim_end_matches('/');
    if endpoint.is_empty() {
        return Err("No LLM endpoint configured — run /llm to set provider, endpoint, and model.".into());
    }
    let url = format!("{endpoint}/chat/completions");
    let mut msgs = String::from(
        "{\"role\":\"system\",\"content\":\"You are Husk, a helpful local AI assistant.\"}",
    );
    for (role, content) in history.iter() {
        msgs.push_str(&format!(
            ",{{\"role\":\"{}\",\"content\":\"{}\"}}",
            role,
            json_escape(content)
        ));
    }
    msgs.push_str(&format!(
        ",{{\"role\":\"user\",\"content\":\"{}\"}}",
        json_escape(message)
    ));
    let body = format!(
        "{{\"model\":\"{}\",\"messages\":[{}],\"stream\":false}}",
        json_escape(config::get(cfg, "LLM_MODEL")),
        msgs
    );
    let mut cmd = Command::new("curl");
    cmd.args([
        "-sS",
        "--fail-with-body",
        "--max-time",
        "300",
        "-X",
        "POST",
        &url,
        "-H",
        "Content-Type: application/json",
    ]);
    if !config::get(cfg, "LLM_API_KEY").is_empty() {
        cmd.arg("-H")
            .arg(format!("Authorization: Bearer {}", config::get(cfg, "LLM_API_KEY")));
    }
    cmd.args(["--data-binary", "@-"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Could not start curl: {e}"))?;
    child
        .stdin
        .take()
        .ok_or("Could not open curl stdin")?
        .write_all(body.as_bytes())
        .map_err(|e| e.to_string())?;
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string()
            + &String::from_utf8_lossy(&output.stdout));
    }
    let raw = String::from_utf8_lossy(&output.stdout);
    extract_content(&raw).ok_or_else(|| {
        format!(
            "Unexpected LLM response: {}",
            raw.chars().take(500).collect::<String>()
        )
    })
}

pub fn send(
    cfg: &HashMap<String, String>,
    history: &mut Vec<(String, String)>,
    message: &str,
    backend_base: &str,
    conversation_id: &mut Option<String>,
) -> Result<String, String> {
    let reply = if !backend_base.is_empty() && backend_healthy(backend_base) {
        match send_via_backend(backend_base, conversation_id, message) {
            Ok(r) => r,
            Err(_) => send_direct(cfg, history, message)?,
        }
    } else {
        send_direct(cfg, history, message)?
    };
    history.push(("user".into(), message.into()));
    history.push(("assistant".into(), reply.clone()));
    Ok(reply)
}
