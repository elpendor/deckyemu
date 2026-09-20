#!/usr/bin/env python3
"""The endpoints that install and remove RetroArch and its cores.

    python scripts/tests/test_retroarch_endpoints.py

`installer.py` and `ra_detect.py` are covered elsewhere; what was not covered is
the layer between them and the panel -- the guards, the re-scan after a change,
and the reasons a removal is refused. That layer is the one every user meets
first, and every one of its answers is a sentence shown on the RetroArch tab.

Nothing here touches flatpak or the network: `installer` and `ra_detect` are
replaced with functions that record what they were asked and answer what the
case under test needs.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import installer  # noqa: E402
import ra_cores  # noqa: E402
import ra_detect  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_FLATPAK = {"kind": "flatpak", "exe": "flatpak", "config_dir": "/tmp/ra", "core_dirs": []}
_CORE = {
    "id": "bsnes_libretro",
    "path": "/tmp/cores/bsnes_libretro.so",
    "display_name": "bsnes",
    "system_name": "Super Nintendo Entertainment System",
    "databases": [],
    "extensions": ["sfc"],
}
_CATALOG = [
    {"id": "bsnes_libretro", "name": "bsnes", "extensions": ["sfc", "smc"]},
    {"id": "mupen64plus_next_libretro", "name": "Mupen64Plus-Next", "extensions": ["n64", "z64"]},
]

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = [_CORE]
plugin._emulators = []
plugin._install = dict(_FLATPAK)


def run(coro):
    return plugin.loop.run_until_complete(coro)


#: What the stand-ins were asked for, so a check can say the call was made.
asked = {}


def _stub(name, module, answer):
    """Replace `module.name` with something that records and answers."""

    def stand_in(*args, **kwargs):
        asked.setdefault(name, []).append(args)
        return answer(*args, **kwargs) if callable(answer) else answer

    setattr(module, name, stand_in)


_stub("core_catalog", installer, lambda refresh=False: [dict(one) for one in _CATALOG])
_stub("list_cores", ra_cores, lambda install: [_CORE])


section("the catalog says which cores are already here")

_catalog = run(plugin.list_installable_cores())
check("every entry says whether it is installed",
      {one["id"]: one["installed"] for one in _catalog},
      {"bsnes_libretro": True, "mupen64plus_next_libretro": False})


section("suggesting a core for a file nothing here can open")

check("an extension is matched however it was written",
      [one["id"] for one in run(plugin.suggest_cores_for_extension(".N64"))],
      ["mupen64plus_next_libretro"])
# Asked for every ROM whose extension no installed core claims, including ones
# with no extension at all -- so this answers rather than searching for "".
check("no extension suggests nothing", run(plugin.suggest_cores_for_extension("")), [])
check("and an extension nobody claims suggests nothing",
      run(plugin.suggest_cores_for_extension("nes")), [])


section("installing and removing a core needs RetroArch to be there")

plugin._install = None
check("installing says so rather than failing later",
      run(plugin.install_core("bsnes_libretro")),
      {"ok": False, "error": "RetroArch was not found on this system."})
check("and so does removing",
      run(plugin.uninstall_core("bsnes_libretro")),
      {"ok": False, "error": "RetroArch was not found on this system."})

plugin._install = dict(_FLATPAK)
_stub("install_core", installer, lambda install, core_id: {"ok": True})
_stub("uninstall_core", installer, lambda install, core_id: {"ok": True})

# The count comes back with the result because the panel shows it, and a
# re-scan is what makes a core selectable without reopening the tab.
check("a finished install re-scans and reports the new count",
      run(plugin.install_core("bsnes_libretro")).get("core_count"), 1)
check("a finished removal does the same",
      run(plugin.uninstall_core("bsnes_libretro")).get("core_count"), 1)

_stub("install_core", installer, lambda install, core_id: {"ok": False, "error": "no"})
check("a failed install carries the error and no count",
      run(plugin.install_core("bsnes_libretro")), {"ok": False, "error": "no"})


section("whether RetroArch can be installed at all")

_stub("flatpak_binary", installer, "/usr/bin/flatpak")
check("with flatpak present, it can", run(plugin.can_install_retroarch()),
      {"flatpak_available": True})
_stub("flatpak_binary", installer, "")
check("without it, it cannot", run(plugin.can_install_retroarch()),
      {"flatpak_available": False})


section("whether this install is DeckyEmu's to remove")

# Each of these is a sentence shown on the tab in place of a button, which is
# the whole reason the backend decides it: a greyed-out control explains
# nothing, and the four reasons are not interchangeable.
plugin._install = None
check("nothing installed", run(plugin.can_uninstall_retroarch())["reason"],
      "RetroArch is not installed.")

plugin._install = {"kind": "native"}
_native = run(plugin.can_uninstall_retroarch())
check("a native package belongs to the system",
      (_native["ok"], "package manager" in _native["reason"]), (False, True))

plugin._install = {"kind": "appimage"}
_appimage = run(plugin.can_uninstall_retroarch())
check("an AppImage nobody here installed is not ours to delete",
      (_appimage["ok"], "not DeckyEmu" in _appimage["reason"]), (False, True))

plugin._install = dict(_FLATPAK)
_stub("flatpak_scope", ra_detect, "system")
_system = run(plugin.can_uninstall_retroarch())
check("a system-wide flatpak needs root, which the plugin has not got",
      (_system["ok"], "root" in _system["reason"]), (False, True))

_stub("flatpak_scope", ra_detect, "user")
check("and a user-scope one can go", run(plugin.can_uninstall_retroarch()),
      {"ok": True, "kind": "flatpak", "scope": "user"})


section("removing it, and what the answer says afterwards")

_stub("retroarch_uninstall_argv", installer, lambda delete_data: [])
check("no flatpak binary is an error, not an attempt",
      run(plugin.uninstall_retroarch())["error"],
      "flatpak is not available on this system.")

_stub("retroarch_uninstall_argv", installer, lambda delete_data: [["flatpak", "uninstall"]])
plugin._run_flatpak = lambda argv: _answer({"ok": True})
# **`refresh_retroarch` calls `ra_detect.detect`, and stubbing anything else
# only looks like it works.** A development machine has no RetroArch, so the
# real call answers None and every check below passes for the wrong reason --
# on a Deck, where one is installed, the same test failed. Stub the name the
# code actually calls.
_stub("detect", ra_detect, None)


async def _answer(value):
    return value


_removed = run(plugin.uninstall_retroarch(True))
check("a removal that worked says the data went too",
      (_removed["ok"], _removed["deleted_data"]), (True, True))
# The re-detect matters most when the removal failed: `--delete-data` removes
# the application first, so a failure in the second half leaves RetroArch
# already gone and the tab still drawing it as installed.
check("and that the install is no longer there", _removed["still_installed"], False)

plugin._run_flatpak = lambda argv: _answer({"ok": False, "error": "flatpak said no"})
plugin._install = dict(_FLATPAK)
_stub("flatpak_scope", ra_detect, "user")
_failed = run(plugin.uninstall_retroarch())
check("a failed removal carries the error and re-detects anyway",
      (_failed["ok"], _failed["error"], _failed["still_installed"]),
      (False, "flatpak said no", False))


section("installing it")

plugin._install = dict(_FLATPAK)
check("not while one is already here",
      run(plugin.install_retroarch())["error"], "RetroArch is already installed.")

plugin._install = None
_stub("retroarch_install_argv", installer, [])
check("and not without flatpak to do it with",
      "flatpak is not available" in run(plugin.install_retroarch())["error"], True)


if __name__ == "__main__":
    summary()
