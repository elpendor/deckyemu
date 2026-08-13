#!/usr/bin/env python3
"""One broken startup step must not cost the others.

    python scripts/tests/test_startup.py

`_main` runs seven things in order. The first two find out what is installed;
the rest are one-time migrations of data already on the device -- launchers
written by an older build, a library entry with no platform recorded, an
emulator whose recommended settings were never applied.

They were a single chain of awaits, which made every one of them a single point
of failure for the whole of startup. An unreadable launcher, an imported
definition that no longer parses, a config file with the wrong owner: the steps
after it never ran. Not only on that start, either -- on every later one too,
because nothing about the state that broke it would change between them. So the
symptom is not a crash but a plugin that is permanently missing whatever the
steps after the failure were meant to do, with one line in a log nobody is
reading.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402
import main  # noqa: E402

section("startup survives a step that fails")

# The failure below is logged with a traceback, which is correct and also reads
# like a broken run. Restored at the end.
_log_level = decky.logger.level
decky.logger.setLevel(logging.CRITICAL)

ran = []


async def _step(name, fail=False):
    ran.append(name)
    if fail:
        raise OSError("[Errno 13] Permission denied: '/home/deck/.config/thing'")


class _Startup(main.Plugin):
    """Only the steps are replaced, so `_main`'s own handling is what runs."""

    async def refresh_retroarch(self):
        await _step("detect")

    async def _backfill_library(self):
        # In the middle, and a real failure mode: library.json readable but
        # holding an entry that no longer resolves to anything.
        await _step("backfill", fail=True)

    async def _adopt_menu_combo(self):
        await _step("menu")

    async def _pin_collection_layout(self):
        await _step("collections")

    async def _upgrade_launchers(self):
        await _step("launchers")

    async def _upgrade_emulator_recipes(self):
        await _step("recipes")

    async def _upgrade_emulator_setups(self):
        await _step("setups")


_plugin = _Startup()
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
try:
    # Reaching the end at all is half the check: `_main` returning is what tells
    # decky the plugin loaded, and an exception here is what this prevents.
    _loop.run_until_complete(_plugin._main())
finally:
    asyncio.set_event_loop(None)
    _loop.close()

check("every step runs even after one raises",
      ran, ["detect", "backfill", "menu", "collections", "launchers", "recipes", "setups"])
# Stated separately because these five are the whole point: they are the ones
# that silently never ran, and the ones whose absence is invisible.
check("the steps after the failure are the ones that matter", ran[2:],
      ["menu", "collections", "launchers", "recipes", "setups"])

# A guard that swallows everything is its own bug: startup carrying on past a
# step that never ran at all would report success for a plugin that had done
# none of its migrations. The list above is what says each one was attempted.
check("and the guard did not skip anything", len(ran), 7)

decky.logger.setLevel(_log_level)


if __name__ == "__main__":
    from harness import summary

    summary()
