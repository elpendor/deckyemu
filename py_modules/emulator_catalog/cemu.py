import emu_config
from .steam_pad import _STEAM_PAD_GUID

_CEMU_CONFIG = ".var/app/info.cemu.Cemu/config/Cemu"

# Cemu writes SDL axes into the same numbering as its buttons: the positive half
# of axis N is 38+N, the negative half 44+N. Every value in a known-good Deck
# profile decodes cleanly against this, which is why the table below could be
# generated from Cemu's own enum rather than copied out of a file.
_CEMU_AXIS_POSITIVE = 38
_CEMU_AXIS_NEGATIVE = 44


def _cemu_axis(index, negative=False):
    return (_CEMU_AXIS_NEGATIVE if negative else _CEMU_AXIS_POSITIVE) + index


# VPADController::ButtonId, which starts at 1 because 0 is kButtonId_None,
# against SDL's button indices.
#
# The face buttons are crossed on purpose. Wii U puts A on the right and B at the
# bottom, where SDL puts B and A -- so Cemu's A takes SDL button 1 and its B
# takes 0. Same reasoning as Dolphin's GameCube pad; getting it "obvious" instead
# would swap confirm and cancel in every game.
#
# Cemu's Mic button is left unbound. A published profile gives it SDL button 8,
# which is also the right stick click, so blowing into the GamePad mic would fire
# every time the stick is pressed.
_CEMU_MAPPINGS = (
    (1, 1),                       # A       <- SDL B, the right face button
    (2, 0),                       # B       <- SDL A, the bottom one
    (3, 3),                       # X       <- SDL Y, the top one
    (4, 2),                       # Y       <- SDL X, the left one
    (5, 9),                       # L       <- left shoulder
    (6, 10),                      # R       <- right shoulder
    (7, _cemu_axis(4)),           # ZL      <- left trigger
    (8, _cemu_axis(5)),           # ZR      <- right trigger
    (9, 6),                       # Plus    <- start
    (10, 4),                      # Minus   <- back
    (11, 11),                     # Up
    (12, 12),                     # Down
    (13, 13),                     # Left
    (14, 14),                     # Right
    (15, 7),                      # StickL click
    (16, 8),                      # StickR click
    (17, _cemu_axis(1, True)),    # StickL up
    (18, _cemu_axis(1)),          # StickL down
    (19, _cemu_axis(0, True)),    # StickL left
    (20, _cemu_axis(0)),          # StickL right
    (21, _cemu_axis(3, True)),    # StickR up
    (22, _cemu_axis(3)),          # StickR down
    (23, _cemu_axis(2, True)),    # StickR left
    (24, _cemu_axis(2)),          # StickR right
)


def _cemu_profile():
    """Cemu's `controller0.xml`, the profile it loads for player one."""
    entries = "\n".join(
        "\t\t\t<entry>\n"
        "\t\t\t\t<mapping>%d</mapping>\n"
        "\t\t\t\t<button>%d</button>\n"
        "\t\t\t</entry>" % pair
        for pair in _CEMU_MAPPINGS
    )
    # The uuid is the SDL joystick index joined to the pad's GUID -- the same
    # Steam Virtual Gamepad every emulator here binds against.
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<emulated_controller>\n"
        "\t<type>Wii U GamePad</type>\n"
        "\t<profile>DeckyEmu</profile>\n"
        "\t<controller>\n"
        "\t\t<api>SDLController</api>\n"
        "\t\t<uuid>0_%s</uuid>\n"
        "\t\t<display_name>Steam Virtual Gamepad</display_name>\n"
        "\t\t<rumble>0</rumble>\n"
        "\t\t<axis>\n\t\t\t<deadzone>0.25</deadzone>\n\t\t\t<range>1</range>\n\t\t</axis>\n"
        "\t\t<rotation>\n\t\t\t<deadzone>0.25</deadzone>\n\t\t\t<range>1</range>\n\t\t</rotation>\n"
        "\t\t<trigger>\n\t\t\t<deadzone>0.25</deadzone>\n\t\t\t<range>1</range>\n\t\t</trigger>\n"
        "\t\t<mappings>\n%s\n\t\t</mappings>\n"
        "\t</controller>\n"
        "</emulated_controller>\n" % (_STEAM_PAD_GUID, entries)
    )


