#!/bin/bash
# Run scripts/deck/ui_probe.py on the Deck without copying it there first,
# and fetch any screenshot it takes into ./ui-shots.
#
#   scripts/deck-ui.sh qam
#   scripts/deck-ui.sh capture "Big Picture" settings
#   scripts/deck-ui.sh press down down a
#
# DECK_HOST picks the Deck (default steamdeck.local), as for deploy.sh.
set -eu

HOST="deck@${DECK_HOST:-steamdeck.local}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Quoted for the remote shell, which ssh hands one joined command line: an
# argument like "Big Picture" would otherwise arrive as two.
ARGS="$(printf '%q ' "$@")"
OUT="$(ssh "$HOST" "python3 - $ARGS" < "$HERE/deck/ui_probe.py")"
printf '%s\n' "$OUT"

case "${1:-}" in
  shot|capture)
    shot="$(printf '%s\n' "$OUT" | tail -1)"
    mkdir -p ui-shots
    scp -q "$HOST:$shot" ui-shots/
    echo "fetched ui-shots/$(basename "$shot")"
    ;;
esac
