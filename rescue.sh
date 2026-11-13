#!/bin/sh
# What the DeckyEmu tile in the Steam library runs.
#
# Opens the service's rescue page in Steam's browser: status, update, roll
# back, restart. If the service is not answering it is restarted first, and if
# it still is not, the previous version is put back and started -- so the tile
# does something useful even when nothing else of DeckyEmu works. Lives in the
# service's root folder, outside every version, for the same reason.
ROOT="$HOME/.local/share/deckyemu"
URL_FILE="$ROOT/run/rescue-url"

answering() {
    [ -s "$URL_FILE" ] && curl -fsS -m 2 "$(cat "$URL_FILE")/ping" >/dev/null 2>&1
}

main_pid() {
    systemctl --user show -p MainPID --value deckyemu.service 2>/dev/null
}

# Up to a minute while the same process lives: a cold start loads the whole
# backend before the page answers. A new process means it died, so give up.
wait_for_service() {
    started=$(main_pid)
    for _ in $(seq 60); do
        answering && return 0
        [ "$started" != 0 ] && [ "$(main_pid)" = "$started" ] || return 1
        sleep 1
    done
    return 1
}

if ! answering; then
    # Tells the service it was the tile: with the plugin in use, it then stays
    # up to serve this page instead of turning itself off (service.py).
    mkdir -p "$ROOT/run" && : > "$ROOT/run/tile-launch"
    systemctl --user restart deckyemu.service
    if ! wait_for_service; then
        python3 "$ROOT/launcher.py" --rollback-only 2>/dev/null
        systemctl --user restart deckyemu.service
        wait_for_service
    fi
fi

if [ -s "$URL_FILE" ]; then
    steam "steam://openurl/$(cat "$URL_FILE")"
fi
# Held open briefly, so Steam does not read the launch as an instant failure.
sleep 3
