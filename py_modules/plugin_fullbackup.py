"""The panel's side of a full backup to a drive. See fullbackup.py."""

import asyncio
import os
import threading

import appenv

import fileserver
import fullbackup
import plugin_base

#: How the download page lists what a backup holds.
_PART_NAMES = {"roms": "ROMs", "saves": "saves", "emulators": "emulators",
               "firmware": "BIOS and firmware", "settings": "settings and games",
               "signins": "cloud sign-ins"}

#: One download of a backup at a time: a second would read every file again.
_sending = threading.Lock()


class FullBackup(plugin_base.PluginContext):
    async def full_backup_drives(self):
        """Drives a backup can go to, with their free space. Mounts any
        removable drive SteamOS left unmounted first."""
        await self._run(fullbackup.mount_removable)
        return {"ok": True, "drives": await self._run(fullbackup.drives),
                "unreadable": await self._run(fullbackup.unreadable),
                "on_deck": await self._run(fullbackup.on_deck),
                "arrivals": await self._run(fullbackup.arrivals)}

    async def full_backup_sizes(self):
        """What each part would carry, for the checklist."""
        return {"ok": True, "sizes": await self._run(fullbackup.sizes)}

    async def cancel_full_backup(self):
        """Stop a running backup at its next block."""
        await self._run(fullbackup.cancel)
        return {"ok": True}

    async def start_full_backup(self, drive: str, include=None, replace_first=False):
        """Start a backup; it reports on `full_backup_progress` and ends on
        `full_backup_done`."""
        include = list(include or fullbackup.PARTS)
        loop = asyncio.get_running_loop()

        def progress(text, percent):
            asyncio.run_coroutine_threadsafe(
                appenv.emit("full_backup_progress", text, percent), loop)

        async def run():
            # No sleeping mid-copy: a drive cut off halfway through a file.
            awake = await self._run(fullbackup.stay_awake, "Backing up to a drive")
            try:
                result = await self._run(fullbackup.backup, drive, include, progress,
                                         bool(replace_first))
            finally:
                await self._run(fullbackup.release, awake)
            ejected, _ = await self._run(fullbackup.eject, drive)
            await appenv.emit("full_backup_done", bool(result.get("ok")),
                              result.get("error") or "", result.get("files") or 0,
                              bool(ejected))

        self._detach(run(), "full_backup_done", False, "", 0, False, once=True)
        return {"ok": True, "started": True}

    async def start_full_restore(self, path: str, keep: bool = True):
        """Start restoring a backup found on a connected drive; it reports on
        `full_restore_progress` and ends on `full_restore_done`."""
        known = [os.path.join(drive["path"], name)
                 for drive in await self._run(fullbackup.drives) for name in drive["backups"]]
        sent = [one["path"] for one in await self._run(fullbackup.on_deck)]
        if path not in known + sent:
            return {"ok": False, "error": "That backup is not on a connected drive."}
        loop = asyncio.get_running_loop()

        def progress(text, percent):
            asyncio.run_coroutine_threadsafe(
                appenv.emit("full_restore_progress", text, percent), loop)

        async def run():
            awake = await self._run(fullbackup.stay_awake, "Restoring a backup")
            try:
                result = await self._run(fullbackup.restore, path, progress, keep)
            finally:
                await self._run(fullbackup.release, awake)
            if result.get("ok") and not result.get("nowhere") and path in sent:
                # Sent over for this restore and now spent; it is also where it
                # came from, and holding 10 GB twice on the Deck helps nobody.
                await self._run(os.remove, path)
            todo = await self._run(fullbackup.still_to_do)
            await appenv.emit("full_restore_done", bool(result.get("ok")),
                              result.get("error") or "", todo)

        self._detach(run(), "full_restore_done", False, "", None, once=True)
        return {"ok": True, "started": True}

    async def full_restore_games(self):
        """The restored games, with what Steam needs to add each back."""
        return {"ok": True, "games": await self._run(fullbackup.games_to_readd),
                "cores": await self._run(fullbackup.cores_to_install)}

    async def full_restore_art(self, app_id: int):
        """One restored game's artwork, ready for Steam."""
        return {"ok": True, "art": await self._run(fullbackup.restored_art, app_id)}

    async def full_restore_rekey(self, old: int, new: int):
        """Move a re-added game's record and files to its new app id."""
        ok, error = await self._run(fullbackup.rekey_game, old, new)
        return {"ok": ok, "error": error}

    async def full_restore_finished(self):
        """The restored games are back in Steam: drop the artwork kept for them."""
        await self._run(fullbackup.forget_restored_art)
        return {"ok": True}

    async def start_full_backup_network(self, include=None):
        """Offer a backup as a download on the transfer server, made as it
        downloads. Each download reports on `full_backup_progress` and ends on
        `full_backup_done`."""
        include = [part for part in (include or fullbackup.PARTS) if part in fullbackup.PARTS]
        if not include:
            return {"ok": False, "error": "Nothing was chosen."}
        _, total = await self._run(fullbackup.measure, include)
        serving = await self._run(fileserver.status)
        if not serving.get("running"):
            started = await self._serve(False)
            if started.get("error"):
                return {"ok": False, "error": started["error"]}
        loop = asyncio.get_running_loop()

        def emit(*args):
            asyncio.run_coroutine_threadsafe(appenv.emit(*args), loop)

        def producer(send):
            if not _sending.acquire(blocking=False):
                return False
            awake = fullbackup.stay_awake("Backing up to a phone or PC")
            try:
                emit("full_backup_progress", "Starting", 0)
                result = fullbackup.stream(
                    send, include, lambda text, percent: emit("full_backup_progress", text, percent))
            finally:
                fullbackup.release(awake)
                _sending.release()
            emit("full_backup_done", bool(result.get("ok")), result.get("error") or "",
                 result.get("files") or 0, False)
            return bool(result.get("ok"))

        await self._run(
            lambda: fileserver.offer_download(
                name=fullbackup.default_name(), size=total, producer=producer,
                emulators=[_PART_NAMES[part] for part in include], heading="DeckyEmu backup"))
        return {"ok": True, **await self._run(fileserver.status)}

    async def end_full_backup_network(self):
        """Withdraw the download, and stop the server if nothing else is moving.
        A download already under way finishes."""
        await self._run(fileserver.offer_download, "")
        status = await self._run(fileserver.status)
        if status.get("running") and not (
                status.get("uploading") or status.get("paused") or status.get("downloading")):
            return await self.stop_file_server()
        return {"ok": True}
