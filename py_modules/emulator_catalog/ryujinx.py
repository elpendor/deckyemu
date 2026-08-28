import emu_config

_RYUJINX_CONFIG = ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx"

# Ryujinx names a pad by SDL joystick index joined to its GUID, and the GUID is
# *not* the one written everywhere else in this file. Ryujinx is C#, and .NET
# reads the first three fields of a GUID little-endian, so the same sixteen
# bytes come out reordered -- and Ryujinx zeroes SDL's crc field before it
# builds the id at all:
#
#   SDL bytes  03 00 | 79 f6 | de 28 | 00 00 | ff 11 | 00 00 01 00 00 00
#              bus     crc     vendor          product
#   Ryujinx    00000003 - 28de - 0000 - ff11 - 000001000000
#
# with the SDL joystick index in front. The crc is SDL's checksum of the device
# name, and dropping it is what makes the id survive a rename; keeping it is
# what made two earlier attempts here bind nothing. Both are confirmed against
# a running Ryujinx: with the crc, 16 "No matching controllers" warnings in
# forty seconds; without it, none.
#
# Two wrong ids came before this one, both from copying somebody else's file --
# f7390003, then f6790003 derived from the crc this hardware really reports. The
# pad is 28de:11ff, Valve's Steam Input virtual gamepad, named "Microsoft X-Box
# 360 pad 0". The generator those files came from asks SDL for it at runtime and
# then throws the crc away, which is what named the mistake.
#
# A wrong id is invisible: Ryujinx logs nothing about the pads it can see, and
# the only symptom is a game sitting forever on "waiting for controller".
_RYUJINX_PAD_ID = "0-00000003-28de-0000-ff11-000001000000"

# Switch face buttons sit where Nintendo has always put them: A on the right, B
# at the bottom, which is where SDL has B and A. Same crossing as Cemu and
# Dolphin, and the same reason -- the plain mapping swaps confirm and cancel.
_RYUJINX_PAD = {
    "left_joycon_stick": {
        "joystick": "Left",
        "invert_stick_x": False,
        "invert_stick_y": False,
        "rotate90_cw": False,
        "stick_button": "LeftStick",
    },
    "right_joycon_stick": {
        "joystick": "Right",
        "invert_stick_x": False,
        "invert_stick_y": False,
        "rotate90_cw": False,
        "stick_button": "RightStick",
    },
    "deadzone_left": 0.1,
    "deadzone_right": 0.1,
    "range_left": 1.0,
    "range_right": 1.0,
    "trigger_threshold": 0.5,
    "motion": {
        "slot": 0,
        "alt_slot": 0,
        "mirror_input": False,
        "dsu_server_host": "127.0.0.1",
        "dsu_server_port": 26760,
        "motion_backend": "GamepadDriver",
        "sensitivity": 100,
        "gyro_deadzone": 1.0,
        "enable_motion": True,
    },
    "rumble": {"strong_rumble": 1.0, "weak_rumble": 1.0, "enable_rumble": True},
    "led": {"enable_led": False, "turn_off_led": False, "use_rainbow": False, "led_color": 0},
    "left_joycon": {
        "button_minus": "Back",
        "button_l": "LeftShoulder",
        "button_zl": "LeftTrigger",
        "button_sl": "Unbound",
        "button_sr": "Unbound",
        "dpad_up": "DpadUp",
        "dpad_down": "DpadDown",
        "dpad_left": "DpadLeft",
        "dpad_right": "DpadRight",
    },
    "right_joycon": {
        "button_plus": "Start",
        "button_r": "RightShoulder",
        "button_zr": "RightTrigger",
        "button_sl": "Unbound",
        "button_sr": "Unbound",
        "button_x": "Y",
        "button_b": "A",
        "button_y": "X",
        "button_a": "B",
    },
    "version": 1,
    "backend": "GamepadSDL2",
    "id": _RYUJINX_PAD_ID,
    "controller_type": "ProController",
    "player_index": "Player1",
}

_RYUJINX_SETUP = {
    "format": emu_config.JSON_KEYS,
    "label": "controller bindings",
    #   1  pad bound using a copied device id, which named an SDL build that is
    #      not the one here, so Ryujinx matched no controller at all
    #   2  the id derived from the guid confirmed on this hardware instead
    #   3  that correction actually reaching an install, which version 2 did not
    #   4  the crc dropped from the id, which is the part Ryujinx does not use
    "version": 4,
    # Ryujinx rewrites Config.json whenever it exits, filling in fields it did
    # not find, so the input_config it saves is no longer the object this plugin
    # wrote -- and version 2 was skipped as "the user's" while being recorded as
    # done. Matching an id we wrote before survives that rewrite, because
    # whatever Ryujinx normalises around it, the id is still ours.
    # Removable once no install can still carry either.
    "superseded": (
        r"f7390003-28de-0000-ff11-000001000000",
        r"f6790003-28de-0000-ff11-000001000000",
    ),
    "files": {
        "%s/Config.json" % _RYUJINX_CONFIG: {
            # Ryujinx ships one input config and it is a keyboard, so out of the
            # box nothing on a Deck moves. Rather than matching the exact
            # keyboard dict it happens to ship -- the trap Dolphin's Wiimote set
            # -- the whole list is replaceable while every entry is still a
            # keyboard, which is what "nobody has set up a pad" actually means.
            "input_config": {
                "value": [_RYUJINX_PAD],
                "replace_when_all": {
                    "key": "backend",
                    "values": ("WindowKeyboard", "Keyboard"),
                },
            },
            # A confirmation dialog on exit, which for a Steam shortcut means the
            # game does not stop the first time you ask it to.
            "show_confirm_exit": {"value": False, "default": True},
        },
    },
}
# check_updates_on_start is already False in a fresh config, and
# update_checker_type is left alone: its accepted values are not something to
# guess at when the setting it gates is off anyway.


