#!/bin/sh
# Install DeckyEmu on a Steam Deck, as the user, with nothing else needed.
#
#   curl -fsSL "$RELEASES/latest/download/install.sh" | sh
#
# where RELEASES is https://github.com/elpendor/deckyemu/releases.
#
# Fetches the newest release, unpacks it, and lets the release install itself
# (service.py --install): its own folder under ~/.local/share/deckyemu, a
# systemd user unit, and the service started. Run from inside an unpacked
# release instead, it installs that one. No root at any point.
set -eu

HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/service.py" ]; then
    exec python3 "$HERE/service.py" --install
fi

URL="https://github.com/elpendor/deckyemu/releases/latest/download/deckyemu.zip"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading DeckyEmu..."
curl -fsSL "$URL" -o "$WORK/deckyemu.zip"
python3 -m zipfile -e "$WORK/deckyemu.zip" "$WORK"
python3 "$WORK/deckyemu/service.py" --install
echo "Done. Steam's UI picks DeckyEmu up the next time Steam starts."
