import emu_config
import steam_layouts
from . import deck_gyro

_SHADPS4_CONFIG = ".var/app/net.shadps4.shadPS4/data/shadPS4/config.json"

_SHADPS4_SETUP = {
    "format": emu_config.JSON_KEYS,
    "label": "game folder",
    #   1  shadPS4 pointed at the folder packages are unpacked into
    #   2  the Vulkan pipeline cache turned on
    #   3  both written as dotted keys, because 1 and 2 addressed shadPS4's
    #      nested sections as if they were flat and silently wrote nothing
    #   4  install_dirs withdrawn -- a list of plain strings is not the shape
    #      shadPS4 reads, and writing one stopped it loading settings at all
    "version": 4,
    "files": {
        _SHADPS4_CONFIG: {
            # No `install_dirs` here, and that is the finding. Written as a list
            # of paths -- which is what the empty default looks like -- shadPS4
            # refused the whole file:
            #
            #   Error loading settings: [json.exception.type_error.304]
            #   cannot use at() with string
            #
            # It calls at() on each entry, so entries are objects, and the
            # binary has `installDirsEnabled` beside `installDirs` which says
            # what one of the fields is. Guessing the rest is what caused this,
            # so nothing is written until shadPS4 has been watched writing one
            # itself. Nothing is lost meanwhile: the panel lists unpacked games
            # by reading the folder, never by asking shadPS4.
            #
            # Off by default, which means every launch recompiles the shader
            # pipelines it built last time. On a Deck that is stutter you pay
            # for again on every run rather than once.
            #
            # This is the only graphics setting touched, and deliberately: the
            # log from a real session on a Deck showed 479 lines for the whole
            # run, so shadPS4's synchronous logging -- the obvious suspect -- is
            # not costing anything here, and the rest are correctness tradeoffs
            # that belong to whoever is playing the game.
            "Vulkan.pipeline_cache_enabled": {"value": True, "default": False},
        }
    },
}

# Vita3K keeps a flat config.yml under XDG config rather than beside its data,
# which is at ~/.local/share/Vita3K/Vita3K. Both read off a Deck after letting
# the AppImage write its own defaults.

