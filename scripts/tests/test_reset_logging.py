#!/usr/bin/env python3
"""A reset has to say what it deleted, or its effects read as bugs later.

    python scripts/tests/test_reset_logging.py

`clear_state` removes settings.json, and the next startup writes part of it
back: `_pin_collection_layout` finds no stored `collection_per_platform` and a
library still full of games, so it pins the layout to one shared collection.
Correct on its own terms, and indistinguishable from the setting having turned
itself off by itself.

That cost a session to work out, twice, because the step that caused it removed
the file with a bare `os.remove` and said nothing -- and `clear_retroarch_data`
deleting RetroArch's directory is what later made "install this core" do nothing
at all, with no line connecting the two. These checks are about the log line,
not the deletion: the deleting already worked.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402  -- installs the decky stub

import decky  # noqa: E402
import devreset  # noqa: E402


class _Recorder:
    """Collects what was logged, without disturbing the level the suite shares."""

    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(message % args)

    def warning(self, message, *args):
        self.lines.append(message % args)

    def exception(self, message, *args):
        self.lines.append(message % args)


section("a reset names what it destroyed")

_real = decky.logger
_recorder = _Recorder()
decky.logger = _recorder
devreset.decky.logger = _recorder
try:
    settings_dir = decky.DECKY_PLUGIN_SETTINGS_DIR
    os.makedirs(settings_dir, exist_ok=True)
    # Two of the seven, so the message has to list what was there rather than
    # everything it might have removed.
    for name in ("settings.json", "library.json"):
        with open(os.path.join(settings_dir, name), "w", encoding="utf-8") as handle:
            handle.write("{}")

    # Derived, not assumed: the suite shares one scratch settings directory and
    # files that ran earlier leave their own state in it, so "only the two I
    # wrote are there" is true alone and false in the suite. Asking what is on
    # disk right now makes the check say the same thing either way -- and says
    # something stronger, since it pins the whole list rather than two of it.
    _expected = sorted(label for path, label in devreset._state_files()
                       if os.path.exists(path))

    devreset.clear_state()
    _said = " ".join(_recorder.lines)

    check("clearing state is reported at all", bool(_recorder.lines), True)
    # The label, not the path: the log is read by whoever is trying to explain a
    # setting that turned itself off, and "Plugin settings" is that sentence.
    check("and names the settings file, which is the one that confuses people",
          "Plugin settings" in _said, True)
    check("and the library record beside it", "Games added to Steam" in _said, True)
    # Everything that was there, and nothing that was not: a reset that
    # over-claims is as misleading as one that says nothing.
    check("naming exactly the files that existed",
          sorted(label for _p, label in devreset._state_files() if label in _said),
          _expected)

    _recorder.lines = []
    devreset.clear_state()
    check("a second pass with nothing left says nothing", _recorder.lines, [])

    # The directory half, which is what removed RetroArch.
    _recorder.lines = []
    victim = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "pretend-retroarch")
    os.makedirs(victim, exist_ok=True)
    with open(os.path.join(victim, "core.so"), "w", encoding="utf-8") as handle:
        handle.write("x" * 32)
    devreset.clear_state()  # unrelated; keeps the recorder honest about sources
    _recorder.lines = []
    devreset._remove(victim)
    check("removing a directory is reported", len(_recorder.lines), 1)
    check("and names the path, since that is what a reader has to recognise",
          "pretend-retroarch" in _recorder.lines[0], True)
    check("removing one that is not there is silent",
          devreset._remove(victim) or _recorder.lines[1:], [])
finally:
    # The suite shares one logger; a file that swaps it must put it back.
    decky.logger = _real
    devreset.decky.logger = _real


if __name__ == "__main__":
    from harness import summary

    summary()
