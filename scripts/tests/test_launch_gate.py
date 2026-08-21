#!/usr/bin/env python3
"""The launch gate: the only thing that can stop a second game starting.

    python scripts/tests/test_launch_gate.py

Steam warns before launching one game over another, but never for these: its
check is gated on `app_type & 1` and a non-Steam shortcut is `1073741824`.
Nothing on the Steam side can stop the launch either -- `CancelGameAction`
terminates the game a second after it starts, `CancelLaunch` only detaches
Steam's tracking and leaves the emulator running. Both measured on a device.

So the generated launcher decides, and these checks are about the two ways that
can be wrong. Refusing when it should not is the serious one: this script runs
in front of every game in the library, so a gate that misfires does not produce
a missing warning, it produces a game that will not start. Every branch below
that ends in "launch anyway" is guarding that.

The shell itself is checked by running it -- POSIX `sh` only, and skipped on
Windows, where there is none. What runs is the real generated launcher with its
`exec` line swapped for an echo, so the thing under test is the text that ships
rather than a copy of it.
"""

import io
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import launchers  # noqa: E402

section("the gate is in every launcher, and only above the exec")

_LAUNCHER = launchers.write_launcher(
    {"kind": "native", "exe": "/usr/bin/retroarch"},
    "Gate Test",
    "/cores/snes9x_libretro.so",
    "/roms/game.sfc",
)
with io.open(_LAUNCHER, encoding="utf-8") as _handle:
    _body = _handle.read()

check("a generated launcher carries the gate", "_dke_self=" in _body, True)
# Below the exec it would run after the emulator had already started, which is
# every bit as useless as not being there.
check("above the exec, which is the only place it does anything",
      _body.index("_dke_self=") < _body.index("\nexec "), True)
check("and the paths in it are this install's, not a placeholder",
      "{gate}" in _body, False)
check("naming the directory the backend reads",
      launchers.LAUNCH_GATE_DIR in _body, True)

# A launcher written before the gate existed does not have one, and nothing
# rewrites launchers on upgrade without this number changing.
check("the format version rose, so existing games are rewritten",
      launchers.FORMAT_VERSION >= 7, True)


section("what the gate does, run as a shell actually runs it")

if os.name != "posix":
    print("SKIP  the gate is POSIX shell; there is none here")
