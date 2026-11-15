# Install

LocalHusk one-line installers use the **main branch source by default**. A local checkout or extracted folder always installs from its local files.

## Default: main branch source

```bash
# Linux / WSL2
curl -fsSL https://raw.githubusercontent.com/nikhilken14/localhusk/main/install.sh | bash
```

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/nikhilken14/localhusk/main/install.ps1 | iex
```

## Optional: prefer the latest CI-built Release ZIP

```bash
curl -fsSL https://raw.githubusercontent.com/nikhilken14/localhusk/main/install.sh | HUSK_PREFER_RELEASE=1 bash
```

```powershell
$env:HUSK_PREFER_RELEASE = "1"; irm https://raw.githubusercontent.com/nikhilken14/localhusk/main/install.ps1 | iex
```

When enabled, the installer selects the latest platform-specific asset (`linux-x86_64` or `windows-x86_64`). If no matching release asset is available, it falls back to the main branch source.

## Exact archive URL

Set `HUSK_RELEASE_URL` to install from that exact URL. It takes precedence over `HUSK_PREFER_RELEASE`; download or extraction errors stop the installation rather than silently switching sources.

```bash
HUSK_RELEASE_URL="https://example.com/localhusk-linux.zip" bash install.sh
```

```powershell
$env:HUSK_RELEASE_URL = "https://example.com/localhusk-windows.zip"
.\install.ps1
```

## Local checkout or extracted archive

```bash
git clone https://github.com/nikhilken14/localhusk.git
cd localhusk
./install.sh
```

```powershell
cd localhusk
.\install.ps1
```

Local files take precedence when the installer is run from a valid project folder. `HUSK_RELEASE_URL` remains an explicit override.

For forks, set `HUSK_GITHUB=owner/repo` for the current shell, or change `HUSK_DEFAULT_GITHUB` in the installer.
