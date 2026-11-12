#!/usr/bin/env bash
# Install Shambles from GitHub Releases into ~/.local/bin (no sudo).
# Usage:
#   curl -fsSL …/scripts/install.sh | bash
#   curl -fsSL …/scripts/install.sh | bash -s v2.1.0
set -euo pipefail

BASE="${SHAMBLES_RELEASE_BASE:-https://github.com/ianchendev/Shambles/releases}"
TAG="${1:-}"
SKIP_SMOKE="${SHAMBLES_SKIP_SMOKE:-0}"
PIPX_HINT="pipx install git+https://github.com/ianchendev/Shambles"

# The oldest glibc the Linux binaries start on. Held by scripts/check_glibc.py
# in the release workflow; keep the two in step.
GLIBC_FLOOR_MAJOR=2
GLIBC_FLOOR_MINOR=35

die() {
  echo "$*" >&2
  exit 1
}

os="$(uname -s)"
arch="$(uname -m)"

# Normalize machine names used in Release assets (Task 1 table).
case "$arch" in
  amd64) arch="x86_64" ;;
  aarch64) arch="arm64" ;;
esac

# A shell running under Rosetta reports x86_64 on an Apple Silicon Mac. The
# Intel binary would run, translated, on every launch for no reason.
if [ "$os" = "Darwin" ] && [ "$arch" = "x86_64" ] \
   && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then
  arch="arm64"
fi

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

# Say why before downloading 30 MB that cannot start. The binaries are built
# against glibc; on musl (Alpine) or an older glibc the only symptom is a
# loader error that names neither Shambles nor a way out.
check_libc() {
  [ "$os" = "Linux" ] || return 0
  [ -z "${SHAMBLES_FORCE_ASSET:-}" ] || return 0
  ldd_says="$(ldd --version 2>&1 || true)"
  case "$ldd_says" in *musl*|*Musl*|*MUSL*) is_musl=1 ;; *) is_musl=0 ;; esac
  if [ -e /etc/alpine-release ] || [ "$is_musl" = "1" ]; then
    die "This system uses musl libc, and the Shambles binaries need glibc.
Install from source instead, which needs no matching system libraries:
  ${PIPX_HINT}"
  fi
  version="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')" || version=""
  [ -n "$version" ] || return 0
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"
  case "$major$minor" in *[!0-9]*) return 0 ;; esac
  if [ "$major" -lt "$GLIBC_FLOOR_MAJOR" ] || {
       [ "$major" -eq "$GLIBC_FLOOR_MAJOR" ] && [ "$minor" -lt "$GLIBC_FLOOR_MINOR" ]; }; then
    die "This system has glibc ${version}; the Shambles binaries need ${GLIBC_FLOOR_MAJOR}.${GLIBC_FLOOR_MINOR} or newer
(Ubuntu 22.04, Debian 12, RHEL 9). Install from source instead:
  ${PIPX_HINT}"
  fi
}

# The window is its own archive: it carries Qt, which is far larger than
# everything else, so it is kept out of the binary every command starts.
# Prints nothing for a platform with no window build.
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
  case "$os" in
    MINGW*|MSYS*|CYGWIN*)
      die "This is a Windows shell. Install with PowerShell instead:
  irm https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.ps1 | iex" ;;
  esac
  die "No Shambles binary for ${os}-${arch} yet. Install from source instead:
  ${PIPX_HINT}"
fi

check_libc

command -v curl >/dev/null 2>&1 || die "curl is needed to download Shambles, and it is not installed."

if [ -n "$TAG" ]; then
  RELEASE="${BASE}/download/${TAG}"
else
  RELEASE="${BASE}/latest/download"
fi

DEST_DIR="${HOME}/.local/bin"
DEST="${DEST_DIR}/shambles"
mkdir -p "$DEST_DIR"

# Beside the destination, not in /tmp. A rename within one directory either
# happens or does not; a move across filesystems is a copy, and a copy that
# is interrupted leaves half a binary under the real name.
TMP="$(mktemp "${DEST_DIR}/.shambles-download.XXXXXX")"
SUMS="$(mktemp "${DEST_DIR}/.shambles-sums.XXXXXX")"
trap 'rm -f "$TMP" "$SUMS"' EXIT

echo "Downloading ${ASSET}…"
curl -fsSL -o "$TMP" "${RELEASE}/${ASSET}" \
  || die "Could not download ${RELEASE}/${ASSET}"

# Check the download against the release's own list. It is served from the
# same place as the binary, so this catches a truncated or mangled download,
# not a tampered release -- the binaries are unsigned and nothing here can
# make up for that.
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    return 1
  fi
}

if [ "${SHAMBLES_SKIP_VERIFY:-0}" = "1" ]; then
  echo "Checksum not verified (SHAMBLES_SKIP_VERIFY=1)."
elif ! curl -fsSL -o "$SUMS" "${RELEASE}/SHA256SUMS" 2>/dev/null; then
  echo "This release publishes no SHA256SUMS; the download was not verified." >&2
