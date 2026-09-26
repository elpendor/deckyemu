"""Ship of Harkinian -- native port of an N64 game. Needs your own ROM

Reads the ROM once and builds its own archive beside itself, which is
why `root` sits under the plugin's own emulators directory rather than a
dot-directory: the archive, the saves and the binary are one install.
"""

ENTRY = {
    "id": "shipwright",
    "name": "Ship of Harkinian",
    "summary": "Native port of an N64 game. Needs your own ROM.",
    "port": True,
    "source": {
        "kind": "github",
        "repo": "HarbourMasters/Shipwright",
        "asset": r"^SoH-[A-Za-z-]+-Linux\.zip$",
        "extract": r"^soh\.appimage$",
    },
    "root": "deckyemu/emulators/shipwright",
    "data": ["deckyemu/emulators/shipwright"],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game (.z64, .n64 or .v64)",
        "extensions": ["z64", "n64", "v64"],
        "id": {
            "at": 60,
            "is": ["ZL", "LZ"],
        },
    },
    "game_beside": True,
    "note": "Reads the ROM once and builds its own archive from it, then "
            "plays from that. Its menu opens with Select+Start. Plays one "
            "game: pick it under Run with for that ROM only.",
    "saves": [
        {"dir": "deckyemu/emulators/shipwright/Save"},
        {"file": "deckyemu/emulators/shipwright/shipofharkinian.json"},
    ],
    "menu_key": "esc",
    "plays": "The Legend of Zelda: Ocarina of Time",
    "first_run": {
        "args": "{rom}",
        "unless": ["oot.o2r", "oot-mq.o2r"],
    },
}
