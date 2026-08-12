import emu_config
from .steam_pad import _STEAM_PAD_GUID

_RPCS3_CONFIG = ".config/rpcs3"

# RPCS3 is the one emulator here that names the pad instead of fingerprinting
# it: its evdev handler matches on the string the kernel reports, which for
# Steam Input's virtual gamepad is this. Read off a Deck's own
# /proc/bus/input/devices, and the same string SDL checksums to reach the guid
# every other entry binds against -- crc16("Microsoft X-Box 360 pad 0") is the
# 79 f6 sitting inside _STEAM_PAD_GUID. Steam appends the index, so a second pad
# would be "pad 1"; player one is the only one bound here.
_RPCS3_PAD_DEVICE = "Microsoft X-Box 360 pad 0"

# No crossing, unlike every Nintendo target here: Cross is PlayStation's bottom
# face button and so is evdev's A, so the two layouts already agree.
_RPCS3_BINDINGS = (
    ("Left Stick Left", "LX-"),
    ("Left Stick Down", "LY+"),
    ("Left Stick Right", "LX+"),
    ("Left Stick Up", "LY-"),
    ("Right Stick Left", "RX-"),
    ("Right Stick Down", "RY+"),
    ("Right Stick Right", "RX+"),
    ("Right Stick Up", "RY-"),
    ("Start", "Start"),
    ("Select", "Select"),
    ("PS Button", "Mode"),
    ("Square", "X"),
    ("Cross", "A"),
    ("Circle", "B"),
    ("Triangle", "Y"),
    ("Left", "Hat0 X-"),
    ("Down", "Hat0 Y+"),
    ("Right", "Hat0 X+"),
    ("Up", "Hat0 Y-"),
    ("R1", "TR"),
    ("R2", "RZ+"),
    ("R3", "Thumb R"),
    ("L1", "TL"),
    ("L2", "LZ+"),
    ("L3", "Thumb L"),
)

# Everything after the bindings, restated because this file is written whole:
# a key left out of it is not a key left alone, it is a key set to whatever
# RPCS3 falls back to. The values are an evdev pad's own defaults as a
# Deck-tested RPCS3 writes them. The emulated device stays a DualShock 3
# (0x054c:0x0268, in decimal here because that is how RPCS3 stores it) -- that
# describes the pad the PS3 game sees, not the one in your hands.
_RPCS3_PAD_TAIL = """\
    Motion Sensor X:
      Axis: X
      Mirrored: false
      Shift: 0
    Motion Sensor Y:
      Axis: Y
      Mirrored: false
      Shift: 0
    Motion Sensor Z:
      Axis: Z
      Mirrored: false
      Shift: 0
    Motion Sensor G:
      Axis: RX
      Mirrored: false
      Shift: 0
    Pressure Intensity Button: ""
    Pressure Intensity Percent: 50
    Left Stick Multiplier: 100
    Right Stick Multiplier: 100
    Left Stick Deadzone: 30
    Right Stick Deadzone: 30
    Left Trigger Threshold: 0
    Right Trigger Threshold: 0
    Left Pad Squircling Factor: 5000
    Right Pad Squircling Factor: 5000
    Color Value R: 0
    Color Value G: 0
    Color Value B: 20
    Blink LED when battery is below 20%: true
    Use LED as a battery indicator: false
    LED battery indicator brightness: 10
    Player LED enabled: true
    Enable Large Vibration Motor: true
    Enable Small Vibration Motor: true
    Switch Vibration Motors: false
    Mouse Movement Mode: Relative
    Mouse Deadzone X Axis: 60
    Mouse Deadzone Y Axis: 60
    Mouse Acceleration X Axis: 200
    Mouse Acceleration Y Axis: 250
    Left Stick Lerp Factor: 100
    Right Stick Lerp Factor: 100
    Analog Button Lerp Factor: 100
    Trigger Lerp Factor: 100
    Device Class Type: 0
    Vendor ID: 1356
    Product ID: 616
  Buddy Device: ""
"""

# RPCS3 keeps seven player slots and reads all of them, so the six nobody is
# holding have to be present and explicitly empty.
_RPCS3_PLAYERS = 7


def _rpcs3_player(device):
    """One `Player N Input:` block. `device` of None is an unused slot."""
    lines = [
        "  Handler: %s" % ("Evdev" if device else '"Null"'),
        "  Device: %s" % (device or '"Null"'),
        "  Config:",
    ]
    for name, value in _RPCS3_BINDINGS:
        lines.append('    %s: %s' % (name, value if device else '""'))
    return "\n".join(lines) + "\n" + _RPCS3_PAD_TAIL


