"""PaperBoat -- native port of an N64 role-playing game. Needs your own ROM

One accepted dump. The first launch builds its archive and asks once
at the end whether to run.
"""

ENTRY = {
    "id": "paperboat",
    "name": "PaperBoat",
    "summary": "Native port of an N64 role-playing game. Needs your own ROM.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "HarbourMasters/PaperBoat",
        "asset": r"^Paperboat-[A-Za-z0-9-]+-Linux\.zip$",
        "unpack": True,
        "extract": r"^Paperboat\.AppImage$",
    },
    "root": "deckyemu/emulators/paperboat",
    "saves": [
        {"dir": "deckyemu/emulators/paperboat/saves"},
        {"file": "deckyemu/emulators/paperboat/paperboat.cfg.json"},
    ],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game, US",
        "extensions": ["z64"],
        "id": {
            "at": 60,
            "is": ["MQ"],
        },
        "sha1": ["3837f44cda784b466c9a2d99df70d77c322b97a0"],
    },
    "game_beside": True,
    "menu_key": "esc",
    "plays": "Paper Mario",
    "first_run": {
        "args": "{rom}",
        "unless": ["pm64.o2r"],
    },
    "note": "The first launch builds its own archive from the ROM, which "
            "takes a few minutes, and asks once at the end whether to run. "
            "Its menu opens with Select+Start. Plays one game: pick it under "
            "Run with for that ROM only.",
    "game_picker": True,
}