# Cemu decides it is starting for the first time like this, at the tag installed
# here (CemuApp.cpp, v2.6):
#
#     bool isFirstStart = !fs::exists(ActiveSettings::GetConfigPath("settings.xml"), ec);
#
# and if it is, shows the Getting Started dialog -- modal, unanswerable with a
# gamepad, in front of a game Steam just launched. So *writing this file at all*
# is what settles it. `gp_download` is the setting the name suggests, and Cemu's
# own source says it is "no longer used ... Despite the name this was used for
# the Getting Started dialog": setting it would have looked right and done
# nothing.
#
# The two values that are still live:
#   check_update  defaults true, and its prompt is a link nobody can follow here
#   vk_warning    is did_show_vulkan_warning, defaults false, so true means the
#                 Vulkan warning has been seen and is not shown again
# Writing this file has a cost that is not obvious: for several keys, Cemu's
# loader falls back to a *different* value than the one the setting is declared
# with, and it assigns unconditionally. So a value being absent from our file
# does not leave Cemu's own default in place -- it replaces it.
#
#   std::wstring tv_device{ L"default" };        // what Cemu means by default
#   const auto tv = audio.get("TVDevice", "");   // what an absent key gives
#   tv_device = boost::nowide::widen(tv);        // assigned either way
#
# An empty device name selects no audio output at all, which is why a game
# booted with picture and no sound. Cemu's own saves always write every key, so
# this can only ever bite a partial file -- that is, ours.
#
# Everything below therefore restates a Cemu default rather than choosing
# anything. They look redundant and are not:
#
#   TVDevice     "default" is a real identifier -- Cemu's cubeb backend inserts
#                a "Default Device" under exactly that name -- while "" means
#                none, and CreateDeviceFromConfig returns silently on empty
#   Graphic/api  graphic_api{kVulkan}, but an absent key gives kOpenGL, quietly
#                downgrading the renderer
#   TVVolume     tv_volume = 50, but an absent key gives 20
#   InputVolume  input_volume = 50, but an absent key gives 20
#
# Audio/api is not that pattern -- it is worse. It defaults to 0 honestly, but
# the enum is `DirectSound = 0, XAudio27, XAudio2, Cubeb`, and the first three
# are Windows-only. So on Linux the configured API is one that does not exist,
# `IsAudioAPIAvailable` is false, the device list is never queried and the lookup
# throws "failed to find selected device". Nothing corrects it at startup: the
# only place audio_api is ever assigned is the Settings dialog, so out of the box
# Cemu on Linux has sound only after somebody opens it in Desktop Mode and picks
# an API by hand. 3 is Cubeb, which is the one its own log reports as available.
#
# Left alone knowingly: UpscaleFilter, declared kBicubicFilter and defaulting to
# kBicubicHermiteFilter when absent. Both are bicubic; the difference is a little
# sharpening, and it is not worth pinning an enum value this file cannot check.
_CEMU_SETTINGS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<content>\n"
    "\t<check_update>false</check_update>\n"
    "\t<vk_warning>true</vk_warning>\n"
    "\t<Graphic>\n"
    "\t\t<api>1</api>\n"
    "\t</Graphic>\n"
    "\t<Audio>\n"
    "\t\t<api>3</api>\n"
    "\t\t<TVDevice>default</TVDevice>\n"
    "\t\t<TVVolume>50</TVVolume>\n"
    "\t\t<InputVolume>50</InputVolume>\n"
    "\t</Audio>\n"
    "</content>\n"
)

_CEMU_SETUP = {
    "format": emu_config.WHOLE_FILE,
    "label": "controller bindings",
    #   1  controller profile, and the first-run dialogs answered
    #   2  the defaults our own settings.xml was displacing, restated -- an
    #      absent TVDevice selected no audio output, so games ran silent
    #   3  the audio API set to Cubeb. Restoring TVDevice was not enough: the
    #      API still pointed at Windows-only DirectSound, so the device lookup
    #      threw and games were still silent
    "version": 3,
    "files": {
        "%s/settings.xml" % _CEMU_CONFIG: _CEMU_SETTINGS,
        "%s/controllerProfiles/controller0.xml" % _CEMU_CONFIG: _cemu_profile(),
    },
}


# Read off a real install rather than guessed at. `flatpak run` under
# QT_QPA_PLATFORM=offscreen writes the whole default settings.ini before it fails
# to open a window, so every default below is what DuckStation itself put there:
# `Up = Keyboard/Up`, `SetupWizardIncomplete = true`, `ConfirmPowerOff = true`.
#
# That also settled where its data lives. DuckStation follows XDG_CONFIG_HOME,
# not XDG_DATA_HOME, so everything -- settings, memory cards, bios -- is under
# `config/duckstation`, and the firmware destination below was pointing at a
# `data/duckstation` that is never created.

ENTRY = {
    "id": "cemu",
    "name": "Cemu",
    "summary": "Wii U.",
    "source": {"kind": "flatpak", "id": "info.cemu.Cemu"},
    "databases": ["Nintendo - Wii U"],
    "args": "-g {rom}",
    "fullscreen_args": "--fullscreen",
    "setup": _CEMU_SETUP,
    "verified": True,
    "firmware": [
        {
            "name": "Wii U title keys (keys.txt)",
            "note": "Cemu cannot decrypt a WUD or WUX disc image without the key for it.",
            "match": r"(?i)^keys\.txt$",
            "expects": "A file called keys.txt, one 32-character key per line. Lines starting with # are comments.",
            # GetUserDataPath, not the config path settings.xml lives in --
            # confirmed against Cemu 2.6 and against the file it created on
            # a real device.
            "dest": ".var/app/info.cemu.Cemu/data/Cemu",
            # Cemu writes this file itself the first time it starts, so it
            # exists long before the user has supplied anything. Without
            # saying which contents are Cemu's own, the panel would report
            # the placeholder as in place and never offer to send a real one.
            "stub": {
                "empty": r"^\s*(?:[#;].*)?$",
                # The one example key Cemu writes, and labels "can be
                # deleted" in its own comment.
                "written": (r"^\s*541b9889519b27d363cd21604b97c67a\b",),
            },
        }
    ],
}
