import emu_config
from .steam_pad import _STEAM_PAD_GUID

_XEMU_DATA = ".var/app/app.xemu.xemu/data/xemu/xemu"
_XEMU_TOML = "%s/xemu.toml" % _XEMU_DATA


# Everything xemu draws over the game, turned off. On a handheld the game is
# the only thing on screen and there is no pointer to dismiss anything with, so
# each of these is furniture that can only get in the way.
#
#   show_menubar        the bar that slides in over the top of the picture.
#                       `false` is not "auto-hide sooner" -- xemu never calls
#                       ShowMainMenu() at all, so the bar cannot come back on
#                       a stray trackpad nudge.
#   show_notifications  the toasts in the upper-right. Mostly "Connected
#                       '<pad>' to port 1", which fires over the boot of every
#                       single launch from Steam.
#   hide_cursor         the mouse pointer, after three seconds of it not
#                       moving. This is the whole of what xemu offers -- there
#                       is no "never show a cursor" -- so the Deck's right
#                       trackpad can still put it back for three seconds. It is
#                       the floor, not a fix.
#   show_welcome        the first-run panel, in front of the game.
#
# **The table names are the load-bearing part.** `show_menubar` lived in
# `[general]` here for a release and did nothing: xemu answers
# `Warning: unrecognized key 'general.show_menubar'` on stderr and carries on
# with the bar switched on, which in Game Mode is indistinguishable from the
# setting not existing. The three interface keys are `[display.ui]`;
# `show_welcome` really is `[general]`, which is why it worked and the other one
# did not, and why one working key is not evidence for its neighbour.
#
# Checked against the installed build rather than guessed, and it is cheap to
# check again: xemu takes `-config_path`, so pointing it at a scratch file and
# reading stderr names every key it did not recognise, without touching the real
# configuration or needing a display.
#
#   flatpak run app.xemu.xemu -config_path /path/to/scratch.toml
_XEMU_SETUP = {
    "format": emu_config.TOML_KEYS,
    "label": "interface",
    #   1  the menu bar and the welcome panel kept off the game
    #   2  ... except the menu bar was written to a table xemu does not read.
    #      Moved to [display.ui], with the notifications and the cursor.
    "version": 2,
    "path": _XEMU_TOML,
    "sections": {
        "general": {
            # `raw`, because these are TOML booleans. Quoted, they would be the
            # string "false", which is true.
            "show_welcome": {"value": "false", "default": "true", "raw": True},
        },
        "display.ui": {
            "show_menubar": {"value": "false", "default": "true", "raw": True},
            "show_notifications": {
                "value": "false", "default": "true", "raw": True},
            "hide_cursor": {"value": "true", "default": "false", "raw": True},
        },
    },
}


def _xemu_path(key):
    """Point one `[sys.files]` key at whatever was just installed."""
    return {
        "path": _XEMU_TOML,
        "section": "sys.files",
        "key": key,
        "format": emu_config.TOML_KEYS,
    }


# All three land in xemu's own data directory rather than staying in the
# transfer folder, because a flatpak reads what is inside its sandbox and
# nothing here should depend on which host paths xemu's manifest happens to
# grant.
_XEMU_FIRMWARE = [
    {
        # Told apart by size, not by name. Both files are a .bin under whatever
        # the dumper called them -- there is no convention to match on -- but an
        # MCPX boot ROM is exactly 512 bytes and a BIOS never is. The file says
        # which it is, which is better than asking the user to rename it.
        "name": "MCPX boot ROM",
        "note": "Dumped from your own Xbox. 512 bytes exactly.",
        "match": r"(?i)^.*\.bin$",
        "sizes": [512],
        "expects": "The 512-byte MCPX boot ROM, under any name.",
        "dest": _XEMU_DATA,
        "configure": _xemu_path("bootrom_path"),
    },
    {
        "name": "Xbox BIOS",
        "note": "Dumped from your own Xbox, or one of the community BIOSes.",
        "match": r"(?i)^.*\.bin$",
        # The three sizes a real Xbox BIOS comes in: 256KB, 512KB and 1MB.
        "sizes": [262144, 524288, 1048576],
        "expects": "A 256KB, 512KB or 1MB BIOS image, under any name.",
        "dest": _XEMU_DATA,
        "configure": _xemu_path("flashrom_path"),
    },
    {
        # The one prerequisite here that is nobody's dump. It is an empty
        # formatted disk, published by xemu's own project, and it is the reason
        # this row can offer a button where the other two ask for a file: there
        # is nothing of Microsoft's in it and nothing to copy off a console.
        "name": "Xbox hard disk image",
        "note": "A blank formatted disk. Not a dump -- this one can be fetched.",
        "match": r"(?i)^xbox_hdd\.qcow2$",
        "expects": "xbox_hdd.qcow2, which the button below downloads.",
        "dest": _XEMU_DATA,
        "configure": _xemu_path("hdd_path"),
        "fetch": {
            "kind": "github",
            "repo": "xemu-project/xemu-hdd-image",
            "asset": r"^xbox_hdd\.qcow2\.zip$",
            # 68KB zipped, because an empty disk compresses to almost nothing.
            "extract": r"(?i)^xbox_hdd\.qcow2$",
        },
    },
]


# button_home is deliberately left on its keyboard default. The Guide button is
# the only sensible pad target for it and Steam takes that button on a Deck --
# the same reason RetroArch's autoconfig menu binding never arrives (section 5).

# The floor under every catalog system: formats this plugin states outright,
# which derivation then widens. Keyed on the same string an entry puts in
# `databases` or `platform`.
#
# This used to hold only the five systems libretro has no core for, and deriving
# the rest was treated as reliable. It is not. A real Deck refused to register
# Cemu because its cached info.zip -- four days old, so still inside the TTL and
# never re-fetched -- had no "Nintendo - Wii U" database at all; libretro had
# added it days earlier. Nothing was broken, nothing was offline, and the answer
# still came back empty, leaving the user told to type extensions by hand. That
# is the one thing this catalog exists to avoid, so no entry may depend on the
# derived list to be usable at all.
#
# Every system an entry claims therefore needs a line here, which
# `extensions_for` tests. Keeping them is cheap: these are container formats and
# they do not move. Erring wide is deliberate -- extensions only decide which
# emulators are *offered* for a ROM, so a surplus one is a shrug while a missing
# one makes a ROM look unplayable.
#
# These are not the whole truth for every system: RPCS3 and Vita3K really run a
# directory (PS3_GAME/USRDIR/EBOOT.BIN, or an installed title), and the entry for
# each says so in `note`. What is listed is what the ROM picker can be pointed at
# and have something happen.

ENTRY = {
    "id": "xemu",
    "name": "xemu",
    "summary": "Original Xbox.",
    "source": {"kind": "flatpak", "id": "app.xemu.xemu"},
    "databases": ["Microsoft - Xbox"],
    "args": "-dvd_path {rom}",
    "fullscreen_args": "-full-screen",
    "verified": True,
    # The setup block deliberately binds no pad, which is a finding rather
    # than an omission: xemu does it itself. Launched from Steam on a real
    # Deck it wrote `port1 = '030079f6de280000ff11000001000000'` with nobody
    # touching anything -- the same guid _STEAM_PAD_GUID holds, arrived at
    # independently. Auto-binding also handles the case a hardcoded value
    # cannot: run outside Steam it binds the Deck's own controller instead.
    "setup": _XEMU_SETUP,
    "firmware": _XEMU_FIRMWARE,
}
