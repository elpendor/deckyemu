import emu_config

_PPSSPP_SETUP = {
    "format": emu_config.PLAIN_INI,
    "label": "the update check",
    "version": 1,
    "files": {
        ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini": {
            "General": {"CheckForNewVersion": {"value": "False", "default": "True"}},
        },
    },
}

ENTRY = {
    "id": "ppsspp",
    "name": "PPSSPP",
    "summary": "PlayStation Portable.",
    "source": {"kind": "flatpak", "id": "org.ppsspp.PPSSPP"},
    "databases": ["Sony - PlayStation Portable"],
    # --pause-menu-exit is PPSSPP's answer to the problem -nogui solves for
    # PCSX2: without it the pause menu's only way out is "Exit to menu",
    # which leaves PPSSPP sitting in its own game browser -- so the Steam
    # shortcut never stops and playtime keeps counting. With it, that entry
    # becomes "Exit" and quitting the game quits the emulator.
    "args": "--pause-menu-exit {rom}",
    "fullscreen_args": "--fullscreen",
    "recipe": 2,
    "setup": _PPSSPP_SETUP,
    "verified": True,
    "firmware": [],
}
