"""Starship -- native port of an N64 game. Needs your own ROM

`game_picker` because the first launch asks whether to extract and then
wants the ROM chosen in its own file browser. The launcher hands it the
path; the question is the port's and cannot be skipped.
"""

ENTRY = {
    "id": "starship",
    "name": "Starship",
    "summary": "Native port of an N64 game. Needs your own ROM.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "HarbourMasters/Starship",
        "asset": r"^Starship-[A-Za-z-]+-Linux\.zip$",
        "unpack": True,
        "extract": r"^starship\.appimage$",
    },
    "root": "deckyemu/emulators/starship",
    "saves": [
        {"file": "deckyemu/emulators/starship/default.sav"},
        {"file": "deckyemu/emulators/starship/starship.cfg.json"},
    ],
    "databases": ["Nintendo - Nintendo 64"],
    "needs": {
        "what": "your own ROM of the game, US 1.0 or 1.1",
        "extensions": ["z64", "n64", "v64"],
        "id": {
            "at": 60,
            "is": ["FX", "XF"],
        },
        "sha1": [
            "d8b1088520f7c5f81433292a9258c1184afa1457",
            "63b69f0ef36306257481afc250f9bc304c7162b2",
            "09f0d105f476b00efa5303a3ebc42e60a7753b7a",
            "f7475fb11e7e6830f82883412638e8390791ab87",
            "9bd71afbecf4d0a43146e4e7a893395e19bf3220",
            "d064229a32cc05ab85e2381ce07744eb3ffaf530",
            "05b307b8804f992af1a1e2fbafbd588501fdf799",
            "09f5d5c14219fc77a36c5a6ad5e63f7abd8b3385",
            "e6dad7523ff8f83fad6fbdb59d472b4f76340c2b",
            "c8a10699dea52f4bb2e2311935c1376dfb352e7a",
            "3a05aba5549fa71e8b16a0c6e2c8481b070818a9",
        ],
    },
    "game_beside": True,
    "menu_key": "f1",
    "plays": "Star Fox 64",
    "note": "The first launch asks whether to extract, and builds its own "
            "archive from the ROM, which takes a few minutes; the ROM is "
            "handed to its picker for you, and the screen stays black while "
            "it works. Its menu opens with Select+Start. Plays one game: "
            "pick it under Run with for that ROM only.",
    "game_picker": True,
}
