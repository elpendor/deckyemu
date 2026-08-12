import emu_config

_PCSX2_PAD = {
    emu_config.ANCHOR: {"key": "Up", "defaults": ("Keyboard/Up",)},
    "Type": "DualShock2",
    "Deadzone": "0.000000",
    "AxisScale": "1.330000",
    "LargeMotorScale": "1.000000",
    "SmallMotorScale": "1.000000",
    "PressureModifier": "0.5",
    "Up": "SDL-0/DPadUp",
    "Right": "SDL-0/DPadRight",
    "Down": "SDL-0/DPadDown",
    "Left": "SDL-0/DPadLeft",
    "Triangle": "SDL-0/Y",
    "Circle": "SDL-0/B",
    "Cross": "SDL-0/A",
    "Square": "SDL-0/X",
    "Select": "SDL-0/Back",
    "Start": "SDL-0/Start",
    "L1": "SDL-0/LeftShoulder",
    "L2": "SDL-0/+LeftTrigger",
    "R1": "SDL-0/RightShoulder",
    "R2": "SDL-0/+RightTrigger",
    "L3": "SDL-0/LeftStick",
    "R3": "SDL-0/RightStick",
    "LUp": "SDL-0/-LeftY",
    "LRight": "SDL-0/+LeftX",
    "LDown": "SDL-0/+LeftY",
    "LLeft": "SDL-0/-LeftX",
    "RUp": "SDL-0/-RightY",
    "RRight": "SDL-0/+RightX",
    "RDown": "SDL-0/+RightY",
    "RLeft": "SDL-0/-RightX",
    "Analog": "SDL-0/Guide",
    "LargeMotor": "SDL-0/LargeMotor",
    "SmallMotor": "SDL-0/SmallMotor",
}

_PCSX2_SETUP = {
    "format": emu_config.PLAIN_INI,
    "label": "controller bindings",
    #   1  Pad1 bound to the Deck
    #   2  the setup wizard answered, and PCSX2's keyboard defaults recognised
    #      as replaceable after its first run overwrote the pad
    "version": 2,
    "files": {
        ".var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini": {
            # PCSX2 runs a setup wizard until this says otherwise, and a wizard
            # is a modal a gamepad cannot complete -- it stops a game launched
            # from Steam before it starts, and its first run rewrites the whole
            # config, which is what wiped the pad bindings below.
            "UI": {"SetupWizardIncomplete": {"value": "false", "default": "true"}},
            # Without SDL as an input source the bindings above address nothing.
            # `false` is stated as replaceable rather than assuming the default:
            # PCSX2 decides it per platform at runtime.
            "InputSources": {"SDL": {"value": "true", "default": "false"}},
            "Pad1": _PCSX2_PAD,
        },
    },
}
# Fullscreen is not here: PCSX2 takes `-fullscreen` on the command line and the
# launch recipe already passes it. Working configs leave StartFullscreen false
# for the same reason.

ENTRY = {
    "id": "pcsx2",
    "name": "PCSX2",
    "summary": "PlayStation 2.",
    "source": {"kind": "flatpak", "id": "net.pcsx2.PCSX2"},
    "databases": ["Sony - PlayStation 2"],
    # -nogui hides the main window, which otherwise appears for a second
    # before the game does, and PCSX2's own help says it implies batch mode
    # -- so quitting the game exits rather than dropping back to the game
    # list, which for a Steam shortcut means Steam keeps counting playtime
    # against a game nobody is playing.
    "args": "-nogui -- {rom}",
    "fullscreen_args": "-fullscreen",
    "recipe": 2,
    "setup": _PCSX2_SETUP,
    "verified": True,
    "firmware": [
        {
            "name": "PS2 BIOS",
            "note": "PCSX2 will not start a game without one. Dump it from your own console.",
            # A PS2 BIOS is scph + *five* digits; the PS1's is four, and both
            # are called scph*.bin. That digit count is the only thing
            # separating a DuckStation BIOS from a PCSX2 one by name.
            # The companion files are part of the same dump and PCSX2 wants
            # them beside it.
            "match": r"(?i)^scph[-_]?\d{5}.*\.(bin|mec|nvm|rom0|rom1|rom2|erom)$",
            "expects": "Named scph plus five digits, e.g. scph39001.bin. Send the .mec, .nvm, .rom0, .rom1, .rom2 and .erom files from the same dump too.",
            "dest": ".var/app/net.pcsx2.PCSX2/config/PCSX2/bios",
        }
    ],
}
