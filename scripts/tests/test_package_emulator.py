#!/usr/bin/env python3
"""A package refuses before it spends anything, and says which emulator it wants.

    python scripts/tests/test_package_emulator.py

A `.pkg` is not a file anything can be pointed at -- it is installed *into* an
emulator -- so with that emulator missing there is nothing useful the panel can
offer except installing it. That answer has to arrive with the package, because
the alternative is finding out by pressing Install, and for one of the three
consoles that was expensive:

  PS3   RPCS3 does the unpacking, so it refused straight away.
  Vita  Vita3K does the unpacking, so it refused straight away.
  PS4   unpacking uses a standalone extractor and never consulted shadPS4, so
        it ran to completion -- minutes, gigabytes, and the .pkg deleted on the
        way -- and failed at the very end when there was nowhere to put the
        result.

So the checks below are in two halves: the state a package reports about its
emulator, and the refusal happening before any work rather than after it.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import emulators  # noqa: E402
import plugin_packages  # noqa: E402


section("a package says which emulator it needs, and whether it is here")

_PackagedGames = plugin_packages.PackagedGames

check("every console maps to a catalog emulator",
      sorted(_PackagedGames._PACKAGE_EMULATORS), ["ps3", "ps4", "vita"])

# Nothing is installed in the test home, so all three report the same shape and
# every one of them is the case the panel has to handle.
_states = {
    console: _PackagedGames._package_emulator(console)
    for console in _PackagedGames._PACKAGE_EMULATORS
}

check("each names the emulator it installs into",
      [_states[c]["emulator_id"] for c in ("ps3", "ps4", "vita")],
      ["rpcs3", "shadps4", "vita3k"])
# The name goes into a sentence on a button. An id would read as a filename.
check("with a name a sentence can use",
      [_states[c]["emulator_name"] for c in ("ps3", "ps4", "vita")],
      ["RPCS3", "shadPS4", "Vita3K"])
check("and none is ready, because none is installed here",
      [_states[c]["emulator_ready"] for c in ("ps3", "ps4", "vita")],
      [False, False, False])

# Installing the emulator is necessary but not always sufficient, and the offer
# says so before the download rather than leaving it to a black screen.
check("PS3 says firmware comes after the install", _states["ps3"]["needs_firmware"], True)
check("and so does the Vita", _states["vita"]["needs_firmware"], True)
check("PS4 needs none, so nothing is claimed", _states["ps4"]["needs_firmware"], False)


section("the refusal comes before the work, on every console")

_plugin = plugin_packages.PackagedGames.__new__(plugin_packages.PackagedGames)


async def _run(func, *args, **kwargs):
    return func(*args, **kwargs)


_plugin._run = _run


def _refusal(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


asyncio.set_event_loop(asyncio.new_event_loop())

# A path that does not exist. If any of these got as far as touching the file,
# the error would be about the file rather than about the emulator -- which is
# exactly the check: the emulator is asked about first.
_absent = os.path.join(os.path.dirname(__file__), "no-such-package.pkg")

_ps3 = _refusal(_plugin.install_ps3_package(_absent))
check("PS3 refuses", _ps3["ok"], False)
check("and names RPCS3", "RPCS3" in _ps3["error"], True)

_vita = _refusal(_plugin.install_vita_package(_absent))
check("Vita refuses", _vita["ok"], False)
check("and names Vita3K", "Vita3K" in _vita["error"], True)

# The one that used to spend everything first. It cannot reach the extractor
# without shadPS4 now, so a missing emulator costs nothing.
_ps4 = _refusal(_plugin.install_ps4_package(_absent))
check("PS4 refuses too, which it did not used to", _ps4["ok"], False)
check("and names shadPS4", "shadPS4" in _ps4["error"], True)

# "Install it first" named a task and not a route, in five places. The panel
# offers the install inline now, but these endpoints are reachable from screens
# that have no such row, so the message still has to say where.
check("every refusal says where to go",
      [("Emulators" in result["error"]) for result in (_ps3, _vita, _ps4)],
      [True, True, True])
check("and none of them still says the old dead end",
      [("Install it first" in result["error"]) for result in (_ps3, _vita, _ps4)],
      [False, False, False])

check("none of this needed an emulator to exist", emulators.find("rpcs3"), None)

summary()
