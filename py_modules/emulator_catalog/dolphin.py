import emu_config

_DOLPHIN_CONFIG = ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu"

# Dolphin has no fullscreen flag either -- the launch recipe comment in
# `emulators.LAUNCH_HINTS` says so and it was never joined up -- and it does not
# auto-map a pad: every working config writes an explicit `Device` line, which is
# not something an emulator that detected its own controller would need.
#
# The bindings come from a tested config, verbatim. Dolphin names buttons by
# compass point (`Button E` is the east/right face button), so the same positional
# argument as Azahar is already baked into them: GameCube A sits on the right,
# which is where the Deck prints B.
#
# `SDL/0/Steam Deck Controller` is the device string, and that name is the one
# SDL reported on a real Deck under Steam Input -- the same identity the Azahar
# GUID resolves to. Only GCPad1 is written; a second player needs a second
# controller, and Dolphin can map that itself.
# Dolphin writes its own default bindings the first time it runs, so a profile
# has to be judged as a whole: `Device` still pointing at the X11 pointer means
# nobody has configured it, whatever the sixty binding lines under it say.
_DOLPHIN_DEFAULT_DEVICES = (
    "",
    "XInput2/0/Virtual core pointer",
    "DInput/0/Keyboard Mouse",
)

_DOLPHIN_PAD = {
    emu_config.ANCHOR: {"key": "Device", "defaults": _DOLPHIN_DEFAULT_DEVICES},
    "Device": "SDL/0/Steam Deck Controller",
    "Buttons/A": "`Button E`",
    "Buttons/B": "`Button S`",
    "Buttons/X": "`Button N`",
    "Buttons/Y": "`Button W`",
    "Buttons/Z": "`Shoulder R`",
    "Buttons/Start": "Start",
    "Main Stick/Up": "`Axis 1-`",
    "Main Stick/Down": "`Axis 1+`",
    "Main Stick/Left": "`Axis 0-`",
    "Main Stick/Right": "`Axis 0+`",
    "Main Stick/Modifier": "`Thumb L`",
    "Main Stick/Modifier/Range": "50.",
    "Main Stick/Calibration": (
        "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42"
    ),
    "C-Stick/Up": "`Axis 4-`",
    "C-Stick/Down": "`Axis 4+`",
    "C-Stick/Left": "`Axis 3-`",
    "C-Stick/Right": "`Axis 3+`",
    "C-Stick/Modifier": "`Thumb R`",
    "C-Stick/Modifier/Range": "50.",
    "C-Stick/Calibration": (
        "100.00 141.42 100.00 141.42 100.00 141.42 100.00 141.42"
    ),
    "Triggers/L": "`Trigger L`",
    "Triggers/R": "`Trigger R`",
    "Triggers/L-Analog": "`Trigger L`",
    "Triggers/R-Analog": "`Trigger R`",
    "D-Pad/Up": "`Pad N`",
    "D-Pad/Down": "`Pad S`",
    "D-Pad/Left": "`Pad W`",
    "D-Pad/Right": "`Pad E`",
    "Rumble/Motor": "Strong",
}

