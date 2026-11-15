#!/usr/bin/env bash
# LocalHusk installer for Linux. Installs per-user; no root required.
#
# Usage (end users):
#   curl -fsSL https://raw.githubusercontent.com/nikhilken14/localhusk/main/install.sh | bash
#   ./install.sh                          # from extracted release / clone
#
# One-line installs use the main branch source by default. Set HUSK_PREFER_RELEASE=1
# to prefer the latest CI-built Release ZIP, or HUSK_RELEASE_URL to use an exact URL.
#
set -euo pipefail

# Maintainers: set this to your public GitHub path so `curl | bash` works with zero env vars.
HUSK_DEFAULT_GITHUB="${HUSK_DEFAULT_GITHUB:-nikhilken14/localhusk}"


say()  { printf '%s\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }
die()  { printf 'Error: %s\n' "$*" >&2; exit 1; }

SRC=""
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "/dev/stdin" && "${BASH_SOURCE[0]}" != "-" ]]; then
  SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

RELEASE_URL="${HUSK_RELEASE_URL:-}"
TMP_EXTRACT=""

# Newest published Linux Release asset (built by CI); empty if none / offline.
latest_release_url() {
  local api json=""
  api="https://api.github.com/repos/$1/releases/latest"
  if command -v curl >/dev/null 2>&1; then
    json="$(curl -fsSL "$api" 2>/dev/null || true)"
  elif command -v wget >/dev/null 2>&1; then
    json="$(wget -qO- "$api" 2>/dev/null || true)"
  fi
  printf '%s' "$json" | grep -oE '"browser_download_url": *"[^"]*linux-x86_64\.zip"' | head -n1 | sed -E 's/.*"(https[^"]*)"$/\1/' || true
}

download_release() {
  local url="$1"
  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/husk-install.XXXXXX")"
  TMP_EXTRACT="$tmp"
  say "Downloading LocalHusk release from: $url"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$tmp/husk.zip"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp/husk.zip" "$url"
  else
    die "curl or wget is required to download a release"
  fi
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$tmp/husk.zip" -d "$tmp/out"
  else
    die "unzip is required to extract the release archive"
  fi
  local candidate
  candidate="$(find "$tmp/out" -maxdepth 3 -type f \( -name 'install.sh' -o -name 'husk.py' \) 2>/dev/null | head -1 || true)"
  if [[ -z "$candidate" ]]; then
    die "Downloaded archive does not look like a LocalHusk release (missing install.sh / husk.py)"
  fi
  SRC="$(cd "$(dirname "$candidate")" && pwd)"
  say "Extracted to: $SRC"
}

cleanup() {
  if [[ -n "${TMP_EXTRACT:-}" && -d "$TMP_EXTRACT" ]]; then
    rm -rf "$TMP_EXTRACT"
  fi
}
trap cleanup EXIT

if [[ -n "$RELEASE_URL" ]]; then
  # An explicit URL is authoritative: never silently substitute another source.
  download_release "$RELEASE_URL"
elif [[ -z "$SRC" ]] || { [[ ! -f "$SRC/husk.py" ]] && [[ ! -d "$SRC/husk" ]]; }; then
  _gh="${HUSK_GITHUB:-$HUSK_DEFAULT_GITHUB}"
  if [[ "${HUSK_PREFER_RELEASE:-0}" == "1" ]]; then
    _latest="$(latest_release_url "$_gh")"
    if [[ -n "$_latest" ]]; then
      download_release "$_latest"
    else
      warn "No Linux x86_64 release asset found; falling back to main branch source."
      download_release "https://github.com/${_gh}/archive/refs/heads/main.zip"
    fi
  else
    say "Installing from the main branch source (default)."
    download_release "https://github.com/${_gh}/archive/refs/heads/main.zip"
  fi
fi

HAS_BACKEND=0
HAS_UI=0
if [[ -f "$SRC/husk/pyproject.toml" || -f "$SRC/husk/src/assistant/main.py" ]]; then
  HAS_BACKEND=1
fi
if [[ -f "$SRC/ui/package.json" ]]; then
  HAS_UI=1
fi
if [[ $HAS_BACKEND -eq 0 && ! -f "$SRC/husk.py" ]]; then
  die "Required project files missing. Expected husk/ (backend) and/or husk.py in: $SRC"
fi

if [[ -n "${HUSK_HOME:-}" ]]; then
  HUSK_DIR="$(eval echo "$HUSK_HOME")"
else
  HUSK_DIR="${HOME}/.husk"
fi
BIN_DIR="${HUSK_DIR}/bin"
VENV_DIR="${HUSK_DIR}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

PYTHON=""
for candidate in python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  fi
done
[[ -n "$PYTHON" ]] || die "Python 3.11+ is required. Install it (apt, brew, pyenv, …) and rerun."

say "Using Python: $PYTHON ($($PYTHON -c 'import sys; print(sys.version.split()[0])'))"
say "HUSK_HOME:    $HUSK_DIR"

