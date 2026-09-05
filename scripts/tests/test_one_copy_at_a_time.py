#!/usr/bin/env python3
"""Saves move for four reasons, and each screen may only draw its own.

    python scripts/tests/test_one_copy_at_a_time.py

Two of the four start on their own -- a game closing copies that emulator up, a
game starting brings down what is missing -- and both were silent. Silent, but
not quiet: they emit the same progress and done events as the copy button and
the restore screen, so a dialog opened in the minute after quitting a game drew
that copy's bar and then announced it as its own. The restore screen went
further and closed itself with "Saves restored" over a copy that was going the
other way.

So every copy now says which it is, and the two somebody presses a button for
refuse to start while anything else is moving the same files.
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
import decky  # noqa: E402
import store  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


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


section("a copy somebody asks for waits for one already running")

_SETTINGS = {"cloud_saves": True, "cloud_remote": "dropbox"}
_planned = []

with Swap((store, "get_settings", lambda: dict(_SETTINGS)),
          (cloudsave, "binary", lambda: "/tools/rclone"),
          (cloudsave, "remotes", lambda: ["dropbox"]),
          (cloudsync, "learn_compare", lambda remote: []),
          (cloudsync, "pull_steps",
           lambda *args, **kwargs: _planned.append(args) or ([], "")),
          (cloudsync, "push_steps",
           lambda *args, **kwargs: _planned.append(args) or ([], ""))):
    plugin._copying = "after-play"
    _backup = run(plugin.cloud_backup_now())
    _restore = run(plugin.cloud_restore("dropbox"))
    plugin._copying = ""

check("the copy button says so rather than starting a second one",
      (_backup["ok"], "in a moment" in _backup["error"]), (False, True))
check("and so does a restore, which is the one that writes over saves",
      (_restore["ok"], "in a moment" in _restore["error"]), (False, True))
# Refused before planning, so nothing was read from the storage either.
check("neither of them got as far as planning anything", _planned, [])


section("what is moving is something the panel can ask about")

_status = {}
with Swap((store, "get_settings", lambda: dict(_SETTINGS)),
          (cloudsave, "binary", lambda: "/tools/rclone"),
          (cloudsave, "remotes", lambda: ["dropbox"]),
          (cloudsave, "remote_kinds", lambda: {"dropbox": "dropbox"}),
          (cloudsave, "label_for", lambda kind: "Dropbox")):
    plugin._copying = "after-play"
    _status = run(plugin.cloud_status(False))
    plugin._copying = ""

check("the panel is told which copy is running", _status.get("copying"), "after-play")


section("every line a copy emits says which copy it is")


async def _stream(steps, kind=""):
    return True, ""


_seen = []


async def _capture(event, *args):
    """Caught here rather than read from the stub's own list, which the whole
    suite shares -- these files run in one process under `test_backend.py`."""
    _seen.append((event, args))


plugin._stream_cloud = _stream
with Swap((decky, "emit", _capture),
          # Written into the same list, because what this section is about is
          # the order of the two.
          (cloudsync, "record_pushes",
           lambda remote, ids: _seen.append(("record_pushes", ())) or (True, "")),
          (cloudsync, "prune", lambda remote: None),
          (store, "set_settings", lambda values: None)):
    run(plugin._carry_saves([{"id": "retroarch", "name": "RetroArch", "argv": []}],
                            "cloud_sync_done", tidy="dropbox", kind="backup"))

_done = [args for event, args in _seen if event == "cloud_sync_done"]
check("the answer names the copy it is about, so one screen takes it",
      [args[-1] for args in _done], ["backup"])

# **The order matters and was wrong.** "Waiting to be copied" is answered from
# the record of what was last sent, and that record is written after the last
# byte moves -- so a panel told at the end of the copy re-read the list before
# it changed, and the row would not go away. Reported from the device.
_order = [event for event, _ in _seen
          if event in ("record_pushes", "cloud_copying", "cloud_sync_done")]
check("the copy is announced as over only once its record is written",
      _order, ["record_pushes", "cloud_copying", "cloud_sync_done"])


if __name__ == "__main__":
    summary()