def _rpcs3_pad():
    """RPCS3's `input_configs/global/Default.yml`."""
    return "".join(
        "Player %d Input:\n%s" % (player, _rpcs3_player(_RPCS3_PAD_DEVICE if player == 1 else None))
        for player in range(1, _RPCS3_PLAYERS + 1)
    )


# Which named input profile is live. RPCS3 would fall back to Default anyway,
# but only until somebody saves a second profile, and then the pad above would
# quietly stop being the one in use.
_RPCS3_ACTIVE_PROFILES = "Active Profiles:\n  global: Default\n"

# RPCS3's Qt settings, which are not in config.yml and not optional.
#
# `infoBoxEnabledWelcome` is the one that matters. RPCS3 shows a modal "Welcome
# to RPCS3" box the first time it opens a window, and it blocks everything
# behind it -- `--installfw` with a valid firmware image sat for ten minutes
# writing nothing, on a Deck, because of it. Answering it here is what lets the
# GUI be reached at all.
#
# The two explore paths are the difference between "open the file browser and
# find your firmware" and "press OK". RPCS3 reopens each picker wherever it was
# last used, so pointing them at the transfer folder means a PUP or a PKG sent
# from the panel is already on screen when the picker opens. Key names read out
# of the installed binary rather than guessed.
_RPCS3_GUI = {
    "Meta": {
        # Its prompt is a link nobody can follow from Game Mode.
        "checkUpdateStart": "false",
    },
    "main_window": {
        "infoBoxEnabledWelcome": "false",
        # Otherwise closing the game asks a question Steam has no way to answer.
        "confirmationBoxExitGame": "false",
        # Two different folders, because these are two different kinds of
        # thing. A PUP is firmware and goes where BIOS files go; a PKG *is* a
        # game -- a whole PS3 title, a couple of hundred megabytes of it -- and
        # arrives through the same transfer as any other ROM.
        #
        # The package picker opens on the staged links rather than on the ROM
        # folder itself, because RPCS3's install dialog is as wide as the
        # filename it prints: a real 101-character name made it 1539px across
        # on a 1280px screen, putting Install off the right edge where a tap
        # could never reach it. The links are named for the title id.
        "lastExplorePathPUP": emu_config.FIRMWARE_TOKEN,
        "lastExplorePathPKG": emu_config.PACKAGES_TOKEN,
    },
}
# The "installed successfully" boxes, infoBoxEnabledInstallPUP and
# ...InstallPKG, are deliberately left on: they come *after* the work and are
# the only confirmation that it happened.

_RPCS3_SETUP = {
    "format": emu_config.WHOLE_FILE,
    "label": "controller bindings",
    #   1  player one bound to the Steam pad
    #   2  the modal welcome box answered, and the firmware and package pickers
    #      pointed at the folder the panel sends files to
    #   3  the package picker moved to the ROM folder, which is where a PKG
    #      actually arrives -- it is a game, not firmware
    #   4  and then to the staged links, so the install dialog is narrow
    #      enough that its buttons are on the screen
    #   5  written to RPCS3's own paths instead of a flatpak sandbox's, since
    #      the entry now installs upstream's AppImage
    "version": 5,
    "files": {
        "%s/input_configs/global/Default.yml" % _RPCS3_CONFIG: _rpcs3_pad(),
        "%s/input_configs/active_profiles.yml" % _RPCS3_CONFIG: _RPCS3_ACTIVE_PROFILES,
        "%s/GuiConfigs/CurrentSettings.ini" % _RPCS3_CONFIG: _RPCS3_GUI,
    },
    # CurrentSettings.ini already exists and already holds the user's language,
    # so it is edited rather than supplied.
    #
    # PLAIN_INI, not QT_INI, even though Qt wrote it: QT_INI's job is the
    # `key\default=false` flag Azahar needs, and RPCS3 has no such convention --
    # writing those would leave a dozen keys it does not recognise. PLAIN_INI
    # spaces its assignments where Qt does not, which QSettings turns out to
    # accept: with `infoBoxEnabledWelcome = false` written that way, the next
    # launch reached the firmware installer instead of the welcome box.
    "formats": {
        "%s/GuiConfigs/CurrentSettings.ini" % _RPCS3_CONFIG: emu_config.PLAIN_INI,
    },
}
# Nothing from config.yml is here, and that is the finding rather than an
# omission: a headless first run writes Renderer: Vulkan, "Start games in
# fullscreen mode: true" and "Automatically start games after boot: true"
# already. The one setting worth changing, leaving the emulator when the game
# stops, is `--no-gui` on the command line instead.

