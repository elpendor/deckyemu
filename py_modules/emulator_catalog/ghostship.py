"""Ghostship -- native port of an N64 game. Needs your own ROM

The release asset is named for the project rather than for the port,
which is why the pattern and the extracted name disagree. `unpack`
because the archive holds data folders the binary needs beside it.
"""

ENTRY = {
    "id": "ghostship",
    "name": "Ghostship",
    "summary": "Native port of an N64 game. Needs your own ROM.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "HarbourMasters/Ghostship",
        "asset": r"^Nautilus-[A-Za-z-]+-Linux\.zip$",
        "unpack": True,
        "extract": r"^ghostship\.appimage$",
    },
    "root": "deckyemu/emulators/ghostship",
    "data": ["deckyemu/emulators/ghostship"],
    "saves": [
        {"dir": "deckyemu/emulators/ghostship/saves"},
        {"file": "deckyemu/emulators/ghostship/ghostship.cfg.json"},
    ],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game, the US or Japanese version",
        "extensions": ["z64", "n64", "v64"],
        "id": {
            "at": 60,
            "is": ["SM", "MS"],
        },
        "sha1": [
            "8a20a5c83d6ceb0f0506cfc9fa20d8f438cafe51",
            "9bef1128717f958171a4afac3ed78ee2bb4e86ce",
        ],
    },
    "game_beside": True,
    "first_run": {
        "args": "{rom}",
        "unless": ["sm64.o2r"],
    },
    "menu_key": "esc",
    "plays": "Super Mario 64",
    "note": "Reads the ROM once and builds its own archive from it, then "
            "plays from that. Its menu opens with Select+Start. Plays one "
            "game: pick it under Run with for that ROM only.",
}
