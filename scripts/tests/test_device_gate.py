#!/usr/bin/env python3
"""Which machine this is, and what the plugin refuses to do when it is not a Deck.

    python scripts/tests/test_device_gate.py

Everything in this plugin was measured on a Steam Deck. Running it elsewhere is
untested rather than merely unusual, and the bug reports it produces cannot be
reproduced on hardware the project targets -- one such report is what led here.

The failure worth guarding against is the *opposite* one: refusing to work on a
real Deck. That would break the plugin for every user who has one, so the checks
below state the Deck cases as loudly as the desktop ones.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import hardware  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import main as plugin_main  # noqa: E402


def _as(vendor, product):
    """Answer as a machine reporting these DMI fields."""
    real = hardware._dmi

    def fake(name):
        return {"sys_vendor": vendor, "product_name": product}.get(name, "")

    hardware._dmi = fake
    try:
        return hardware.detect()
    finally:
        hardware._dmi = real


section("what the hardware says it is")
# Read off a real Deck over ssh rather than recalled: sys_vendor is "Valve" and
# product_name "Galileo" on the OLED, both world-readable so this needs no
# privileges. "Jupiter" is Valve's published name for the LCD and is *not*
# verified here -- which is exactly why the vendor decides and the board name
# only labels the answer.
check("an OLED Deck is a Deck", _as("Valve", "Galileo")["supported"], True)
check("and is named as one", _as("Valve", "Galileo")["model"], "Steam Deck (OLED)")
check("an LCD Deck is a Deck", _as("Valve", "Jupiter")["supported"], True)
# The case a whitelist gets wrong: hardware released after this version shipped.
# Locking its owner out of a working plugin is worse than a warning nobody
# needed, so Valve's name alone is enough.
check("a Valve board this version has never heard of is still supported",
      _as("Valve", "Neptune 3")["supported"], True)
check("the vendor is matched whatever its case", _as("VALVE", "Galileo")["supported"], True)

# The report that led here: Fedora on a desktop.
check("a desktop is not", _as("LENOVO", "20XW")["supported"], False)
check("and is described by what it actually said", _as("LENOVO", "20XW")["model"], "LENOVO 20XW")
# Told apart from a desktop deliberately: a machine that would not identify
# itself has not been shown to be the wrong hardware, and a Deck with unreadable
# DMI must not be told it is a PC.
check("a machine that says nothing is unsupported but not accused",
      (_as("", "")["supported"], _as("", "")["why"]), (False, "unknown"))
check("while a named non-Valve vendor is", _as("LENOVO", "20XW")["why"], "not-valve")

# os-release is deliberately not consulted: a Deck running Bazzite reports
# Fedora and is still a Deck, and a desktop running HoloISO reports SteamOS and
# is not one. The firmware tables are what the hardware says about itself.
check("the answer does not come from the distribution",
      "os-release" in open(hardware.__file__, encoding="utf-8").read().split('"""')[2],
      False)


section("the gate over the methods decky can call")
# A backstop, not the user interface -- the panel shows the explanation and does
# not call the rest. So what stays reachable is only what is needed to see that
# explanation, act on it, and report it if it is wrong.
_ungated = plugin_main.UNGATED_METHODS
check("the panel can still ask what this machine is",
      "get_status" in _ungated, True)
check("and can still render the rest of its mount",
      ("list_added" in _ungated, "shortcut_health" in _ungated), (True, True))
check("the override can be written, or the block could never be lifted",
      ("get_settings" in _ungated, "set_settings" in _ungated), (True, True))
check("a frontend error can still be logged",
      "log_frontend_error" in _ungated, True)
# Both of these are how somebody gets *out* of a wrong answer here: one moves to
# a fixed version, the other tells us it was wrong.
check("the updater still answers, so a bad gate can be updated away",
      sorted(m for m in ("check_for_update", "stage_update", "plugin_version")
             if m in _ungated),
      ["check_for_update", "plugin_version", "stage_update"])
check("and a diagnostic report can still be produced",
      sorted(m for m in ("start_report", "end_report") if m in _ungated),
      ["end_report", "start_report"])

# The whole point: everything that changes the machine is behind it. Named
# individually rather than counted, so adding an endpoint cannot quietly widen
# the exemption.
for _method in ("register_game", "install_emulator", "install_retroarch",
                "install_core", "install_firmware", "prepare_shortcut",
                "clear_library", "uninstall_emulator", "delete_rom"):
    check("%s is gated" % _method, _method in _ungated, False)


section("and what that gate actually does to a call")
# Membership in a set is not the behaviour; this is. A gated method must refuse
# on hardware that is not a Deck, and must stop refusing the moment the user
# says to continue -- otherwise the override is a button that does nothing.
import asyncio  # noqa: E402

import store  # noqa: E402

_plugin = plugin_main.Plugin()
_plugin.loop = asyncio.new_event_loop()
# What `_main` sets before any method is reachable. Set here rather than by
# calling `_main`, which starts servers and touches the network: the gate is
# what is under test, and a method that gets past it has to be able to run far
# enough to prove it did.
_plugin._install = None
_plugin._cores = []
_plugin._emulators = []
_real_dmi = hardware._dmi
try:
    hardware._dmi = lambda name: {"sys_vendor": "LENOVO", "product_name": "20XW"}.get(name, "")
    store.set_settings({"allow_unsupported_device": False})

    def _call(method):
        try:
            _plugin.loop.run_until_complete(method())
        except plugin_main.UnsupportedDevice:
            return "refused"
        except Exception as error:  # anything else means it got through the gate
            return "ran (%s)" % type(error).__name__
        return "ran"

    check("a method that changes things is refused on a desktop",
          _call(_plugin.list_systems), "refused")
    check("while the panel can still ask what the machine is",
          _call(_plugin.get_settings), "ran")

    store.set_settings({"allow_unsupported_device": True})
    check("and the override actually lets it through",
          _call(_plugin.list_systems), "ran")
finally:
    store.set_settings({"allow_unsupported_device": False})
    hardware._dmi = _real_dmi
    _plugin.loop.close()


if __name__ == "__main__":
    summary()
