#!/usr/bin/env python3
"""An install from a source the catalog has stopped naming says so, once.

    python scripts/tests/test_source_moved.py

Vita3K's `source` has moved twice: upstream's rolling release, then a fork of
the emulator while its motion fix was pending, now upstream's numbered builds.
Nothing carries an existing install across any of those. `source` is read live,
but the AppImage already on disk is never re-fetched, and AppImage updates are
not offered at all — so those installs would sit on a retired source forever
while the panel said nothing.

Which install that is needs neither a record nor a network call: the recipe
already says. Anything below the recipe at which the source moved was
necessarily downloaded from the old place.

The message is promised to appear once, and that promise is the reason this
file exists. `told` in the frontend is module scope and clears on every plugin
reload, so "once" has to be remembered by the record or it comes back after
every update — which is worse than never having promised.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_ENTRY = emulator_catalog.find("vita3k")
_MOVED_AT = _ENTRY["source_moved"]["recipe"]

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)


def install(recipe):
    """A Vita3K record as an install made under `recipe` would have left it.

    Recorded as a flatpak, which is not what Vita3K is: `validate` requires a
    `path` target to be an existing POSIX absolute path, and this suite also
    runs on Windows. Nothing under test reads `kind` -- the upgrade pass finds
    the entry by id -- and a fixture the validator rejects would be saved by
    nothing, which is exactly the failure this note replaced.
    """
    emulators._write([{
        "id": "vita3k", "name": "Vita3K", "kind": "flatpak",
        "target": "org.vita3k.Vita3K",
        "args": "{rom}", "extensions": ["pkg"], "databases": [],
        "platform": "Vita", "catalog_recipe": recipe,
        "catalog_args": "{rom}", "catalog_fullscreen_args": "--fullscreen",
        "workarounds_off": ["vita-motion"],
    }])
    plugin._emulators = emulators.list_emulators()


def stored():
    return emulators.find("vita3k") or {}


section("The recipe is the provenance")

install(_MOVED_AT - 1)
run(plugin._upgrade_emulator_recipes())
check("an install from before the move is flagged", stored().get("stale_source"), True)
# And the flag is *persisted*, not just computed: the upgrade pass saves only
# when something moved, so a flag left out of that comparison would be worked
# out on every start and written on none.
check("and the flag survives the pass that set it",
      emulators.find("vita3k").get("stale_source"), True)

install(_MOVED_AT)
run(plugin._upgrade_emulator_recipes())
check("an install from the current source is not flagged",
      bool(stored().get("stale_source")), False)


section("An install already running a fix keeps it")

# The gap this closes. Motion used to be part of the entry, applied to
# everybody; it is a switch now, defaulting to off. Reading "no choice
# recorded" as "apply the defaults" is right for a fresh install and wrong for
# the install that was already running it: the gyro stops working during a
# plugin update, nothing says so, and the user is left to find a setting they
# never knew existed.
install(_MOVED_AT - 1)                       # v0.9.19 applied motion to everybody
_record = stored()
_record.pop("workarounds_off", None)         # the key did not exist yet
_record["env"] = dict(emulator_catalog.deck_gyro.motion_env())
emulators._write([_record])
run(plugin._upgrade_emulator_recipes())
check("what it was already running stays on",
      stored().get("workarounds_off"), [])

# And the other half of the same rule: an install that never had it does not
# silently acquire it, which is what makes "absent means the defaults" right
# everywhere else.
install(_MOVED_AT - 1)
_record = stored()
_record.pop("workarounds_off", None)
_record["env"] = {}
emulators._write([_record])
run(plugin._upgrade_emulator_recipes())
check("and one that never had it stays off",
      stored().get("workarounds_off"), ["vita-motion"])


section("It is said until the emulator is updated")

install(_MOVED_AT - 1)
run(plugin._upgrade_emulator_recipes())
_listed = {row["id"]: row for row in emulators.list_emulators()}
check("the Emulators tab carries the note",
      _listed["vita3k"]["source_notice"], _ENTRY["source_moved"]["note"])

# The tab keeps saying it after the dialog has been shown -- somebody who
# dismissed that and forgot still needs somewhere to find out what it was.
_after = dict(stored(), source_notice_shown=True)
emulators._write([_after])
check("and goes on carrying it after the dialog has been shown",
      {r["id"]: r for r in emulators.list_emulators()}["vita3k"]["source_notice"],
      _ENTRY["source_moved"]["note"])


section("The dialog is said once, and the record is what remembers")

install(_MOVED_AT - 1)
run(plugin._upgrade_emulator_recipes())
_notices = emulators.launch_notices(stored())
check("a launch is told once", [n["state"] for n in _notices], ["source_moved"])
check("and told the sentence, not a flag",
      _notices[0]["note"], _ENTRY["source_moved"]["note"])

check("recording it is idempotent",
      [run(plugin.source_notice_shown("vita3k"))["ok"] for _ in range(2)],
      [True, True])
check("and the next launch is told nothing",
      emulators.launch_notices(stored()), [])

# The workaround notices are a different thing and must not be swept up in it:
# motion is switched off in this fixture, so there is nothing to say about it.
check("nothing else was invented to say", stored().get("fix_notices"), None)


section("Updating the emulator keeps what the user chose")

# The bug this catches. `to_emulator` records the catalog's *defaults* for the
# corrections, which is right for a first install and wrong for every later
# one: an update threw the user's choice away and switched motion back off
# without saying anything. `save` cannot rescue it -- it carries a key only
# when the caller sends nothing, and this caller sends the defaults.
# shadPS4 rather than Vita3K, and for a reason worth stating: `to_emulator`
# gives a github-sourced entry `kind: "path"`, and `validate` requires such a
# target to be an existing POSIX absolute path -- so on Windows the save fails,
# the registration returns early, and an assertion about the stored record
# passes without the code under test ever running. It did, until this was
# checked. shadPS4's flatpak record validates anywhere.
_SHAD = emulator_catalog.find("shadps4")
emulators._write([dict(
    emulator_catalog.to_emulator(_SHAD, "net.shadps4.shadPS4", {"x": ["bin"]}),
    workarounds_off=[])])                          # motion deliberately on
run(plugin._register_installed_emulator(_SHAD, "net.shadps4.shadPS4"))
check("an update leaves the corrections as the user left them",
      (emulators.find("shadps4") or {}).get("workarounds_off"), [])
emulators._write([])
check("and the defaults still apply to an install with no choice recorded",
      emulator_catalog.to_emulator(_ENTRY, "x", {}).get("workarounds_off"),
      ["vita-motion"])


section("Updating the emulator ends it")

# Both flags, because a user who never saw the message still gets a clean
# record out of updating -- and because the install came from wherever `source`
# names now, so anything said about the old one is finished.
_reinstalled = emulator_catalog.to_emulator(
    _ENTRY, "/home/deck/deckyemu/emulators/vita3k/Vita3K-x86_64.AppImage", {})
check("a fresh install carries neither flag",
      (_reinstalled.get("stale_source"), _reinstalled.get("source_notice_shown")),
      (None, None))
check("and records the recipe that clears it",
      _reinstalled.get("catalog_recipe"), _MOVED_AT)

emulators._write([])

if __name__ == "__main__":
    summary()
