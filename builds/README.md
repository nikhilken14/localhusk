# Prebuilt CLI binaries (v1.0.0)

> These binaries must be rebuilt from `cli-rs/` (`cargo build --release`) whenever the CLI source changes. A binary built before the CLI changes in `CHANGELOG.md` (Unreleased) will still show the old banner and old exit behaviour.

Optional native launchers. The installer and `husk.py` work without them (Python fallback).

| Platform | Binary | Notes |
|----------|--------|-------|
| **Linux** (x86_64) | `linux/husk` | Built on Ubuntu / glibc. Works on most modern x86_64 Linux. |
| **Windows** (x86_64) | `windows/husk.exe` | Built on Windows runners (or cross-compiled with mingw). |

## How the installer uses these

`install.sh` / `install.ps1` look for, in order:

1. `cli-rs/target/release/husk` (or `husk.exe`)
2. `builds/<os>/husk` (or `husk.exe`)
3. A small Python wrapper that runs `husk.py`

You can also copy the matching binary into `~/.husk/bin/husk` (Linux) or `%USERPROFILE%\.husk\bin\husk.exe` (Windows) manually.

## Building yourself

```bash
# Linux
cd cli-rs && cargo build --release
# → target/release/husk

# Windows (PowerShell)
cd cli-rs; cargo build --release
# → target\release\husk.exe
```