# Wii is a separate file with a separate device, and GCPadNew.ini does nothing
# for it -- so "GameCube works" says nothing about whether a Wii game does.
#
# Also from that config, verbatim, minus the Classic-controller keys, which only
# apply when Extension is Classic and this profile uses Nunchuk.
#
# Two parts are worth knowing about because they look wrong otherwise. The IR
# pointer is bound to the X11 cursor, which is how the right trackpad aims:
# Steam Input drives the pointer and Dolphin reads it. And `Accel`/`Gyro` are
# the Deck's own motion sensors, so pointer-and-waggle games work without a real
# Wiimote.
_DOLPHIN_WIIMOTE = {
    emu_config.ANCHOR: {"key": "Device", "defaults": _DOLPHIN_DEFAULT_DEVICES},
    "Device": "SDL/0/Steam Deck Controller",
    "Buttons/A": "`Button S`|`Thumb R`|`XInput2/0/Virtual core pointer:Click 1`",
    "Buttons/B": "`Button E`",
    "Buttons/1": "`Button N`",
    "Buttons/2": "`Button W`",
    "Buttons/-": "Back",
    "Buttons/+": "Start",
    "Buttons/Home": "Return",
    "D-Pad/Up": "`Pad N`",
    "D-Pad/Down": "`Pad S`",
    "D-Pad/Left": "`Pad W`",
    "D-Pad/Right": "`Pad E`",
    "IR/Vertical Offset": "12.",
    "IR/Total Yaw": "19.",
    "IR/Total Pitch": "22.",
    "IR/Auto-Hide": "True",
    "IR/Up": "`XInput2/0/Virtual core pointer:Cursor Y-`",
    "IR/Down": "`XInput2/0/Virtual core pointer:Cursor Y+`",
    "IR/Left": "`XInput2/0/Virtual core pointer:Cursor X-`",
    "IR/Right": "`XInput2/0/Virtual core pointer:Cursor X+`",
    "IR/Hide": "`Thumb L`",
    "IR/Calibration": (
        "100.00 101.96 108.24 112.67 116.44 114.62 108.11 101.96 100.00 101.96 "
        "108.11 113.10 115.81 113.90 108.24 101.96 100.00 101.96 108.24 114.93 "
        "115.13 115.19 108.24 101.96 100.00 101.96 108.13 112.88 112.20 110.97 "
        "108.24 101.96"
    ),
    "Shake/X": "`Shoulder L`",
    "Shake/Y": "`Shoulder L`",
    "Shake/Z": "`Shoulder L`",
    "Tilt/Forward": "`Trigger L`&`Left Y+`",
    "Tilt/Backward": "`Trigger L`&`Left Y-`",
    "Tilt/Left": "`Trigger L`&`Left X-`",
    "Tilt/Right": "`Trigger L`&`Left X+`",
    "Tilt/Modifier/Range": "50.",
    "IMUIR/Enabled": "False",
    "IMUAccelerometer/Up": "`Accel Up`",
    "IMUAccelerometer/Down": "`Accel Down`",
    "IMUAccelerometer/Left": "`Accel Left`",
    "IMUAccelerometer/Right": "`Accel Right`",
    "IMUAccelerometer/Forward": "`Accel Forward`",
    "IMUAccelerometer/Backward": "`Accel Backward`",
    "IMUGyroscope/Pitch Up": "`Gyro Pitch Up`",
    "IMUGyroscope/Pitch Down": "`Gyro Pitch Down`",
    "IMUGyroscope/Roll Left": "`Gyro Roll Left`",
    "IMUGyroscope/Roll Right": "`Gyro Roll Right`",
    "IMUGyroscope/Yaw Left": "`Gyro Yaw Left`",
    "IMUGyroscope/Yaw Right": "`Gyro Yaw Right`",
    "Hotkeys/Sideways Toggle": "Back&`Thumb R`",
    "Extension": "Nunchuk",
    "Nunchuk/Buttons/C": "`Shoulder R`",
    "Nunchuk/Buttons/Z": "`Trigger R`",
    "Nunchuk/Stick/Up": "`Axis 1-`",
    "Nunchuk/Stick/Down": "`Axis 1+`",
    "Nunchuk/Stick/Left": "`Axis 0-`",
    "Nunchuk/Stick/Right": "`Axis 0+`",
    "Nunchuk/Stick/Modifier/Range": "50.",
    "Nunchuk/Stick/Calibration": (
        "100.00 101.96 107.70 111.02 112.30 107.98 106.91 101.96 100.00 101.96 "
        "108.24 113.14 114.55 111.79 108.24 101.96 100.00 101.96 108.24 113.60 "
        "114.92 113.33 108.24 101.96 100.00 101.96 108.24 110.60 109.10 108.88 "
        "108.24 101.96"
    ),
    "Nunchuk/Shake/X": "`Full Axis 2+`",
    "Nunchuk/Shake/Y": "`Full Axis 2+`",
    "Nunchuk/Shake/Z": "`Full Axis 2+`",
    "Nunchuk/Tilt/Modifier/Range": "50.",
    "Rumble/Motor": "Strong",
    "Options/Upright Wiimote": "`Trigger L`",
}

