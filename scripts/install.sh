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

# The window is its own archive: Qt is far larger than everything else, so
# it is kept out of the binary every command starts. Prints nothing for a
# platform with no window build.
resolve_window() {
  case "$1" in
    shambles-linux-x86_64) echo "shambles-window-linux-x86_64.tar.gz" ;;
    shambles-linux-arm64)  echo "shambles-window-linux-arm64.tar.gz" ;;
    shambles-macos-x86_64) echo "shambles-window-macos-x86_64.tar.gz" ;;
    shambles-macos-arm64)  echo "shambles-window-macos-arm64.tar.gz" ;;
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

# The window, unless told not to: SHAMBLES_NO_WINDOW=1 skips it, which saves
# about 70 MB on a machine that will only ever use the terminal.
#
# Unpacked beside the old one and swapped in, so a download that fails halfway
# leaves the window that was already there. A release from before the window
# existed has no such archive; that is reported and is not an error, because
# everything else still works.
WINDOW_ASSET="$(resolve_window "$ASSET")"
if [ "${SHAMBLES_NO_WINDOW:-0}" != "1" ] && [ -n "$WINDOW_ASSET" ]; then
  if [ -n "$TAG" ]; then
    WINDOW_URL="${BASE}/download/${TAG}/${WINDOW_ASSET}"
  else
    WINDOW_URL="${BASE}/latest/download/${WINDOW_ASSET}"
  fi
  WINDOW_DIR="${HOME}/.local/share/shambles/window"
  WINDOW_TMP="$(mktemp -d)"
  echo "Downloading ${WINDOW_ASSET}…"
  if curl -fsSL -o "${WINDOW_TMP}/window.tar.gz" "$WINDOW_URL" \
      && tar -xzf "${WINDOW_TMP}/window.tar.gz" -C "$WINDOW_TMP" \
      && [ -x "${WINDOW_TMP}/shambles-window/shambles-window" ]; then
    mkdir -p "$(dirname "$WINDOW_DIR")"
    rm -rf "$WINDOW_DIR"
    mv "${WINDOW_TMP}/shambles-window" "$WINDOW_DIR"
    echo "Installed the window to ${WINDOW_DIR}"
    echo "  shambles gui    opens it"
  else
    echo "No window in this release, or it could not be unpacked."
    echo "  'shambles gui' still opens the classic window."
  fi
  rm -rf "$WINDOW_TMP"
fi

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
