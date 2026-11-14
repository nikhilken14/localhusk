# LocalHusk installer for Windows PowerShell. Installs per-user; no admin rights required.
#
# Usage:
#   .\install.ps1
#   $env:HUSK_RELEASE_URL = "https://github.com/nikhilken14/localhusk/archive/refs/heads/main.zip"; irm $url | iex   (or run this script after download)
#   $env:HUSK_GITHUB = "owner/repo"; .\install.ps1
#
$ErrorActionPreference = "Stop"

# Default repo for irm|iex installs (override with HUSK_GITHUB / HUSK_RELEASE_URL).
$HuskDefaultGithub = if ($env:HUSK_DEFAULT_GITHUB) { $env:HUSK_DEFAULT_GITHUB } else { "nikhilken14/localhusk" }


function Say([string]$m) { Write-Host $m }
function Warn([string]$m) { Write-Warning $m }

$Src = $null
if ($MyInvocation.MyCommand.Path) {
    $Src = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$ReleaseUrl = $env:HUSK_RELEASE_URL
$TmpExtract = $null

function Download-Release([string]$url) {
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("husk-install-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    $script:TmpExtract = $tmp
    Say "Downloading LocalHusk release from: $url"
    $zip = Join-Path $tmp "husk.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $out = Join-Path $tmp "out"
    Expand-Archive -Path $zip -DestinationPath $out -Force
    $candidate = Get-ChildItem -Path $out -Recurse -Filter "install.ps1" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $candidate) {
        $candidate = Get-ChildItem -Path $out -Recurse -Filter "husk.py" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if (-not $candidate) {
        throw "Downloaded archive does not look like a LocalHusk release (missing install.ps1 / husk.py)"
    }
    $script:Src = $candidate.DirectoryName
    Say "Extracted to: $Src"
}

try {
    if ($ReleaseUrl) {
        Download-Release $ReleaseUrl
    } elseif (-not $Src -or (-not (Test-Path (Join-Path $Src "husk.py")) -and -not (Test-Path (Join-Path $Src "husk")))) {
         $gh = if ($env:HUSK_GITHUB) { $env:HUSK_GITHUB } else { $HuskDefaultGithub }
        if ($gh) {
            Download-Release "https://github.com/$gh/archive/refs/heads/main.zip"
        } else {
            throw "Run install.ps1 from an extracted LocalHusk release, or set HUSK_RELEASE_URL / HUSK_GITHUB."
        }
    }

    $HasBackend = (Test-Path (Join-Path $Src "husk\pyproject.toml")) -or (Test-Path (Join-Path $Src "husk\src\assistant\main.py"))
    $HasUi = Test-Path (Join-Path $Src "ui\package.json")
    if (-not $HasBackend -and -not (Test-Path (Join-Path $Src "husk.py"))) {
        throw "Required project files missing. Expected husk\ (backend) and/or husk.py in: $Src"
    }

    $ConfiguredHome = if ($env:HUSK_HOME) { $env:HUSK_HOME } else { [Environment]::GetEnvironmentVariable("HUSK_HOME", "User") }
    if ([string]::IsNullOrWhiteSpace($ConfiguredHome)) { $ConfiguredHome = Join-Path $env:USERPROFILE ".husk" }
    $HuskDir = [Environment]::ExpandEnvironmentVariables($ConfiguredHome)
    $BinDir = Join-Path $HuskDir "bin"

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $pythonArgs = @("-3.11") } else { $py = Get-Command python -ErrorAction SilentlyContinue; $pythonArgs = @() }
    if (-not $py) { throw "Python 3.11+ is required: https://python.org" }
    & $py.Source @pythonArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required. Install Python 3.11 or newer and rerun this installer." }

    New-Item -ItemType Directory -Force $HuskDir, $BinDir, (Join-Path $HuskDir "data"), (Join-Path $HuskDir "logs") | Out-Null
    $VenvPython = Join-Path $HuskDir "venv\Scripts\python.exe"
    & $py.Source @pythonArgs -m venv (Join-Path $HuskDir "venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create LocalHusk virtual environment at $(Join-Path $HuskDir 'venv')." }
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip in LocalHusk virtual environment." }

    if ($HasBackend) {
        & $VenvPython -m pip install (Join-Path $Src "husk") rich
        if ($LASTEXITCODE -ne 0) { throw "Backend dependencies failed to install." }
        & $VenvPython -c "import fastapi, uvicorn, assistant; print('LocalHusk backend dependencies verified')"
        if ($LASTEXITCODE -ne 0) { throw "FastAPI/Uvicorn backend verification failed." }
    } else {
        & $VenvPython -m pip install rich fastapi uvicorn
        Say "Installed minimal deps (no full husk package in this archive)."
    }

    if ($HasBackend) {
        if (Test-Path (Join-Path $HuskDir "husk")) { Remove-Item (Join-Path $HuskDir "husk") -Recurse -Force }
        Copy-Item (Join-Path $Src "husk") $HuskDir -Recurse
    }
    if ($HasUi) {
        if (Test-Path (Join-Path $HuskDir "ui")) { Remove-Item (Join-Path $HuskDir "ui") -Recurse -Force }
        Copy-Item (Join-Path $Src "ui") $HuskDir -Recurse
        Remove-Item (Join-Path $HuskDir "ui\.env") -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path (Join-Path $Src "husk.py")) {
        Copy-Item (Join-Path $Src "husk.py") $HuskDir -Force
    }
    Remove-Item (Join-Path $HuskDir "husk\.env") -Force -ErrorAction SilentlyContinue

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if ($HasUi -and $npm) {
        Push-Location (Join-Path $HuskDir "ui")
        try {
            & $npm.Source install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { Warn "Frontend npm install failed. You can retry later from $(Join-Path $HuskDir 'ui')." }
        } finally { Pop-Location }
    } elseif ($HasUi) {
        Warn "Node.js/npm not found. The CLI can run, but /ui requires Node.js 20+ and npm."
    }

    # Prefer native Rust launcher
    $rustCandidates = @(
        (Join-Path $Src "cli-rs\target\release\husk.exe"),
        (Join-Path $Src "builds\windows\husk.exe"),
        (Join-Path $Src "bin\husk.exe"),
        (Join-Path $Src "husk.exe")
    )
    $installedNative = $false
    foreach ($rb in $rustCandidates) {
        if (Test-Path $rb) {
            Copy-Item $rb (Join-Path $BinDir "husk.exe") -Force
            Say "Installed native Rust launcher: $(Join-Path $BinDir 'husk.exe')"
            $installedNative = $true
            break
        }
    }
    if (-not $installedNative -and (Test-Path (Join-Path $Src "husk.py"))) {
        Warn "Rust release binary not found. Using Python compatibility launcher. Build cli-rs for native speed."
    }

    @'
@echo off
setlocal
if not defined HUSK_HOME set "HUSK_HOME=%USERPROFILE%\.husk"
if exist "%HUSK_HOME%\bin\husk.exe" (
  "%HUSK_HOME%\bin\husk.exe" %*
) else (
  "%HUSK_HOME%\venv\Scripts\python.exe" "%HUSK_HOME%\husk.py" %*
)
'@ | Set-Content (Join-Path $BinDir "husk.cmd") -Encoding ASCII

    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("HUSK_HOME", "User"))) {
        [Environment]::SetEnvironmentVariable("HUSK_HOME", $HuskDir, "User")
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $pathParts = @($userPath -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_.TrimEnd('\') -ine $BinDir.TrimEnd('\') })
    $newUserPath = (@($BinDir) + $pathParts) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
    $env:HUSK_HOME = $HuskDir
    $env:Path = "$BinDir;$env:Path"

    Write-Host "`nHusk installed successfully." -ForegroundColor Green
    Write-Host "HUSK_HOME:      $HuskDir"
    Write-Host "Backend Python: $VenvPython"
    Write-Host "Launcher:       $(Join-Path $BinDir 'husk.exe') (native, when built) / husk.cmd (shim)"
    if (-not $npm -and $HasUi) { Warn "Install Node.js 20+ to use /ui." }
    Write-Host "This session's PATH has been updated. Try: husk"
    Write-Host "For future terminals, close and reopen PowerShell."
}
finally {
    if ($TmpExtract -and (Test-Path $TmpExtract)) {
        Remove-Item $TmpExtract -Recurse -Force -ErrorAction SilentlyContinue
    }
}
