"""The panel's side of a full backup to a drive. See fullbackup.py."""

import asyncio
import os

import appenv

import fullbackup
import plugin_base


class FullBackup(plugin_base.PluginContext):
    async def full_backup_drives(self):
        """Drives a backup can go to, with their free space. Mounts any
        removable drive SteamOS left unmounted first."""
        await self._run(fullbackup.mount_removable)
        return {"ok": True, "drives": await self._run(fullbackup.drives),
                "unreadable": await self._run(fullbackup.unreadable)}

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

    async def start_full_restore(self, path: str):
        """Start restoring a backup found on a connected drive; it reports on
        `full_restore_progress` and ends on `full_restore_done`."""
        known = [os.path.join(drive["path"], name)
                 for drive in await self._run(fullbackup.drives) for name in drive["backups"]]
        if path not in known:
            return {"ok": False, "error": "That backup is not on a connected drive."}
        loop = asyncio.get_running_loop()

        def progress(text, percent):
            asyncio.run_coroutine_threadsafe(
                appenv.emit("full_restore_progress", text, percent), loop)

        async def run():
            awake = await self._run(fullbackup.stay_awake, "Restoring a backup")
            try:
                result = await self._run(fullbackup.restore, path, progress)
            finally:
                await self._run(fullbackup.release, awake)
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
