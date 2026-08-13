#!/usr/bin/env python3
"""Clearing the library has to say what it is doing.

    python scripts/tests/test_clear_progress.py

It is the one destructive action with no upper bound on how long it takes:
deleting an unpacked PS3 game is an rmtree over tens of gigabytes, and a library
of them runs for minutes. The button said "Removing..." for the whole of it,
which on a Deck -- no second window, no console -- is indistinguishable from a
hang, and the only thing worse than waiting is pressing it again.

So the checks here are about the two properties a bar has to have to be worth
drawing: it names something recognisable, and it never goes backwards.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402
import main  # noqa: E402
import store  # noqa: E402

section("clearing the library reports progress")

plugin = main.Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


def clear():
    """Clear, and hand back only the progress events it emitted."""
    decky.emitted.clear()
    run(plugin.clear_library())
    return [args for event, args in decky.emitted if event == "clear_library_progress"]


# The registry only, not `plugin.clear_library` -- when this file runs as part of
# the big suite it inherits whatever that left behind, and those entries point at
# fixture files the plugin-level clear would delete. Dropping the records first
# means the clear below sees three games and nothing else, here and standalone.
store.clear_library()

for app_id, title in ((910, "Cave Story"), (911, "Mega Man X"), (912, "Sonic")):
    store.remember_game(app_id, {"app_id": app_id, "title": title})

events = clear()
labels = [text for text, _ in events]
percents = [percent for _, percent in events]

# Named, not counted. "Deleting 2 of 3" is true of any library and tells the
# person watching nothing about whether the one they cared about has gone.
check("each game is named as it goes", [label for label in labels if "Deleting" in label],
      ["Deleting Cave Story", "Deleting Mega Man X", "Deleting Sonic"])
check("the launcher pass is announced too", "Removing launchers" in labels, True)
check("and the stray sweep, which is not instant on a large directory",
      "Tidying up leftover launchers" in labels, True)

check("progress never goes backwards", percents, sorted(percents))
check("and stays inside the bar", all(0 <= p <= 100 for p in percents), True)
# Short of 100 on purpose: the frontend still has the collections and the
# shortcuts to undo after this returns, and a bar that fills before the work
# ends is the thing it was drawn to avoid.
check("the backend does not claim to have finished", max(percents) < 100, True)

# The percentage is `index * 90 / total`, which divides by the library size.
# Nothing to delete, so only the two fixed phases are announced.
check("an empty library does not divide by zero",
      [text for text, _ in clear()],
      ["Removing launchers", "Tidying up leftover launchers"])

plugin.loop.close()


if __name__ == "__main__":
    from harness import summary

    summary()
