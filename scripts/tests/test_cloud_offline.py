#!/usr/bin/env python3
"""A storage that cannot be reached never stops a game or loses a save.

    python scripts/tests/test_cloud_offline.py

The two things cloud saves do around a game are the two that run when nobody is
watching: the check before a launch and the copy after one. Both had their
network-failure paths written and none of them exercised -- and a launch is
exactly when the network is least likely to be there, because the Deck is on
somebody's train.

What is pinned here is that failure is uneventful. The launch is released
whatever happens, including a check that throws; a copy that could not run
leaves the record alone, so the next one still sends the save; and a name that
will not resolve is reported as a failure rather than read as a storage with
nothing on it.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import cloudsave  # noqa: E402
import cloudsync  # noqa: E402
import launchers  # noqa: E402
import savedata  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

#: One emulator, shaped as `savedata._all_sources` returns them.
SOURCES = [{"id": "retroarch", "name": "RetroArch", "whole": False,
            "roots": [("saves", "/home/deck/ra/saves")]}]

#: What rclone says when the Deck has no network. Taken from the device: the
#: resolver fails first, so the message is about a host and not about a file.
OFFLINE = ("dial tcp: lookup api.dropboxapi.com: no such host")

SETTINGS = {"cloud_saves": True, "cloud_remote": "dropbox",
            "cloud_before_play": True, "cloud_after_play": True}


class Swap:
    """Replaces module attributes for one block and puts them all back."""

    def __init__(self, *changes):
        self.changes = changes
        self.was = []

    def __enter__(self):
        for module, name, value in self.changes:
            self.was.append((module, name, getattr(module, name)))
            setattr(module, name, value)
        return self

    def __exit__(self, *_):
        for module, name, value in reversed(self.was):
            setattr(module, name, value)


section("the check before a launch, with nothing to check against")

# The record beside the saves is one `rclone cat`, and it is the only request
# the check makes. Failing it is the whole of being offline here.
with Swap((cloudsave, "rclone", lambda args, seconds: (False, OFFLINE)),
          (savedata, "_all_sources", lambda: list(SOURCES))):
    _found = cloudsync.compare("dropbox", "retroarch")

check("the comparison reports the failure rather than a verdict",
      (_found["error"] != "", _found["missing"], _found["differing"]),
      (True, 0, []))
check("and answers in the shape the caller reads either way",
      sorted(_found), sorted(cloudsync._nothing("x")))

# The same test used to be `"no such" in output`, which a name that will not
# resolve matches -- so an offline Deck read as a storage holding nothing, and
# the launch went on believing it had looked.
with Swap((cloudsave, "rclone", lambda args, seconds: (False, "object not found")),
          (savedata, "_all_sources", lambda: list(SOURCES))):
    _fresh = cloudsync.compare("dropbox", "retroarch")

check("while a storage nothing has been sent to yet is not a failure",
      (_fresh["error"], _fresh["missing"]), ("", 0))

# **Offline, rclone waits rather than failing.** Measured with wifi off: the
# check spent its whole six seconds and every launch made away from a network
# paid that, because the defaults retry three times over a sixty-second connect
# timeout. The restore screen reads the same record without these: there a
# spurious failure is a dialog saying the storage could not be read.
_asked = []
with Swap((cloudsave, "rclone", lambda args, seconds: _asked.append(args) or (False, OFFLINE)),
          (savedata, "_all_sources", lambda: list(SOURCES))):
    cloudsync.compare("dropbox", "retroarch")
    cloudsync.adopt_state("dropbox", "retroarch")

check("the check in front of a game gives up quickly",
      [flag for flag in ("--retries", "--contimeout") if flag in _asked[0]],
      ["--retries", "--contimeout"])
check("and reading the same record anywhere else does not",
      any(flag in _asked[1] for flag in ("--retries", "--contimeout")), False)


section("a launch is released whatever the check does")

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


_woken = []


def _wake(app_id):
    _woken.append(app_id)


def _boom(*args, **kwargs):
    raise RuntimeError("rclone died")


with Swap((store, "get_settings", lambda: dict(SETTINGS)),
          (cloudsave, "binary", lambda: "/tools/rclone"),
          (cloudsave, "rclone", lambda args, seconds: (False, OFFLINE)),
          (savedata, "_all_sources", lambda: list(SOURCES)),
          (launchers, "wake_launch", _wake)):
    _answer = run(plugin.cloud_before_play(4711, "snes9x_libretro"))

check("a check that could not run still starts the game",
      (_answer["ok"], _answer["restored"], _answer["differing"]),
      (True, 0, []))
check("and the launcher waiting on it is released", _woken, [4711])

# The `finally` is the point: a launch left waiting on a check that died is a
# game that never starts, which is worse than anything the check prevents.
del _woken[:]
_threw = ""
with Swap((store, "get_settings", lambda: dict(SETTINGS)),
          (cloudsave, "binary", lambda: "/tools/rclone"),
          (cloudsync, "learn_compare", lambda remote: []),
          (cloudsync, "compare", _boom),
          (launchers, "wake_launch", _wake)):
    try:
        run(plugin.cloud_before_play(4712, "snes9x_libretro"))
    except RuntimeError as problem:
        _threw = str(problem)

check("a check that throws releases the launch on the way out",
      (_threw, _woken), ("rclone died", [4712]))


section("a copy that could not run leaves the record alone")

_recorded = []
_saved = []


async def _failed_stream(steps, kind=""):
    return False, "connection refused"


async def _worked_stream(steps, kind=""):
    return True, ""


_common = (
    (store, "get_settings", lambda: dict(SETTINGS)),
    (store, "set_settings", lambda values: _saved.append(values)),
    (cloudsave, "binary", lambda: "/tools/rclone"),
    (savedata, "_all_sources", lambda: list(SOURCES)),
    (launchers, "took_off", lambda app_id: True),
    (cloudsync, "changed_since_push", lambda source: True),
    (cloudsync, "learn_compare", lambda remote: []),
    (cloudsync, "push_steps", lambda remote, ids: ([{"name": "saves", "argv": []}], "")),
    (cloudsync, "record_push", lambda remote, source: _recorded.append(source)),
    (cloudsync, "prune", lambda remote: None),
)

plugin._stream_cloud = _failed_stream
with Swap(*_common):
    _after = run(plugin.cloud_backup_after_play("snes9x_libretro", 4711))

check("the failure is reported rather than swallowed",
      (_after["ok"], _after["error"]), (False, "connection refused"))
# Without this the next launch compares against a record saying the storage
# holds what the Deck holds, and the save that never went up is never sent.
check("nothing is written down as having been sent", _recorded, [])
check("and the last-sync time is left as it was", _saved, [])

# The control: the same call with a copy that works does record it, so the
# checks above are about the failure and not about a call that did nothing.
plugin._stream_cloud = _worked_stream
with Swap(*_common):
    _good = run(plugin.cloud_backup_after_play("snes9x_libretro", 4711))

check("a copy that ran is written down", (_good["ok"], _recorded), (True, ["retroarch"]))
check("and stamps when the storage was last written to",
      [sorted(one) for one in _saved], [["cloud_last_sync"]])


if __name__ == "__main__":
    summary()
