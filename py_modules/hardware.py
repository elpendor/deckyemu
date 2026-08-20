"""Which machine this is, and whether the plugin claims to work on it.

Everything in this plugin was built and measured on a Steam Deck: the Game Mode
assumptions, the controller profile, the gamescope handling, the emulator
configs. None of it is checked anywhere else, so running it on a desktop is not
"probably fine", it is untested -- and the failures it produces arrive as bug
reports that cannot be acted on, because reproducing them needs hardware the
project does not target.

Read from DMI rather than from /etc/os-release, and the difference matters in
both directions. A Deck running Bazzite or ChimeraOS reports Fedora in
os-release and is still a Deck; a desktop running HoloISO reports SteamOS and is
not one. The firmware tables are what the hardware says about itself.

    $ cat /sys/class/dmi/id/sys_vendor    -> Valve
    $ cat /sys/class/dmi/id/product_name  -> Galileo

Both are world-readable (-r--r--r--), so this needs no privileges. Measured on
an OLED Deck; `Jupiter` for the LCD is taken from Valve's published board names
and is *not* verified here, which is the reason the vendor is what decides and
the board name only labels the answer.
"""

import os

import decky

DMI_DIR = "/sys/class/dmi/id"

#: The vendor string that means "Valve made this". Lowercased on both sides
#: before comparing -- nothing promises the case of a DMI field.
DECK_VENDOR = "valve"

#: Board names that name a Deck, and what to call each one.
#:
#: Only used for the label. An unrecognised Valve board is still treated as
#: supported, deliberately: a whitelist written today would lock out a Deck
#: revision released tomorrow, and being wrong in that direction costs a user
#: their working plugin, while being wrong in the other costs a warning that
#: was not needed.
DECK_BOARDS = {
    "jupiter": "Steam Deck (LCD)",
    "galileo": "Steam Deck (OLED)",
}


def _dmi(name):
    """One DMI field, or "" if it cannot be read.

    Absent is normal rather than exceptional -- a VM or an ARM box may have no
    DMI at all -- so this never raises and the caller reads "" as "the hardware
    did not say".
    """
    try:
        with open(os.path.join(DMI_DIR, name), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def detect():
    """What this machine is, as the UI and the diagnostic report need it.

    `supported` is the only field anything should branch on. `why` exists so the
    message can differ between "this is a desktop" and "this device would not
    say what it is", which are different situations for the person reading it.
    """
    vendor = _dmi("sys_vendor")
    product = _dmi("product_name")
    board = product.strip().lower()

    if vendor.strip().lower() == DECK_VENDOR:
        return {
            "supported": True,
            "vendor": vendor,
            "product": product,
            "model": DECK_BOARDS.get(board, "Valve hardware (unrecognised board)"),
            "why": "deck" if board in DECK_BOARDS else "valve-unknown",
        }

    return {
        "supported": False,
        "vendor": vendor,
        "product": product,
        "model": (" ".join(part for part in (vendor, product) if part)) or "unknown",
        # Told apart because the remedy differs: one is "this plugin is not for
        # this machine", the other is "this machine would not identify itself,
        # which may be nothing to do with the plugin".
        "why": "not-valve" if vendor else "unknown",
    }


def describe():
    """One line for the diagnostic report."""
    found = detect()
    return "%s (%s)" % (
        found["model"],
        "supported" if found["supported"] else "unsupported: %s" % found["why"],
    )


def log_once():
    """Say what this is at startup, so a report explains itself without asking."""
    found = detect()
    if found["supported"]:
        decky.logger.info("Device: %s", found["model"])
    else:
        decky.logger.warning(
            "Device is not a Steam Deck: vendor=%r product=%r (%s)",
            found["vendor"], found["product"], found["why"],
        )
    return found
