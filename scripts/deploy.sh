#!/usr/bin/env bash
#
# Install this tree on a Steam Deck over SSH, as a new version beside the
# installed ones, and restart the service into it.
#
# Nothing needs root: the service, its versions and its state all live under
# ~/.local/share/deckyemu, and the unit is a systemd user unit. So this runs to
# the end on its own -- there is no step left for anybody to type a password at.
#
# Usage:
#   DECK_HOST=steamdeck.local ./scripts/deploy.sh
#
# Configuration via environment (all optional):
#   DECK_HOST    hostname or IP of the Deck        (default steamdeck.local)
#   DECK_USER    SSH user                          (default deck)
#   DECK_PORT    SSH port                          (default 22)
#
# Uses tar over ssh rather than rsync: rsync is not present in Git Bash on
# Windows, but tar and ssh are available everywhere.

set -euo pipefail

DECK_HOST="${DECK_HOST:-steamdeck.local}"
DECK_USER="${DECK_USER:-deck}"
DECK_PORT="${DECK_PORT:-22}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

for built in dist/preload.js dist/deckyemu.js; do
  if [[ ! -f "$built" ]]; then
    echo "error: $built is missing. Run 'pnpm run build' first." >&2
    exit 1
  fi
done

# The shadPS4 motion shim, built on the Deck rather than here: it is a Linux
# shared object and this script is usually run from Windows. The flatpak SDK is
# the right toolchain anyway -- it targets the same glibc as the runtime shadPS4
# loads it into, which a host compiler would not.
#
# Not fatal when it cannot be built. The catalog drops `LD_PRELOAD` when the
# file is absent (`emulators.resolved_env`), so the cost is PS4 motion, not a
# service that will not start.
build_shim() {
  local remote="$1" ssh_opts=("${@:2}")
  if ! ssh "${ssh_opts[@]}" "$remote" 'flatpak info org.freedesktop.Sdk' >/dev/null 2>&1; then
    echo "warning: org.freedesktop.Sdk is not installed on the Deck, so the" >&2
    echo "         shadPS4 motion shim cannot be built. PS4 gyro will be off." >&2
    echo "         Install it with: flatpak install -y flathub org.freedesktop.Sdk" >&2
    return 1
  fi
  mkdir -p bin
  ssh "${ssh_opts[@]}" "$remote"     'mkdir -p /tmp/deckyemu-shim && cat > /tmp/deckyemu-shim/gyroshim.c' < shim/gyroshim.c
  ssh "${ssh_opts[@]}" "$remote"     'flatpak run --command=gcc --filesystem=/tmp org.freedesktop.Sdk -shared -fPIC -O2        -o /tmp/deckyemu-shim/gyroshim.so /tmp/deckyemu-shim/gyroshim.c -ldl      && for s in SDL_WaitEvent SDL_PollEvent SDL_WaitEventTimeout; do            nm -D --defined-only /tmp/deckyemu-shim/gyroshim.so | grep -qw "$s" || exit 1;          done       && cat /tmp/deckyemu-shim/gyroshim.so' > bin/gyroshim.so
  # Verified on the Deck, above, before a single byte is sent back: the shim
  # works by *shadowing* three SDL entry points, so a misspelled one still
  # compiles and still loads and silently intercepts nothing -- shadPS4 then
  # runs with motion switched on and its axes unrotated, which reads as broken
  # motion rather than as a build fault. A failed check sends nothing, so the
  # empty file below is the one failure path either way.
  if [[ ! -s bin/gyroshim.so ]]; then
    echo "warning: building or checking the motion shim failed; PS4 gyro will be off." >&2
    rm -f bin/gyroshim.so
    return 1
  fi
  echo "==> built bin/gyroshim.so on the Deck"
}

# Only what runs on the Deck: no src/, no node_modules/, no .git.
PAYLOAD=(service.py launcher.py rescue.sh main.py package.json py_modules dist assets)
for item in "${PAYLOAD[@]}"; do
  if [[ ! -e "$item" ]]; then
    echo "error: expected '$item' in $REPO_ROOT" >&2
    exit 1
  fi
done

SSH_OPTS=(-p "$DECK_PORT")
REMOTE="${DECK_USER}@${DECK_HOST}"

if build_shim "$REMOTE" "${SSH_OPTS[@]}"; then
  PAYLOAD+=(bin)
fi

# A build stamp of its own, so the Updates tab and the rescue page say this is
# a deploy rather than claiming to be the release it sits beside.
STAMP="$(mktemp -d)"
trap 'rm -rf "$STAMP"' EXIT
printf '{"version": "%s", "build": "%s", "deployed": true}\n' \
  "$(node -p 'require("./package.json").version')" \
  "$(git rev-parse --short HEAD 2>/dev/null || echo dev)" > "$STAMP/build.json"

NAME="dev-$(date +%Y%m%d-%H%M%S)"
echo "==> deploying to ${REMOTE} as ${NAME}"

# Unpacked straight into a new version folder, then installed from there: the
# running version is never touched, and the previous one stays to go back to.
{ tar czf - --exclude='__pycache__' --exclude='*.pyc' "${PAYLOAD[@]}"; } \
  | ssh "${SSH_OPTS[@]}" "$REMOTE" "set -e
      dest=\"\$HOME/.local/share/deckyemu/app/${NAME}\"
      mkdir -p \"\$dest\"
      tar xzf - -C \"\$dest\"
      chmod +x \"\$dest/rescue.sh\""
ssh "${SSH_OPTS[@]}" "$REMOTE" "cat > ~/.local/share/deckyemu/app/${NAME}/build.json" < "$STAMP/build.json"
ssh "${SSH_OPTS[@]}" "$REMOTE" "python3 ~/.local/share/deckyemu/app/${NAME}/service.py --install"

echo "==> done. The service is restarting into ${NAME}."
echo "    Log:"
echo "      ssh ${REMOTE} 'journalctl --user -u deckyemu -f'"
