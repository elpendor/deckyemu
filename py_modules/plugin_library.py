"""The part of the Plugin class that holds the record of what was added.

Reading the registry, taking one game out of it, and emptying it entirely --
which also deletes the games.

Split from the add flow rather than from the shortcuts block as a whole, and the
line is worth stating because `register_game` stayed behind. Adding a game is a
*flow*: a launcher, a Steam shortcut, artwork, a collection and a registry
record, in an order that matters, and it reads next to `prepare_shortcut` and
`update_game` because those three are one act. What is here is the other side --
the record as a thing in its own right, and the two ways it shrinks.

**`clear_library` deletes the games.** It was once a tidy-up that unregistered
entries and left the files, and that was the wrong promise: what it left behind
was a ROM folder nobody could account for and shortcuts pointing into it. It is
the most destructive thing the plugin does outside the development resets, and
having it in a file named for the library is most of the reason this file
exists -- somebody looking for what removes everything should find it by
looking.

Mixed into `Plugin` rather than called by it, like the others: decky exposes the
methods it finds on the plugin object, so the names have to stay there while the
code lives somewhere findable. Nothing here may be instantiated alone.
"""

import decky

import plugin_base

import launchers
import romshelf
import emulators
import store


class Library(plugin_base.PluginContext):
    """The registry of added games, and taking things out of it."""

    async def unregister_game(self, app_id: int):
        """Forget a game and delete its launcher. Steam removal is done frontend-side."""
        entry = await self._run(store.forget_game, app_id)
        if entry:
            await self._run(launchers.remove_launcher, entry.get("launcher_path", ""))
        return entry
    async def games_needing_layout(self):
        """Games already added whose emulator depends on a Steam Input layout.

        Adding a game pins the layout its emulator asks for, which does nothing
        for the games added before the emulator asked. Vita3K is the case and the
        symptom is silent: the Deck powers its gyro down unless the running
        game's layout binds it, so motion in every Vita game added earlier stays
        dead with nothing on screen to say why.

        Answering here rather than having the frontend join two lists: the
        library knows `core_id`, the emulator record knows the layout, and
        neither is the frontend's to reason about.
        """
        library = await self._run(store.get_library)
        emulators_by_id = {
            emulator.get("id"): emulator
            for emulator in await self._run(emulators.list_emulators)
        }

        wanted = []
        for entry in library.values():
            app_id = entry.get("app_id")
            core_id = str(entry.get("core_id") or "")
            if not app_id or not core_id.startswith("emu:"):
                continue
            # Resolved for *this* game: a shortcut may have motion switched
            # off while the emulator has it on, or the other way round.
            emulator = emulators.for_game(
                emulators_by_id.get(core_id[4:]) or {}, entry.get("options"))
            # Every game of a plugin-managed emulator, with the layout it should
            # be wearing -- and an empty string means "should be wearing none of
            # ours", not "nothing to do".
            #
            # Deliberately not narrowed to emulators that currently declare a
            # layout. That was the bug: when a workaround is deleted from the
            # catalog, nothing is left describing the layout it pinned, so
            # nothing asked for it to come off and every game kept it forever.
            # The frontend decides by looking at what each game is actually
            # wearing, which needs no catalog knowledge at all.
            wanted.append({"app_id": app_id, "layout": emulator.get("layout") or ""})
        return wanted

    async def launch_notices_for_game(self, app_id: int):
        """Anything worth saying about the fixes this game is about to run with.

        Asked as the game starts, which is the only moment the message reliably
        reaches anybody: a line in a settings page is read by people who were
        already going to open that page, and they are not the ones who need it.

        Resolved through the same helper the launcher uses, so a notice cannot
        claim a fix is running that is not -- a warning about something that
        already stopped is worse than saying nothing.
        """
        library = await self._run(store.get_library)
        entry = next(
            (item for item in library.values() if item.get("app_id") == app_id), None)
        core_id = str((entry or {}).get("core_id") or "")
        if not entry or not core_id.startswith("emu:"):
            return {"notices": []}
        emulator = await self._run(emulators.find, core_id[4:])
        return {
            "notices": await self._run(
                emulators.launch_notices, emulator, entry.get("options")),
        }

    async def list_added(self):
        library = await self._run(store.get_library)
        return sorted(library.values(), key=lambda entry: entry.get("title", "").lower())
    async def clear_library(self):
        """Forget every game and delete every launcher this plugin wrote.

        Returns what the frontend must still undo on the Steam side -- the app ids
        to remove and which collection each was filed into -- because the backend
        cannot touch Steam. Reported before anything is deleted, since afterwards
        the records naming those apps are gone.

        Stray scripts in the launcher directory go too. "Clear the library" that
        left files behind for the orphan audit to complain about would not have
        cleared anything the user can see.
        """
        library = await self._run(store.get_library)
        games = [
            {
                "app_id": entry.get("app_id"),
                "title": entry.get("title", ""),
                "collection": entry.get("collection", ""),
            }
            for entry in library.values()
            if entry.get("app_id")
        ]

        # And the games themselves, for the same reason removing one game
        # deletes it: a file this plugin put on the disk that nothing points at
        # any more is not a saving, it is something to reconcile later. "Clear
        # the library" leaving twenty gigabytes of ROMs behind was the largest
        # instance of exactly that.
        #
        # Which is also why this reports progress on `clear_library_progress`.
        # Deleting an unpacked PS3 game is an rmtree over tens of gigabytes, and
        # a library of them takes minutes with nothing to look at -- the button
        # said "Removing..." for the whole of it, which is indistinguishable
        # from a hang on a device with no second window to check.
        total = len(library) or 1
        freed = 0
        for index, entry in enumerate(library.values()):
            await decky.emit(
                "clear_library_progress",
                "Deleting %s" % (entry.get("title") or "game"),
                # By count, not by bytes. The sizes are not known until each one
                # is walked, and a bar that recalculated its own scale partway
                # through would go backwards.
                int(index * 90 / total),
            )
            freed += await self._delete_game_files(entry.get("rom_path", ""))

        await decky.emit("clear_library_progress", "Removing launchers", 90)
        removed = 0
        for entry in library.values():
            if await self._run(launchers.remove_launcher, entry.get("launcher_path", "")):
                removed += 1
        # One write rather than one per game: the whole registry goes, so there is
        # nothing to preserve between the individual deletions.
        await self._run(store.clear_library)

        await decky.emit("clear_library_progress", "Tidying up leftover launchers", 96)
        strays = await self._run(self._stray_launchers, set())
        for path in strays:
            if await self._run(launchers.remove_launcher, path):
                removed += 1

        decky.logger.info(
            "Cleared the library: %d game(s), %d launcher(s), %d bytes freed",
            len(games), removed, freed,
        )
        return {
            "ok": True,
            "games": games,
            # Deduped but order-stable, so the frontend can report them.
            "collections": list(dict.fromkeys(g["collection"] for g in games if g["collection"])),
            "launchers_deleted": removed,
            "freed": freed,
        }
    async def _delete_game_files(self, rom_path):
        """Delete whatever this plugin put on the disk for one game. Bytes freed.

        The same two cases the remove dialog covers, and the same boundary: a
        game unpacked inside an emulator, or a ROM filed under its system. A ROM
        the user keeps somewhere of their own is not ours and is left, here as
        everywhere else.
        """
        if not rom_path:
            return 0

        for system, module in self._PACKAGED.items():
            info = await self._run(module.game_info, rom_path)
            if info.get("ok") and info.get("title_id"):
                gone, error = await self._run(module.delete_game, info["title_id"])
                if error:
                    decky.logger.warning("Could not delete %s: %s", rom_path, error)
                return gone

        library = await self._run(romshelf.library_dir)
        if await self._run(romshelf.owned, rom_path, library):
            gone, error = await self._run(romshelf.delete_rom, rom_path, library)
            if error:
                decky.logger.warning("Could not delete %s: %s", rom_path, error)
            return gone
        return 0
