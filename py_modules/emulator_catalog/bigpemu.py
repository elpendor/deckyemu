# The Jaguar is the one system with no core worth running. RetroArch's only
# option is Virtual Jaguar, whose own libretro documentation says to expect
# games that do not work at all; BigPEmu runs the entire retail library.
#
# **Installed from the author's own update feed**, which is the file BigPEmu's
# own "Check for Updates" reads -- found in the binary's strings, since it is
# documented nowhere:
#
#     BUILD_INFO 1
#     VERSION 1.221
#     Linux64 "http://.../BigPEmu_Linux64_v1221.tar.gz" "" C1B241BBFA5135CB ...
#
# A version, a download and a 64-bit FNV-1a of the file. That is more than a
# GitHub release gives us -- nothing else in this catalog can verify what it
# downloaded against a number the publisher stated -- and it means nothing here
# is a mirror, a repack, or a guess at a URL.
#
# **What it cannot do is go back.** The feed carries only the current build and
# the project publishes no changelog; the Wayback Machine has no snapshot of
# either, and the AUR package tracks only what is current. Old files do remain
# on the server, but naming one means a convention the author never wrote down
# and which already breaks at 1.20. `emulator_builds` says so in those words
# rather than drawing an empty list.
#
# A pkgforge AppImage of this exists and is not used: it is a repack rather
# than the publisher, and its build script deletes the ReadMe that BigPEmu's
# own licence requires be distributed with it.
import emu_config

# **Its settings live in `~/.bigpemu_userdata`, not beside the binary.** Read
# off a Deck after a real run, and worth writing down because every other
# source says otherwise: the ReadMe gives the Windows path, and EmuDeck's page
# describes a `UserData` folder next to the build, which is their own symlink
# rather than where this program looks. The EEPROM saves land there too, in
# `game<hash>_eeprom.bigpeep`.
_BIGPEMU_CONFIG = ".bigpemu_userdata/BigPEmuConfig.bigpcfg"

# The one setting that must not be left as it comes. BigPEmu has no fullscreen
# flag -- `-windowx`, `-noborder` and `-cfgpath` are the window options its
# ReadMe documents, and none of them is this -- so the config is the only
# route, which is the same position Dolphin and Azahar are in.
#
# `DisplayMode` is an index into the three modes its own string table lists, in
# this order: Borderless Window, Window, Fullscreen. A fresh run on a Deck
# writes 0; 2 was read off that ordering and then confirmed on screen.
_BIGPEMU_SETUP = {
    "format": emu_config.JSON_KEYS,
    "label": "fullscreen and the controller",
    "version": 1,
    # Dotted, not nested: `json-keys` addresses a nested key as "a.b.c" and
    # refuses a dict, because a section handed over as if it were a value is
    # silently skipped and then recorded as applied -- which is how shadPS4's
    # settings once wrote nothing and never ran again.
    "files": {
        _BIGPEMU_CONFIG: {
            # `default` is what makes this a change rather than a refusal: the
            # value is only replaced while it is still what BigPEmu itself
            # wrote, which a fresh run on a Deck showed is 0. Set it to
            # anything else and that is the user's choice, kept.
            "BigPEmuConfig.Video.DisplayMode": {"value": 2, "default": 0},
            # **Without this the pad does nothing at all.** BigPEmu binds
            # inputs to one device by id, and the id it stores is whichever
            # controller it met first -- which on a Deck is not the one a game
            # launched from the library is handed. Auto-assign binds whatever
            # turns up instead, and its own text says so: "Jaguar inputs will
            # be auto-assigned for any new input device with recognized
            # controller mappings". Measured: off, the pad is dead; on, port
            # one is bound at first launch and the game plays.
            "BigPEmuConfig.Input.AutoAssign": {"value": 1, "default": 0},
        },
    },
}

ENTRY = {
    "id": "bigpemu",
    "name": "BigPEmu",
    "summary": "Atari Jaguar and Jaguar CD, the whole retail library.",
    "source": {
        "kind": "url",
        "feed": "https://www.richwhitehouse.com/jaguar/build_info.txt",
        # The feed lists Win64, WinARM64, DEV-Win64, Linux64 and LinuxARM64.
        "select": "Linux64",
        # A tarball holding the program and its data folders, so everything
        # comes out and `extract` names the one to run.
        "unpack": True,
        "extract": r"^bigpemu$",
    },
    # Extensions come from this, and Virtual Jaguar's info file is where the
    # list is written down: j64, jag, rom, abs, cof, bin, prg, cue, cdi. The
    # core is not worth running and its metadata still is.
    "databases": ["Atari - Jaguar"],
    # The ROM path and nothing else. The flags its ReadMe documents are for
    # window placement and split-screen -- `-windowx`, `-noborder`, `-cfgpath`
    # -- and none of them is a fullscreen switch: fullscreen is a property it
    # remembers for itself, and under gamescope the window is fullscreen
    # regardless.
    "args": "{rom}",
    # No BIOS, no keys, no firmware of any kind. Unusual enough among the
    # entries here to be worth saying rather than leaving as an empty list.
    "firmware": [],
    # **Steam's on-screen keyboard, otherwise, on every launch.** The SDL
    # plugin calls `SDL_StartTextInput` at startup -- for its own menu, which
    # draws its own text entry -- and the SDL on a Deck is sdl2-compat over
    # SDL3, so that request goes out over the Wayland text-input protocol and
    # Steam raises the keyboard over the game. Saying the application
    # implements its own IME is both accurate and what stops it.
    #
    # `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0` is deliberately *not*
    # here, though `vita3k` sets it. Steam Input holds the physical pad, so
    # hiding the virtual one leaves the emulator with no controller at all:
    # measured inside a launch, `SDL_NumJoysticks` returned 0, and the symptom
    # was a dead pad with every binding looking correct.
    "env": {
        "SDL_ENABLE_SCREEN_KEYBOARD": "0",
        "SDL_IME_IMPLEMENTED_UI": "1",
    },
    "setup": _BIGPEMU_SETUP,
    # Confirmed on a Deck: the ROM path alone boots the game, and Pitfall came
    # up fullscreen at the right aspect with the pad working -- which is the
    # display index above measured rather than read off a string table.
    "verified": True,
    # Both directories this install owns: the build, and the settings folder it
    # makes in the home directory.
    "data": ["deckyemu/emulators/bigpemu", ".bigpemu_userdata"],
    # The EEPROM saves and the save states, which is the whole of that folder
    # apart from the config. Jaguar games save little and save rarely, and a
    # cartridge EEPROM is the only copy there is.
    "saves": [".bigpemu_userdata"],
    # The config lives in with them, and it is not a save: its bindings name
    # one controller by device id, so a restore onto another Deck leaves the
    # pad bound to hardware that is not there. Its display settings are for
    # that Deck's screen too.
    "saves_except": ["BigPEmuConfig.bigpcfg"],
}
