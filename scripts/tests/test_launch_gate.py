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
import threading
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

section("a launch that never reached the emulator says so")

# **"A game closed" is not "a game was played".** Steam counts an app as
# running from the moment it starts the script, so a launch the two-games gate
# refused and one declined at the save conflict both end exactly like a
# session -- and both were uploading afterwards. The conflict one overwrote the
# saves the person had just declined to overwrite, and after two or three goes
# there was nothing left to decline.
check("the marker is written past every gate, not before them",
      _body.index("launching-") < _body.index("ran-"), True)
check("and it is the last thing before the emulator, so anything that refuses "
      "a launch refuses it first",
      _body.rindex("ran-") > _body.rindex("kill -STOP"), True)

check("nothing has taken off until a launcher says so",
      launchers.took_off(4242), False)
check("and a marker is consumed once, so one session is not counted twice",
      (launchers.ran_marker().count("ran-"), launchers.took_off(4242)),
      (1, False))

section("waiting for cloud saves, in the script")

check("the wait is in the launcher",
      "launching-" in _body and "kill -STOP" in _body, True)
# The race this closes: the panel hears about a launch at the same moment the
# script runs, so asking once whether it has claimed the launch asks too early.
# Measured on the device -- the script won and the round trip through decky
# lost, and the game started while the save was still coming down.
check("and none of it happens without somewhere for saves to go",
      _body.index(launchers.CLOUD_ON_FILE) < _body.index("launching-"), True)
# **"Nobody has answered yet" and "nobody is there" are different questions.**
# They used to be one number and it had to be short, because a Deck with decky
# reloading must still start its games -- so a dialog somebody was reading got
# thirty seconds and then the game ran anyway.
check("a launch believes that file only while it is fresh",
      "-newermt" in _body and str(launchers.CLOUD_STALE_SECONDS) in _body, True)
check("and it is bounded, so a launch cannot be held forever",
      str(launchers.CLOUD_MAX_SECONDS) in _body, True)
# **The wait is a stopped process, not a conversation.** Every timing bug in
# versions 22-27 was in that conversation: two lost a race with Steam, one gave
# up 0.2s before the answer came, one left a note that refused the next launch.
# A stopped process has no timing to get wrong.
check("the script stops itself rather than polling for an answer",
      ("kill -STOP" in _body, "cloudbusy-" in _body), (True, False))
check("and says which process to wake, which is the whole protocol",
      "launching-" in _body, True)
# The two-games check can end a launch outright. Waiting for saves and then
# refusing to start would be a wait nobody got anything for.
check("the two-games check comes first",
      _body.index("bounced-") < _body.index("launching-"), True)


section("what the gate does, run as a shell actually runs it")

if os.name != "posix":
    print("SKIP  the gate is POSIX shell; there is none here")
