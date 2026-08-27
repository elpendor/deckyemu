#!/usr/bin/env bash
#
# Push the plugin to a Steam Deck over SSH.
#
# This plugin has no compiled backend, so it does not need Docker or the Decky
# CLI -- only the runtime files have to land in ~/homebrew/plugins. Decky's file
# watcher (LIVE_RELOAD, on by default) notices the change and reloads the
# plugin, so this script is the whole edit/test cycle.
#
# Usage:
#   DECK_HOST=steamdeck.local ./scripts/deploy.sh
#
# Configuration via environment (all optional except DECK_HOST):
#   DECK_HOST    hostname or IP of the Deck        (default steamdeck.local)
#   DECK_USER    SSH user                          (default deck)
#   DECK_PORT    SSH port                          (default 22)
#   PLUGIN_DIR   folder name under homebrew/plugins (default deckyemu)
#
# Uses tar over ssh rather than rsync: rsync is not present in Git Bash on
# Windows, but tar and ssh are available everywhere.

set -euo pipefail

DECK_HOST="${DECK_HOST:-steamdeck.local}"
DECK_USER="${DECK_USER:-deck}"
DECK_PORT="${DECK_PORT:-22}"
PLUGIN_DIR="${PLUGIN_DIR:-deckyemu}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f dist/index.js ]]; then
  echo "error: dist/index.js is missing. Run 'pnpm run build' first." >&2
  exit 1
fi

# The shadPS4 motion shim, built on the Deck rather than here: it is a Linux
# shared object and this script is usually run from Windows. The flatpak SDK is
# the right toolchain anyway -- it targets the same glibc as the runtime shadPS4
# loads it into, which a host compiler would not.
#
# Not fatal when it cannot be built. The catalog drops `LD_PRELOAD` when the
# file is absent (`emulators.resolved_env`), so the cost is PS4 motion, not a
# plugin that will not start.
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

# Only what the plugin needs at runtime: no src/, no node_modules/, no .git.
PAYLOAD=(main.py plugin.json package.json py_modules dist)
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
STAGING="/tmp/${PLUGIN_DIR}-deploy.tar.gz"

echo "==> deploying to ${REMOTE}:homebrew/plugins/${PLUGIN_DIR}"

# Two separate ssh sessions on purpose.
#
# Phase 1 pipes the tarball in, so this session's stdin belongs to tar and must
# not have a TTY. Phase 2 may need to prompt for a sudo password, which requires
# a TTY *and* a free stdin -- if both phases shared one session, the password
# prompt would read from the tar stream and corrupt the upload.
tar czf - --exclude='__pycache__' --exclude='*.pyc' "${PAYLOAD[@]}" \
  | ssh "${SSH_OPTS[@]}" "$REMOTE" "cat > '$STAGING'"

ssh "${SSH_OPTS[@]}" -t "$REMOTE" "
    set -e
    TARGET=\"\$HOME/homebrew/plugins/${PLUGIN_DIR}\"
    PLUGINS=\"\$(dirname \"\$TARGET\")\"
    # Staged beside the plugins directory, not inside it: decky watches
    # ~/homebrew/plugins recursively and reloads on every file event, so
    # unpacking there produces a burst of reloads -- and any frontend call in
    # flight during one is dropped without a reply. Unpacking outside and then
    # renaming into place is a single event, so the plugin reloads once.
    STAGE=\"\$HOME/homebrew/.${PLUGIN_DIR}.stage\"

    # decky-loader installs differ: some root-own the plugins directory, some
    # leave it to the user. Only elevate when we actually have to.
    if mkdir -p \"\$TARGET\" 2>/dev/null && [ -w \"\$TARGET\" ]; then
      SUDO=''
    else
      echo '--> plugins directory is not user-writable; using sudo'
      SUDO='sudo'
    fi

    \$SUDO rm -rf \"\$STAGE\"
    \$SUDO mkdir -p \"\$STAGE\"
    \$SUDO tar xzf '$STAGING' -C \"\$STAGE\"

    # Carry the build stamp across. It is CI's, not ours -- it is not in the
    # payload, and the swap below replaces the whole directory -- so without
    # this every deploy onto a released install silently deletes it. Two things
    # then break at once: the Updates tab loses \"what's new\", and the plugin
    # starts reporting itself as a development build, because that is exactly
    # how devreset tells the two apart. A deploy is meant to replace the code,
    # not to change what the install claims to be.
    if [ -f \"\$TARGET/build.json\" ]; then
      \$SUDO cp -a \"\$TARGET/build.json\" \"\$STAGE/build.json\"
    fi
    \$SUDO chown -R ${DECK_USER}:${DECK_USER} \"\$STAGE\"
    \$SUDO chmod -R u=rwX,go=rX \"\$STAGE\"

    # Same filesystem, so these are renames rather than copies.
    \$SUDO rm -rf \"\$TARGET.old\"
    if [ -d \"\$TARGET\" ]; then \$SUDO mv \"\$TARGET\" \"\$TARGET.old\"; fi
    \$SUDO mv \"\$STAGE\" \"\$TARGET\"
    \$SUDO rm -rf \"\$TARGET.old\"
    rm -f '$STAGING'

    echo \"--> installed \$(du -sh \"\$TARGET\" | cut -f1) at \$TARGET\"
  "

echo "==> done. Decky's file watcher should reload the plugin within a second or two."
# Decky names each log after the load timestamp, so point at the newest one.
echo "    Backend log:"
echo "      ssh ${REMOTE} 'tail -f \"\$(ls -t ~/homebrew/logs/${PLUGIN_DIR}/*.log | head -1)\"'"
