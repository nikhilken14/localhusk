# Contributing to LocalHusk

Thanks for helping improve LocalHusk — a local-first AI assistant.

## Development setup

See **[DEVELOPMENT.md](DEVELOPMENT.md)** for full instructions. Short version:

```bash
# Backend
cd husk
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q

# Frontend
cd ../ui
npm install
npm run dev

# Native CLI (optional)
cd ../cli-rs
cargo build --release
```

Run the Python launcher from the repo root while developing:

```bash
python husk.py
```

## Guidelines

1. **Small, focused changes** – one concern per PR when practical.
2. **Do not break existing installs** – keep `~/.husk` layout and the `husk` command stable.
3. **Tests** – add or update tests for backend behavior changes; run `pytest` before submitting.
4. **UI** – keep TypeScript clean; `npm run build` must succeed.
5. **Secrets** – never commit `.env`, API keys, databases, or personal data.
6. **Public name vs internal paths** – product name is LocalHusk; CLI command, package import (`assistant`), and data dir remain `husk` for compatibility.
7. **Security-sensitive changes** – call out SSRF, auth, keyring, or approval-flow changes in the PR description.

## Pull requests

- Describe the problem and the solution.
- Link related issues.
- Note any migration or upgrade steps for existing users.
- Ensure CI is green (Python tests, UI build, Rust check).

## Code of Conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing you agree that your contributions are licensed under the MIT License (see [LICENSE](LICENSE)).
