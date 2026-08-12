import emu_config

_DUCKSTATION_CONFIG = ".var/app/org.duckstation.DuckStation/config/duckstation"

# Same input manager as PCSX2, so the same binding syntax and the same anchor
# key. Cross is A and Circle is B: PlayStation and Xbox face buttons sit in the
# same places, so there is no positional argument to make.
#
# `Analog` is deliberately left unbound. The only pad button worth it is Guide,
# Steam takes that one on a Deck, and DuckStation defaults ForceAnalogOnReset to
# true -- so analog mode is already on and a binding that might fire by accident
# could only turn it off mid-game.
_DUCKSTATION_PAD = {
    emu_config.ANCHOR: {"key": "Up", "defaults": ("Keyboard/Up",)},
    "Type": "AnalogController",
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
    "R1": "SDL-0/RightShoulder",
    "L2": "SDL-0/+LeftTrigger",
    "R2": "SDL-0/+RightTrigger",
    "L3": "SDL-0/LeftStick",
    "R3": "SDL-0/RightStick",
    "LLeft": "SDL-0/-LeftX",
    "LRight": "SDL-0/+LeftX",
    "LDown": "SDL-0/+LeftY",
    "LUp": "SDL-0/-LeftY",
    "RLeft": "SDL-0/-RightX",
    "RRight": "SDL-0/+RightX",
    "RDown": "SDL-0/+RightY",
    "RUp": "SDL-0/-RightY",
    "SmallMotor": "SDL-0/SmallMotor",
    "LargeMotor": "SDL-0/LargeMotor",
}

_DUCKSTATION_SETUP = {
    "format": emu_config.PLAIN_INI,
    "label": "controller bindings",
    #   1  Pad1 bound to the Deck, the setup wizard answered
    #   2  the update check switched off
    "version": 2,
    "files": {
        "%s/settings.ini" % _DUCKSTATION_CONFIG: {
            # DuckStation checks GitHub for a release on every start and puts the
            # result in a dialog in front of the game. Nothing on the other side
            # of that dialog can be acted on from Game Mode -- updating is the
            # plugin's job, not a link the user cannot follow.
            "AutoUpdater": {"CheckAtStartup": {"value": "false", "default": "true"}},
            "Main": {
                # The same wizard PCSX2 runs, and the same problem: a modal no
                # gamepad can complete, in front of a game Steam just launched.
                "SetupWizardIncomplete": {"value": "false", "default": "true"},
                # Quitting otherwise asks "are you sure", which for a Steam
                # shortcut means the game never stops on the first try.
                "ConfirmPowerOff": {"value": "false", "default": "true"},
            },
            # Already DuckStation's own default, unlike PCSX2's -- stated anyway
            # so the bindings below cannot end up addressing nothing.
            "InputSources": {"SDL": {"value": "true", "default": "true"}},
            "Pad1": _DUCKSTATION_PAD,
        },
    },
}
# Fullscreen is not here: `-fullscreen` on the command line already does it.


# PPSSPP needs no bindings. Its own defaults already map pad device 10 -- D-pad,
# all four face buttons, Start, Select, both shoulders and the analog stick --
# and a freshly generated controls.ini confirmed it. So the only thing worth
# writing is the update check, which on a Deck in Game Mode is a network call on
# every launch and a banner offering a download nobody can act on from there.

ENTRY = {
    "id": "duckstation",
    "name": "DuckStation",
    "summary": "PlayStation 1.",
    "source": {"kind": "flatpak", "id": "org.duckstation.DuckStation"},
    "databases": ["Sony - PlayStation"],
    # -nogui, in DuckStation's own words, "disables main window from being
    # shown, exits on shutdown" -- the same two problems it solves for PCSX2.
    "args": "-nogui -- {rom}",
    "fullscreen_args": "-fullscreen",
    "recipe": 2,
    "setup": _DUCKSTATION_SETUP,
    "verified": True,
    "firmware": [
        {
            "name": "PS1 BIOS",
            "note": "Optional, but compatibility is better with one.",
            # Four digits, where the PS2's has five -- see the PCSX2 entry.
            "match": r"(?i)^scph[-_]?\d{4}\.(bin|rom)$",
            "expects": "Named scph plus four digits, e.g. scph1001.bin. Five digits is a PS2 BIOS and goes to PCSX2 instead.",
            "dest": "%s/bios" % _DUCKSTATION_CONFIG,
        }
    ],
}
