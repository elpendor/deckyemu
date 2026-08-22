#!/usr/bin/env python3
"""The menu shortcut must not land on buttons that already quit.

    python scripts/tests/test_menu_combo_collision.py

This plugin's default menu shortcut is Start+Select. EmuDeck's RetroArch config
binds the same press to quitting, twice over: as
`input_quit_gamepad_combo = "4"`, and again as the hotkey pair
`input_enable_hotkey_btn = "4"` (Select) with `input_exit_emulator_btn = "6"`
(Start). Both installed, pressing the shortcut opens the menu *and* quits --
RetroArch unloads the core and the game disappears.

Found on a device, and the timestamps are the whole story: the config from
before EmuDeck ran was 661 bytes with no combo lines at all and the shortcut
worked; the one EmuDeck wrote is 111KB and carries all three bindings. The core
installed in the same run, Beetle bsnes, aborts inside `retro_deinit`, so the
quit arrived as a crash rather than as a clean exit -- which is why it read as
the game being broken rather than as a hotkey doing its job.

The fix is confined to the per-launch override. What EmuDeck set still holds for
anything launched outside this plugin, which is the rule the whole override file
follows.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import launchers  # noqa: E402


def _config(**values):
    """A retroarch.cfg holding `values`, and the directory it is in."""
    where = os.path.join(TMP, "racfg-%d" % len(values))
    os.makedirs(where, exist_ok=True)
    with io.open(os.path.join(where, "retroarch.cfg"), "w", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write('%s = "%s"\n' % (key, value))
    return where


def _override(config_dir, menu_combo="start_select"):
    """The text of the override this config and combo produce."""
    path = launchers.write_override_config(
        "keep", menu_combo, None, config_dir=config_dir
    )
    if not path:
        return ""
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


section("EmuDeck's layout, which is the case this exists for")

_emudeck = _config(
    input_quit_gamepad_combo="4",
    input_enable_hotkey_btn="4",
    input_exit_emulator_btn="6",
    input_menu_toggle_gamepad_combo="2",
)
_text = _override(_emudeck)

check("the menu shortcut is still set", 'input_menu_toggle_gamepad_combo = "4"' in _text, True)
# Both spellings of the same press, or the one left standing still quits.
check("the quit combo on those buttons is cleared",
      'input_quit_gamepad_combo = "0"' in _text, True)
check("and so is the exit hotkey built from them",
      'input_exit_emulator_btn = "nul"' in _text, True)
# The modifier is shared by every other hotkey the user has -- volume, save
# state, screenshot. Taking it away to fix one of them would cost all of them.
check("while the hotkey modifier is left alone",
      "input_enable_hotkey_btn" in _text, False)


section("a config that has no such binding is not touched")

# What RetroArch writes for itself: no quit combo at all. This is the ordinary
# case and the override must stay as short as it was.
_plain = _config(input_menu_toggle_gamepad_combo="2")
_text = _override(_plain)
check("nothing is cleared when nothing collides",
      ("input_quit_gamepad_combo" in _text, "input_exit_emulator_btn" in _text),
      (False, False))
check("and the menu shortcut is still set", 'input_menu_toggle_gamepad_combo = "4"' in _text, True)

# No RetroArch, or a config that cannot be read. The shortcut is still worth
# setting; there is simply nothing to check it against.
check("an unreadable config is not an error",
      'input_menu_toggle_gamepad_combo = "4"' in _override(os.path.join(TMP, "nowhere")),
      True)
check("and neither is having no config directory at all",
      'input_menu_toggle_gamepad_combo = "4"' in _override(""), True)


section("the comparison is by buttons, not by the number")

# `3` is L1+R1+Start+Select and `4` is Start+Select. Pressing the four includes
# pressing the two, so a quit bound to either collides with a menu shortcut on
# the other. Comparing the numbers would have missed it.
_wider = _config(input_quit_gamepad_combo="3")
check("a wider quit combo containing the same buttons is cleared",
      'input_quit_gamepad_combo = "0"' in _override(_wider), True)

# L3+R3 shares no button with Start+Select, so both can be held at once and
# neither is the other. Clearing it would take away a binding that works.
_elsewhere = _config(input_quit_gamepad_combo="2")
check("a quit combo on other buttons is left alone",
      "input_quit_gamepad_combo" in _override(_elsewhere), False)

# The same the other way round: our shortcut somewhere harmless.
check("and a menu shortcut on other buttons checks nothing",
      "input_quit_gamepad_combo" in _override(_emudeck, menu_combo="l3_r3"), False)

# Off means no shortcut, so there is nothing to collide with and nothing to
# take away from the user.
check("with the shortcut off, the user's bindings stand",
      ("input_quit_gamepad_combo" in _override(_emudeck, menu_combo="off"),
       "input_exit_emulator_btn" in _override(_emudeck, menu_combo="off")),
      (False, False))


section("a half-configured hotkey is not a collision")

# Only the modifier bound, with nothing on the exit key: pressing Start+Select
# does not quit, so there is nothing to clear.
_partial = _config(input_enable_hotkey_btn="4", input_exit_emulator_btn="nul")
check("a modifier with no exit key bound is left alone",
      "input_exit_emulator_btn" in _override(_partial), False)

# Both on the same button is not a two-button press at all.
_same = _config(input_enable_hotkey_btn="4", input_exit_emulator_btn="4")
check("and neither is a hotkey whose two halves are one button",
      "input_exit_emulator_btn" in _override(_same), False)

summary()
