"""Lighthouse -- native port of an N64 platformer. Needs your own ROM

Four accepted dumps, more than any other port here takes.
"""

ENTRY = {
    "id": "lighthouse",
    "name": "Lighthouse",
    "summary": "Native port of an N64 platformer. Needs your own ROM.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "HarbourMasters/Lighthouse",
        "asset": r"^Lighthouse-[A-Za-z0-9-]+-Linux\.zip$",
        "unpack": True,
        "extract": r"^lighthouse\.appimage$",
    },
    "root": "deckyemu/emulators/lighthouse",
    "saves": [
        {"dir": "deckyemu/emulators/lighthouse/saves"},
        {"file": "deckyemu/emulators/lighthouse/lighthouse.cfg.json"},
    ],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game, US 1.0 or 1.1, Japanese or PAL",
        "extensions": ["z64"],
        "id": {
            "at": 60,
            "is": ["BK"],
        },
        "sha1": [
            "1fe1632098865f639e22c11b9a81ee8f29c75d7a",
            "ded6ee166e740ad1bc810fd678a84b48e245ab80",
            "bb359a75941df74bf7290212c89fbc6e2c5601fe",
            "90726d7e7cd5bf6cdfd38f45c9acbf4d45bd9fd8",
        ],
    },
    "game_beside": True,
    "menu_key": "esc",
    "plays": "Banjo-Kazooie",
    "first_run": {
        "args": "{rom}",
        "unless": ["bk.o2r"],
    },
    "note": "The first launch builds its own archive from the ROM, which "
            "takes a few minutes, and asks once at the end whether to run. "
            "Its menu opens with Select+Start. Plays one game: pick it under "
            "Run with for that ROM only.",
    "game_picker": True,
}