# Reading SetDefaultControllerConfig suggested PCSX2 writes no bindings at all
# -- it clears the section and sets `Type` -- but a real install disagreed: the
# first run rewrote the whole file with keyboard defaults, `Up = Keyboard/Up`
# and the rest, wiping the bindings written at install time. So `Keyboard/Up` is
# listed as a default the anchor may replace, or the pad would be skipped
# forever exactly the way Dolphin's Wiimote was. Source told half the story;
# the device told the other half.
#
# Tested bindings again, and the mapping is the plain one -- PS2 and Xbox face
# buttons sit in the same places, so Cross is A and Circle is B with no
# positional argument to make.

_DOLPHIN_SETUP = {
    "format": emu_config.PLAIN_INI,
    "label": "controller bindings and fullscreen",
    #   1  fullscreen, and GCPad1 bound to the Deck
    #   2  Wiimote1 as well -- GameCube working said nothing about Wii, which
    #      reads from a different file and was left unconfigured
    #   3  profiles judged by their Device line, since Dolphin had already
    #      written its own bindings and every key was skipped one at a time;
    #      and the analytics prompt answered
    #   4  Dolphin's own on-screen messages off
    "version": 4,
    "files": {
        # `False` is Dolphin's own default, so it is stated as replaceable.
        # Anything else there was chosen by somebody and is left alone.
        "%s/Dolphin.ini" % _DOLPHIN_CONFIG: {
            "Display": {"Fullscreen": {"value": "True", "default": "False"}},
            # Dolphin asks, on first run, whether it may report usage data. The
            # dialog is modal and a gamepad cannot dismiss it, so it stops a
            # game launched from Steam before it starts. Answering it here says
            # no: PermissionAsked stops the prompt, Enabled states the answer
            # rather than leaving it to a default that could change.
            "Analytics": {
                "Enabled": {"value": "False", "default": "True"},
                "PermissionAsked": {"value": "True", "default": "False"},
            },
            # The messages Dolphin writes into the top-left corner of the game
            # -- its version on startup, controller connections, save states,
            # speed changes. On a desktop they are a status line; on a game
            # launched from Steam they are text over the first seconds of
            # somebody's game, saying things they did not ask about and cannot
            # act on. The same argument as RetroArch's on-screen chatter, which
            # this plugin turns off by default for the same reason.
            #
            # `[Interface] OnScreenDisplayMessages` confirmed twice: the string
            # is in the installed binary, and RetroDECK's own Deck-tested
            # Dolphin.ini carries it in that section beside ShowActiveTitle and
            # UsePanicHandlers. True is Dolphin's default, so anything else in
            # there was chosen by somebody and is left alone.
            "Interface": {"OnScreenDisplayMessages": {"value": "False", "default": "True"}},
        },
        "%s/GCPadNew.ini" % _DOLPHIN_CONFIG: {"GCPad1": _DOLPHIN_PAD},
        "%s/WiimoteNew.ini" % _DOLPHIN_CONFIG: {"Wiimote1": _DOLPHIN_WIIMOTE},
    },
}


# xemu keeps its settings in a TOML file inside its flatpak data directory, and
# the three files it cannot start without are three paths in it. Read off a Deck
# from a config xemu wrote itself, not from its source.
# shadPS4 finds installed games through the folders in `install_dirs`, and ships
# with that list empty -- so a freshly unpacked game is invisible to it until
# somebody adds the folder by hand. This points it at where this plugin unpacks,
# so the emulator's own list and the panel's always agree.
#
# `{ps4games}` rather than a literal path: the catalog is evaluated at import and
# the home directory is not known then. Config keys read off a Deck's own
# config.json, not from source.

ENTRY = {
    "id": "dolphin",
    "name": "Dolphin",
    "summary": "GameCube and Wii.",
    "source": {"kind": "flatpak", "id": "org.DolphinEmu.dolphin-emu"},
    "databases": ["Nintendo - GameCube", "Nintendo - Wii"],
    # -b exits when the game stops rather than dropping back to the game
    # list; -e picks the file. Fullscreen is a config setting, not a flag,
    # which is what `setup` is for.
    "args": "-b -e {rom}",
    "fullscreen_args": "",
    "setup": _DOLPHIN_SETUP,
    "verified": True,
    "firmware": [],
}
