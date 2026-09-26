"""SpaghettiKart -- native port of an N64 kart racer. Needs your own ROM

Finds the ROM beside itself, so the first launch asks only for a
confirmation. Its controller-pak saves are a glob rather than a list:
the port writes one file per pak page.
"""

ENTRY = {
    "id": "spaghetti",
    "name": "SpaghettiKart",
    "summary": "Native port of an N64 kart racer. Needs your own ROM.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "HarbourMasters/SpaghettiKart",
        "asset": r"^spaghetti-linux\.zip$",
        "unpack": True,
        "extract": r"^spaghetti\.appimage$",
    },
    "root": "deckyemu/emulators/spaghetti",
    "data": ["deckyemu/emulators/spaghetti"],
    "saves": [
        {"file": "deckyemu/emulators/spaghetti/default.sav"},
        {"file": "deckyemu/emulators/spaghetti/spaghettify.cfg.json"},
        {"file": "deckyemu/emulators/spaghetti/controllerPak_header.sav"},
        "deckyemu/emulators/spaghetti/controllerPak_file_*.sav",
    ],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game, US",
        "extensions": ["z64"],
        "id": {
            "at": 60,
            "is": ["KT"],
        },
        "sha1": ["579c48e211ae952530ffc8738709f078d5dd215e"],
    },
    "game_beside": True,
    "menu_key": "f1",
    "plays": "Mario Kart 64",
    "note": "The first launch builds its own archive from the ROM, which "
            "takes a few minutes and shows a message to confirm before it "
            "starts. It finds the ROM beside itself, so nothing is asked "
            "for. Its menu opens with Select+Start. Plays one game: pick it "
            "under Run with for that ROM only.",
    "game_picker": True,
}
