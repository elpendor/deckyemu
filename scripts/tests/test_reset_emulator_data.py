#!/usr/bin/env python3
"""Uninstalling every emulator takes their data with them, except what stayed.

    python scripts/tests/test_reset_emulator_data.py

The reset exists so that the next run is a first run. An emulator whose
`~/.var/app/<id>` survived its uninstall comes back already configured, already
holding the firmware it unpacked, and reporting itself set up -- which is
exactly the state the whole tab is for getting rid of, so leaving the data was
the reset quietly not resetting.

Two things worth checking rather than one. The data has to go for both kinds:
`flatpak uninstall --delete-data` is the only thing that reaches a flatpak's,
and an AppImage's lives in ordinary folders that only the catalog knows about,
so a sweep afterwards is what covers those. And it has to *stay* for an
emulator whose removal was refused -- a system-wide flatpak belongs to root and
is still installed afterwards, so taking its saves would destroy data for
something this reset could not touch.
"""

import asyncio
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section, summary  # noqa: E402  -- installs the stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402
import devreset  # noqa: E402
import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import emulators  # noqa: E402
import main  # noqa: E402
import sysenv  # noqa: E402

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def _run(coro):
    return LOOP.run_until_complete(coro)


def _catalog(entry_id):
    entry = emulator_catalog.find(entry_id)
    assert entry, "the catalog no longer has %r; pick another for this test" % entry_id
    return entry


# One of each kind, and a second flatpak to be refused. Read from the catalog
# rather than invented, so a definition that stops declaring where its data
# lives fails here rather than silently testing nothing.
REMOVED_FLATPAK = _catalog("pcsx2")
REFUSED_FLATPAK = _catalog("dolphin")
APPIMAGE = _catalog("vita3k")

HOME = sysenv.user_home()


def _data_dirs(entry):
    source = entry["source"]
    relatives = ([os.path.join(".var", "app", source["id"])]
                 if source["kind"] == "flatpak" else list(entry.get("data") or ()))
    return [os.path.join(HOME, *relative.split("/")) for relative in relatives]


def _seed(entry):
    """A data directory with something in it, as a real install would leave."""
    paths = _data_dirs(entry)
    assert paths, "%s declares nowhere its data lives" % entry["id"]
    for path in paths:
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "config.ini"), "w") as handle:
            handle.write("x" * 32)
    return paths


class _Plugin(main.Plugin):
    """The removals faked at the outermost point that still exercises the flow.

    `_run_flatpak` rather than the endpoints above it: the argv is what carries
    `--delete-data`, so faking any higher would stop testing the thing the
    flatpak half depends on.
    """

    def __init__(self):
        self.flatpak_argv = []

    async def _run_flatpak(self, argv):
        self.flatpak_argv.append(list(argv))
        return {"ok": True}

    async def refresh_retroarch(self):
        self._install = None
        return {}


plugin = _Plugin()
plugin.loop = LOOP
plugin._install = None

_real = {
    "flatpak_installed": emu_install.flatpak_installed,
    "flatpak_scope": emu_install.flatpak_scope,
    "installed_appimage": emu_install.installed_appimage,
    "remove_appimage": emu_install.remove_appimage,
    "flatpak_binary": emu_install.flatpak_binary,
    "remove": emulators.remove,
}

_installed_flatpaks = {REMOVED_FLATPAK["source"]["id"], REFUSED_FLATPAK["source"]["id"]}

emu_install.flatpak_installed = lambda app_id: app_id in _installed_flatpaks
# The refused one is the whole point of the second check: system scope is what
# the plugin cannot remove, because doing so needs a password it has not got.
emu_install.flatpak_scope = lambda app_id: (
    "system" if app_id == REFUSED_FLATPAK["source"]["id"]
    else ("user" if app_id in _installed_flatpaks else "")
)
emu_install.installed_appimage = lambda entry_id: (
    "/nonexistent/%s.AppImage" % entry_id if entry_id == APPIMAGE["id"] else None
)
emu_install.remove_appimage = lambda entry_id: (True, "")
emu_install.flatpak_binary = lambda: "/usr/bin/flatpak"
emulators.remove = lambda entry_id: None

section("uninstalling every emulator deletes what those emulators owned")

_removed_data = _seed(REMOVED_FLATPAK)
_refused_data = _seed(REFUSED_FLATPAK)
_appimage_data = _seed(APPIMAGE)

try:
    result = _run(plugin.dev_reset("emulators"))
finally:
    for name, value in _real.items():
        setattr(emu_install if name != "remove" else emulators, name, value)

check("the reset runs", result.get("ok"), True)
check("and reports what came off", REMOVED_FLATPAK["name"] in result.get("removed", []), True)

# The flatpak half. `--delete-data` is flatpak's own and is the only thing that
# reaches the data before the application id stops existing, so its absence
# would leave the directory standing on a real device however well the sweep
# afterwards works.
check("a flatpak is uninstalled with its data",
      any("--delete-data" in argv and REMOVED_FLATPAK["source"]["id"] in argv
          for argv in plugin.flatpak_argv), True)
check("and the directory is gone",
      [path for path in _removed_data if os.path.isdir(path)], [])

# The AppImage half, which no uninstall touches: its data is in ordinary
# folders and only the catalog knows where, so the sweep is the only thing that
# can reach it.
check("an AppImage's data is deleted too",
      [path for path in _appimage_data if os.path.isdir(path)], [])
check("and the bytes are reported", result.get("freed", 0) > 0, True)

# The one that must survive. Refusing to remove an emulator and deleting its
# saves anyway would be the worst outcome available here.
check("an emulator that could not be removed keeps its data",
      sorted(path for path in _refused_data if os.path.isdir(path)),
      sorted(_refused_data))
check("and is reported as refused",
      any(REFUSED_FLATPAK["name"] in item for item in result.get("failed", [])), True)


section("the dialog names the data before anything is deleted")

# Re-seeded: the run above deleted what it listed. The inventory is what the
# confirm dialog renders, and an action that destroys save games while the
# dialog lists only emulator names is the one shape this must not have.
_seed(REFUSED_FLATPAK)
_inventory = devreset.inventory()
_labels = [item["label"] for item in _inventory["emulators"]]
check("the emulator group lists the data directories",
      any("data (" in label for label in _labels), True)
check("with their sizes",
      any(item["bytes"] > 0 for item in _inventory["emulators"]), True)
# Still its own action, because deleting data without uninstalling is a
# different thing to want -- and the row above is not a substitute for it.
check("and the data group still stands on its own",
      len(_inventory["emulator_data"]) > 0, True)


section("narrowing by id is what keeps a refused emulator's data")

_only = [entry["id"] for entry in emulator_catalog.CATALOG
         if entry["id"] != REFUSED_FLATPAK["id"]]
check("what a narrowed sweep would find excludes it",
      [path for _name, path in devreset._emulator_data_dirs(_only)
       if path in _refused_data], [])
check("while the unrestricted one still finds it",
      sorted(set(path for _name, path in devreset._emulator_data_dirs()) & set(_refused_data)),
      sorted(_refused_data))


# The seeded directories go again. The suite shares one home, and a file that
# leaves an emulator's data lying around is invisible until something further
# down counts what is on disk and finds one more than it wrote.
for _path in _refused_data:
    shutil.rmtree(_path, ignore_errors=True)

decky.logger.info("done")
summary()
