"""Reaching a port's own menu from the pad, with no keyboard.

A port is a PC program: its menu opens with a key, and Game Mode has no
keyboard. `gptokeyb2` turns hold-Select-press-Start into that keystroke, the
gesture RetroArch already uses.

Not a Steam Input layout: a layout binds one fixed key per file, so a second
port wanting another key needs another layout, one wanting gyro as well cannot
have both, and applying one replaces whatever the game had.
"""

#: The helper, fetched the way a motion server is. Two members: the binary is
#: linked against the library beside it, so taking only the first leaves
#: something that cannot start.
KEYBOARD_SERVER = {
    "name": "gptokeyb2",
    "label": "Hotkey helper",
    "repo": "PortsMaster/gptokeyb2",
    "asset": r"^gptokeyb2-all\.zip$",
    "extract": [r"^gptokeyb2\.x86_64$", r"^libinterpose\.x86_64\.so$"],
}

#: The button held to reach the second set of bindings, by default.
#:
#: Select, because the consoles these ports come from mostly have no such button
#: -- an N64 or GameCube game cannot miss it. A port of a console that *does*
#: use Select says so with `menu_modifier`: while the chord is held the pad is
#: taken from the game, so a button the game wants is the wrong one to hold.
MODIFIER = "back"

#: What gptokeyb2 treats as its own hotkey button.
#:
#: Start plus this button quits the helper, hardcoded past any config. Its
#: default is Select, which is half the gesture below -- so it must be moved,
#: and the Steam button is one the Deck never delivers.
HOTKEY_BUTTON = "guide"


def modifier_for(entry):
    """The button this entry holds to reach its keys."""
    return (entry or {}).get("menu_modifier") or MODIFIER


def config_text(bindings, modifier=MODIFIER):
    """The `gptokeyb2` config for one port, as text.

    `bindings` maps a button to the key it sends while Select is held, e.g.
    {"start": "esc"}. Nothing is bound outside that state, so every button
    reaches the game exactly as it did before -- the helper adds a gesture and
    takes nothing away.
    """
    lines = [
        "# Written by DeckyEmu. Hold Select to reach these; see hotkeys.py.",
        "[controls]",
        "overlay = clear",
        "%s = hold_state hotkey" % modifier,
        "",
        "[controls:hotkey]",
        "overlay = parent",
        # Take the pad while Select is held, so the game does not also see the
        # Start that opens the menu. An EVIOCGRAB, dropped the moment Select
        # comes up, so nothing is held past the gesture.
        "exclusive = true",
    ]
    lines += ["%s = %s" % (button, key) for button, key in sorted(bindings.items())]
    return "\n".join(lines) + "\n"


def bindings_for(entry):
    """What this entry wants on the pad, or {}.

    `menu_key` is the one nearly every port needs and the only one most declare.
    `hotkeys` is for the rest -- a save-state key, a fullscreen toggle -- and the
    two are merged so an entry can have a menu and one more thing without
    repeating itself.
    """
    found = {}
    menu_key = (entry or {}).get("menu_key") or ""
    if menu_key:
        found["start"] = menu_key
    found.update((entry or {}).get("hotkeys") or {})
    return found
