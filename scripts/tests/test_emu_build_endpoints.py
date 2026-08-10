#!/usr/bin/env python3
"""What the version endpoints refuse, and that going back holds.

    python scripts/tests/test_emu_build_endpoints.py

flatpak is not on the machine running this suite and would not have these
emulators installed if it were, so what is checked is the decision layer: which
requests are turned down and with what reason, and whether a rollback pins the
build it moved to.

The refusals are the point. Every one of them exists because the alternative is
a button that can only fail -- a system-scope flatpak cannot be changed without
a password the plugin has no way to give, and an AppImage has no commit history
to choose from. `can_uninstall_retroarch` established the rule these follow:
report the reason, never show a dead control.

The hold is the other half. A downgrade that is not pinned is undone by the next
update, and the person it happens to has no way to connect a game that broke a
week later to a version change they did not ask for. So "moved but could not
hold" has to be a distinct, reported outcome rather than success.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402
import emu_install  # noqa: E402
import main  # noqa: E402

section("changing an emulator's build -- what is refused, and what holds")

decky.logger.setLevel(logging.CRITICAL)

emitted = []


async def _record(event, *args):
    emitted.append((event, args))


decky.emit = _record

plugin = main.Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._emulators = []


def run(coro):
    return plugin.loop.run_until_complete(coro)


# ------------------------------------------------------------------- refusals

_r = run(plugin.update_emulator("no-such-emulator"))
check("an unknown emulator is refused", _r["ok"], False)
check("and named as not in the catalog", "not in the catalog" in _r["error"], True)

# Azahar is a github AppImage entry, so it has no Flathub build history and no
# commit to move to. Saying so beats offering a control that cannot work.
_r = run(plugin.update_emulator("azahar"))
check("an AppImage emulator is refused for updates", _r["ok"], False)
check("and the reason names Flathub", "Flathub" in _r["error"], True)

_r = run(plugin.emulator_build_list("azahar"))
check("an AppImage emulator lists no builds", _r["builds"], [])
check("and says why rather than returning an empty list quietly",
      "Flathub" in _r["error"], True)

# Not installed at all -- the suite's home is a temp directory with no flatpaks.
_r = run(plugin.update_emulator("dolphin"))
check("an emulator that is not installed is refused", _r["ok"], False)
check("and the reason says so", "not installed" in _r["error"], True)

_r = run(plugin.hold_emulator("dolphin", True))
check("holding one that is not installed is refused", _r["ok"], False)

# A commit is a value from the frontend heading for a command line.
for bad in ("", "abc", "$(id)", "d8644a97df3d"):
    _r = run(plugin.rollback_emulator("dolphin", bad))
    check("a bad commit never starts a rollback %r" % bad, _r["ok"], False)

# Nothing above should have reached the point of reporting progress.
check("a refused request emits nothing", emitted, [])


# --------------------------------------------------- rollback holds the build

# The entry, the argv builders and flatpak itself are all stubbed: what is under
# test is `_change_emulator_build`, not flatpak.
ENTRY = {"id": "pcsx2", "name": "PCSX2", "source": {"kind": "flatpak", "id": "net.pcsx2.PCSX2"}}

_streamed = []
_holds = []

# Restored at the end of the file. The whole suite runs these in one process, so
# a module left patched is a failure in whatever happens to run next -- and one
# that would look like a bug in that file rather than in this one.
_real_hold = emu_install.flatpak_hold
_real_commit = emu_install.flatpak_installed_commit


async def _fake_stream(entry_id, steps, must_succeed=("install",)):
    _streamed.append((entry_id, list(steps)))
    return True, ""


def _fake_hold(app_id, held):
    _holds.append((app_id, held))
    return True, ""


def _fake_commit(app_id):
    return "d8644a97df3db3cdd46eff2f7aea7d429c40f7e1e7ed5788a191714cc29a74a8"


plugin._stream_flatpak = _fake_stream
emu_install.flatpak_hold = _fake_hold
emu_install.flatpak_installed_commit = _fake_commit

emitted.clear()
run(plugin._change_emulator_build(ENTRY, [["flatpak", "update"]], "Going back", hold_after=True))
check("going back pins the build it moved to", _holds, [("net.pcsx2.PCSX2", True)])
check("and reports success", emitted[-1][1][1], True)
# Empty message: nothing went wrong, so there is nothing to caveat.
check("with no caveat when the hold took", emitted[-1][1][2], "")

# An update is not a rollback and must not pin anything -- pinning on update
# would stop every future update for an emulator nobody asked to freeze.
_holds.clear()
emitted.clear()
run(plugin._change_emulator_build(ENTRY, [["flatpak", "update"]], "Updating"))
check("a plain update pins nothing", _holds, [])
check("and reports success", emitted[-1][1][1], True)


# The outcome that must not read as plain success: moved, but not held. Left
# unsaid, the version moves again on the next update and nothing explains it.
def _refuse_hold(app_id, held):
    return False, "error: nothing matches org.foo"


emu_install.flatpak_hold = _refuse_hold
emitted.clear()
run(plugin._change_emulator_build(ENTRY, [["flatpak", "update"]], "Going back", hold_after=True))
check("a hold that fails still reports the move as done", emitted[-1][1][1], True)
check("but says it may move again", "may move it again" in emitted[-1][1][2], True)
check("and carries flatpak's reason", "nothing matches" in emitted[-1][1][2], True)


# A failed move must not be reported as a build change at all.
async def _fail_stream(entry_id, steps, must_succeed=("install",)):
    return False, "flatpak exited with code 1: no space left on device"


plugin._stream_flatpak = _fail_stream
_holds.clear()
emitted.clear()
run(plugin._change_emulator_build(ENTRY, [["flatpak", "update"]], "Going back", hold_after=True))
check("a failed move reports failure", emitted[-1][1][1], False)
check("and carries the reason", "no space left" in emitted[-1][1][2], True)
# Pinning a build that was never deployed would hold the old one instead.
check("and pins nothing", _holds, [])

emu_install.flatpak_hold = _real_hold
emu_install.flatpak_installed_commit = _real_commit
check("the module is handed back unpatched",
      (emu_install.flatpak_hold, emu_install.flatpak_installed_commit),
      (_real_hold, _real_commit))

plugin.loop.close()


if __name__ == "__main__":
    from harness import summary

    summary()
