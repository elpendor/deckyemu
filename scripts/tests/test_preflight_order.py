#!/usr/bin/env python3
"""A launch that cannot work is refused before anything waits on a network.

    python scripts/tests/test_preflight_order.py

A launcher can end a launch in three places: the two-games gate, the check that
the ROM and the emulator are actually there, and -- much later -- the wait for
saves to come down. The first two are stats and answer at once. The third is a
network round trip.

They used to run in the wrong order. The preflight sat behind the save wait, so
a game whose emulator had been uninstalled left its note only once the fetch
finished: measured at 4.5 seconds on a Deck, against the four the panel spends
looking for that note. The dialog naming the missing emulator appeared or did
not depending on how long the network took, and the same launch, tried again a
minute later, behaved differently -- which reads as the check being broken
rather than as a race.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import launchers  # noqa: E402


section("the two gates are written apart")

check("the two-games gate stands alone",
      ("_dke_others" in launchers.launch_gate(),
       "cloudstop" in launchers.launch_gate()),
      (True, False))
check("and so does the wait for saves",
      ("cloudstop" in launchers.cloud_gate(),
       "_dke_others" in launchers.cloud_gate()),
      (True, False))


section("and a written launcher runs them in that order")

with tempfile.TemporaryDirectory() as home:
    import sysenv

    _real = sysenv.user_home
    sysenv.user_home = lambda: home
    try:
        install = {"kind": "flatpak", "exe": "/usr/bin/flatpak",
                   "config_dir": os.path.join(home, "ra"),
                   "core_dirs": [], "info_dirs": []}
        core = os.path.join(home, "ra", "cores", "c.so")
        os.makedirs(os.path.dirname(core))
        open(core, "w", encoding="utf-8").write("x")
        rom = os.path.join(home, "g.bin")
        open(rom, "w", encoding="utf-8").write("x")
        body = open(launchers.write_launcher(install, "Order", core, rom),
                    encoding="utf-8").read()
    finally:
        sysenv.user_home = _real

_two = body.index("_dke_others=")
_pre = body.index("_dke_missing=")
_cloud = body.index("cloudstop-")
check("the two-games gate, then the preflight, then the save wait",
      (_two < _pre, _pre < _cloud), (True, True))
# The note is the whole point of refusing rather than failing, and it is
# written from the preflight -- so it has to be reachable without the wait
# above it having finished.
check("and the note comes from the preflight, ahead of the wait",
      body.index('"$_dke_gate/missing-$_dke_self"') < _cloud, True)
