"""The Steam Input layout an emulator needs, derived from one Steam ships.

Only Vita3K needs this today, and the need is not a preference: the Deck powers
its gyro down unless the *running game's* layout binds it, so a Vita game on any
ordinary layout reads a sensor that never moves. Steam ships exactly one Deck
template that binds gyro -- "Gamepad with Gyro" -- and it binds it to the mouse,
which drifts the pointer across the screen. Vita3K maps that pointer to the
Vita's touchscreen, so the drift is both visible and in the way.

`gyro_to_joystick` is the mode that does the same job without a cursor. No stock
template uses it, so this makes one: Valve's own file, with the gyro group's mode
changed and a title that says where it came from.

**Derived on the device rather than shipped.** The source is Valve's content and
has no business living in this repository, and a copy taken today would rot
against whatever Steam ships next. Reading the installed template and rewriting
one line keeps this to a transform of the user's own files.
"""

import os
import re

import decky

#: Where Steam keeps the layouts its picker offers, and where a derived one has
#: to sit to be selectable. Third-party tools put templates here too -- the
#: RetroDECK entries in that directory are the same idea.
TEMPLATES = os.path.expanduser("~/.steam/steam/controller_base/templates")

#: The one stock Deck template that binds gyro at all, which is what makes it
#: the only sane starting point: everything else about it is Valve's tuning for
#: a gamepad, and only the gyro group is wrong for us.
SOURCE = "controller_neptune_gamepad_mouse_gyro.vdf"

#: Named for the plugin so it is obvious in Steam's list who put it there, and
#: so removing it is a decision somebody can make without guessing.
DERIVED = "deckyemu_controller_neptune_gamepad_gyro.vdf"

#: What a catalog entry points at. The `template://` form is what Steam's own
#: configurator writes, and what `SetActiveConfigForApp` expects.
DERIVED_URL = "template://%s" % DERIVED

_TITLE = "Gamepad with Gyro (DeckyEmu)"
_DESCRIPTION = (
    "Valve's gamepad layout with the gyro sent to the right stick instead of the "
    "mouse. Emulators that read the Deck's motion sensor need a layout that uses "
    "gyro at all -- Steam powers the sensor down otherwise -- and this one does "
    "that without a mouse pointer drifting across the game."
)


def rewrite(text):
    """Valve's mixed-input template with the gyro sent to a stick, not the mouse.

    Returns "" when the text is not the template this expects, which is the
    honest answer to Steam having changed it: a half-rewritten layout would be
    worse than leaving the stock one in place.

    The mode is the whole functional change. Everything else -- every button,
    both sticks, the trackpads, the tuning -- stays exactly as Valve wrote it,
    because none of it is what this is for.
    """
    if '"gyro_to_mouse"' not in text or '"controller_neptune"' not in text:
        return ""

    out = text.replace('"gyro_to_mouse"', '"gyro_to_joystick"', 1)
    # The title is what the user sees in Steam's picker, so it says who made it.
    out = re.sub(
        r'("title"\s+")Gamepad with Gyro(")', r"\g<1>%s\g<2>" % _TITLE, out, count=1
    )
    out = re.sub(
        r'("description"\s+")[^"]*(")', r"\g<1>%s\g<2>" % _DESCRIPTION, out, count=1
    )
    return out


def ensure(templates_dir=None):
    """Write the derived template if it is missing or out of date.

    Returns (path, error). A failure here is untidy rather than fatal: without
    it a Vita game lands on whatever Steam chose, which is the situation this
    improves rather than one it depends on.
    """
    base = templates_dir or TEMPLATES
    source = os.path.join(base, SOURCE)
    target = os.path.join(base, DERIVED)

    if not os.path.isfile(source):
        return "", "Steam's gyro template is not installed."

    try:
        with open(source, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as error:
        return "", "Could not read Steam's gyro template: %s" % error

    derived = rewrite(text)
    if not derived:
        return "", "Steam's gyro template is not the one this expects."

    # Rewritten when Valve's has moved on, so a Steam update that retunes the
    # layout is inherited rather than pinned to whatever was there first.
    try:
        if os.path.isfile(target):
            with open(target, "r", encoding="utf-8", errors="replace") as handle:
                if handle.read() == derived:
                    return target, ""
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(derived)
    except OSError as error:
        return "", "Could not write the gyro layout: %s" % error

    decky.logger.info("Wrote the gyro layout template to %s", target)
    return target, ""
