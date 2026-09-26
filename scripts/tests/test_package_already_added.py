#!/usr/bin/env python3
"""A package whose game is installed is recognised as already added.

    python scripts/tests/test_package_already_added.py

The path match is made against the file that was picked, and for every other
console that is the file the record carries. A package is the exception: what
is added is what boots after the install -- `ux0/app/<id>/eboot.bin` for the
Vita, `dev_hdd0/game/<id>/USRDIR/EBOOT.BIN` for the PS3 -- so the `.pkg` in
front of the user matches neither the path nor the name of its own game, and
picking one already in the library said nothing at all.

The probe already knows: `installed` and `eboot` come back from the package
state. Asking again with the path that would be recorded is the whole fix.
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402

import ps4_games  # noqa: E402
import store  # noqa: E402
import vita_games  # noqa: E402

sys.path.insert(0, REPO_ROOT)
from main import Plugin  # noqa: E402

_EBOOT = "/home/deck/.local/share/Vita3K/Vita3K/ux0/app/ABCD00001/eboot.bin"

_dir = tempfile.mkdtemp(prefix="deckyemu-pkg-")
_pkg = os.path.join(_dir, "Some Game.pkg")
with open(_pkg, "wb") as _handle:
    _handle.write(b"\x7fPKG" + b"\0" * 64)

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


def probe(installed, eboot=_EBOOT, already=None):
    """`_probe_kinds` over a .pkg whose console says it is or is not installed."""
    result = {"already_added": already}
    plugin._vita_package_state = lambda path: {
        "installed": installed, "eboot": eboot if installed else "",
        "title": "Some Game", "title_id": "ABCD00001",
    }
    run(plugin._probe_kinds(result, _pkg, "pkg", False))
    return result


# Stubs rather than real headers: which console a package is for is
# `plugin_packages`' question and is tested there. What is under test is what
# happens once the answer is "installed".
_real_ps4, _real_vita = ps4_games.is_package, vita_games.is_package
ps4_games.is_package = lambda path: False
vita_games.is_package = lambda path: True

try:
    store.clear_library()
    store.remember_games({
        2001: {"app_id": 2001, "name": "Some Game", "title": "Some Game",
               "core_id": "emu:vita3k", "rom_path": _EBOOT,
               "system": "", "collection": "", "launcher_path": ""},
    })

    section("a package whose game is installed and added")

    _found = probe(True)["already_added"]
    check("the game is found", (_found or {}).get("name"), "Some Game")
    check("and reported as certain, because the boot path is exact",
          (_found or {}).get("same_file"), True)
    check("with the appid, so the panel can name the entry",
          (_found or {}).get("app_id"), "2001")

    section("and every way that must stay silent")

    check("a package not installed yet says nothing",
          probe(False)["already_added"], None)
    # Installed by the console but never added here, which is the state after
    # removing the game and keeping the data.
    store.clear_library()
    check("installed but not in the library says nothing",
          probe(True)["already_added"], None)

    section("a match the picked file already made is not overwritten")

    # The `.pkg` itself can be what a record carries -- a game added before it
    # was installed, or one whose emulator runs the package directly. That
    # answer is about the file in front of the user and outranks this one.
    _kept = {"app_id": "9", "name": "From the package", "same_file": True}
    check("the earlier answer stands", probe(True, already=_kept)["already_added"], _kept)

    section("an installed package with nowhere recorded to point at")

    store.remember_games({
        2001: {"app_id": 2001, "name": "Some Game", "title": "Some Game",
               "core_id": "emu:vita3k", "rom_path": _EBOOT,
               "system": "", "collection": "", "launcher_path": ""},
    })
    # `installed` without an eboot is what a console reports when it knows the
    # title id and cannot find the game. Nothing to compare, so nothing said.
    check("no boot path is not a match against everything",
          probe(True, eboot="")["already_added"], None)

    store.clear_library()
    plugin.loop.close()
finally:
    ps4_games.is_package, vita_games.is_package = _real_ps4, _real_vita
    try:
        os.remove(_pkg)
        os.rmdir(_dir)
    except OSError:
        pass


if __name__ == "__main__":
    from harness import summary
    summary()
