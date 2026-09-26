"""2 Ship 2 Harkinian -- native port of an N64 game. Needs your own ROM

`twoship.py` because a module name cannot start with a digit; the id
is still `2ship`. Its gyro option reads a sensor Steam's pad has not.
"""

ENTRY = {
    "id": "2ship",
    "name": "2 Ship 2 Harkinian",
    "summary": "Native port of an N64 game. Needs your own ROM.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "2ship2harkinian/2Ship2Harkinian",
        "asset": r"^2Ship-[A-Za-z-]+-Linux\.zip$",
        "extract": r"^2ship\.appimage$",
    },
    "root": "deckyemu/emulators/2ship",
    "saves": [
        {"dir": "deckyemu/emulators/2ship/saves"},
        {"file": "deckyemu/emulators/2ship/2ship2harkinian.json"},
    ],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game (NTSC-U 1.0 or the GameCube "
                "version)",
        "extensions": ["z64", "n64", "v64"],
        "id": {
            "at": 60,
            "is": ["ZS", "SZ"],
        },
    },
    "game_beside": True,
    "menu_key": "esc",
    "plays": "The Legend of Zelda: Majora's Mask",
    "note": "Reads the ROM once and builds its own archive from it, then "
            "plays from that. Its menu opens with Select+Start. Its gyro "
            "option reads the pad's own sensor, which Steam's pad has not -- "
            "leave it off. Plays one game: pick it under Run with for that "
            "ROM only.",
    "first_run": {
        "args": "{rom}",
        "unless": ["mm.o2r"],
    },
}
