#!/usr/bin/env python3
"""Keeping what the emulator said, for a game that starts and dies.

    python scripts/tests/test_launch_log.py
"""

import io
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import diagnostics  # noqa: E402
import launchers  # noqa: E402

section("the launcher keeps its game's last run")

# The plugin took this channel away itself: `hide_osd` defaults to "all", which
# suppresses RetroArch's own error text along with its chatter, and the stated
# replacement -- the firmware check -- runs when a game is added and answers
# nothing afterwards. A BIOS moved since is a black screen and silence.

_launcher = os.path.join(TMP, "launchlog", "Some Game-abc123.sh")
os.makedirs(os.path.dirname(_launcher), exist_ok=True)

_log = launchers.launch_log_path(_launcher)
check("the log is named after the launcher, not the appid",
      os.path.basename(_log), "Some Game-abc123.log")

_shell = launchers.log_capture(_launcher)
check("it truncates before redirecting, so one run is what is kept",
      '> "$_dke_log"' in _shell, True)
# Every branch of it. This runs in front of every game in the library, and a
# game that will not start is a far worse failure than a diagnostic nobody
# collected -- the same rule the launch gate follows.
check("and redirects only if that worked", _shell.count("if : >"), 1)
check("so a read-only disk leaves the game launching as before",
      "then exec >>" in _shell, True)

section("what it captures, run for real")

if os.name != "posix":
    print("SKIP the shell that does the capturing is POSIX-only")
else:
    _script = os.path.join(TMP, "launchlog", "run.sh")
    with io.open(_script, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("#!/bin/sh\n" + _shell + "\nexec echo 'core not found: bios.bin'\n")
    os.chmod(_script, 0o755)
    subprocess.run([_script], check=False, capture_output=True)

    check("what the emulator said is on disk",
          launchers.read_launch_log(_launcher), "core not found: bios.bin")

    # The tail, because what explains a failure is the last thing said before
    # it, and a verbose emulator's first lines are its own startup banner.
    with io.open(_log, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("\n".join("line %d" % n for n in range(2000)))
    _tail = launchers.read_launch_log(_launcher, limit=200)
    check("a long log is read from the end", _tail.endswith("line 1999"), True)
    check("and starts on a line boundary rather than mid-word",
          _tail.splitlines()[0].startswith("line "), True)

section("a log that grew during a long session is trimmed, not deleted")

os.makedirs(launchers.LAUNCH_LOG_DIR, exist_ok=True)
_big = os.path.join(launchers.LAUNCH_LOG_DIR, "big-game.log")
with io.open(_big, "w", encoding="utf-8", newline="\n") as _handle:
    _handle.write("x" * (launchers.LAUNCH_LOG_CAP + 5000))
check("the sweep cuts it", launchers.sweep_launch_logs(), 1)
check("to something under the cap", os.path.getsize(_big) < launchers.LAUNCH_LOG_CAP, True)
# Trimmed rather than removed: the tail is the half that explains anything, and
# a game whose log was swept has still just been played.
check("but not to nothing", os.path.getsize(_big) > 0, True)
check("and a second sweep finds nothing left to do", launchers.sweep_launch_logs(), 0)
os.remove(_big)

section("removing a game keeps what its emulator said")

# **The case this exists for is removing a game *because it did not work*.**
# That is the likeliest reason anybody removes one, and it is exactly the moment
# the log explaining why becomes the only evidence left -- the launcher is gone,
# the registry entry is gone, and the ROM may be gone too.
#
# This was briefly the other way round, on the argument that a log whose
# launcher is gone can never be matched to a game again and is therefore litter.
# True, and beside the point: what it costs to keep is a few kilobytes in a file
# that truncates itself every run, and what it costs to delete is the answer to
# the question the user is about to ask.

os.makedirs(launchers.LAUNCHER_DIR, exist_ok=True)
os.makedirs(launchers.LAUNCH_LOG_DIR, exist_ok=True)
_script = os.path.join(launchers.LAUNCHER_DIR, "gone-game-abcd1234.sh")
with io.open(_script, "w", encoding="utf-8", newline="\n") as _handle:
    _handle.write("#!/bin/sh\n")
_its_log = launchers.launch_log_path(_script)
with io.open(_its_log, "w", encoding="utf-8", newline="\n") as _handle:
    _handle.write("could not read content file\n")

check("the launcher goes", launchers.remove_launcher(_script), True)
check("and the log stays", os.path.exists(_its_log), True)
check("with what the emulator said still in it",
      "could not read content file" in launchers.read_launch_log(_script), True)

# The report reads the newest log whatever became of its game, and says which
# state it is in -- so a reader is not sent hunting for a library entry that is
# not there any more. Checked here because the note is derived from the launcher
# being absent, which is the thing this section just arranged.
check("the report says the game is gone",
      "since been removed" in diagnostics._last_launch(), True)

os.remove(_its_log)

if __name__ == "__main__":
    summary()