else:
    # The real directory, not a stand-in. The script and the backend have to
    # agree on it, and pointing the script somewhere else is exactly the way to
    # write a passing check for two halves that never meet.
    _dir = launchers.LAUNCH_GATE_DIR
    _gate = launchers.launch_gate()

    _script = os.path.join(TMP, "gate.sh")
    with io.open(_script, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("#!/bin/sh\n" + _gate + "\necho LAUNCHED\n")
    os.chmod(_script, 0o755)

    # Steam runs every launcher as `reaper SteamLaunch AppId=<id> -- <script>`,
    # and the gate reads its own id off that parent. This stands in for it, with
    # the same argv shape -- separate arguments, because `AppId=<id>` being its
    # own argv entry is exactly what the gate matches on.
    _reaper = os.path.join(TMP, "reaper")
    with io.open(_reaper, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write('#!/bin/sh\nshift 3\n"$@"\n')
    os.chmod(_reaper, 0o755)

    def _launch(app_id, script=None):
        """Run the gate as Steam would, returning what the script printed."""
        result = subprocess.run(
            [_reaper, "SteamLaunch", "AppId=%d" % app_id, "--", script or _script],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout

    check("syntax the shell accepts",
          subprocess.run(["sh", "-n", _script]).returncode, 0)

    check("with nothing else running, the game launches",
          "LAUNCHED" in _launch(111), True)
    check("and leaves no note behind, because there is nothing to say",
          [name for name in os.listdir(_dir) if name.startswith("bounced-")]
          if os.path.isdir(_dir) else [], [])

    # Another launch, held open for as long as this takes.
    _other = subprocess.Popen(
        [_reaper, "SteamLaunch", "AppId=222", "--", "sleep", "30"],
    )
    try:
        time.sleep(0.5)
        _blocked = _launch(111)
        check("with another game running, nothing starts", "LAUNCHED" in _blocked, False)

        _note = os.path.join(_dir, "bounced-111")
        check("and a note says so", os.path.isfile(_note), True)
        with io.open(_note, encoding="utf-8") as _handle:
            _saw = _handle.read().split()
        # The id, so the panel can say what is in the way even when Steam's own
        # running list has moved on by the time it asks.
        check("naming what was in the way", _saw, ["222"])

        # Reading it is what takes it: two panels asking must not both answer,
        # and a note nobody collects must not sit there forever.
        check("the backend reads the note", launchers.take_bounce(111), "222")
        check("and consumes it", os.path.exists(_note), False)
        check("so a second ask finds nothing", launchers.take_bounce(111), "")

        # The user said go. One launch gets past, and only one.
        check("approving writes the token", launchers.approve_launch(111), True)
        check("an approved launch starts even with the other game up",
              "LAUNCHED" in _launch(111), True)
        check("and the token is spent", os.path.exists(os.path.join(_dir, "approved-111")), False)
        check("so the launch after it is judged again",
              "LAUNCHED" in _launch(111), False)

        # The gate is per game. A conflict for one must not hold up another.
        check("a different game is judged on its own", "LAUNCHED" in _launch(333), False)
    finally:
        _other.terminate()
        _other.wait(timeout=10)

    check("once the other game is gone, launching resumes",
          "LAUNCHED" in _launch(111), True)

    section("every uncertainty ends in the game starting")

    # No reaper above it, so there is no app id to be had. This is what happens
    # if Steam ever stops wrapping launches that way, and it must not be what
    # stops the library working.
    check("an unrecognisable parent launches anyway",
          "LAUNCHED" in subprocess.run(
              [_script], capture_output=True, text=True, timeout=30).stdout, True)

    # An unwritable gate directory: the note cannot be left, but the decision was
    # already made and a launch that stops with nobody able to explain why is the
    # worst of both.
    _readonly = os.path.join(TMP, "gate-ro")
    os.makedirs(_readonly, exist_ok=True)
    _ro_script = os.path.join(TMP, "gate-ro.sh")
    with io.open(_ro_script, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "#!/bin/sh\n"
            + launchers.launch_gate().replace(
                launchers.LAUNCH_GATE_DIR, os.path.join(_readonly, "nope", "deeper")
            )
            + "\necho LAUNCHED\n"
        )
    os.chmod(_ro_script, 0o755)
    os.chmod(_readonly, 0o500)
    try:
        _other = subprocess.Popen([_reaper, "SteamLaunch", "AppId=222", "--", "sleep", "30"])
        try:
            time.sleep(0.5)
            # It still refuses -- the decision does not depend on the note -- but
            # nothing here may raise or hang.
            _out = _launch(111, _ro_script)
            check("an unwritable gate directory does not hang or crash the launcher",
                  isinstance(_out, str), True)
        finally:
            _other.terminate()
            _other.wait(timeout=10)
    finally:
        os.chmod(_readonly, 0o700)


section("the note expires rather than accumulating")

os.makedirs(launchers.LAUNCH_GATE_DIR, exist_ok=True)
_stale = os.path.join(launchers.LAUNCH_GATE_DIR, "bounced-999")
with io.open(_stale, "w", encoding="utf-8") as _handle:
    _handle.write("222")
_old = time.time() - launchers.BOUNCE_SECONDS - 60
os.utime(_stale, (_old, _old))
# A bounce from a launch nobody is waiting on any more -- one written while the
# plugin was reloading, say. Answering it would put a dialog about a game on
# screen minutes after the user gave up on it.
check("a stale note is not answered", launchers.take_bounce(999), "")
check("but is still cleared away", os.path.exists(_stale), False)
check("a game that never bounced reads as no", launchers.take_bounce(12345), "")

summary()
