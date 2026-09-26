"""DevilutionX -- native port of a 1996 PC action RPG. Needs your own data file

The one port here whose game is not a console ROM, so it claims
`platform` rather than `databases`. The data file has to keep its name:
the program looks for two exact filenames and nothing else.
"""

ENTRY = {
    "id": "devilutionx",
    "name": "DevilutionX",
    "summary": "Native port of a 1996 PC action RPG. Needs your own data "
               "file.",
    "verified": True,
    "port": True,
    "source": {
        "kind": "github",
        "repo": "diasurgical/DevilutionX",
        "asset": r"^devilutionx-linux-x86_64\.appimage$",
    },
    "root": ".local/share/diasurgical/devilution",
    "data": [".local/share/diasurgical/devilution"],
    "saves": [
        {"dir": ".local/share/diasurgical/devilution"},
    ],
    "platform": "Microsoft - Windows",
    "needs": {
        "what": "DIABDAT.MPQ from your own copy, or the free shareware "
                "spawn.mpq",
        "extensions": ["mpq"],
    },
    "game_beside": True,
    "note": "Its menu is already on the pad -- hold Select and press Start, "
            "its own binding. The file has to keep its name: it looks for "
            "DIABDAT.MPQ or spawn.mpq and nothing else.",
    "plays": "Diablo",
}