elif ! actual="$(sha256_of "$TMP")"; then
  echo "No sha256sum or shasum on this system; the download was not verified." >&2
else
  expected="$(awk -v name="$ASSET" '{ f = $2; sub(/^\*/, "", f); if (f == name) print $1 }' "$SUMS" | head -n 1)"
  if [ -z "$expected" ]; then
    echo "SHA256SUMS does not list ${ASSET}; the download was not verified." >&2
  elif [ "$expected" != "$actual" ]; then
    die "The download does not match the release checksum, so nothing was installed.
  expected ${expected}
  got      ${actual}
Try again; if it keeps happening, please open an issue."
  else
    echo "Checksum verified."
  fi
fi

chmod +x "$TMP"

if [ "$SKIP_SMOKE" != "1" ]; then
  # Before it replaces a working install, not after.
  if ! smoke="$("$TMP" --version 2>&1)"; then
    echo "$smoke" >&2
    die "The downloaded binary does not start on this system, so nothing was installed.
Install from source instead, which needs no matching system libraries:
  ${PIPX_HINT}"
  fi
fi

mv -f "$TMP" "$DEST"
WINDOW_TMP=""
cleanup() {
  rm -f "$SUMS"
  if [ -n "$WINDOW_TMP" ]; then rm -rf -- "$WINDOW_TMP"; fi
}
trap cleanup EXIT

echo "Installed to ${DEST}"
if [ "$SKIP_SMOKE" != "1" ]; then
  echo "$smoke"
fi

case ":${PATH}:" in
  *":${DEST_DIR}:"*) ;;
  *)
    echo "Add ~/.local/bin to your PATH:"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac

# The window, unless SHAMBLES_NO_WINDOW=1. Optional: the binary above is
# already installed and works without it, so nothing here can undo that.
#
# Checked against the same SHA256SUMS as the binary, and unpacked beside its
# final place so that putting it there is a rename. The old window is only
# replaced once the new one has arrived whole; a failed or mismatched
# download leaves it as it was. A release from before the window existed has
# no such archive, which is reported and is not an error.
install_window() {
  local name dir parent archive expected actual
  name="$(resolve_window "$ASSET")"
  [ -n "$name" ] || return 0

  dir="${HOME}/.local/share/shambles/window"
  parent="$(dirname "$dir")"
  mkdir -p "$parent"
  WINDOW_TMP="$(mktemp -d "${parent}/.window-download.XXXXXX")"
  archive="${WINDOW_TMP}/window.tar.gz"

  echo "Downloading ${name}..."
  if ! curl -fsSL -o "$archive" "${RELEASE}/${name}" 2>/dev/null; then
    echo "This release has no window to download; 'shambles gui' opens the classic one."
    return 0
  fi

  if [ "${SHAMBLES_SKIP_VERIFY:-0}" = "1" ]; then
    echo "Checksum not verified (SHAMBLES_SKIP_VERIFY=1)."
  elif [ ! -s "$SUMS" ]; then
    echo "This release publishes no SHA256SUMS; the window was not verified." >&2
  elif ! actual="$(sha256_of "$archive")"; then
    echo "No sha256sum or shasum on this system; the window was not verified." >&2
  else
    expected="$(awk -v name="$name" '{ f = $2; sub(/^\*/, "", f); if (f == name) print $1 }' "$SUMS" | head -n 1)"
    if [ -z "$expected" ]; then
      echo "SHA256SUMS does not list ${name}; the window was not verified." >&2
    elif [ "$expected" != "$actual" ]; then
      echo "The window download does not match the release checksum, so it was not installed.
  expected ${expected}
  got      ${actual}
Shambles itself is installed. Run the installer again to retry the window." >&2
      return 0
    else
      echo "Checksum verified."
    fi
  fi

  if ! tar -xzf "$archive" -C "$WINDOW_TMP" 2>/dev/null \
      || [ ! -x "${WINDOW_TMP}/shambles-window/shambles-window" ]; then
    echo "The window archive could not be unpacked, so it was not installed." >&2
    return 0
  fi

  rm -rf -- "${dir}.old"
  if [ -e "$dir" ]; then mv "$dir" "${dir}.old"; fi
  mv "${WINDOW_TMP}/shambles-window" "$dir"
  rm -rf -- "${dir}.old"
  echo "Installed the window to ${dir}"
  echo "  shambles gui    opens it"
}

if [ "${SHAMBLES_NO_WINDOW:-0}" != "1" ]; then
  install_window
fi

if [ "$os" = "Linux" ] && grep -qi microsoft /proc/version 2>/dev/null; then
  echo "Note: this is WSL. Shambles here manages the Claude Code and Codex installed"
  echo "inside WSL, not the ones installed on Windows itself."
fi

echo "Run 'shambles' to start. See the README for what is supported on each system."
echo "Done."
