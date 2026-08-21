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

# Not asserted as literals -- copying a number into a check only proves it was
# copied. What matters is what the numbers buy.
_plugin = plugin_main.Plugin()

# 60 unauthenticated requests an hour, shared by every caller on the address.
# One check every six hours is four a day.
check("the settled interval cannot come close to GitHub's hourly budget",
      3600.0 / _plugin._UPDATE_INTERVAL <= 1, True)
check("nor is it so long that a day could pass without a check",
      _plugin._UPDATE_INTERVAL <= 24 * 60 * 60, True)

# The ladder replaces a fixed delay before the first check. The property that
# matters is that a network arriving late is not punished with six hours of
# silence -- so the first retry has to be minutes, not hours.
check("a check that failed is retried in minutes",
      _plugin._UPDATE_RETRY_DELAYS[0] <= 5 * 60, True)
check("every rung is shorter than simply waiting for the next round",
      max(_plugin._UPDATE_RETRY_DELAYS) < _plugin._UPDATE_INTERVAL, True)
# Bounded on the other side too: a device with no network at all must not sit
# in a retry loop spending requests.
check("and the whole ladder is over inside an hour",
      sum(_plugin._UPDATE_RETRY_DELAYS) <= 60 * 60, True)


section("what one pass tells the icon")

_plugin.loop = asyncio.new_event_loop()

_calls = []
# The last entry ends the watch: the handler re-raises CancelledError, which is
# also the real way this loop stops -- decky unloading the plugin.
#
# Two kinds of failure on purpose. A raised exception is the network being
# unreachable; a reply with checked=False is GitHub refusing, which does not
# raise anywhere. Both have to climb the ladder, and neither may emit.
_script = [
    RuntimeError("the network was not up"),
    {"available": False, "current": "1.0.0", "checked": False,
     "error": "GitHub did not answer.", "count": 0},
    _release("1.4.0"),
    asyncio.CancelledError(),
]


async def _fake_check(force=False):
    item = _script[len(_calls)] if len(_calls) < len(_script) else asyncio.CancelledError()
    _calls.append(force)
    if isinstance(item, BaseException):
        raise item
    return item


_plugin.check_for_update = _fake_check

# Nothing should really sleep, but what it *would* have slept is the whole point
# of this section, so it is recorded. Put back in the finally below: the suite
# shares one asyncio.
_delays = []
_real_sleep = asyncio.sleep


async def _fake_sleep(seconds, *args, **kwargs):
    _delays.append(seconds)
    return await _real_sleep(0)

_emitted = []


async def _record(event, *args):
    _emitted.append((event, args))


# A recorder of our own, saved and put back. `decky.emitted` is not usable here:
# two other files in this suite install their own `decky.emit` and do not
# restore it, so whichever ran first decides where these events land. This is
# the shared-state hazard the suite is full of -- it passed alone and failed
# together, which is the tell.
_level = decky.logger.level
_real_emit = decky.emit
try:
    asyncio.sleep = _fake_sleep
    decky.emit = _record
    decky.logger.level = logging.CRITICAL  # the failed check is deliberate
    try:
        _plugin.loop.run_until_complete(_plugin._watch_for_updates())
    except asyncio.CancelledError:
        pass
finally:
    asyncio.sleep = _real_sleep
    decky.emit = _real_emit
    decky.logger.level = _level

_emitted = [entry for entry in _emitted if entry[0] == "update_available"]

check("a check that answered says what it found", _emitted[0] if _emitted else None,
      ("update_available", (True, "1.4.0")))
# The one that matters most: a check that could not reach GitHub must say
# nothing at all. `available=False` is indistinguishable from "you are up to
# date", so emitting it would put out a dot a working check had lit.
check("and the two that could not answer said nothing", len(_emitted), 1)

# Four checks ran after the first one raised, which could not have happened if
# the exception had ended the task.
check("a failed check does not end the watch", len(_calls), 4)

section("and how long it waits before trying again")

# 60 then 120 from the ladder, then the settled interval once a check answered.
check("the first failure is retried on the first rung",
      _delays[0], _plugin._UPDATE_RETRY_DELAYS[0])
check("a second failure climbs rather than repeating",
      _delays[1], _plugin._UPDATE_RETRY_DELAYS[1])
check("and an answer settles it back to the ordinary interval",
      _delays[2], _plugin._UPDATE_INTERVAL)
check("nothing waited that was not one of those", len(_delays), 3)

# The first attempt of a cycle may use the cache -- a reload minutes after the
# last check should not spend a request. A retry may not: it exists because the
# last attempt failed, and the module's own 15-minute failure backoff would turn
# every rung below that into a call that never reaches the network.
check("the first check is happy with a cached answer", _calls[0], False)
check("while a retry insists on asking", _calls[1:3], [True, True])
# And the counter resets: the fourth check follows one that answered, so it is
# the first attempt of a new cycle rather than a fourth retry.
check("an answer puts the next check back on the cached path", _calls[3], False)

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
