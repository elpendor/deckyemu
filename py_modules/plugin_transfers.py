"""The part of the Plugin class that moves files on and off the device.

One HTTP server, used in both directions. Sending is the point: a ROM, a BIOS
dump or an emulator definition reaches `~/deckyemu` from a phone or a laptop
over a QR code or a six-digit code, with no cable, no Desktop Mode and no
keyboard worth the name. Reading a diagnostic report back off the Deck is the
same server run backwards, with the same token and the same lockout, because the
alternative was asking somebody in Game Mode to find a log file.

The endpoints here are thin: `fileserver` owns the sockets, the token, the
lockout and the idle timeout, and `fileserver_page` owns what goes over the
wire. What is left in this file is what the *plugin* has to decide -- where a
send should land by default, which emulators are installed so a definition can
name one, and what a report may contain before it leaves the device.

Split out of main.py because it answers a different question from the file it
sat in: adding a game to a library is not the same subject as getting the file
onto the device in the first place, and neither half reads the other.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import os

import decky

import plugin_base

import diagnostics
import emu_install
import emulator_catalog
import fileserver
import store


class Transfers(plugin_base.PluginContext):
    """Sending files to the Deck and reading a report back. See the module docstring."""

    async def file_server_status(self):
        status = await self._run(fileserver.status)
        status["received"] = await self._run(fileserver.received_files)
        # Its own folder, not wherever ROMs are browsed from -- see
        # fileserver.default_dir.
        status["suggested_dir"] = await self._run(fileserver.default_dir)
        return status

    async def start_report(self):
        """Gather a diagnostic report and put it where another device can read it.

        The plugin logs plenty and none of it is reachable from Game Mode, so the
        best report a user can give is "it didn't work" -- which is also the
        least useful one. This is the same problem the transfer server already
        solves in the other direction, so it is the same server: a QR code for a
        camera, six digits for anything with a keyboard.

        What is gathered and what is struck out of it is `diagnostics`, and the
        striking out is the part that matters -- the settings hold a
        RetroAchievements token that is password-equivalent, and this text is
        going into a public issue.
        """
        # The session's own transfer token is struck by value: it is minted per
        # session so no settings file holds it, it reaches the log as a bare
        # request path that no URL rule catches, and it is live on the network
        # at the moment somebody reads the report.
        serving = await self._run(fileserver.status)
        report = await self._run(
            diagnostics.build,
            await self.plugin_version(),
            self._install,
            self._emulators,
            await self._run(store.get_library),
            await self._run(self._installed_catalog_ids),
            [serving.get("url", "").rstrip("/").rsplit("/", 1)[-1]],
            await self._run(fileserver.default_dir, False),
        )

        if not serving.get("running"):
            # Started to hand a report out, and nothing else: a server brought up
            # for this does not accept files. Showing somebody a report should
            # not also hand them somewhere to write, and they could not tell
            # they had been given one.
            started = await self._run(
                fileserver.start, await self._run(fileserver.default_dir), 0, "", False
            )
            if started.get("error"):
                return {"ok": False, "error": started["error"]}

        await self._run(fileserver.offer_report, report)
        decky.logger.info("Diagnostic report ready (%d characters)", len(report))
        return {"ok": True, **await self._run(fileserver.status)}

    async def end_report(self):
        """Withdraw the report, and stop the server if it was only serving that.

        Pressing Done means done: the report is the tail of a log, and leaving it
        on the network afterwards is exposure nobody asked for. The page already
        open on the other device keeps working -- it is one load, and its text is
        in that browser rather than fetched again -- so ending this costs the
        reader nothing they are looking at.

        The server itself only stops when nothing is arriving. `start_report`
        will have started it if it was down, but it may equally have been up for
        a transfer that is still running, and cutting a multi-gigabyte ROM off
        because somebody closed an unrelated dialog is the failure this guard
        exists for. The transfer's own dialog uses the same rule.
        """
        await self._run(fileserver.offer_report, "")
        status = await self._run(fileserver.status)
        if status.get("running") and not (status.get("uploading") or status.get("paused")):
            return await self.stop_file_server()
        return {"ok": True, **await self._run(fileserver.status)}

    @staticmethod
    def _installed_catalog_ids():
        """Which catalog emulators are actually on the device, as `id (channel)`.

        Deliberately not async. It goes through `_run` because probing a flatpak
        shells out, and handing `_run` a coroutine function does not run it --
        the executor calls it, gets a coroutine object back, and nothing ever
        awaits it. What reaches the caller is that object rather than a list,
        and the first thing done with it raises somewhere else entirely.
        """
        found = []
        for entry in emulator_catalog.CATALOG:
            source = entry.get("source") or {}
            kind = source.get("kind")
            if kind == "flatpak" and emu_install.flatpak_installed(source.get("id", "")):
                found.append("%s (flatpak)" % entry["id"])
            elif kind == "github" and emu_install.installed_appimage(entry["id"]):
                found.append("%s (appimage)" % entry["id"])
        return found

    async def start_file_server(self, target_dir: str = ""):
        # Empty means the default folder. Lets a caller start receiving in one call
        # without first asking where that is.
        target_dir = (target_dir or "").strip() or await self._run(fileserver.default_dir)

        settings = await self._run(store.get_settings)
        remember = bool(settings.get("transfer_remember"))
        result = await self._run(
            fileserver.start,
            target_dir,
            int(settings.get("transfer_port") or 0) if remember else 0,
            (settings.get("transfer_token") or "") if remember else "",
        )
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        # The server may already have been up to hand out a report, which does
        # not accept files. This is a transfer, so it does now.
        await self._run(fileserver.allow_uploads)

        if remember:
            # Whatever was actually bound and minted, not what was asked for: a
            # remembered port can be taken by something else and fallen back from,
            # and recording the request rather than the outcome would hand out a
            # link to an address nothing is listening on.
            await self._run(
                store.set_settings,
                {
                    "transfer_port": result.get("port", 0),
                    "transfer_token": await self._run(fileserver.current_token),
                },
            )

        result["received"] = await self._run(fileserver.received_files)
        return {"ok": True, **result}

    async def reset_transfer_link(self):
        """Invalidate every saved link. The next start issues a fresh one.

        All or nothing by design: the link is the credential, so there is nothing
        per-device to revoke. Refused while a transfer is running, because taking
        the address away mid-upload would cut off the very device that is using it.
        """
        status = await self._run(fileserver.status)
        if status.get("uploading"):
            return {
                "ok": False,
                "error": "A transfer is still running. Wait for it to finish, or cancel it first.",
            }

        await self._run(store.set_settings, {"transfer_port": 0, "transfer_token": ""})
        decky.logger.info("Reset the transfer link; saved bookmarks no longer work")

        # Restarted rather than left running, so the old link stops working now
        # instead of at the end of a session the user thinks they have revoked.
        if status.get("running"):
            await self._run(fileserver.stop)
            return await self.start_file_server(status.get("target_dir", ""))
        return {"ok": True, "running": False}

    async def stop_file_server(self):
        """Stop the server, whatever is happening. The Stop button."""
        result = await self._run(fileserver.stop)
        result["received"] = await self._run(fileserver.received_files)
        return {"ok": True, **result}

    async def stop_file_server_if_idle(self):
        """Stop it only if nothing is arriving. Dismissing the dialog.

        Its own endpoint rather than a flag on the one above, because the two
        are different promises: Stop is the user ending the transfer, and this
        is the dialog going away, which must never do that. The difference used
        to be decided in the dialog from its last poll -- up to a few seconds
        old -- so closing it quickly after sending a file stopped the server on
        top of the upload that had just begun.
        """
        result = await self._run(fileserver.stop_if_idle)
        result["received"] = await self._run(fileserver.received_files)
        return {"ok": True, **result}

    async def discard_transferred_file(self, name: str):
        """Delete one file from the transfer folder. The only way to, in Game Mode.

        Everything else that removes something from there does it as a side
        effect of using it: an import consumes the definition, a firmware
        install moves the file where the emulator reads it, a cancel deletes the
        partial it was writing. Nothing removed a file that was simply not
        wanted -- a refused definition, a ROM thought better of, a BIOS for an
        emulator since uninstalled -- so the staging folder only ever grew, and
        the alternative was Desktop Mode and a file manager, which is the thing
        this plugin exists to avoid.

        By name out of the folder rather than by a path the frontend supplies.
        `inbox_path` refuses anything that is not already the basename of a real
        file in there, so this cannot be pointed at a save game or a launcher.
        """
        path = await self._run(fileserver.inbox_path, name)
        if not path:
            # Already gone is the answer the caller wanted, not a failure: two
            # presses on a slow list should not produce an error the second time.
            return {"ok": True, "removed": False,
                    "received": await self._run(fileserver.received_files)}

        try:
            await self._run(os.remove, path)
        except OSError as error:
            return {"ok": False, "error": "Could not delete %s: %s" % (name, error)}

        decky.logger.info("Discarded %s from the transfer folder", name)
        return {"ok": True, "removed": True,
                "received": await self._run(fileserver.received_files)}


    async def cancel_upload(self, upload_id: int = 0):
        """Abandon a transfer in progress. 0 means every one of them.

        The half-written file goes with it, and this is the one thing that
        deletes one. An interrupted upload keeps its partial so the sender can
        carry on from it; a cancelled one is the user saying they do not want
        this file, which is a different answer. The handler deletes its own,
        being the only thread that can do it safely while the file is open.
        """
        cancelled = await self._run(fileserver.cancel, upload_id or None)
        status = await self._run(fileserver.status)
        status["received"] = await self._run(fileserver.received_files)
        return {"ok": True, "cancelled": cancelled, **status}
