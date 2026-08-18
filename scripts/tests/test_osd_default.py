#!/usr/bin/env python3
"""Hiding every on-screen message is the default, and it reaches games already added.

    python scripts/tests/test_osd_default.py

A game launched from Steam should look like a game from Steam. The old default
took away RetroArch's load animation and left the rest -- save-state
confirmations, shader notices, the autoconfig line -- which is a frontend's
chrome appearing over somebody's console game.

Two halves, and the second is the one that goes wrong quietly. Settings are
merged from the defaults when they are read, so changing one changes it for
everybody who never opened that toggle -- but a launcher names the override file
it was written with, and nothing rewrites launchers on upgrade. Without the
format version moving too, the panel would read "Hide all on-screen messages"
while every game already in the library went on showing them, which is a
disagreement between two screens rather than a setting that did not take.

The third check is what makes the rewrite safe: a game given its own OSD mode
keeps it. Per-game overrides are stored absent when they follow the global, so a
rebuild resolves each game's options again rather than stamping the new default
over choices somebody made.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import launchers  # noqa: E402
import store  # noqa: E402

section("hiding everything is what a game gets unless it says otherwise")

check("the default is to hide every on-screen message",
      store.get_settings()["hide_osd"], "all")

# The setting is only as good as the file a launcher points at, and there is one
# override file per mode -- games can want different modes at once, so a shared
# file let the last one written decide for everyone.
_override = launchers.write_override_config("all")
check("and it resolves to the override file for that mode",
      os.path.normpath(_override),
      os.path.normpath(launchers.OVERRIDE_CONFIGS["all"]))
with io.open(_override, encoding="utf-8") as _handle:
    _text = _handle.read()
# The two RetroArch keys that actually silence it. Asserted by name because the
# mode is a label and these are the behaviour behind it.
check("which turns RetroArch's notifications off",
      ("video_font_enable" in _text, "menu_show_load_content_animation" in _text),
      (True, True))
# Whatever else is appended, this must be: RetroArch saves the merged config on
# quit, so without it every value here becomes permanent and global.
check("and still refuses to let RetroArch save the merged config",
      'config_save_on_exit = "false"' in _text, True)


section("the change reaches games that were added before it")

# A launcher written under the old default names the old file, and goes on
# naming it however the setting reads afterwards. The format version is what
# drags those forward; if it did not move with this change, nothing would.
check("the launcher format moved with the default", launchers.FORMAT_VERSION >= 6, True)


section("and a game that was given its own mode keeps it")

# The rewrite resolves each game's options rather than stamping the global over
# them, which is the property that makes dragging launchers forward safe at all.
_kept = launchers.write_override_config("keep")
check("a game asking to keep notifications gets the keep file",
      os.path.normpath(_kept), os.path.normpath(launchers.OVERRIDE_CONFIGS["keep"]))
with io.open(_kept, encoding="utf-8") as _handle:
    _keep_text = _handle.read()
# `keep` suppresses nothing and exists only so the menu shortcut can still reach
# games whose notifications are left alone.
check("and that file silences nothing",
      ("video_font_enable" in _keep_text, "menu_show_load_content_animation" in _keep_text),
      (False, False))
check("the three modes are still three separate files",
      len({os.path.normpath(p) for p in launchers.OVERRIDE_CONFIGS.values()}), 3)


if __name__ == "__main__":
    summary()
