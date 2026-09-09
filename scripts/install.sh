#!/usr/bin/env bash
# Install Shambles from GitHub Releases into ~/.local/bin (no sudo).
# Usage:
#   curl -fsSL …/scripts/install.sh | bash
#   curl -fsSL …/scripts/install.sh | bash -s v2.1.0
set -euo pipefail

BASE="${SHAMBLES_RELEASE_BASE:-https://github.com/ianchendev/Shambles/releases}"
TAG="${1:-}"
SKIP_SMOKE="${SHAMBLES_SKIP_SMOKE:-0}"

os="$(uname -s)"
arch="$(uname -m)"

# Normalize machine names used in Release assets (Task 1 table).
case "$arch" in
  amd64) arch="x86_64" ;;
  aarch64) arch="arm64" ;;
esac

resolve_asset() {
  case "$os" in
    Linux)
      case "$arch" in
        x86_64) echo "shambles-linux-x86_64" ;;
        arm64)  echo "shambles-linux-arm64" ;;
        *)      return 1 ;;
      esac
      ;;
    Darwin)
      case "$arch" in
        x86_64) echo "shambles-macos-x86_64" ;;
        arm64)  echo "shambles-macos-arm64" ;;
        *)      return 1 ;;
      esac
      ;;
    *)
      return 1
      ;;
  esac
}

if [ -n "${SHAMBLES_FORCE_ASSET:-}" ]; then
  ASSET="$SHAMBLES_FORCE_ASSET"
elif ! ASSET="$(resolve_asset)"; then
  echo "No Shambles binary for ${os}-${arch} yet" >&2
  exit 1
fi

if [ -n "$TAG" ]; then
  URL="${BASE}/download/${TAG}/${ASSET}"
else
  URL="${BASE}/latest/download/${ASSET}"
fi

DEST_DIR="${HOME}/.local/bin"
DEST="${DEST_DIR}/shambles"
mkdir -p "$DEST_DIR"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "Downloading ${ASSET}…"
curl -fsSL -o "$TMP" "$URL"
chmod +x "$TMP"
mv "$TMP" "$DEST"
trap - EXIT

echo "Installed to ${DEST}"

case ":${PATH}:" in
  *":${DEST_DIR}:"*) ;;
  *)
    echo "Add ~/.local/bin to your PATH:"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac

echo "Note: a successful install does not mean account switching is supported on this OS."
echo "See the README support matrix for Linux / macOS / Windows status."

if [ "$SKIP_SMOKE" != "1" ]; then
  if "$DEST" --version >/dev/null 2>&1; then
    "$DEST" --version
  else
    echo "Smoke check skipped or failed (binary may need a real Release asset)." >&2
  fi
fi

echo "Done."
