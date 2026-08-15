"""The part of the Plugin class that finds and repairs drift.

Five things can disagree about what the library contains: this plugin's
registry, the launcher scripts, the ROM files, Steam's own shortcuts, and
Steam's collections. Four of them are visible from here; whether a shortcut
still exists is only knowable in the frontend, which is why `audit_library`
returns the registry for it to cross-check rather than answering that itself.

Also the way back from a previous install under a different plugin folder name.
decky derives the settings directory from the folder, so renaming it orphans
every record while leaving the Steam shortcuts working -- these are what adopt
those games or forget them.

Mixed into `Plugin` rather than called by it -- see plugin_firmware for why.
"""

import glob
import json
import os

import decky

import plugin_base

import launchers
import romshelf
import steam_shortcuts
import store


class Audit(plugin_base.PluginContext):
    """Library audit and repair endpoints. See the module docstring."""

    async def audit_library(self):
        """Find entries whose backing files or Steam shortcuts have gone missing.

        Four things can drift apart: the registry, the launcher scripts, the ROM
        files and Steam's own shortcuts. Anything the backend can see is reported
        here; whether a Steam shortcut still exists can only be checked from the
        frontend, so the registry is returned for it to cross-check.
        """
        library = await self._run(store.get_library)

        registry, broken, referenced = await self._run(self._inspect_library, library)

        strays = await self._run(self._stray_launchers, referenced)

        previous = await self._run(self._find_previous_installs)

        decky.logger.info(
            "audit: %d broken, %d stray launcher(s), %d previous install(s)",
            len(broken),
            len(strays),
            len(previous),
        )
        return {
            "registry": registry,
            "broken": broken,
            "strays": sorted(strays),
            "previous_installs": previous,
            "unknown_shortcuts": await self._run(self._unknown_shortcuts, library),
            "mispointed": await self._run(self._mispointed_entries, library),
            "unused_roms": await self._run(self._unused_roms, library),
        }


    async def shortcut_health(self):
        """How many of our Steam shortcuts the registry cannot account for.

        Its own endpoint rather than a read of `audit_library`, because the
        panel asks this every time it opens and the full audit walks the ROM
        library and every previous install's directory looking for things this
        does not need.

        Exists because the problem it reports is invisible by nature: a
        shortcut whose registry entry and launcher script are both gone shows
        up in Steam as an ordinary game that happens to do nothing, and the
        only way anybody found out was noticing a duplicate by chance. A
        cleanup screen nobody has a reason to open cannot report it.
        """
        library = await self._run(store.get_library)
        found = await self._run(self._unknown_shortcuts, library)
        counts = {"dead": 0, "duplicate": 0, "orphan": 0}
        for item in found:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        return {"unknown": len(found), **counts}

    async def shortcut_for_launcher(self, exe: str):
        """The appid of an existing Steam shortcut that runs `exe`, or 0.

        Asked before a game is added, so re-adding one whose record was lost
        takes back the shortcut it already has instead of making a second
        alongside it.

        Steam's file is written on Steam's own schedule, so a shortcut created
        moments ago may not be in it yet. That makes this answer "no" too often
        rather than "yes" wrongly, which is the right way round: a missed
        duplicate is a row in the cleanup screen, while a wrong match would
        rewrite a shortcut belonging to something else.
        """
        wanted = (exe or "").strip().strip('"')
        if not wanted:
            return {"app_id": 0}

        def look():
            for item in steam_shortcuts.ours():
                if os.path.normpath(item["exe"]) == os.path.normpath(wanted):
                    return item["app_id"]
            return 0

        return {"app_id": await self._run(look)}

    @staticmethod
    def _unknown_shortcuts(library):
        """Shortcuts of ours that the registry does not account for.

        The one check that does not begin with a registry entry, and the only
        one that can see a game whose registry entry and launcher script were
        both deleted. That pair is not an edge case: it is what a reset leaves,
        every time, and the shortcuts it leaves behind cannot start anything.

        Three outcomes, because the right offer differs:

        `dead` -- the launcher script is gone. It cannot launch and nothing can
        bring it back, so removing it is the only thing to do with it.

        `duplicate` -- a registered game already runs this exact launcher under
        a different appid. Removing it costs nothing: the game stays, under the
        entry the plugin knows about.

        `orphan` -- the launcher works but no registry entry claims it. This one
        still plays, so it is reported rather than swept up with the others.
        """
        known = {str(app_id) for app_id in (library or {}).keys()}
        registered_launchers = {
            str((entry or {}).get("launcher_path") or "")
            for entry in (library or {}).values()
        }
        registered_launchers.discard("")

        report = []
        for item in steam_shortcuts.ours():
            if str(item["app_id"]) in known:
                continue
            if not item["launcher_exists"]:
                kind = "dead"
            elif item["exe"] in registered_launchers:
                kind = "duplicate"
            else:
                kind = "orphan"
            report.append(dict(item, kind=kind))

        decky.logger.info(
            "audit: %d shortcut(s) the registry does not know (%s)",
            len(report),
            ", ".join(sorted({item["kind"] for item in report})) or "none",
        )
        return report

    @staticmethod
    def _mispointed_entries(library):
        """Entries whose appid belongs to a shortcut running something else.

        The other direction of `_unknown_shortcuts`, and the one nothing asked.
        Every check here starts from an entry and asks whether the *files* it
        names are still there; whether the Steam shortcut it claims is still
        that game was never tested, though `shortcuts.vdf` has the appid and the
        executable written down side by side and the answer is a comparison.

        Steam reuses the appids of deleted shortcuts -- `setupShortcut` relies
        on knowing that -- so a registry entry can end up naming an id that now
        belongs to something else entirely. Editing that game then rewrites
        somebody else's shortcut, and removing it deletes their entry. The
        frontend's own check sees an app exists under that id and is satisfied,
        because from there a shortcut's executable cannot be read at all.

        Only shortcuts this plugin made are compared. An entry whose appid is
        not in the file is either a real Steam game's id or a shortcut Steam has
        not written out yet, and neither is something to report -- the first is
        not ours to comment on and the second would be a finding that appears
        for a moment after every add.
        """
        ours = {item["app_id"]: item for item in steam_shortcuts.ours()}

        found = []
        for entry in library.values():
            app_id = entry.get("app_id")
            launcher = entry.get("launcher_path", "")
            shortcut = ours.get(app_id)
            if not app_id or not launcher or not shortcut:
                continue
            if os.path.normpath(shortcut["exe"]) == os.path.normpath(launcher):
                continue
            found.append(
                {
                    "app_id": app_id,
                    "title": entry.get("title", ""),
                    "launcher_path": launcher,
                    # What the shortcut runs instead, so the report can say
                    # which game would have been rewritten.
                    "runs": shortcut["exe"],
                    "runs_title": shortcut["title"],
                }
            )

        if found:
            decky.logger.info(
                "audit: %d entry(s) point at a shortcut running something else", len(found)
            )
        return found

    @staticmethod
    def _inspect_library(library):
        """(registry, broken, referenced launchers) for every tracked game.

        One executor pass rather than two per game. Every check in here touches
        the filesystem, so doing it a game at a time meant two round trips
        through the thread pool each, for a question that is the same shape for
        all of them.
        """
        registry = []
        broken = []
        referenced = set()

        for entry in library.values():
            launcher = entry.get("launcher_path", "")
            rom = entry.get("rom_path", "")
            if launcher:
                referenced.add(os.path.normpath(launcher))

            reasons = []
            if not rom or not os.path.isfile(rom):
                reasons.append("the ROM file is gone")
            if not launcher or not os.path.isfile(launcher):
                reasons.append("the launcher script is gone")

            record = {
                "app_id": entry.get("app_id"),
                "title": entry.get("title", ""),
                "rom_path": rom,
                "launcher_path": launcher,
            }
            registry.append(record)
            if reasons:
                broken.append(dict(record, reasons=reasons))

        return registry, broken, referenced


    @staticmethod
    def _unused_roms(library):
        """Filed ROMs that no game in the library points at.

        Removing a game offers to delete its ROM and defaults to not doing it,
        which is the right default and does leave things behind. This is where
        they are swept from -- along with anything left by a shortcut deleted in
        Steam itself, which never reaches the remove dialog at all.

        Only the library folder, and only files this plugin filed there. A ROM
        the user keeps elsewhere is not ours to count, let alone offer to
        delete.
        """
        used = {
            os.path.realpath(entry.get("rom_path", ""))
            for entry in library.values()
            if entry.get("rom_path")
        }

        root = romshelf.library_dir()
        found = []
        try:
            systems = sorted(os.listdir(root))
        except OSError:
            return found

        for system in systems:
            folder = os.path.join(root, system)
            if not os.path.isdir(folder):
                continue
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            # A cue sheet's tracks are not unused games in their own right, so
            # anything named by a file that *is* in use is accounted for.
            spoken_for = set()
            for name in names:
                path = os.path.join(folder, name)
                if os.path.realpath(path) in used:
                    spoken_for.update(romshelf.companions(path) or [])
            for name in names:
                path = os.path.join(folder, name)
                if not os.path.isfile(path) or name in spoken_for:
                    continue
                if os.path.realpath(path) in used:
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue
                found.append({"path": path, "name": name, "system": system, "bytes": size})
        return found


    @staticmethod
    def _find_previous_installs():
        """Libraries left behind by an earlier version under a different name.

        Renaming the plugin changes its data directory, so a rename or reinstall
        orphans the old registry -- its Steam shortcuts still work, because the
        old launcher scripts remain on disk, but nothing manages them any more.
        """
        found = []
        ours = os.path.normpath(decky.DECKY_PLUGIN_SETTINGS_DIR)

        for path in glob.glob(os.path.join(decky.DECKY_HOME, "settings", "*", "library.json")):
            if os.path.normpath(os.path.dirname(path)) == ours:
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue

            # Only claim libraries that look like ours.
            games = [
                entry
                for entry in data.values()
                if isinstance(entry, dict)
                and entry.get("app_id")
                and entry.get("rom_path")
                and entry.get("launcher_path")
            ]
            if games:
                found.append(
                    {
                        "name": os.path.basename(os.path.dirname(path)),
                        "path": path,
                        "games": [
                            {
                                "app_id": game["app_id"],
                                "title": game.get("title", ""),
                                "rom_path": game["rom_path"],
                                "core_id": game.get("core_id", ""),
                                "rom_exists": os.path.isfile(game["rom_path"]),
                            }
                            for game in games
                        ],
                    }
                )
        return found


    async def adopt_previous_install(self, path: str):
        """Take over a previous install's games.

        Their launchers are rewritten into this install's runtime directory, so
        the caller must point each Steam shortcut at the new script -- otherwise
        the shortcut keeps running the old one and later settings changes would
        silently not apply.
        """
        previous = await self._run(self._find_previous_installs)
        match = next((item for item in previous if item["path"] == path), None)
        if not match:
            return {"ok": False, "error": "That library is no longer there."}

        settings = await self._run(store.get_settings)
        adopted = []
        skipped = []
        # Accumulated and written once at the end: adopting a whole previous
        # library otherwise rewrote the registry once per game taken over.
        records = {}

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            return {"ok": False, "error": "Could not read that library: %s" % error}

        for entry in data.values():
            if not isinstance(entry, dict) or not entry.get("app_id"):
                continue
            rom = entry.get("rom_path", "")
            core_id = entry.get("core_id", "")
            core = self._core_by_id(core_id)
            emulator = self._emulator_for_core_id(core_id)

            if not rom or not os.path.isfile(rom) or not core:
                skipped.append(entry.get("title") or str(entry.get("app_id")))
                continue

            title = entry.get("title", "Game")
            # The old record's overrides, not the globals. Writing the globals
            # here undid every per-game choice the previous install carried --
            # and did it invisibly, because the record it wrote alongside said
            # the overrides were still in force. `_launch_options` resolves one
            # against the other, which is what `rebuild_launchers` does too.
            launch = self._launch_options(settings, entry)
            try:
                script = await self._run(
                    launchers.write_launcher,
                    self._install,
                    title,
                    core["path"],
                    rom,
                    launch["hide_osd"],
                    emulator,
                    launch["fullscreen"],
                    launch["extra_args"],
                    self._menu_combo(settings),
                    settings,
                )
            except OSError as error:
                decky.logger.warning("Could not rebuild launcher for %r: %s", title, error)
                skipped.append(title)
                continue

            # Built from the old record rather than beside it, so everything the
            # previous install knew that is not recomputed here survives -- the
            # per-game launch overrides above all, which a hand-built record
            # dropped, quietly resetting every one of them to the global
            # setting. It also keeps the game on the system it was filed under:
            # this took the core's first database, which files every Wii game
            # under GameCube for as long as the entry lives.
            record = self._entry_for(
                settings, entry["app_id"], title, rom, core_id, core, script,
                previous=entry,
            )
            records[entry["app_id"]] = record
            # The caller must actually file it into `collection`. Recording the
            # name without adding the app would make a later rename believe the
            # game was already in place and skip it.
            adopted.append(
                {
                    "app_id": entry["app_id"],
                    "title": title,
                    "exe": script,
                    "collection": record["collection"],
                }
            )

        await self._run(store.remember_games, records)

        decky.logger.info("Adopted %d game(s), skipped %d", len(adopted), len(skipped))
        return {"ok": True, "adopted": adopted, "skipped": skipped}


    async def discard_previous_install(self, path: str):
        """Delete an old install's registry so it stops being offered.

        Adoption alone never ends the cycle: the old library.json stays on disk, so
        the next audit offers the same games again, and adopting games whose Steam
        shortcuts are gone just manufactures fresh orphans to forget. Discarding is
        the other half of the choice.

        Only the registry goes. The launcher scripts stay, because the whole reason
        an old install's shortcuts still work is that they point at those scripts --
        deleting them would break games this is supposed to be tidying up after.
        """
        target = os.path.normpath(path or "")
        settings_root = os.path.normpath(os.path.join(decky.DECKY_HOME, "settings"))
        ours = os.path.normpath(decky.DECKY_PLUGIN_SETTINGS_DIR)

        # Most specific first, so the message names the real objection: our own
        # registry lives inside the settings folder too, and reporting it as "out
        # of bounds" would be both wrong and confusing.
        if os.path.basename(target) != "library.json":
            return {"ok": False, "error": "That is not a registry file."}
        if os.path.normpath(os.path.dirname(target)) == ours:
            return {"ok": False, "error": "That is this install's own registry."}
        if not target.startswith(settings_root + os.sep):
            return {"ok": False, "error": "Refusing to delete outside the settings folder."}

        def _count():
            try:
                with open(target, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                return len(data) if isinstance(data, dict) else 0
            except (OSError, ValueError):
                return 0

        count = await self._run(_count)

        try:
            await self._run(os.remove, target)
        except FileNotFoundError:
            return {"ok": True, "discarded": 0}
        except OSError as error:
            return {"ok": False, "error": "Could not delete it: %s" % error}

        decky.logger.info("Discarded a previous install's registry: %s (%d game(s))", target, count)
        return {"ok": True, "discarded": count}


    async def forget_games(self, app_ids: list):
        """Drop registry entries and their launchers, without touching Steam.

        Returns each forgotten game with the collection it was filed into, so the
        caller can take it out of that collection too. Without this a forgotten
        game left its collection behind, holding nothing.
        """
        forgotten = await self._run(store.forget_games, app_ids)

        removed = []
        games = []
        # Over `app_ids` rather than the returned mapping, so the reported order
        # is the caller's own and an id that was not tracked is simply absent.
        for app_id in app_ids or []:
            entry = forgotten.get(str(app_id))
            if not entry:
                continue
            await self._run(launchers.remove_launcher, entry.get("launcher_path", ""))
            removed.append(entry.get("title", str(app_id)))
            games.append(
                {
                    "app_id": entry.get("app_id", app_id),
                    "title": entry.get("title", ""),
                    "collection": entry.get("collection", ""),
                }
            )
        return {"ok": True, "removed": removed, "games": games}


    async def delete_stray_launchers(self, paths: list):
        deleted = 0
        for path in paths or []:
            if await self._run(launchers.remove_launcher, path):
                deleted += 1
        return {"ok": True, "deleted": deleted}
