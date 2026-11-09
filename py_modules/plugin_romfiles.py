"""The part of the Plugin class that manages files kept beside a game's ROM.

ROM hacks, which RetroArch applies at launch, and a Switch game's updates and
DLC, which Ryujinx is told about.
"""

import asyncio
import os

import appenv

import plugin_base

import emulators
import fileserver
import gamecontent
import rompatch
import store
import switch_content


class RomFiles(plugin_base.PluginContext):
    def _rom_of(self, app_id):
        """The ROM path of a tracked game, or "" if it is not one."""
        library = store.get_library()
        entry = library.get(str(app_id)) or {}
        return entry.get("rom_path", "")

    async def rom_patches(self, app_id: int) -> dict:
        """This game's ROM hacks, in the order RetroArch applies them."""
        rom_path = await self._run(self._rom_of, app_id)
        if not rom_path:
            return {"ok": False, "error": "That game is no longer tracked."}
        # RetroArch applies hand-placed patches too, so they are listed.
        await self._run(rompatch.adopt, app_id, rom_path)
        return {
            "ok": True,
            "patches": await self._run(rompatch.listing, app_id),
            "warning": await self._run(rompatch.warning_for, rom_path),
            # The transfer folder, where a sent patch lands.
            "start_in": await self._run(fileserver.default_dir),
        }

    async def add_rom_patch(self, app_id: int, patch_path: str) -> dict:
        """Take a patch into this game's list and apply it.

        A patch from the inbox's top level is removed from there once copied,
        as adding a game moves its ROM out. Anything kept elsewhere is left.
        """
        source = (patch_path or "").strip()
        row, error = await self._run(rompatch.add, app_id, source)
        if error:
            return {"ok": False, "error": error}

        inbox = await self._run(fileserver.default_dir)
        if inbox and os.path.dirname(source) == os.path.normpath(inbox):
            try:
                await self._run(os.remove, source)
            except OSError as remove_error:  # untidy, not broken
                appenv.logger.warning("Could not clear %s from the inbox: %s",
                                     source, remove_error)
        return await self.sync_rom_patches(app_id, name=(row or {}).get("name", ""))

    async def remove_rom_patch(self, app_id: int, stored: str) -> dict:
        """Drop one patch, delete our copy of it, and rewrite what is applied."""
        error = await self._run(rompatch.remove, app_id, stored)
        if error:
            return {"ok": False, "error": error}
        return await self.sync_rom_patches(app_id)

    async def switch_rom_patch(self, app_id: int, stored: str, on: bool) -> dict:
        """Turn one patch on or off. The copy is kept either way."""
        error = await self._run(rompatch.switch, app_id, stored, on)
        if error:
            return {"ok": False, "error": error}
        return await self.sync_rom_patches(app_id)

    async def sync_rom_patches(self, app_id: int, name: str = "") -> dict:
        """Write the switched-on patches beside the ROM.

        Also called after the ROM changes, because the files are named after it.
        """
        rom_path = await self._run(self._rom_of, app_id)
        if not rom_path:
            return {"ok": False, "error": "That game is no longer tracked."}
        written, error = await self._run(rompatch.sync, app_id, rom_path)
        appenv.logger.info("rom patches: app_id=%s applied=%s%s",
                          app_id, written, " (%s)" % error if error else "")
        if error:
            return {"ok": False, "error": error,
                    "patches": await self._run(rompatch.listing, app_id)}
        return {"ok": True, "name": name, "applied": written,
                "patches": await self._run(rompatch.listing, app_id)}

    async def patch_targets(self, patch_path: str) -> dict:
        """The games a ROM hack could be installed on, the likely ones first.

        RetroArch games only: standalone emulators ignore a patch beside the ROM.
        """
        path = (patch_path or "").strip()
        if not await self._run(rompatch.kind_of, path):
            return {"ok": False, "error": ("That is not an IPS, BPS or UPS patch. "
                                           "Check you picked the patch and not the ROM.")}
        library = await self._run(store.get_library)
        games = [
            entry for entry in library.values()
            if entry.get("app_id") and not emulators.is_emulator_id(entry.get("core_id", ""))
        ]
        return {"ok": True, "games": await self._run(rompatch.rank_targets, path, games)}

    def _game_content_for(self, app_id):
        """`(entry, games_root, base_id, problem)` for one game's updates and DLC.

        `games_root` is empty for emulators that take none (all but Ryujinx).
        `problem` is set when the game's file does not say which game it is, so
        nothing can be matched to it.
        """
        entry = store.get_library().get(str(app_id))
        if not entry:
            return None, "", "", "That game is no longer tracked."
        games_root = gamecontent.games_root_for(entry.get("core_id", ""))
        if not games_root:
            return entry, "", "", ""
        base_id = switch_content.inspect(entry.get("rom_path", ""))["base_id"]
        if not base_id:
            return entry, games_root, "", (
                "The game's own file does not say which game it is, so no update "
                "or DLC can be matched to it.")
        return entry, games_root, base_id, ""

    async def game_content(self, app_id: int) -> dict:
        """A game's updates and DLC, or `supported: False` for any other emulator."""
        entry, games_root, _base_id, problem = await self._run(self._game_content_for, app_id)
        if entry is None:
            return {"ok": False, "error": problem}
        return {
            "ok": True,
            "supported": bool(games_root),
            "problem": problem,
            "rows": await self._run(gamecontent.rows, app_id) if games_root else [],
            "start_in": await self._run(fileserver.default_dir),
        }

    async def install_game_content(self, app_id: int, path: str) -> dict:
        """Keep an update or DLC for a game and tell Ryujinx about it."""
        entry, games_root, base_id, problem = await self._run(self._game_content_for, app_id)
        if entry is None or problem or not games_root:
            return {"ok": False, "error": problem
                    or "This game's emulator does not take updates or DLC."}
        inbox = await self._run(fileserver.default_dir)
        # An .nsz is unpacked on the way in, with progress as for Unpack.
        loop = asyncio.get_running_loop()
        name = os.path.basename(path or "")

        def report(done, total):
            percent = int(done * 100 / total) if total else -1
            asyncio.run_coroutine_threadsafe(
                appenv.emit("nsz_unpack_progress", name, percent), loop)

        row, error = await self._run(
            gamecontent.add, app_id, (path or "").strip(), base_id, inbox, report)
        if error:
            return {"ok": False, "error": error,
                    "rows": await self._run(gamecontent.rows, app_id)}
        return await self._sync_game_content(app_id, games_root, base_id,
                                              (row or {}).get("file", ""))

    async def remove_game_content(self, app_id: int, file: str) -> dict:
        """Delete one kept update or DLC and take it off Ryujinx's list."""
        entry, games_root, base_id, problem = await self._run(self._game_content_for, app_id)
        if entry is None or problem or not games_root:
            return {"ok": False, "error": problem
                    or "This game's emulator does not take updates or DLC."}
        error = await self._run(gamecontent.remove, app_id, file)
        if error:
            return {"ok": False, "error": error,
                    "rows": await self._run(gamecontent.rows, app_id)}
        return await self._sync_game_content(app_id, games_root, base_id, file)

    async def _sync_game_content(self, app_id, games_root, base_id, name):
        error = await self._run(gamecontent.sync, app_id, base_id, games_root)
        rows = await self._run(gamecontent.rows, app_id)
        appenv.logger.info("game content: app_id=%s base=%s kept=%d%s", app_id, base_id,
                          len(rows), " (%s)" % error if error else "")
        if error:
            return {"ok": False, "error": error, "rows": rows}
        return {"ok": True, "name": name, "rows": rows}
