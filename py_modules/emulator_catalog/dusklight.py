"""Dusklight -- native port of a GameCube game. Needs your own disc image

Takes the disc image through `game_config` rather than on the command
line: its own launcher re-reads the config at start, so the path has to
be in the file before the process begins. `isoVerification` is off
because the check refuses dumps this port otherwise plays.
"""

ENTRY = {
    "id": "dusklight",
    "name": "Dusklight",
    "summary": "Native port of a GameCube game. Needs your own disc image.",
    "port": True,
    "source": {
        "kind": "github",
        "repo": "TwilitRealm/dusklight",
        "asset": r"^Dusklight-v[0-9][0-9A-Za-z.+-]*-linux-x86_64\.AppImage$",
    },
    "root": ".local/share/TwilitRealm/Dusklight",
    "data": [".local/share/TwilitRealm/Dusklight"],
    "databases": ["Nintendo - GameCube"],
    "needs": {
        "what": "a GameCube disc image of the game (.iso, not a compressed "
                ".rvz)",
        "extensions": ["iso", "gcm"],
        "id": {
            "at": 0,
            "is": ["GZ2E01", "GZ2P01", "GZ2J01"],
        },
    },
    "setup": {
        "format": "json-flat",
        "path": ".local/share/TwilitRealm/Dusklight/config.json",
        "sections": {
            "backend.skipPreLaunchUI": True,
            "video.enableFullscreen": True,
        },
    },
    "game_config": {
        "keys": {"backend.isoPath": "{rom}", "backend.isoVerification": 0},
    },
    "note": "Plays one game: pick it under Run with for that disc only.",
    "saves": [
        {"dir": ".local/share/TwilitRealm/Dusklight/USA"},
        {"file": ".local/share/TwilitRealm/Dusklight/achievements.json"},
    ],
    "plays": "The Legend of Zelda: Twilight Princess",
}
