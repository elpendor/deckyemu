"""The part of the Plugin class that installs RetroArch and its cores.

Everything that *changes* what is installed. Reading what currently is stays in
main.py, with the detected install and the core list it keeps -- these two
halves look alike and are not: one answers a question, and the other spends
twenty minutes of somebody's evening and then has to say so while it happens.

Two sources, because RetroArch and its cores are distributed separately.
RetroArch is a flatpak from Flathub, installed by running `flatpak` and reading
its output back as progress. Cores come from libretro's buildbot as individual
.so files, which is why installing one is quick and installing RetroArch is not.

`installer.py` does the fetching and the argv building. What is here is the part
that has to be a plugin endpoint: streaming a long install to a panel that is
watching, refusing an uninstall the plugin cannot perform, and re-detecting
afterwards so the rest of the object is not describing the state from before.

**A system-wide flatpak cannot be removed without root**, which the plugin has
not got. EmuDeck installs one that way, so this is an ordinary case rather than
an edge one, and `can_uninstall_retroarch` exists so the interface can say why
the button is not there instead of offering a dead one.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import asyncio

import decky

import plugin_base

import installer
import procout
import ra_cores
import ra_detect


class RetroArchInstall(plugin_base.PluginContext):
    """Installing RetroArch and cores. See the module docstring."""

    async def list_installable_cores(self, refresh: bool = False):
        """The full buildbot catalog, annotated with what is already installed."""
        catalog = await self._run(installer.core_catalog, refresh)
        installed = {core["id"] for core in await self.list_cores()}
        for entry in catalog:
            entry["installed"] = entry["id"] in installed
        return catalog

    async def suggest_cores_for_extension(self, extension: str):
        """Installable cores that claim `extension`, for ROMs with no local core."""
        ext = (extension or "").lower().lstrip(".")
        if not ext:
            return []
        catalog = await self.list_installable_cores()
        return [entry for entry in catalog if ext in entry["extensions"]]

    async def install_core(self, core_id: str):
        if not self._install:
            return {"ok": False, "error": "RetroArch was not found on this system."}

        await decky.emit("core_install_progress", core_id, "downloading", 0)
        result = await self._run(installer.install_core, self._install, core_id)

        if result.get("ok"):
            # Re-scan so the new core is immediately selectable.
            self._cores = await self._run(ra_cores.list_cores, self._install)
            result["core_count"] = len(self._cores)
            await decky.emit("core_install_progress", core_id, "done", 100)
        else:
            await decky.emit("core_install_progress", core_id, "failed", 0)

        return result

    async def uninstall_core(self, core_id: str):
        if not self._install:
            return {"ok": False, "error": "RetroArch was not found on this system."}
        result = await self._run(installer.uninstall_core, self._install, core_id)
        if result.get("ok"):
            self._cores = await self._run(ra_cores.list_cores, self._install)
            result["core_count"] = len(self._cores)
        return result

    async def can_install_retroarch(self):
        return {"flatpak_available": bool(await self._run(installer.flatpak_binary))}

    async def can_uninstall_retroarch(self):
        """Whether removing RetroArch is something this plugin may attempt.

        Reported rather than decided in the UI so the reason can be shown: a
        greyed-out button with no explanation is worse than no button.
        """
        if not self._install:
            return {"ok": False, "reason": "RetroArch is not installed."}

        kind = self._install.get("kind")
        if kind != "flatpak":
            return {
                "ok": False,
                "kind": kind,
                "reason": (
                    "This is a native package install, which belongs to the system's package "
                    "manager and would need SteamOS's read-only filesystem unlocked."
                    if kind == "native"
                    else "This is a loose AppImage that DeckyEmu did not install, so it is not "
                    "DeckyEmu's to delete. Remove the file yourself if you want it gone."
                ),
            }

        scope = await self._run(ra_detect.flatpak_scope)
        if scope == "system":
            return {
                "ok": False,
                "kind": kind,
                "scope": scope,
                "reason": (
                    "This flatpak was installed system-wide, most likely by EmuDeck or Discover. "
                    "Removing it needs root, which the plugin cannot supply. Uninstall it from "
                    "Discover in desktop mode."
                ),
            }

        return {"ok": True, "kind": kind, "scope": scope or "user"}

    async def uninstall_retroarch(self, delete_data: bool = False):
        """Remove the user-scope RetroArch flatpak.

        Deliberately synchronous, unlike the install: removal takes a couple of
        seconds and has nothing worth streaming, and a result the UI can act on
        beats a progress bar here.

        Games already added to Steam keep their shortcuts and launcher scripts.
        Nothing is rewritten, because reinstalling RetroArch makes every one of
        them work again -- and deleting them here would be an unrelated,
        irreversible act hidden behind a button labelled "uninstall RetroArch".
        """
        allowed = await self.can_uninstall_retroarch()
        if not allowed.get("ok"):
            return {"ok": False, "error": allowed.get("reason", "RetroArch cannot be removed.")}

        argv = await self._run(installer.retroarch_uninstall_argv, bool(delete_data))
        if not argv:
            return {"ok": False, "error": "flatpak is not available on this system."}

        result = await self._run_flatpak(argv)

        # Re-detected whether or not that succeeded, and the failure case is the
        # one that needs it. `--delete-data` removes the application first and
        # its data second, so a failure in the second half leaves RetroArch
        # already gone -- and returning the error without re-detecting left every
        # tab still showing it as installed, which is a worse answer than the
        # error. It is also how a failed-but-zero-exit removal gets caught.
        await self.refresh_retroarch()
        if not result.get("ok"):
            return dict(result, still_installed=bool(self._install))
        return {
            "ok": True,
            "still_installed": bool(self._install),
            "deleted_data": bool(delete_data),
        }

    async def install_retroarch(self):
        """Kick off a user-scope flatpak install, streaming progress as events."""
        if self._install:
            return {"ok": False, "error": "RetroArch is already installed."}

        steps = await self._run(installer.retroarch_install_argv)
        if not steps:
            return {
                "ok": False,
                "error": "flatpak is not available on this system, so RetroArch cannot be installed automatically.",
            }

        self._detach(self._run_retroarch_install(steps), "retroarch_install_done")
        return {"ok": True, "started": True}

    async def _run_retroarch_install(self, steps):
        """RetroArch is a large download, so progress is streamed to the UI."""
        env = self._subprocess_env()
        decky.logger.info(
            "Install environment: HOME=%s XDG_DATA_HOME=%s",
            env.get("HOME"),
            env.get("XDG_DATA_HOME"),
        )

        try:
            for argv in steps:
                decky.logger.info("Running: %s", " ".join(argv))
                try:
                    process = await asyncio.create_subprocess_exec(
                        *argv,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        env=env,
                    )
                except (OSError, NotImplementedError) as error:
                    # NotImplementedError happens when the event loop cannot
                    # spawn children, which is not obvious from an exit code.
                    decky.logger.exception("Could not start %s", argv[0])
                    await decky.emit(
                        "retroarch_install_done", False, "Could not run flatpak: %s" % error
                    )
                    return

                # The output keeps its own last few lines, so a failure can be
                # explained rather than reduced to a number -- flatpak writes
                # the actual reason there.
                output = procout.Output()
                async for text in output.segments(process.stdout):
                    decky.logger.info("flatpak: %s", text)
                    await decky.emit(
                        "retroarch_install_progress", text, self._parse_percent(text)
                    )

                code = await process.wait()
                decky.logger.info("%s exited with %d", argv[1] if len(argv) > 1 else argv[0], code)

                # remote-add is allowed to fail: the remote usually already exists.
                if code != 0 and "install" in argv:
                    await decky.emit(
                        "retroarch_install_done",
                        False,
                        "flatpak exited with code %d: %s" % (code, output.reason),
                    )
                    return

            status = await self.refresh_retroarch()
            await decky.emit(
                "retroarch_install_done",
                bool(status["found"]),
                "" if status["found"] else "Install finished but RetroArch was still not found.",
            )
        # Only the expected failure, and deliberately not CancelledError: this
        # runs detached, so `_detach` re-raises a cancellation properly and
        # reports anything else. Catching it here swallowed an unload, then tried
        # to emit over the socket that was closing.
        except OSError as error:
            decky.logger.exception("RetroArch install failed")
            await decky.emit("retroarch_install_done", False, str(error))
