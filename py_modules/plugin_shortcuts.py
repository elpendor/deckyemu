"""The part of the Plugin class that turns a chosen game into something to run.

Writing a game's launcher and the record Steam's shortcut is built from, editing
both later, rebuilding every launcher when a setting baked into them changes,
and collecting the notes a launcher leaves when it refuses to start.
"""

import os
from typing import Optional

import appenv

import plugin_base

import emulators
import fileserver
import findfiles
import launchers
import libretro_meta
import ra_cores
import romshelf
import store
import vita_games


def _own_launcher(path):
    """`path` if it is a script in our launcher folder, else ""."""
    if not path or not path.endswith(".sh"):
        return ""
    folder = os.path.realpath(launchers.LAUNCHER_DIR)
    return path if os.path.realpath(os.path.dirname(path)) == folder else ""


def _title_id_for(rom_path):
    """The title id a launcher needs, or "" for a game that launches by path.

    Empty for all but Vita3K's games, which are installed rather than opened:
    their launcher runs `-r <TITLE_ID>` with no path. Derived from the ROM, so
    older libraries rebuild correctly. Every launcher writer gets it from here.
    """
    return vita_games.title_of(rom_path or "")


class Shortcuts(plugin_base.PluginContext):
    # How a game runs; plugin_audit and plugin_startup use these too.
    @staticmethod
    def _menu_combo(settings):
        """The RetroArch menu shortcut to bake in, validated before it is used.

        Global, not per game. An unknown key would reach RetroArch as no combo,
        leaving no way into the menu.
        """
        combo = settings.get("menu_combo", "start_select")
        return combo if combo in launchers.MENU_COMBOS else "start_select"

    @classmethod
    def _launch_options(cls, settings, entry):
        """How this game should be launched: its overrides over the globals."""
        options = entry.get("options") or {}
        hide_osd = options.get("hide_osd") or ""
        fullscreen = options.get("fullscreen")
        return {
            "hide_osd": (
                hide_osd if hide_osd in cls._OSD_MODES else settings.get("hide_osd", "startup")
            ),
            "fullscreen": (
                bool(settings.get("emulator_fullscreen", True))
                if fullscreen is None
                else bool(fullscreen)
            ),
            "extra_args": (options.get("extra_args") or "").strip(),
            # Resolved by `emulators.for_game`, which has the emulator.
            "workarounds": dict(options.get("workarounds") or {}),
        }

    @classmethod
    def _clean_options(cls, options):
        """Keep only real overrides, so 'follow the global setting' stays absent."""
        options = options or {}
        cleaned = {}
        hide_osd = options.get("hide_osd") or ""
        if hide_osd in cls._OSD_MODES:
            cleaned["hide_osd"] = hide_osd
        fullscreen = options.get("fullscreen")
        if fullscreen is not None:
            cleaned["fullscreen"] = bool(fullscreen)
        extra_args = (options.get("extra_args") or "").strip()
        if extra_args:
            cleaned["extra_args"] = extra_args
        # `{id: bool}` for the ids this game decides; the rest follow the
        # emulator.
        workarounds = {
            str(key): bool(value)
            for key, value in (options.get("workarounds") or {}).items()
            if key
        }
        if workarounds:
            cleaned["workarounds"] = workarounds
        return cleaned

    async def prepare_shortcut(
        self, title: str, core_id: str, rom_path: str, system: str = "",
        title_id: str = "", launch_name: str = "",
    ):
        """Write the launcher script and return the fields Steam needs.

        `system` is resolve_game's answer, which picks the collection for a
        core covering several systems (Dolphin: GameCube and Wii).

        `launch_name` is for a multi-disc set whose emulator cannot read a
        playlist (PCSX2): `rom_path` stays the playlist, which filing and
        deleting follow, while the launcher runs this disc. A bare filename,
        resolved in the folder the game is filed into.
        """
        appenv.logger.info("prepare_shortcut: title=%r core=%s rom=%s", title, core_id, rom_path)
        # The last chance to catch an emulator that reset its settings since
        # they were written, before its first game is played.
        await self._recheck_emulator_setups()
        emulator = self._emulator_for_core_id(core_id)
        # A standalone emulator does not need RetroArch.
        if not self._install and not emulator:
            return {"ok": False, "error": "RetroArch was not found on this system."}

        core = self._core_by_id(core_id)
        if not core:
            return {"ok": False, "error": "Core '%s' is no longer available." % core_id}

        if not os.path.isfile(rom_path):
            return {"ok": False, "error": "ROM file no longer exists: %s" % rom_path}

        # An emulator that starts installed titles by id (Vita3K) cannot run a
        # file path, so refuse here rather than fail silently at launch.
        if emulator and emulator.get("installed_args") and not title_id:
            return {
                "ok": False,
                "error": "%s starts games it has already installed, not files. "
                "Send the game as a .pkg with its licence key and install it "
                "here, then add it from the installed list."
                % (emulator.get("name") or "This emulator"),
            }

        clean_title = (title or "").strip() or libretro_meta.display_title(
            libretro_meta.rom_stem(rom_path)
        )

        settings = await self._run(store.get_settings)

        # Filed before the launcher is written: the path ends up in its argv,
        # its filename and the library, so it must not move afterwards. Falls
        # back to the platform name for emulators with no libretro database.
        rom_path = await self._run(
            romshelf.file_rom,
            rom_path,
            self._system_for(core, system) or core.get("platform_full", ""),
            await self._run(fileserver.default_dir),
            await self._run(romshelf.library_dir),
        )

        # After filing, so it names the disc where it now is. Falls back to the
        # playlist, which at least exists, rather than a missing file.
        launch_path = await self._run(launchers.launch_target, core, rom_path)
        if launch_name:
            candidate = os.path.join(os.path.dirname(rom_path), os.path.basename(launch_name))
            if await self._run(os.path.isfile, candidate):
                launch_path = candidate
            else:
                appenv.logger.warning(
                    "prepare_shortcut: %s is not beside %s; launching the playlist",
                    launch_name, rom_path,
                )

        try:
            script = await self._run(
                launchers.write_launcher,
                self._install,
                clean_title,
                core["path"],
                launch_path,
                settings.get("hide_osd", "startup"),
                # A new game has no overrides yet, so this follows the emulator.
                emulators.for_game(emulator),
                settings.get("emulator_fullscreen", True),
                "",
                self._menu_combo(settings),
                settings,
                title_id,
            )
        except OSError as error:
            appenv.logger.exception("Failed writing launcher")
            return {"ok": False, "error": "Could not write launcher script: %s" % error}

        return {
            "ok": True,
            "title": clean_title,
            "exe": script,
            "start_dir": os.path.dirname(script),
            "launch_options": "",
            "launcher_path": script,
            "core_path": core["path"],
            # Where the ROM was filed, for the library to record.
            "rom_path": rom_path,
            # Resolved here so per-platform naming lives in one place.
            "collection_name": self._collection_name(
                settings,
                self._entry_platform(
                    settings, core, {"system": self._system_for(core, system)}
                ),
            ),
            # `_install` is None when a standalone emulator was chosen.
            "warn_flatpak_sdcard": self._install is not None
            and self._install["kind"] == "flatpak"
            and rom_path.startswith("/run/media"),
            # The Steam Input layout the emulator asks for, if any: the Deck
            # powers its gyro down unless the game's layout binds it (Vita3K).
            # See `steam/layout.ts`.
            "layout": (emulator or {}).get("layout", ""),
        }

    @classmethod
    def _entry_for(
        cls, settings, app_id, title, rom_path, core_id, core, launcher_path,
        system="", previous=None,
    ):
        """The registry record for one game; every writer builds it here.

        Fields of `previous` not recomputed here survive, such as `options`.
        `system` matters for a core covering several (Dolphin); absent, the
        stored one is kept while the core still claims it.
        """
        entry = dict(previous or {})
        resolved = cls._system_for(core, system, entry.get("system", ""))
        platform = cls._entry_platform(settings, core, {"system": resolved})
        entry.update(
            {
                "app_id": app_id,
                "title": title,
                "rom_path": rom_path,
                "core_id": core_id,
                "core_path": core["path"] if core else entry.get("core_path", ""),
                "system": resolved,
                "platform": platform,
                # So a later rename knows which collection to move it out of.
                "collection": cls._collection_name(settings, platform),
                "launcher_path": launcher_path,
            }
        )
        return entry

    async def register_game(
        self,
        app_id: int,
        title: str,
        rom_path: str,
        core_id: str,
        launcher_path: str,
        system: str = "",
        remember_core: bool = True,
        collection: Optional[str] = None,
    ):
        core = self._core_by_id(core_id)
        appenv.logger.info("register_game: app_id=%s title=%r", app_id, title)
        settings = await self._run(store.get_settings)
        entry = self._entry_for(
            settings, app_id, title, rom_path, core_id, core, launcher_path, system
        )
        # The collection the frontend actually filed it into, which renames and
        # removals act on. None means "work it out"; "" means on no shelf.
        if collection is not None:
            entry["collection"] = collection
        await self._run(store.remember_game, app_id, entry)
        await self._share_firmware([core_id])

        # By content extension, so a zipped ROM counts as a loose one. Callers
        # turn it off for PS3 (whose `.bin` would mislead every PS1 disc), and
        # never for a port.
        extension = (await self._run(ra_cores.content_extension, rom_path)
                     if remember_core and not emulators.core_is_port(core_id) else "")
        if extension and core_id:
            settings = await self._run(store.get_settings)
            by_ext = dict(settings.get("last_core_by_ext", {}))
            by_ext[extension] = core_id
            await self._run(store.set_settings, {"last_core_by_ext": by_ext})

        return entry

    async def update_game(
        self,
        app_id: int,
        title: str,
        core_id: str,
        rom_path: str = "",
        options: Optional[dict] = None,
        system: str = "",
    ):
        """Change a tracked game's name, ROM, what runs it, or how it launches.

        Not artwork, which the picker applies itself. The caller finishes on
        the Steam side (rename, repoint, move collections) with what this
        returns, including the previous collection.
        """
        appenv.logger.info(
            "update_game: app_id=%s title=%r core=%s rom=%s options=%s",
            app_id,
            title,
            core_id,
            rom_path or "(unchanged)",
            options or {},
        )

        library = await self._run(store.get_library)
        entry = library.get(str(app_id))
        if not entry:
            return {"ok": False, "error": "That game is no longer tracked."}

        previous_rom = entry.get("rom_path", "")
        rom_path = (rom_path or "").strip() or previous_rom
        if not rom_path or not await self._run(os.path.isfile, rom_path):
            return {"ok": False, "error": "The ROM file is missing: %s" % rom_path}
        rom_changed = bool(previous_rom) and os.path.normpath(previous_rom) != os.path.normpath(
            rom_path
        )

        core = self._core_by_id(core_id)
        if not core:
            return {"ok": False, "error": "Core '%s' is not available." % core_id}
        emulator = self._emulator_for_core_id(core_id)

        # Refused now rather than launching an emulator with nothing to run.
        if rom_changed:
            # What launches: a playlist this core can't read starts disc 1.
            extension = await self._run(
                ra_cores.content_extension,
                await self._run(launchers.launch_target, core, rom_path))
            supported = [text.lower() for text in core.get("extensions", [])]
            if extension and supported and extension.lower() not in supported:
                return {
                    "ok": False,
                    "error": "%s does not support .%s files."
                    % (core.get("display_name") or core_id, extension),
                }

        cleaned_options = self._clean_options(options)
        try:
            await self._run(launchers.split_extra_args, cleaned_options.get("extra_args", ""))
        except ValueError:
            return {
                "ok": False,
                "error": "Those launch arguments have an unclosed quote.",
            }

        settings = await self._run(store.get_settings)
        clean_title = (title or "").strip() or entry.get("title") or libretro_meta.display_title(
            libretro_meta.rom_stem(rom_path)
        )
        launch = self._launch_options(settings, {"options": cleaned_options})

        try:
            script = await self._run(
                launchers.write_launcher,
                self._install,
                clean_title,
                core["path"],
                await self._run(launchers.launch_target, core, rom_path),
                launch["hide_osd"],
                # Resolved for this game: a shortcut may run with motion on
                # while the rest of that emulator's games do not.
                emulators.for_game(emulator, cleaned_options),
                launch["fullscreen"],
                launch["extra_args"],
                self._menu_combo(settings),
                settings,
                # Positional, as `_run` forwards no keywords: easy to drop.
                _title_id_for(rom_path),
            )
        except OSError as error:
            appenv.logger.exception("Could not rewrite launcher")
            return {"ok": False, "error": "Could not write the launcher: %s" % error}

        # The launcher's name embeds the title and a hash of the ROM path, so
        # an edit can make a new file; the old one goes.
        old_launcher = entry.get("launcher_path", "")
        launcher_changed = bool(old_launcher) and os.path.normpath(old_launcher) != os.path.normpath(
            script
        )
        if launcher_changed:
            await self._run(launchers.remove_launcher, old_launcher)

        previous_collection = entry.get("collection", "")
        # A given `system` re-files a multi-system core's game (rules in
        # `_entry_for`). The ROM file itself stays where it is.
        entry = self._entry_for(
            settings, app_id, clean_title, rom_path, core_id, core, script,
            system, previous=entry,
        )
        entry["options"] = cleaned_options
        platform = entry["platform"]
        collection = entry["collection"]
        await self._run(store.remember_game, app_id, entry)
        await self._share_firmware([core_id])

        return {
            "ok": True,
            "title": clean_title,
            "rom_path": rom_path,
            "rom_changed": rom_changed,
            "exe": script,
            "start_dir": os.path.dirname(script),
            "launcher_changed": launcher_changed or not old_launcher,
            "collection": collection,
            "previous_collection": previous_collection,
            "platform": platform,
        }

    async def launch_bounced(self, app_id: int) -> dict:
        """Did this game's launcher refuse to start, and what was in the way?

        The launcher's gate (`launchers.launch_gate`) stops a second game and
        leaves a note, collected here so the panel's dialog follows what really
        happened. Consumed by reading.
        """
        others = await self._run(launchers.take_bounce, app_id)
        return {"bounced": bool(others), "others": others}

    async def approve_launch(self, app_id: int) -> dict:
        """Let this game past the gate once, because the user said so."""
        return {"ok": await self._run(launchers.approve_launch, app_id)}

    async def launch_missing(self, app_id: int) -> dict:
        """Did this game's launcher stop because a piece of it is gone?

        Collected like `launch_bounced`, from the note the launcher leaves.
        Answers "rom" or "emulator", with the emulator's name as the launcher
        recorded it, since its record may be gone. Consumed by reading.
        """
        kind, name = await self._run(launchers.take_missing, app_id)
        return {"missing": kind, "name": name}

    @staticmethod
    def _stray_launchers(referenced):
        """Launcher scripts in our own directory that no registry entry claims."""
        return sorted(
            path
            for path in findfiles.in_directory(launchers.LAUNCHER_DIR, ".sh")
            if os.path.normpath(path) not in referenced
        )

    async def rebuild_launchers(self):
        """Regenerate every launcher script from the current settings.

        Works without RetroArch: only libretro games need it, and those are
        skipped by name, while standalone emulators' launchers are rebuilt.
        """
        settings = await self._run(store.get_settings)
        library = await self._run(store.get_library)

        # Worked out here in memory, then written in one executor pass. Per
        # game, so each game's own overrides survive.
        jobs = []
        for entry in library.values():
            core_id = entry.get("core_id", "")
            core = self._core_by_id(core_id)
            launch = self._launch_options(settings, entry)
            jobs.append(
                {
                    "title": entry.get("title", "Game"),
                    "label": entry.get("title", "?"),
                    # Tells libretro from emulator games when no record says.
                    "core_id": core_id,
                    "core_path": core["path"] if core else entry.get("core_path", ""),
                    "rom_path": entry.get("rom_path", ""),
                    "core": core,
                    # Per game, as in `prepare_shortcut`: it keeps each game's
                    # workarounds and picks which binary runs.
                    "emulator": emulators.for_game(
                        self._emulator_for_core_id(core_id), entry.get("options")),
                    "hide_osd": launch["hide_osd"],
                    "fullscreen": launch["fullscreen"],
                    "extra_args": launch["extra_args"],
                    "title_id": _title_id_for(entry.get("rom_path", "")),
                    # The script the Steam shortcut runs, if it is one of ours.
                    "path": _own_launcher(entry.get("launcher_path", "")),
                }
            )

        rebuilt, skipped = await self._run(
            self._write_launchers, self._install, self._menu_combo(settings), settings, jobs
        )

        appenv.logger.info("Rebuilt %d launcher(s), skipped %d", rebuilt, len(skipped))
        return {"ok": True, "rebuilt": rebuilt, "skipped": skipped}

    @staticmethod
    def _write_launchers(install, menu_combo, settings, jobs):
        """Write every launcher in `jobs`. Returns (rebuilt, skipped titles).

        Runs in the executor. A missing ROM is still written for: the launcher
        is what reports it, and an SD card may be back tomorrow. Only a job with
        no ROM path or core is skipped, as there is no command to write.
        """
        rebuilt = 0
        skipped = []
        for job in jobs:
            if not job["core_path"] or not job["rom_path"]:
                skipped.append(job["label"])
                continue
            # A libretro game needs RetroArch installed.
            if not install and not job["emulator"]:
                skipped.append(job["label"])
                continue
            # An emulator no longer registered: writing would treat its program
            # as a libretro core. The script on disk is the last good one.
            if emulators.is_emulator_id(job.get("core_id", "")) and not job["emulator"]:
                skipped.append(job["label"])
                continue
            try:
                launchers.write_launcher(
                    install,
                    job["title"],
                    job["core_path"],
                    launchers.launch_target(job.get("core"), job["rom_path"]),
                    job["hide_osd"],
                    job["emulator"],
                    job["fullscreen"],
                    job["extra_args"],
                    menu_combo,
                    settings,
                    job.get("title_id", ""),
                    job.get("path") or None,
                )
                rebuilt += 1
            except OSError as error:
                appenv.logger.warning(
                    "Could not rebuild launcher for %r: %s", job["label"], error
                )
                skipped.append(job["label"])
        return rebuilt, skipped