else:
    # The real directory, not a stand-in. The script and the backend have to
    # agree on it, and pointing the script somewhere else is exactly the way to
    # write a passing check for two halves that never meet.
    _dir = launchers.LAUNCH_GATE_DIR
    # Both gates, in the order a launcher runs them. They are written
    # separately now -- the preflight goes between them -- and the pair is
    # still what a launch meets.
    _gate = launchers.launch_gate() + launchers.cloud_gate()

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

    def _launch_code(app_id):
        """What the launch printed, and the status Steam would see."""
        done = subprocess.run(
            [_reaper, "SteamLaunch", "AppId=%d" % app_id, "--", _script],
            capture_output=True, text=True, timeout=30,
        )
        return done.stdout, done.returncode

    def _elapsed(app_id):
        """How long a launch took, and what it printed."""
        began = time.time()
        said = _launch(app_id)
        return time.time() - began, said

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

        # **A yes goes stale.** The panel writes the token and launches in the
        # same breath, so anything older is an approval whose launch never
        # happened -- and honouring it would wave the *next* launch past the
        # gate without asking, which reads as the warning being unreliable.
        check("approving again writes a token", launchers.approve_launch(111), True)
        _token = os.path.join(_dir, "approved-111")
        _stale = time.time() - launchers.APPROVAL_SECONDS - 5
        os.utime(_token, (_stale, _stale))
        check("but an old one does not open the gate", "LAUNCHED" in _launch(111), False)
        check("and is cleared rather than left to be found again",
              os.path.exists(_token), False)
        # The bounce note is still written, so the panel asks as it would have.
        check("the launch is reported like any other", launchers.take_bounce(111), "222")

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

    section("a launch waits by stopping, and is woken or ended")

    os.makedirs(_dir, exist_ok=True)
    try:
        os.remove(os.path.join(_dir, "launching-321"))
    except OSError:
        pass

    # Cloud saves off. **This is the one that matters to everybody else**: a
    # Deck that does not use this feature must not pay a millisecond for it, and
    # the check is one `[ -f ]` on a file that is not there.
    launchers.set_cloud_wanted(False)
    _took, _said = _elapsed(321)
    check("with cloud saves off, a launch is not delayed and announces nothing",
          ("LAUNCHED" in _said, _took < 1, launchers.launches_waiting()),
          (True, True, []))

    launchers.set_cloud_wanted(True)

    # A file that says cloud saves are on but has not been touched in minutes
    # means the plugin is not running. Nothing waits for it.
    _stale = os.path.join(_dir, launchers.CLOUD_ON_FILE)
    os.utime(_stale, (time.time() - 600, time.time() - 600))
    _took, _said = _elapsed(321)
    check("with the plugin not saying anything for minutes, a launch does not "
          "stop at all",
          ("LAUNCHED" in _said, _took < 1, launchers.launches_waiting()),
          (True, True, []))
    launchers.say_alive()

    # **The whole protocol is a pid in a file.** Two earlier versions had the
    # script poll for an answer and both lost a race with Steam; a third gave up
    # 0.2s before the answer arrived. A stopped process has no timing to get
    # wrong -- it waits exactly as long as it is left stopped.
    _seen = []

    def _wake():
        _seen.extend(launchers.launches_waiting())
        launchers.wake_launch(321)

    _waker = threading.Timer(1.0, _wake)
    _waker.start()
    try:
        _took, _said = _elapsed(321)
        check("a stopped launch is visible to whatever is watching, and carries "
              "on the moment it is woken",
              ("LAUNCHED" in _said, 321 in _seen, 0.8 < _took < 5),
              (True, True, True))
    finally:
        _waker.cancel()
    check("and it takes its own file away afterwards",
          [name for name in os.listdir(_dir) if name.endswith("-321")], [])

    # **Told not to start.** The process is stopped and has not reached the
    # emulator, so ending it costs nothing -- and unlike a note left in a file,
    # it cannot arrive too late and refuse the *next* launch instead.
    _refused = []
    _killer = threading.Timer(
        1.0, lambda: _refused.append(launchers.refuse_launch(321)))
    _killer.start()
    try:
        _said, _code = _launch_code(321)
            # **A clean exit, not a kill.** Steam is waiting on this process: killed,
        # its loading screen stayed up and the launch never finished. `exit 0`
        # is what the two-games gate has always done.
        check("a refused launch never reaches the game, and exits cleanly",
              ("LAUNCHED" in _said, _refused, _code), (False, [True], 0))
    finally:
        _killer.cancel()

    # **The file has to go with it.** A killed launch never reaches the line
    # that would have cleared its own file, and a file nothing clears is a
    # launch the backend answers again on every look -- the same conflict
    # dialog, endlessly, for a game that is not going to start.
    check("and the file it left goes with it",
          [name for name in os.listdir(_dir) if name.startswith("launching-")], [])

    # The same hazard from the other direction: a launch whose process died for
    # any other reason.
    with io.open(os.path.join(_dir, "launching-321"), "w", encoding="utf-8") as _h:
        _h.write(os.linesep.join(["999999", "/gone/for/good.sh"]))
    check("a file whose process is gone is recognised and cleared, not answered",
          (launchers.gone(321), launchers.which_launch(321)), (True, 0))
    launchers.forget_launch(321)
    check("and clearing it is what leaves nothing to answer",
          launchers.launches_waiting(), [])

    # **A question belongs to one launch.** There is one file per game, so
    # relaunching replaces it -- and a wait still standing over the previous
    # launch keeps that game marked in flight, which silently skips every later
    # launch of it. That is how a conflict dialog stopped appearing after one
    # was left unanswered.
    with io.open(os.path.join(_dir, "launching-321"), "w", encoding="utf-8") as _h:
        _h.write(os.linesep.join([str(os.getpid()), sys.argv[0]]))
    _first = launchers.which_launch(321)
    check("a wait can tell which launch it belongs to", _first > 0, True)
    with io.open(os.path.join(_dir, "launching-321"), "w", encoding="utf-8") as _h:
        _h.write(os.linesep.join(["999999", "/gone/for/good.sh"]))
    check("and a launch that replaced it does not read as the same one",
          launchers.which_launch(321) == _first, False)
    launchers.forget_launch(321)

    # Nobody answers at all -- decky reloading, the plugin gone. The script
    # wakes itself. Rebuilt with a short watchdog so the suite does not sit
    # through the real one, which is deliberately generous.
    _was = launchers.CLOUD_MAX_SECONDS
    launchers.CLOUD_MAX_SECONDS = 2
    try:
        _patient = os.path.join(TMP, "gate-patient.sh")
        with io.open(_patient, "w", encoding="utf-8", newline="\n") as _handle:
            _handle.write("#!/bin/sh\n" + launchers.launch_gate()
                          + launchers.cloud_gate() + "\necho LAUNCHED\n")
        os.chmod(_patient, 0o755)
        _began = time.time()
        _said = _launch(321, _patient)
        _took = time.time() - _began
        check("with nobody there at all, the launch wakes itself and the game "
              "starts anyway",
              ("LAUNCHED" in _said, 1.5 < _took < 8), (True, True))
    finally:
        launchers.CLOUD_MAX_SECONDS = _was

    # A pid comes out of a file and one of the two things done with it is a
    # kill. A file left by a launch whose process has gone names a number the
    # system is free to have given to something else.
    check("and a pid that is not the launcher that wrote it is never signalled",
          (launchers._is_ours(os.getpid(), "/nothing/like/this"),
           launchers._is_ours(999999, _script),
           launchers._is_ours(0, "")),
          (False, False, False))

    launchers.set_cloud_wanted(False)
    check("switching cloud saves off takes the wait away again",
          os.path.exists(os.path.join(_dir, launchers.CLOUD_ON_FILE)), False)

    # An unwritable gate directory: the note cannot be left, but the decision was
    # already made and a launch that stops with nobody able to explain why is the
    # worst of both.
    _readonly = os.path.join(TMP, "gate-ro")
    os.makedirs(_readonly, exist_ok=True)
    _ro_script = os.path.join(TMP, "gate-ro.sh")
    with io.open(_ro_script, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "#!/bin/sh\n"
            + (launchers.launch_gate() + launchers.cloud_gate()).replace(
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
