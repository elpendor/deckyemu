#!/usr/bin/env python3
"""The timer that looks for a new release, and what it tells the icon.

    python scripts/tests/test_update_watch.py

Self-distribution is why this exists. A plugin in decky's store gets an update
notice from the loader -- a toast and a dot on decky's own icon, on a six-hour
timer -- and none of that reaches a plugin installed from its own releases page.
So the timer is ours to run.

The part worth guarding is the loop's stamina, not its arithmetic: it runs for
the whole life of the plugin, mostly while nobody is watching, and a check that
fails is the ordinary case rather than the exception -- a Deck's first check of
the day happens seconds after wake, with the network still coming up. A watch
that ends on the first of those is a watch that silently never runs again.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import main as plugin_main  # noqa: E402


def _release(version):
    return {"available": True, "current": "1.0.0", "checked": True, "error": "",
            "count": 1, "latest": {"version": version}}


_NOTHING = {"available": False, "current": "1.0.0", "checked": True, "error": "", "count": 0}


section("how often it asks")

# Not asserted as literals -- the numbers are decky's, and copying them into a
# check would only prove they were copied. What matters is what they buy.
_plugin = plugin_main.Plugin()
check("the first check waits, because the network is not up when Steam starts",
      _plugin._UPDATE_FIRST_DELAY > 0, True)
# 60 unauthenticated requests an hour, shared by every caller on the address.
# One check every six hours is four a day.
check("and the interval cannot come close to GitHub's hourly budget",
      3600.0 / _plugin._UPDATE_INTERVAL <= 1, True)
check("nor is it so long that a day could pass without a check",
      _plugin._UPDATE_INTERVAL <= 24 * 60 * 60, True)


section("what one pass tells the icon")

_plugin.loop = asyncio.new_event_loop()
# Nothing here should actually sleep; the delays are what the section above is
# for. Set on the instance so the class keeps the real values.
_plugin._UPDATE_FIRST_DELAY = 0
_plugin._UPDATE_INTERVAL = 0

_calls = []
# The last entry ends the watch: the handler re-raises CancelledError, which is
# also the real way this loop stops -- decky unloading the plugin.
_script = [
    _release("1.4.0"),
    RuntimeError("the network was not up"),
    _NOTHING,
    asyncio.CancelledError(),
]


async def _fake_check():
    item = _script[len(_calls)] if len(_calls) < len(_script) else asyncio.CancelledError()
    _calls.append(1)
    if isinstance(item, BaseException):
        raise item
    return item


_plugin.check_for_update = _fake_check

_level = decky.logger.level
_before = len(decky.emitted)
try:
    decky.logger.level = logging.CRITICAL  # the failed check is deliberate
    try:
        _plugin.loop.run_until_complete(_plugin._watch_for_updates())
    except asyncio.CancelledError:
        pass
finally:
    decky.logger.level = _level

_emitted = [entry for entry in decky.emitted[_before:] if entry[0] == "update_available"]

check("a check that found something says so", _emitted[0] if _emitted else None,
      ("update_available", (True, "1.4.0")))
# The transition after the first one: the user installed it. An event that only
# ever means yes can light the dot but never put it out.
check("and a check that found nothing says that too",
      _emitted[-1] if _emitted else None, ("update_available", (False, "")))
check("exactly one event per check that answered", len(_emitted), 2)

# The whole point of the section. Three checks ran after the one that raised,
# which could not have happened if the exception ended the task.
check("a failed check does not end the watch", len(_calls), 4)
check("and nothing is claimed on its behalf",
      [args for _, args in _emitted if args[0] and not args[1]], [])

_plugin.loop.close()


section("and it can be stopped")

# decky calls _unload when it is done with the plugin. A watch left running
# holds a reference to a plugin nobody wants and wakes up hours later to call
# methods on it.
check("_unload cancels the task it started",
      "_update_task" in open(plugin_main.__file__, encoding="utf-8").read()
      .split("async def _unload")[1].split("async def _uninstall")[0],
      True)
check("and the watch is started where startup cannot strand it",
      open(plugin_main.__file__, encoding="utf-8").read()
      .split("async def _main")[1].split("for label, step in")[0]
      .find("_watch_for_updates") > 0,
      True)


if __name__ == "__main__":
    summary()
