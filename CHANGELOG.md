# Changelog

All notable changes to LocalHusk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
