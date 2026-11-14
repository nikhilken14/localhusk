# Security Policy

LocalHusk is designed to run **locally**. The backend binds to `127.0.0.1` by default and does not expose a public interface unless you deliberately reconfigure it.

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a vulnerability

Please open a **private** security advisory on GitHub, or contact the maintainers privately.  
Do **not** file public issues for undisclosed vulnerabilities.

## Threat model (summary)

- **In scope**: secrets leakage via logs, SSRF via MCP/HTTP tools, unauthorized agent actions, accidental exposure of the local API.
- **Out of scope**: physical access to the machine, compromised OS keyring, malicious local processes with the same user privileges.

## Design controls

### Network

- Default bind address: `127.0.0.1` (see `Settings.host`).
- `allowed_hosts` and CORS origins default to localhost only.
- MCP HTTP client:
  - Rejects non-HTTP(S) schemes.
  - Resolves hostnames and **requires public (global) IP addresses** (blocks private/link-local/loopback except explicit localhost HTTP).
  - Does **not** follow redirects.
  - Short timeouts.

### Secrets

- LLM API keys prefer the **OS keyring** (service name `localhusk`).
  - Python CLI (`husk.py`) and backend (`assistant.core.secrets`) share this convention.
  - Older `husk-cli` entries are still readable for migration.
- When the keyring is unavailable, a warning is shown; the key is not written to plain-text `.env` by the CLI for the primary LLM key.
- Mail OAuth client secrets belong only in `~/.husk/.env` (mode `0600` on Unix when written by the tools).
- Log redaction (`assistant.core.redact`) strips common key/token patterns before records are stored or printed.

### Agents & tools

- Agent tool execution can require **user approval** (`require_approval` / approval queue).
- Approval records are stored and can be reviewed via the API/UI.
- Do not grant broad shell/file tools without understanding the approval model.

### Data at rest

- Conversations, tasks, notes, etc. live under `~/.husk/data/` (SQLite).
- Runtime logs under `~/.husk/logs/`.
- These paths are listed in `.gitignore` and must never be committed.

### Logging

- Application logs go through a redacting filter before SQLite / console sinks.
- Avoid `print`/`logging` of raw request bodies that may contain credentials.

## Hardening recommendations for operators

1. Keep the process listening only on loopback unless you add authentication + TLS.
2. Use a real OS keyring backend (Windows Credential Manager, macOS Keychain, or Secret Service / KWallet on Linux).
3. Review agent and MCP server configurations before enabling them.
4. Periodically prune history and logs if the machine is shared.
5. Treat `~/.husk/.env` as sensitive; restrict filesystem permissions.

## Exclusions from source control

Confirmed via `.gitignore`:

- `.env`, `*.db`, `data/`, `logs/`, `.husk/`, `ui/node_modules/`, `cli-rs/target/`, etc.