ENTRY = {
    "id": "shadps4",
    "name": "shadPS4",
    "summary": "PlayStation 4. Early, but it runs real games.",
    "source": {"kind": "flatpak", "id": "net.shadps4.shadPS4"},
    # The PS4's user accounts, one directory each, holding that account's
    # savedata and trophies. All four slots rather than the first: shadPS4
    # creates 1000-1003 whether or not anything has used them, and a backup that
    # took only the one somebody happened to play on would be silently partial.
    "saves": [".var/app/net.shadps4.shadPS4/data/shadPS4/home"],
    "databases": [],
    "platform": "Sony - PlayStation 4",
    # The flatpak does not run shadPS4. Its manifest names
    # `shadPS4QtLauncher`, a picker for which build of shadPS4 to use, and
    # handing that a game path fails outright: "Error: specified emulator
    # name or path is not found" -- it read the game as an emulator. Read
    # off a Deck by running both and comparing their --help.
    "command": "shadps4",
    # Without this every game renders on the CPU. shadPS4 enumerated four
    # Vulkan devices on a Deck and chose llvmpipe -- the software
    # rasteriser -- with `gpu_id: -1` meaning "pick one for me":
    #
    #   Instance: Found 4 physical devices
    #   CollectDeviceParameters: GPU_Vendor: llvmpipe
    #
    # Two unrelated 2D games were slow, which is what gave it away: a
    # compatibility problem does not affect everything equally. Restricting
    # the loader to the AMD driver leaves one device to pick and it picks
    # the right one -- confirmed on the same Deck, same game:
    #
    #   Instance: Found 1 physical devices
    #   GPU_Model: AMD Custom GPU 0932 (RADV VANGOGH)
    #
    # Both paths are listed because the runtime ships the ICD in both, and
    # the loader skips entries it cannot read: naming one file would turn a
    # runtime that moved it into an emulator that will not start at all,
    # which is worse than the bug being fixed.
    "env": {
        "VK_DRIVER_FILES": ":".join((
            "/usr/share/vulkan/icd.d/radeon_icd.x86_64.json",
            "/usr/lib/x86_64-linux-gnu/GL/vulkan/icd.d/radeon_icd.x86_64.json",
        )),
    },
    # Motion, and the only part of this entry a user can switch off.
    #
    # shadPS4 copies SDL's gamepad sensor axes into the emulated DualShock
    # without converting them, and SDL's convention is not Sony's: it calls a
    # DualShock's *face normal* +Y, and the Deck's *top-edge* direction +Y with
    # the screen normal +Z. X is left-right on both, so pitch works while yaw
    # and roll land on each other -- tilting the Deck moved the game, turning it
    # did nothing. Measured on a Deck: a real 90 degree yaw arrives as -89.1 on
    # z[2] against +23.5 on y[1]. Vita3K has converted correctly for years, in
    # `motion.cpp`'s `from_gamepad` branch; shadPS4 never has.
    #
    # `shim/gyroshim.c` rotates it back from `LD_PRELOAD`, which is possible at
    # all because shadPS4 links libSDL3 dynamically -- the flatpak stays stock
    # and keeps updating, and nothing is forked, pinned or rebuilt. The preload
    # is dropped when the file is missing (`emulators.resolved_env`), so a build
    # without the shim loses motion rather than failing to launch.
    #
    # Switchable because it is not free: reading the Deck's own pad means Steam
    # Input stops shaping it, for *every* PS4 game, including the many with no
    # motion at all. That is the cost `costs` states, and the reason this is a
    # workaround rather than part of the entry.
    "workarounds": [{
        "id": "ps4-motion",
        "name": "Motion controls",
        "because": "shadPS4 copies SDL's sensor axes into the emulated "
                   "DualShock without converting them, so turning the Deck "
                   "does nothing while tilting it works.",
        "upstream": "https://github.com/shadps4-emu/shadPS4/issues/3871",
        "costs": "Steam Input stops shaping the pad for every PS4 game -- "
                 "remapped buttons, stick curves and the back buttons stop "
                 "applying, including in games that have no motion at all.",
        # Off unless asked for. Motion is worth having and it is not free:
        # every PS4 game loses Steam Input for it, including the many with
        # no motion at all, so nobody pays that without choosing to.
        "default": False,
        "apply": {
            "env": deck_gyro.motion_env(LD_PRELOAD="{plugin}/bin/gyroshim.so"),
            # Steam powers the Deck's IMU down unless the running game's layout
            # binds gyro, and the sensors then read exactly `(0, 0, 0)`. Gyro to
            # a stick rather than Steam's stock gyro-to-mouse, because
            # `input_mouse.cpp` reads the pointer for `MouseMode::Touchpad`, so
            # a drifting cursor is a DualSense touchpad being dragged.
            "layout": steam_layouts.DERIVED_URL,
        },
    }],
    # `-g` rather than a bare path. shadPS4 accepts either, but the
    # fullscreen switch is prepended ahead of it, and a flag swallowing the
    # positional after it is a known way for an emulator to silently open its
    # game list instead of the game.
    "args": "-g {rom}",
    # Takes a value rather than being a bare switch: `-f, --fullscreen TEXT
    # (true|false)`, from shadPS4's own --help.
    "fullscreen_args": "--fullscreen true",
    #   2  the Vulkan driver pinned, so it stops rendering on the CPU. An
    #      emulator registered before that has none of it stored, and the
    #      recipe is what carries the correction to it.
    #   3  motion: the SDL variables and the shim preload. `env` is taken from
    #      the entry only when this number moves, so shipping them without
    #      raising it would leave every existing install without gyro.
    "recipe": 3,
    # Booted on a Deck. Two games played from their Steam shortcuts, at
    # full speed once VK_DRIVER_FILES stopped it rendering on the CPU.
    "verified": True,
    # No longer "point this at eboot.bin": a .pkg installs from the add
    # flow and hands off the eboot itself, and shadPS4's own list of
    # installed games is the way back to one.
    "note": "Add a game from its .pkg — it is unpacked for you.",
    # shadPS4 cannot unpack a package and no fork of it can either -- the
    # code that used to do it was taken out and published as a command-line
    # tool, which is this. GPL-2.0, an AppImage from its own release, and
    # descended from shadPS4's own extractor, so what comes out is what
    # shadPS4 expects. Fetched the first time a PS4 package is added rather
    # than with the emulator, since most people will never need it.
    "helper": {
        "name": "ps4-pkg-extractor",
        "label": "PS4 package extractor",
        "repo": "AzaharPlus/shadPS4Plus",
        "asset": r"^ShadPs4Plus-PkgExtractor-.*-linux\.AppImage$",
    },
    "setup": _SHADPS4_SETUP,
    "firmware": [],
}