ENTRY = {
    "id": "ryujinx",
    "name": "Ryujinx",
    "summary": "Nintendo Switch. The Ryubing continuation.",
    "source": {"kind": "flatpak", "id": "io.github.ryubing.Ryujinx"},
    # The Switch's internal storage, split the way the console splits it: user
    # saves and the index Ryujinx keeps beside them, then the system's own.
    # `bis/user/Contents` is where installed titles and updates land and is
    # deliberately not here.
    "saves": [
        ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/bis/user/save",
        ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/bis/user/saveMeta",
        ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/bis/system/save",
    ],
    "databases": [],
    "platform": "Nintendo - Switch",
    "args": "{rom}",
    "fullscreen_args": "--fullscreen",
    "setup": _RYUJINX_SETUP,
    # Confirmed on a Deck rather than read: Pokemon Brilliant Diamond
    # launched from a Steam shortcut built with exactly these arguments,
    # opened fullscreen, and played on the pad `_RYUJINX_SETUP` binds.
    "verified": True,
    "firmware": [
        # One row each, and the reason is that a row is the only way to send a
        # file. These were a single requirement matching both names, which was
        # itself an improvement on a row called "prod.keys" that silently
        # installed a title.keys sent beside it -- but it left no route to the
        # second file at all. A row with anything installed reads as done, and a
        # done row offers Delete and Remove where the Send button would be. So
        # sending prod.keys first, which is what everyone does because it is the
        # one that matters, closed the only door title.keys had.
        {
            "name": "prod.keys",
            "note": "Dumped from your own Switch. Nothing runs without it.",
            "match": r"(?i)^prod\.keys$",
            "expects": "A file named exactly prod.keys.",
            "dest": ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/system",
        },
        {
            "name": "title.keys",
            "note": "Dumped from your own Switch, alongside prod.keys. The "
            "games that need it will not boot without it; most do not need it.",
            "match": r"(?i)^title\.keys$",
            "expects": "A file named exactly title.keys.",
            # So adding a Switch game does not report the emulator as missing
            # something every time. Same reason RPCS3's licence row carries it:
            # what is optional must not be counted as unmet.
            "optional": True,
            "dest": ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx/system",
        },
        {
            "name": "Switch firmware",
            "note": "Needed by most games.",
            "match": r"(?i)^.*firmware.*\.(zip|xci)$",
            "expects": "A .zip or .xci with 'firmware' in the name.",
            # Ryujinx unpacks a firmware archive into its own system folder
            # rather than reading it in place, and will only do it through
            # its own window. Checked at the source rather than assumed:
            # `--install-firmware <path>` exists, but it is read inside
            # MainWindow's template callback and then waits on a Yes/No
            # dialog, so there is no headless route -- and no headless build
            # either, the Ryujinx.Headless project is gone from the fork.
            #
            # What the flag does buy is the file browser. Without it the
            # user opens Ryujinx, finds Tools > Install Firmware, and steers
            # a file picker to the transfer folder with a thumbstick.
            "gui_install": {
                "args": ["--install-firmware", "{file}"],
                # Said in the toast as the window opens, so it is on screen
                # at the moment the dialog appears. The row says the same
                # thing beforehand -- see `manual` -- and neither repeats
                # the other's words.
                "prompt": "Press Yes to confirm, then quit Ryujinx when it "
                "has finished.",
            },
            # Ryujinx asks before installing and stays open afterwards,
            # neither of which this plugin can do anything about. Both are
            # said before the button is pressed rather than discovered.
            "manual": "Press Install: Ryujinx opens with the file already "
            "chosen. Confirm it, wait, then quit Ryujinx to come back.",
            # Where those unpacked contents land, so an installed firmware
            # can be seen rather than assumed absent. Read off a Deck with
            # firmware installed: 238 .nca directories under here, named by
            # hash -- which is why this is a "is there anything in it"
            # check and not a filename match. The folder itself exists
            # before any firmware does, so emptiness is the real signal.
            "detect": {
                "path": ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx"
                        "/bis/system/Contents/registered",
                "label": "installed",
            },
            # Installing it is Ryujinx's job, but removing it is only a
            # directory, and knowing where it is is the whole difficulty.
            # System titles only: games and their updates live under
            # sdcard/ and bis/user, and are not touched.
            "removes": [
                ".var/app/io.github.ryubing.Ryujinx/config/Ryujinx"
                "/bis/system/Contents/registered",
            ],
        },
    ],
}
