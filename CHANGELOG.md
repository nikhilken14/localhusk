# Changelog

All notable changes to LocalHusk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- CLI: the banner now shows the real version (from `Cargo.toml`) instead of a hardcoded `1.4`.
- CLI: cleaner layout — status block, no empty model/provider placeholders, word-wrapped replies, a spinner while waiting, and a single prompt line instead of two rules around every input.
- CLI: enables ANSI colours and UTF-8 on Windows PowerShell 5.1 / conhost so box-drawing characters render correctly, and uses the real console width.
- CLI: `/ui` opens the browser; new `/clear` and `/version`; `/chat <message>` (listed in `/help`) now works.

### Fixed

- CLI: `/exit`, Ctrl+C, EOF and closing the window now reliably stop the backend and web UI that Husk started, and `/exit` reports what it stopped.
- CLI: EOF on stdin no longer loops forever on empty input.
- CLI: replies containing non-ASCII text or `\uXXXX` escapes are decoded correctly, and slicing the model list can no longer panic on multi-byte characters.
- Web UI: the topbar model label and token counters now refresh right after a chat reply and after any model change (the `husk:usage` event was listened for but never sent), and it distinguishes "No default model" from "No model connected".
- CLI: panels and replies use the full terminal width.
- Installers: `install.ps1` / `install.sh` run via `irm | iex` / `curl | bash` now install the latest published GitHub Release (with its freshly built launcher) instead of the launcher committed on `main`, which could be outdated. New `husk --version` / `husk --help` print without starting the backend.
- Web UI: `NoteDetailPage` accepts the `notify` prop passed by `App.tsx` (fixes the TypeScript build error).
- Backend: migration `0009` creates the `chat_attachments` foreign keys that the ORM model declares.
- Tests: updated for local-only calendar, removed task time filters, and the current agent/automation behaviour; migration tests follow the Alembic head revision.

## [1.0.0] – 2026-11-14

### Added

- First public release of **LocalHusk**, a local-first AI assistant.
- Python backend (FastAPI + SQLite + Alembic) with agents, automations, MCP, tasks, notes, calendar, and mail.
- Web UI (React + TypeScript + Vite).
- Cross-platform CLI: native Rust launcher with Python fallback (`husk.py`).
- Installers for Linux (`install.sh`) and Windows (`install.ps1`).
- Prebuilt CLI binaries under `builds/linux` and `builds/windows`.
- OS keyring integration for LLM API keys (service `localhusk`).
- Log redaction for common secret patterns.
- MCP HTTP client with SSRF protections (public IPs only, no redirects).
- GitHub Actions: CI (Python, UI, Rust, Linux installer smoke) and dual-platform Release workflow.
- Documentation: README, USER_MANUAL, ARCHITECTURE, DEVELOPMENT, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT.

### Platforms

- Linux x86_64
- Windows x86_64

### Notes

- macOS is not an official target for v1.0.0; the Python CLI and backend still run where Python/Node are available.
