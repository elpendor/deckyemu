"""The panel's side of compressing games. See romcompress.py."""

import asyncio

import appenv

import emu_install
import emulators
import fullbackup
import launchers
import plugin_base
import romcompress
import rompatch
import store
from plugin_shortcuts import _own_launcher, _title_id_for


class Compress(plugin_base.PluginContext):
    def _compress_entries(self, library):
        """The library's records with what `romcompress.plan` needs to judge them."""
        entries = []
        for key, record in library.items():
            core_id = record.get("core_id", "")
            core = self._core_by_id(core_id) or {}
            try:
                patched = any(row.get("on") for row in rompatch.listing(key))
            except (OSError, ValueError):
                patched = False
            entries.append({
                "app_id": int(key),
                "title": record.get("title", ""),
                "system": record.get("system", ""),
                "rom_path": record.get("rom_path", ""),
                "extensions": core.get("extensions") or [],
                "libretro": bool(core) and not emulators.is_emulator_id(core_id),
                "emulator": core.get("display_name") or core.get("name") or "",
                "patched": patched,
            })
        return entries

    def _compress_tools(self):
        """What each method runs, or what is missing. ({method: argv}, {method: why})."""
        tools, missing = {}, {}
        chdman = emu_install.installed_tool("chdman")
        if chdman:
            tools["chdman"] = [chdman]
        azahar = emulators.find("azahar")
        if azahar and azahar.get("target"):
            tools["azahar"] = emulators.tool_argv(azahar, [])
        else:
            missing["z3ds"] = "Azahar isn't installed."
        dolphin = emulators.find("dolphin")
        if not dolphin or dolphin.get("target") != romcompress.DOLPHIN:
            missing["rvz"] = "Dolphin isn't installed."
        return tools, missing

    async def compress_plan(self):
        """The games that can be compressed, and the ones that can't and why."""
        library = await self._run(store.get_library)
        entries = self._compress_entries(library)
        result = await self._run(romcompress.plan, entries)
        _, missing = await self._run(self._compress_tools)
        games = []
        for game in result["games"]:
            # The shelf name the library shows, for grouping.
            game["platform"] = (library.get(str(game["app_id"])) or {}).get("platform")                 or game["system"]
            if game["method"] in missing:
                result["skipped"].append({"title": game["title"],
                                          "reason": missing[game["method"]]})
            else:
                games.append(game)
        return {"ok": True, "games": games, "skipped": result["skipped"]}

    async def cancel_compress(self):
        """Stop after the game being compressed; that game is left as it was."""
        await self._run(romcompress.cancel)
        return {"ok": True}

    async def start_compress(self, app_ids=None):
        """Compress the chosen games one at a time. Reports on `compress_progress`
        (text, percent) and ends on `compress_done` (ok, error, done, saved, failed)."""
        wanted = {int(one) for one in app_ids or []}
        loop = asyncio.get_running_loop()

        def say(text, percent):
            asyncio.run_coroutine_threadsafe(
                appenv.emit("compress_progress", text, percent), loop)

        async def run():
            await self._run(romcompress.reset)
            planned = await self.compress_plan()
            games = [game for game in planned["games"] if game["app_id"] in wanted]
            total = sum(game["bytes"] for game in games) or 1

            if any(romcompress.TOOLS[game["method"]] == "chdman" for game in games) \
                    and not emu_install.installed_tool("chdman"):
                say("Downloading the disc compressor", 0)
                _, error = await self._run(emu_install.install_named_tool, "chdman")
                if error:
                    await appenv.emit("compress_done", False,
                                      "Could not download chdman: %s" % error, 0, 0, [])
                    return
            tools, _ = await self._run(self._compress_tools)

            awake = await self._run(fullbackup.stay_awake, "Compressing games")
            done, saved, failed, before = 0, 0, [], 0
            try:
                for game in games:
                    def progress(fraction, game=game, before=before):
                        say(game["title"],
                            int(100 * (before + fraction * game["bytes"]) / total))
                    progress(0)
                    try:
                        result = await self._run(romcompress.compress, game, tools, progress)
                    except romcompress.Cancelled:
                        break
                    before += game["bytes"]
                    if not result["ok"]:
                        failed.append({"title": game["title"], "reason": result["error"]})
                        continue
                    error = await self._repoint(game, result["rom_path"])
                    if error:
                        await self._run(romcompress.undo, game, result["created"])
                        failed.append({"title": game["title"], "reason": error})
                        continue
                    await self._run(romcompress.finish, game)
                    done += 1
                    saved += result["saved"]
            finally:
                await self._run(fullbackup.release, awake)
            appenv.logger.info("Compressed %d game(s), saved %d bytes, %d failed",
                               done, saved, len(failed))
            await appenv.emit("compress_done", True, "", done, saved, failed)

        # No args: a crash then emits compress_done(False, message).
        self._detach(run(), "compress_done", once=True)
        return {"ok": True, "started": True}

    async def _repoint(self, game, rom_path):
        """Point a game's record and launcher at its compressed file. An error, or ""."""
        library = await self._run(store.get_library)
        entry = library.get(str(game["app_id"]))
        if not entry:
            return "That game is no longer in the library."
        # Rewritten even when a playlist keeps its path: the launcher may run
        # its first disc (PCSX2), and that file is about to be deleted.
        entry = dict(entry, rom_path=rom_path)
        launcher = _own_launcher(entry.get("launcher_path", ""))
        if launcher:
            settings = await self._run(store.get_settings)
            core = self._core_by_id(entry.get("core_id", "")) or {}
            emulator = self._emulator_for_core_id(entry.get("core_id", ""))
            if not self._install and not emulator:
                return "RetroArch isn't installed, so its launcher can't be rewritten."
            launch = self._launch_options(settings, entry)
            try:
                await self._run(
                    launchers.write_launcher,
                    self._install, entry.get("title", "Game"),
                    core.get("path") or entry.get("core_path", ""),
                    launchers.launch_target(core, rom_path),
                    launch["hide_osd"],
                    emulators.for_game(emulator, entry.get("options")),
                    launch["fullscreen"], launch["extra_args"],
                    self._menu_combo(settings), settings, _title_id_for(rom_path), launcher)
            except OSError as error:
                return "Could not rewrite its launcher: %s" % error
        # A zip keeps the ROM's stem, so patches beside it still apply.
        await self._run(store.remember_game, game["app_id"], entry)
        return ""
