import emu_config

# Confirmed by running the AppImage on a Deck rather than read anywhere: Xenia
# announces its own paths at startup, and the first line is a surprise.
#
#   i> Storage root: /home/deck/.local/share/Xenia
#   i> Content root: /home/deck/.local/share/Xenia/content
#   i> Host cache root: /home/deck/.local/share/Xenia/cache_host
#
# `Xenia` with a capital X, under `.local/share`, while the config file inside
# it is lowercase and hyphenated. Neither half follows from the other, and a
# reset pointed at `.local/share/xenia` would silently clear nothing on a
# case-sensitive filesystem -- which every Deck has.
_XENIA_STORAGE = ".local/share/Xenia"
_XENIA_CONFIG = "%s/xenia-canary.config.toml" % _XENIA_STORAGE

# Fullscreen is a config setting here rather than a launch argument, and the
# reason is worth stating because the flag exists and looks usable.
#
# `fullscreen` is a real cvar -- it is in the config Xenia writes itself, under
# [Display], described as "Whether to launch the emulator in fullscreen", and
# defaulting to false. The `--name=value` syntax works too: passing
# `--storage_root=/tmp/xstore` moved the storage root, and Xenia said so in its
# own startup log.
#
# What makes the flag untrustworthy is what happens to one it does not know.
# Xenia was started with `--zzz_not_a_flag=1` and ran normally to the timeout:
# no error, no warning, nothing in xenia.log. `--help` behaves the same way --
# with a display it ignores the argument and opens the GUI, and with none it
# prints "Failed to initialize GTK+" and exits before parsing anything. So there
# is no observable difference between a flag that worked and a flag that was
# discarded, which is precisely the case `verified` in schema.py warns about.
#
# The config file is the emulator's own, in its own syntax, and re-applying it
# is a no-op. That is the half that can be checked.
_XENIA_SETUP = {
    "format": emu_config.TOML_KEYS,
    "label": "fullscreen",
    "version": 1,
    "path": _XENIA_CONFIG,
    "sections": {
        "Display": {
            # `raw`, for the reason xemu's entry gives: quoted, this is the
            # string "false", which is true.
            "fullscreen": {"value": "true", "default": "false", "raw": True},
        },
    },
}

ENTRY = {
    "id": "xenia",
    "name": "Xenia Canary",
    # The caveat belongs in the summary as well as the note, because the summary
    # is what the emulator list shows and the note needs a tap to reach.
    "summary": "Xbox 360. Experimental, and rough on this hardware.",
    # Canary rather than mainline, which is not a preference: `xenia-project/xenia`
    # publishes no releases at all -- the API returns an empty list -- so there is
    # no asset to install. Canary is the fork the emulation community treats as
    # the real one and the only branch shipping a Linux build with any history.
    #
    # A native AppImage, which every Steam Deck guide still says does not exist;
    # they have you install the Windows build and add Proton on top. It does now,
    # at 17MB, and it is the same channel Azahar and Vita3K already use.
    "source": {
        "kind": "github",
        "repo": "xenia-canary/xenia-canary",
        "asset": r"^xenia_canary_linux\.AppImage$",
    },
    # One directory holds all of it -- config, saves, and the host cache. Xenia
    # has no second home under `.config`.
    "data": [_XENIA_STORAGE],
    "root": _XENIA_STORAGE,
    # libretro has no Xbox 360 core, so the platform label carries the system and
    # `MANUAL_EXTENSIONS` carries iso/xex. Both were already in the tree before
    # this entry existed; it was the one platform declared with no emulator
    # behind it.
    "databases": [],
    "platform": "Microsoft - Xbox 360",
    # A bare path, which is what the bundled `xenia_canary.desktop` asks Xenia
    # for itself: `Exec=xenia_canary %f`.
    "args": "{rom}",
    # Both, and the config is the one that has to be right. `fullscreen` is a
    # real cvar -- `DEFINE_bool(fullscreen, false, ..., "Display")` in
    # emulator_window.cc -- and `--name=value` demonstrably parses, since
    # `--storage_root=/tmp/xstore` moved the storage root. What the flag cannot
    # do is *report*: Xenia runs normally when handed `--zzz_not_a_flag=1`, so a
    # broken flag looks exactly like a working one.
    #
    # It earns its place anyway. The config is only in effect once Xenia has
    # written one for the settings to be merged into, and until then this is
    # what stops the first launch of the first game being a windowed game with a
    # GTK menu bar across the top of it -- which is what a Deck actually got.
    "fullscreen_args": "--fullscreen=true",
    # Bumped so an install made before these existed picks them up: `zar` and
    # `stfs` in the extension list, and `--fullscreen=true` above. Without it
    # the record written at install time keeps `iso, xex` and an empty
    # fullscreen switch forever -- which is exactly what happened, and the
    # symptom was an unpacked XBLA title with no emulator offered for it.
    "recipe": 2,
    "setup": _XENIA_SETUP,
    # No firmware of any kind. Xbox 360 emulation needs no BIOS dump, so unlike
    # xemu or the PlayStation entries there is nothing for the user to supply.
    #
    # Nor any controller bindings. Xenia carries SDL2 and picks the Deck up
    # unaided -- `SDL OnControllerDeviceAdded: "Steam Deck"` with a complete
    # mapping, on a first run with no config -- so the setup block above has the
    # one key it needs and no more.
    "verified": False,
    # The archive half of this is worth saying in the panel rather than only in
    # a comment. Xenia refuses a .zip with a message box, and a message box is
    # invisible under gamescope -- so from a Steam shortcut the refusal looks
    # exactly like the emulator hanging.
    "note": "Xbox 360 emulation is experimental everywhere and hardest on "
            "handhelds. Expect many games not to boot at all; smaller Xbox "
            "Live Arcade titles do best. Unzip first: Xenia reads .iso, .xex "
            "and its own .zar, and refuses .zip and .7z outright.",
}
