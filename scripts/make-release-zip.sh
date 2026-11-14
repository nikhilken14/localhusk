#!/usr/bin/env bash
# Build a release zip locally (same shape as CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-1.3.0}"
STAGE="husk-v${VERSION}"
OUT="${ROOT}/dist"
rm -rf "${OUT}/${STAGE}"
mkdir -p "${OUT}/${STAGE}"

if [[ -d "${ROOT}/cli-rs" ]]; then
  (cd "${ROOT}/cli-rs" && cargo build --release)
fi

rsync -a \
  --exclude '.git' \
  --exclude 'cli-rs/target' \
  --exclude 'dist' \
  --exclude '**/__pycache__' \
  --exclude '**/*.pyc' \
  --exclude 'ui/node_modules' \
  --exclude 'ui/dist' \
  "${ROOT}/" "${OUT}/${STAGE}/"

if [[ -x "${ROOT}/cli-rs/target/release/husk" ]]; then
  mkdir -p "${OUT}/${STAGE}/cli-rs/target/release"
  cp "${ROOT}/cli-rs/target/release/husk" "${OUT}/${STAGE}/cli-rs/target/release/husk"
fi
chmod +x "${OUT}/${STAGE}/install.sh" 2>/dev/null || true

cd "${OUT}"
zip -r "${STAGE}-full.zip" "${STAGE}"
echo "Wrote ${OUT}/${STAGE}-full.zip"
