#!/usr/bin/env python3
"""The update check answers for the list its button sits under.

    python scripts/tests/test_update_scope.py

`EmulatorCatalogPanel` is rendered twice -- once as **Ready-made emulators**,
once as **Ports** -- and everything in it is filtered by which one it is: the
rows, the heading, the empty-state sentence. The update check was not, so the
button below the ports list asked every emulator as well.

The visible cost was a Deck with every port removed answering *"4 emulators have
updates"* on the ports tab. The count was true and the reader was not looking at
any of it. Three separate leaks of the one omission, and this pins the one that
cannot be seen from the frontend: what the backend actually walks.

Also here because it is the same call: the cache of last-seen tags is written
back whole, so an id the catalog no longer has used to stay in it for good.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import emulator_catalog  # noqa: E402
import emu_install  # noqa: E402
import main  # noqa: E402


def entry(entry_id, port):
    return {
        "id": entry_id,
        "name": entry_id.title(),
        "summary": "x",
        "args": "{rom}",
        "port": port,
        "source": {"kind": "github", "repo": "someone/" + entry_id,
                   "asset": "^x\\.AppImage$"},
    }


CATALOG = [entry("anemu", False), entry("aport", True)]

section("the check walks one half of the catalog")

asked = []


def _fake_latest_tag(one):
    asked.append(one["id"])
    return "v2", ""


plugin = main.Plugin()
# The endpoints run on a loop the plugin normally gets from decky.
plugin.loop = asyncio.new_event_loop()
_real = (emulator_catalog.CATALOG, emu_install.latest_tag,
         emu_install.installed_appimage, emu_install.read_build_record,
         emu_install.read_latest_tags, emu_install.write_latest_tags)
written = {}

emulator_catalog.CATALOG = tuple(CATALOG)
emu_install.latest_tag = _fake_latest_tag
emu_install.installed_appimage = lambda one: "x.AppImage"
emu_install.read_build_record = lambda one: {"tag": "v1"}
emu_install.read_latest_tags = lambda: {"anemu": "v1", "aport": "v1", "gone": "v9"}
emu_install.write_latest_tags = lambda tags: written.update(tags)

def run(coro):
    """The endpoints are async; the plugin carries the loop they were built on."""
    return plugin.loop.run_until_complete(coro)


try:
    asked.clear()
    result = run(plugin.check_emulator_updates(False))
    check("asked for emulators is the emulators", asked, ["anemu"])
    check("and counts only them", (result["checked"], result["available"]), (1, 1))

    asked.clear()
    result = run(plugin.check_emulator_updates(True))
    check("asked for ports is the ports", asked, ["aport"])
    check("and counts only them", (result["checked"], result["available"]), (1, 1))

    # The default is the emulators, because that is the tab the button has
    # always been on -- a caller that has not been updated must not silently
    # start reporting on ports.
    asked.clear()
    run(plugin.check_emulator_updates())
    check("the default is the emulators", asked, ["anemu"])

    section("the tag cache drops what the catalog no longer has")

    # `gone` is an emulator that was removed. Nothing reads its tag, but the
    # file was written back whole, so it stayed there for good -- and it is the
    # first place somebody debugging this count would look.
    check("a removed id is not written back", "gone" in written, False)
    check("and the ones still here are", sorted(written), ["anemu", "aport"])
finally:
    (emulator_catalog.CATALOG, emu_install.latest_tag,
     emu_install.installed_appimage, emu_install.read_build_record,
     emu_install.read_latest_tags, emu_install.write_latest_tags) = _real
    plugin.loop.close()


if __name__ == "__main__":
    from harness import summary

    summary()
