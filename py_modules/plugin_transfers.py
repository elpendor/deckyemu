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
import savedata
import unpack
import store


class Transfers(plugin_base.PluginContext):
    """Sending files to the Deck and reading a report back. See the module docstring."""

    async def file_server_status(self):
        status = await self._run(fileserver.status)
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
            started = await self._serve(False)
            if started.get("error"):
                return {"ok": False, "error": started["error"]}

        await self._run(fileserver.offer_report, report)
        decky.logger.info("Diagnostic report ready (%d characters)", len(report))
        return {"ok": True, **await self._run(fileserver.status)}

    async def save_backup_sources(self):
        """What a save backup would carry, per emulator, measured on the device.

        Asked before anything is built, because the sizes are the whole of the
        decision: an emulator that declares its save directory contributes
        kilobytes, and one that does not contributes everything it keeps. The
        panel shows both and lets the second be unticked.
        """
        return {"ok": True, "sources": await self._run(savedata.sources)}

    async def start_save_backup(self, ids=None):
        """Build a save backup and put it where another device can read it.

        The same errand as `start_report` and deliberately the same shape: a
        server that hands one thing out and accepts nothing, a QR code for a
        camera and six digits for anything else. What differs is that this one
        writes a real file, so it has a lifetime -- `end_save_backup` deletes it,
        and so does the next backup, because two copies of somebody's saves in
        decky's runtime directory is one more than anybody asked for.
        """
        await self._run(self._clear_backups)

        destination = os.path.join(savedata.BACKUP_DIR, savedata.default_name())
        built = await self._run(savedata.build, destination, ids)
        if not built.get("ok"):
            return built

        serving = await self._run(fileserver.status)
        if not serving.get("running"):
            # Started to hand a backup out and nothing else. Same rule as the
            # report: showing somebody a file must not also hand them somewhere
            # to write, and they could not tell they had been given one.
            started = await self._serve(False)
            if started.get("error"):
                await self._run(self._clear_backups)
                return {"ok": False, "error": started["error"]}

        await self._run(
            fileserver.offer_download,
            destination,
            os.path.basename(destination),
            built.get("bytes", 0),
            built.get("emulators") or [],
        )
        decky.logger.info(
            "Save backup ready: %s (%d bytes)", os.path.basename(destination),
            built.get("bytes", 0),
        )
        return {"ok": True, "backup": built, **await self._run(fileserver.status)}

    async def end_save_backup(self):
        """Withdraw the backup, delete it, and stop the server if that was all it did.

        The deletion is the part that matters. A report is a log tail held in
        memory; this is a copy of somebody's save files sitting in decky's
        runtime directory, and leaving it there means the next person to read
        that directory finds it. Pressing Done means it is gone.

        The server itself only stops when nothing is moving in either direction.
        It may have been up for a transfer that is still running -- cutting off a
        multi-gigabyte ROM because somebody closed an unrelated dialog is the
        failure this guard exists for -- and it may be streaming this very backup
        to the device that asked for it. That second half was missing: the report
        this borrowed its shape from is one page load and is in the reader's
        browser before anything can interrupt it, and 75MB over a phone's wifi is
        not.
        """
        await self._run(fileserver.offer_download, "")
        await self._run(self._clear_backups)
        status = await self._run(fileserver.status)
        if status.get("running") and not (
            status.get("uploading") or status.get("paused") or status.get("downloading")
        ):
            return await self.stop_file_server()
        return {"ok": True, **await self._run(fileserver.status)}

    async def list_save_backups(self):
        """Backups on this Deck, newest first.

        Restoring starts from the Library tab beside taking a backup, rather
        than from the ROM picker: the file is not a game, and every row of the
        add flow -- the name, the artwork, the core -- is about something this
        is not. So the tab finds the file instead of the user pointing at it.

        Both folders are read. `savedata.take_delivery` moves an arriving backup
        into its own, but one that could not be moved is still restorable, and an
        install that predates that has its backups where they landed.
        """
        return {
            "ok": True,
            # Where a backup belongs, so the transfer dialog can be pointed at it
            # and say so truthfully. It used to be started on the ROM inbox and
            # told the user files would land there, while `take_delivery` moved
            # them somewhere else the moment they arrived.
            "dir": await self._run(savedata.arrivals_dir),
            "backups": await self._run(
                savedata.backups_in,
                await self._run(savedata.arrivals_dir),
                await self._run(fileserver.default_dir),
            ),
        }

    async def discard_save_backup(self, path: str):
        """Delete one backup from this Deck without restoring it.

        Restoring already consumes the archive, so this is for the other case:
        a backup somebody has finished with, or sent by mistake, or that is
        simply the old one. Without it the only way to remove a 75MB file is to
        restore from it, which is not a thing to have to do to tidy up.
        """
        backups = await self._run(
            savedata.backups_in,
            await self._run(savedata.arrivals_dir),
            await self._run(fileserver.default_dir),
        )
        # Only something this plugin just listed. The path comes from the
        # frontend, and a delete pointed at an arbitrary path is not what this
        # is for -- the same rule `inbox_path` enforces for the folder next door.
        if not any(entry["path"] == path for entry in backups):
            return {"ok": False, "error": "That backup is not on this Deck."}
        try:
            await self._run(os.remove, path)
        except OSError as error:
            return {"ok": False, "error": "Could not delete it: %s" % error}
        decky.logger.info("Discarded save backup %s", os.path.basename(path))
        return {"ok": True, "removed": True}

    async def describe_save_backup(self, path: str):
        """What an archive holds and whether this Deck can take it.

        Answers before anything is written, because the counts are the decision:
        how many of these files are already here is what separates "put back what
        is missing" from "replace what is there".
        """
        return await self._run(savedata.describe, path)

    async def restore_save_backup(self, path: str, ids=None, replace: bool = False):
        """Put saves back from an archive sent to this Deck, then delete it.

        `replace` overwrites saves already here and is the one destructive thing
        in it; off, nothing already present is touched.

        **The archive goes once it has been read**, the same as
        `unpack_transferred_file` deletes the zip it extracted, and for the rule
        that file states: everything that uses a file takes it out of the folder.

        This was written the other way first, on the reasoning that a partial
        restore skips saves already here and the archive is therefore the only
        copy of the versions it did not write. That reasoning is wrong: the
        archive *arrived from another device*, so the copy it was sent from is
        still there. What it produced was 75MB sitting on the Deck with nothing
        in Game Mode able to remove it -- the same fault
        `discard_transferred_file` exists to fix, one folder over.

        Only after a restore that succeeded. A failure leaves the file, because
        then it really is the way to try again.
        """
        result = await self._run(savedata.restore, path, ids, replace)
        if not result.get("ok"):
            return result
        try:
            await self._run(os.remove, path)
            result["removed"] = os.path.basename(path)
        except OSError as error:
            # The saves are back, which is what was asked for. An archive that
            # could not be deleted is untidy, not a failed restore.
            decky.logger.warning("Restored from %s but could not remove it: %s", path, error)
        return result

    @staticmethod
    def _clear_backups():
        """Delete every archive left in the staging directory.

        Everything in there is this plugin's own, named by `savedata`, and each
        one is a full copy of the saves it was taken from. Cleared before
        building and again when the dialog closes, so the only time one exists is
        while somebody is looking at the address it is offered on.
        """
        try:
            names = os.listdir(savedata.BACKUP_DIR)
        except OSError:
            return
        for name in names:
            path = os.path.join(savedata.BACKUP_DIR, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError as error:
                decky.logger.warning("Could not remove old backup %s: %s", path, error)

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
        if status.get("running") and not (
            status.get("uploading") or status.get("paused") or status.get("downloading")
        ):
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

    async def _serve(self, uploads, target_dir=""):
        """Start the file server the one way there is, and record what it bound.

        **A remembered link is remembered whichever door asks for the server.**
        Three callers start it -- a transfer, a diagnostic report, a save backup
        -- and only the first honoured `transfer_remember`, so somebody who had
        deliberately made their link durable and bookmarked it on a laptop got a
        different address, a different token and a different six digits the
        moment they asked for a report or a backup. The setting says "keep the
        transfer address the same between sessions"; a session is a session.

        Recording matters as much as reusing. The port and token written back are
        whatever was *actually* bound and minted, never what was asked for: a
        remembered port can be taken by something else and fallen back from, and
        the first durable session started by a report would otherwise never be
        saved -- so the next transfer would mint a different one and quietly
        break the bookmark.

        `uploads` stays the caller's business and is deliberately not folded in
        here. It answers a different question -- whether this server is an inbox
        or only hands something out -- and the report and the backup need it off
        for a reason no remembered link changes.
        """
        settings = await self._run(store.get_settings)
        remember = bool(settings.get("transfer_remember"))
        result = await self._run(
            fileserver.start,
            target_dir or await self._run(fileserver.default_dir),
            int(settings.get("transfer_port") or 0) if remember else 0,
            (settings.get("transfer_token") or "") if remember else "",
            uploads,
        )
        if result.get("error"):
            return result
        if remember:
            await self._run(
                store.set_settings,
                {
                    "transfer_port": result.get("port", 0),
                    "transfer_token": await self._run(fileserver.current_token),
                },
            )
        return result

    async def start_file_server(self, target_dir: str = ""):
        # Empty means the default folder. Lets a caller start receiving in one call
        # without first asking where that is.
        result = await self._serve(True, (target_dir or "").strip())
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        # The server may already have been up to hand out a report, which does
        # not accept files. This is a transfer, so it does now.
        await self._run(fileserver.allow_uploads)
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
        # And the same for the other direction, which this used not to consider.
        # The restart below brings the server back up as an *inbox* -- which is
        # right when it was one, and turns a server that existed only to hand a
        # report or a backup out into somewhere the holder of the old QR code can
        # write. Refusing while something is being offered keeps that from
        # happening behind the user's back, and it is the same answer the line
        # above gives for an upload: finish what you are doing first.
        if status.get("downloading") or status.get("report_url") or status.get("download_url"):
            return {
                "ok": False,
                "error": "Something is still being handed out. Close that dialog first.",
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


    async def unpack_transferred_file(self, name: str):
        """Extract a zip in the transfer folder, in place. The only way to, in Game Mode.

        Xbox 360 content is what forced this. Every XBLA release is distributed
        zipped, Xenia refuses a zip outright -- it shows an error box, which
        gamescope will not draw, so it presents as a hang -- and nothing here
        could extract one. The route from "sent to the Deck" to "playable" went
        through Desktop Mode and a file manager, which section 1a says a feature
        may not require. Zipped multi-file games had the same dead end long
        before Xenia existed; nobody had hit it because RetroArch reads a zip
        itself, and every emulator that cannot is a recent arrival.

        By name out of the folder, like the delete beside it: `inbox_path`
        refuses anything that is not already the basename of a real file in
        there, so this cannot be aimed at an archive somewhere else on the
        device and made to write its contents into the transfer folder.
        """
        path = await self._run(fileserver.inbox_path, name)
        if not path:
            return {"ok": False, "error": "%s is not in the transfer folder." % name}
        if not name.lower().endswith(".zip"):
            # `.7z` and `.rar` are the ones people ask about next. Neither is in
            # the standard library and neither has a tool on a stock SteamOS, so
            # offering the button and failing at the end would be worse than
            # saying so.
            return {"ok": False,
                    "error": "Only .zip files can be unpacked here."}

        written, error = await self._run(
            unpack.into_folder, path, await self._run(fileserver.default_dir)
        )
        if error:
            return {"ok": False, "error": error}

        # The zip has served its purpose, so it goes -- the same thing importing
        # a definition does to the definition, installing firmware does by
        # moving the file where the emulator reads it, and adding a ROM does by
        # filing it under its system. The transfer folder is a waypoint, and
        # everything that uses a file takes it out of there.
        #
        # This was briefly the exception, on the reasoning that an extraction
        # can go subtly wrong and the archive is the only way back. That is true
        # of importing a definition too, and it is not how this folder works:
        # what it produced was 47MB of duplicate sitting beside the game, and a
        # second unpack refused because the name was taken.
        #
        # Only after a clean extraction. `into_folder` is all-or-nothing, so
        # reaching here means every member is on disk under its real name.
        try:
            await self._run(os.remove, path)
        except OSError as error:
            # The contents are out, which is what was asked for. A zip that
            # could not be deleted is a tidiness problem with a delete button
            # next to it, not a failed unpack.
            decky.logger.warning("Unpacked %s but could not remove it: %s", name, error)

        return {"ok": True, "written": written,
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
        return {"ok": True, "cancelled": cancelled, **status}