mkdir -p "$HUSK_DIR" "$BIN_DIR" "$HUSK_DIR/data" "$HUSK_DIR/logs"

"$PYTHON" -m venv "$VENV_DIR"
"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
if [[ $HAS_BACKEND -eq 1 ]]; then
  "$VENV_PYTHON" -m pip install "$SRC/husk" rich
  "$VENV_PYTHON" -c "import fastapi, uvicorn, assistant; print('LocalHusk backend dependencies verified')" \
    || die "Backend import check failed. See pip output above."
else
  "$VENV_PYTHON" -m pip install rich fastapi uvicorn
  say "Installed minimal deps (no full husk package in this archive)."
fi

if [[ $HAS_BACKEND -eq 1 ]]; then
  rm -rf "$HUSK_DIR/husk"
  cp -R "$SRC/husk" "$HUSK_DIR/"
fi
if [[ $HAS_UI -eq 1 ]]; then
  rm -rf "$HUSK_DIR/ui"
  cp -R "$SRC/ui" "$HUSK_DIR/"
fi
if [[ -f "$SRC/husk.py" ]]; then
  cp "$SRC/husk.py" "$HUSK_DIR/husk.py"
fi

if [[ $HAS_UI -eq 1 ]] && command -v npm >/dev/null 2>&1; then
  NODE_MAJOR=$(node -v 2>/dev/null | sed 's/v//;s/\..*//' || echo 0)
  if [[ "$NODE_MAJOR" -ge 18 ]]; then
    say "Building frontend (Node $(node -v))..."
    (cd "$HUSK_DIR/ui" && npm install --silent && npm run build) \
      || warn "Frontend build failed; CLI and API still work. Run npm install in $HUSK_DIR/ui later."
  else
    warn "Node.js 18+ recommended for /ui. Found: $(node -v 2>/dev/null || echo none)"
  fi
elif [[ $HAS_UI -eq 1 ]]; then
  warn "Node.js/npm not found. The CLI can run, but the web UI requires Node.js 18+."
fi

install_native() {
  local candidates=(
    "$SRC/cli-rs/target/release/husk"
    "$SRC/builds/linux/husk"
    "$SRC/bin/husk"
    "$SRC/husk"
  )
  local bin
  for bin in "${candidates[@]}"; do
    if [[ -x "$bin" && ! -d "$bin" ]]; then
      cp "$bin" "$BIN_DIR/husk"
      chmod +x "$BIN_DIR/husk"
      say "Installed native launcher: $BIN_DIR/husk"
      return 0
    fi
  done
  return 1
}

if install_native; then
  :
else
  cat > "$BIN_DIR/husk" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Maintainers: set this to your public GitHub path so `curl | bash` works with zero env vars.

HUSK_HOME="${HUSK_HOME:-$HOME/.husk}"
if [[ -x "$HUSK_HOME/bin/husk.native" ]]; then
  exec "$HUSK_HOME/bin/husk.native" "$@"
fi
exec "$HUSK_HOME/venv/bin/python" "$HUSK_HOME/husk.py" "$@"
EOF
  chmod +x "$BIN_DIR/husk"
  say "Installed Python compatibility launcher: $BIN_DIR/husk"
fi

export HUSK_HOME="$HUSK_DIR"
export PATH="$BIN_DIR:$PATH"

add_to_path_rc() {
  local rc="$1"
  [[ -f "$rc" ]] || return 0
  if ! grep -q 'HUSK_HOME\|\.husk/bin' "$rc" 2>/dev/null; then
    {
      echo ""
      echo "# LocalHusk Local AI"
      echo "export HUSK_HOME=\"$HUSK_DIR\""
      echo "export PATH=\"\$HUSK_HOME/bin:\$PATH\""
    } >> "$rc"
    say "Updated $rc"
  fi
}

case "${SHELL:-}" in
  */zsh)  add_to_path_rc "$HOME/.zshrc" ;;
  */bash) add_to_path_rc "$HOME/.bashrc"; add_to_path_rc "$HOME/.bash_profile" ;;
  */fish)
    mkdir -p "$HOME/.config/fish"
    if [[ -f "$HOME/.config/fish/config.fish" ]] && ! grep -q HUSK_HOME "$HOME/.config/fish/config.fish" 2>/dev/null; then
      {
        echo "set -gx HUSK_HOME $HUSK_DIR"
        echo "set -gx PATH \$HUSK_HOME/bin \$PATH"
      } >> "$HOME/.config/fish/config.fish"
      say "Updated fish config"
    fi
    ;;
  *) add_to_path_rc "$HOME/.profile" ;;
esac

say ""
say "LocalHusk installed successfully."
say "  HUSK_HOME:      $HUSK_DIR"
say "  Backend Python: $VENV_PYTHON"
say "  Launcher:       $BIN_DIR/husk"
say ""
say "This shell already has PATH updated. Try:  husk"
say "Open a new terminal (or source your shell rc) for permanent availability."
if ! command -v npm >/dev/null 2>&1; then
  say "Install Node.js 18+ to use the web UI (husk ui / /ui)."
fi
