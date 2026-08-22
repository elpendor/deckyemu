"""The part of the Plugin class that puts a development device back to nothing.

Four resets, each named for what it destroys: RetroArch and its cores, the
one-click emulators and their data, the files sent over transfer, and the state
this plugin keeps about a library. One action per press, never bundled --
what they cost differs by orders of magnitude, and a single "reset everything"
would hide a trip to another machine for your BIOS dumps behind something that
rebuilds itself by using the plugin.

Gated twice, and deliberately not once. The Reset tab is compiled out of a
release bundle entirely, but "compiled out" is a property of one artifact and
these endpoints are reachable by anything that can talk to the plugin -- so
every one of them asks `devreset.available` as well, which keys on CI's
build.json rather than on a setting somebody could turn on after reading the
docs. This deletes save data.

Split out of main.py because it answers a different question from everything
around it: the file it sat in is about adding games to a library, and this is
about there not being one. Nothing else here reads it, and a release never runs
it.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import decky

import plugin_base

import devreset
import emu_install
import emulator_catalog
import sysenv


class DevReset(plugin_base.PluginContext):
    """Development-only resets. See the module docstring."""

    async def dev_reset_available(self):
        """Whether the reset tab may do anything. See py_modules/devreset.py.

        The frontend tab is compiled out of a release build entirely, so this is
        the second of two independent gates rather than the only one. It exists
        because "compiled out" is a property of one artifact and these endpoints
        are reachable by anything that can talk to the plugin.
        """
        return {"ok": True, "available": devreset.available(sysenv.PLUGIN_ROOT)}

    async def dev_reset_inventory(self):
        """What each reset would delete, with sizes, before anything happens."""
        if not devreset.available(sysenv.PLUGIN_ROOT):
            return {"ok": False, "error": "Not a development build."}
        return {"ok": True, "groups": await self._run(devreset.inventory)}

    async def dev_reset(self, action: str):
        """Run one reset. One action per press, named, never bundled.

        Separate because what they cost differs by orders of magnitude: state
        is rebuilt by using the plugin, a download is twenty minutes, and sent
        dumps and save games mean a trip to another machine. A single "reset
        everything" would hide the third behind the first.
        """
        if not devreset.available(sysenv.PLUGIN_ROOT):
            return {"ok": False, "error": "Not a development build."}

        decky.logger.warning("Dev reset requested: %s", action)

        if action == "retroarch":
            return await self._dev_reset_retroarch()
        if action == "emulators":
            return await self._dev_reset_emulators()

        simple = {
            "emulator_data": devreset.clear_emulator_data,
            "transfers": devreset.clear_transfers,
            "downloads": devreset.clear_downloads,
            "state": devreset.clear_state,
        }
        if action not in simple:
            return {"ok": False, "error": "Unknown reset %r." % action}

        freed = await self._run(simple[action])
        # Whatever was just deleted, this backend is still holding what it
        # detected before -- which RetroArch is installed, which cores it has,
        # which emulators are registered. Re-detected here rather than left to
        # whoever asks next, because the answer they would get is wrong and
        # nothing about it looks stale.
        await self.refresh_retroarch()
        decky.logger.warning("Dev reset %s freed %d bytes", action, freed)
        return {"ok": True, "freed": freed}

    async def _dev_reset_emulators(self):
        """Uninstall every catalog emulator this plugin can remove, data and all.

        Through the same endpoint the Emulators tab uses, so a system-wide
        flatpak is refused here for the same reason and with the same words --
        removing one needs root, which the plugin has not got.

        The data goes with it, and that is the difference between this and the
        tab's own Remove, where keeping it is a question worth asking. Here it
        is not: the reset exists so the next run is a first run, and an emulator
        whose `~/.var/app/<id>` survived comes back already configured, already
        holding its firmware, and reports itself set up -- which is the exact
        state this is for getting rid of.

        Two passes because neither alone covers it. `--delete-data` is
        flatpak's own and is the only thing that reaches a flatpak's data before
        the application id stops existing; the sweep afterwards is what reaches
        an AppImage's, which lives in ordinary folders the catalog has to name.

        Only for what actually came off: an emulator whose removal was refused
        is still installed, so deleting its saves would take data from an
        emulator this reset could not touch.
        """
        removed, failed, cleared = [], [], []
        for entry in emulator_catalog.CATALOG:
            present = (
                await self._run(emu_install.flatpak_installed, entry["source"]["id"])
                if entry["source"]["kind"] == "flatpak"
                else bool(await self._run(emu_install.installed_appimage, entry["id"]))
            )
            if not present:
                # Not installed, but its data can still be sitting there from an
                # install some earlier reset took away -- which is the leftover
                # that makes a reinstall arrive pre-configured.
                cleared.append(entry["id"])
                continue
            result = await self.uninstall_emulator(entry["id"], True)
            if result.get("ok"):
                removed.append(entry["name"])
                cleared.append(entry["id"])
            else:
                failed.append("%s (%s)" % (entry["name"], result.get("error", "")))
        freed = await self._run(devreset.clear_emulator_data, cleared)
        await self.refresh_retroarch()
        decky.logger.warning(
            "Dev reset emulators: %d removed, %d refused, %d bytes of data deleted",
            len(removed), len(failed), freed,
        )
        return {"ok": True, "removed": removed, "failed": failed, "freed": freed}

    async def _dev_reset_retroarch(self):
        """Remove RetroArch itself, its cores and its configuration."""
        app_id = "org.libretro.RetroArch"
        scope = await self._run(emu_install.flatpak_scope, app_id)
        if scope == "system":
            return {
                "ok": False,
                "error": "RetroArch was installed system-wide, most likely by EmuDeck. "
                "Removing it needs root, which the plugin cannot supply.",
            }

        # Only if it is there. A reset should be runnable twice, and the second
        # press finding nothing installed is success rather than a flatpak
        # error about an unknown application.
        if scope:
            removed = await self._flatpak_uninstall(app_id)
            if not removed["ok"]:
                return removed

        # The data directory survives a flatpak uninstall, and it is where the
        # cores, the system folder and every config override live -- so leaving
        # it is the difference between "removed" and "removed and forgotten".
        freed = await self._run(devreset.clear_retroarch_data)
        # Not just the emulators: RetroArch itself and its cores were what this
        # deleted, and both are held in this object until something re-detects.
        await self.refresh_retroarch()
        return {"ok": True, "freed": freed}