ENTRY = {
    "id": "rpcs3",
    "name": "RPCS3",
    "summary": "PlayStation 3.",
    "source": {
        "kind": "github",
        "repo": "RPCS3/rpcs3-binaries-linux",
        "asset": r"^rpcs3-v.*_linux64\.AppImage$",
    },
    # Everything RPCS3 owns: firmware, unpacked games, licences, saves and
    # config, all under one directory. A flatpak needs no such list -- its
    # application id is the answer -- but an AppImage writes where it likes
    # and only the catalog can say where.
    "data": [".config/rpcs3"],
    "databases": [],
    "platform": "Sony - PlayStation 3",
    # --no-gui boots the game with no game list behind it and closes RPCS3
    # when the game stops, which is what a Steam shortcut needs. RPCS3's own
    # help says --fullscreen is "only used when no-gui is set", so the two
    # cannot be separated the way they are elsewhere here -- windowed still
    # means no GUI.
    "args": "--no-gui {rom}",
    "fullscreen_args": "--fullscreen",
    "recipe": 2,
    "setup": _RPCS3_SETUP,
    "verified": True,
    "note": "Point this at the game's PS3_GAME/USRDIR/EBOOT.BIN, not at a folder.",
    "firmware": [
        {
            "name": "PS3 firmware (PS3UPDAT.PUP)",
            "note": "Sony publish it freely, so this one can be downloaded.",
            "match": r"(?i)^PS3UPDAT\.PUP$",
            "expects": "PS3UPDAT.PUP, exactly as Sony publish it -- or press "
            "download and it is fetched from Sony.",
            # What installing created, and so what taking it back out
            # means. dev_flash holds nothing but firmware -- saves, games
            # and settings all live elsewhere -- so this is the whole of it
            # and none of the user's own.
            "removes": [".config/rpcs3/dev_flash"],
            # Sony's own update list, which is where a PS3 looks. Read each
            # time rather than pinned, because they still publish new
            # versions: it named 4.9300 at the time of writing, and a
            # hardcoded address would rot the moment that changed.
            "fetch": {
                "kind": "index",
                "index": "http://fus01.ps3.update.playstation.net"
                         "/update/ps3/list/us/ps3-updatelist.txt",
                "find": r"(https?://\S+?PS3UPDAT\.PUP)",
                "name": "PS3UPDAT.PUP",
            },
            # Not a copy: RPCS3 unpacks the PUP into its own dev_flash, and
            # `--headless` is the branch where it does that with no window
            # and no dialog. Six seconds on a Deck, start to finish.
            "import": {
                "args": ["--headless", "--installfw", "{file}"],
                # RPCS3's own record of which firmware is installed, written
                # by the unpack itself. Read off a Deck rather than guessed:
                # the first line is `release:04.9300:`.
                "installed": ".config/rpcs3/dev_flash/vsh/etc/version.txt",
                "label": r"release:0*(\d+\.\d\d)",
                # Generous: six seconds observed, but a cold SD card and a
                # firmware Sony have since grown are both possible, and the
                # cost of being wrong here is a half-finished dev_flash.
                "seconds": 600,
            },
        },
        {
            # Found the hard way: Braid installed from its package, appeared
            # in the game list, and then `Booting ... failed! Reason: Failed
            # to decrypt content`. A store game is encrypted against the
            # licence issued to the PS3 it was bought on, and without that
            # file the game is installed and unplayable -- which looks
            # exactly like a broken emulator rather than a missing file.
            #
            # Not every package needs one. Anything sold as licence-free
            # boots without it, so this row is offered rather than demanded.
            "name": "Game licences (.rap)",
            "note": "Only for store games. Dumped from your own PS3.",
            # So it does not count towards "RPCS3 is missing something".
            # Whether a licence is needed is a question about one game, not
            # about the emulator, and the add flow answers it there -- from
            # the package's own content id, which is the only place the
            # answer exists.
            "optional": True,
            "match": r"(?i)^.*\.rap$",
            # The name is not a convention, it is the whole binding: a .rap
            # is sixteen bytes of key material with nothing inside naming
            # the game it unlocks, and RPCS3 finds it by filename alone.
            # Renamed, it silently never works -- so the row says so rather
            # than letting "In place" mean a file that will never be read.
            "expects": "One .rap per game, named exactly after the game's "
            "content id -- UP4049-NPUB30133_00-BRAID00000000001.rap for "
            "Braid. The name is what RPCS3 matches on, so a renamed licence "
            "is never used. Send as many as you like at once.",
            "dest": ".config/rpcs3/dev_hdd0/home/00000001/exdata",
            # RPCS3 reads only a lowercase extension, and says so nowhere
            # until a game fails to boot. A .RAP would sit here looking
            # installed and decrypt nothing.
            "lower_ext": True,
        },
    ],
}
