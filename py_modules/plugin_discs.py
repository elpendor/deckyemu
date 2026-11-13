"""The part of the Plugin class that handles games on more than one disc.

Finding the discs that belong together, letting the user build a set by hand,
adding a disc to a game already in the library, and writing the playlist.
"""

import os

import appenv

import plugin_base

import discset
import fileserver
import romshelf
import store


class Discs(plugin_base.PluginContext):
    async def disc_set_for(self, rom_path: str):
        """The discs beside `rom_path` that look like one game with it.

        `probe_rom`'s `disc_set`, without the probe's cost, for the transfer
        dialog. Returns {discs, playlist}; fewer than two discs is not a set.
        """
        discs = await self._run(discset.find_set, rom_path)
        if len(discs) < 2:
            return {"discs": [], "playlist": ""}
        return {"discs": discs,
                "playlist": await self._run(discset.playlist_name, discs)}

    async def disc_candidate(self, rom_path: str, folder: str):
        """Whether `rom_path` may be added to a set being built by hand.

        For sets the naming rules miss (`Quest d1.cue`, `Quest d2.cue`). A disc
        must sit in the same folder, as a playlist names files beside itself.
        Returns {ok, name, error}; `name` goes in the playlist.
        """
        name = os.path.basename(rom_path)
        if not name or not await self._run(os.path.isfile, rom_path):
            return {"ok": False, "name": "", "error": "That file is not there."}
        if os.path.dirname(os.path.realpath(rom_path)) != os.path.realpath(folder):
            return {
                "ok": False, "name": "",
                "error": "A disc has to be in the same folder as the others. "
                         "Move it there first.",
            }
        # The picker shows every file, so a CD's `.bin` tracks look like discs.
        if await self._run(romshelf.part_of_a_disc, rom_path):
            return {
                "ok": False, "name": "",
                "error": "%s is one track of a disc, not a disc. Pick the .cue "
                         "that names it instead." % name,
            }
        return {"ok": True, "name": name, "error": ""}

    async def add_disc_to_game(self, app_id: int, disc_path: str):
        """Put another disc into a game that is already in the library.

        For a disc that turns up after the game was added, without removing
        and re-adding it, which would lose its app id, play time and layout.
        The disc is filed beside the others and the playlist written or
        extended. Returns {ok, playlist, discs, error}; the caller decides
        whether to point the shortcut at `playlist`, as that depends on the core.
        """
        library = await self._run(store.get_library)
        entry = library.get(str(app_id))
        if not entry:
            return {"ok": False, "playlist": "", "discs": [],
                    "error": "That game is no longer tracked."}

        rom_path = entry.get("rom_path", "")
        folder = os.path.dirname(rom_path)
        if not rom_path or not await self._run(os.path.isdir, folder):
            return {"ok": False, "playlist": "", "discs": [],
                    "error": "This game's folder is not there."}

        if not disc_path or not await self._run(os.path.isfile, disc_path):
            return {"ok": False, "playlist": "", "discs": [],
                    "error": "That file is not there."}
        # As in disc_candidate: a CD's tracks look like discs in the picker.
        if await self._run(romshelf.part_of_a_disc, disc_path):
            return {"ok": False, "playlist": "", "discs": [],
                    "error": "%s is one track of a disc, not a disc. Pick the "
                             ".cue that names it instead."
                             % os.path.basename(disc_path)}

        # Filed as adding a game files a ROM. One kept elsewhere is not moved,
        # and a playlist cannot name it from another folder, so it is refused.
        filed = await self._run(
            romshelf.file_rom, disc_path, entry.get("system", ""),
            await self._run(fileserver.default_dir, False),
        )
        if os.path.dirname(os.path.realpath(filed)) != os.path.realpath(folder):
            return {"ok": False, "playlist": "", "discs": [],
                    "error": "A disc has to be in the same folder as the "
                             "others, and this one could not be moved there."}

        name = os.path.basename(filed)
        playlist = rom_path if rom_path.lower().endswith(".m3u") else ""
        if not playlist:
            # A set joined before the record followed its playlist: adopt it.
            beside = os.path.join(folder, await self._run(
                discset.playlist_name, [os.path.basename(rom_path), name]))
            named = await self._run(romshelf.named_by, beside)
            if named and os.path.basename(rom_path) in named:
                playlist = beside
        if playlist:
            known = await self._run(romshelf.named_by, playlist)
            if known is None:
                return {"ok": False, "playlist": "", "discs": [],
                        "error": "This game's playlist could not be read."}
        else:
            known = [os.path.basename(rom_path)]

        if any(one.lower() == name.lower() for one in known):
            return {"ok": True, "playlist": playlist, "discs": known,
                    "error": ""}

        discs = await self._run(discset.in_disc_order, known + [name])
        written, error = await self._run(
            discset.write_playlist, folder, discs,
            os.path.basename(playlist) if playlist else "",
        )
        if error:
            return {"ok": False, "playlist": "", "discs": [], "error": error}

        appenv.logger.info("Added %s to %s; playlist now names %d discs",
                          name, entry.get("title"), len(discs))
        return {"ok": True, "playlist": written, "discs": discs, "error": ""}

    async def join_disc_to_game(self, app_id: int, disc_path: str):
        """Add a disc to a game and repoint its shortcut, in one press.

        For the transfer dialog. The record always moves to the playlist, so
        later discs and compression see the set; a core that can't read `m3u`
        still starts its first disc (`launchers.launch_target`). Returns
        {ok, error, title, exe, launcher_changed}.
        """
        added = await self.add_disc_to_game(app_id, disc_path)
        if not added["ok"]:
            return {"ok": False, "error": added["error"], "title": "",
                    "exe": "", "launcher_changed": False}

        library = await self._run(store.get_library)
        entry = library.get(str(app_id)) or {}
        if not added["playlist"]:
            return {"ok": True, "error": "", "title": entry.get("title", ""),
                    "exe": "", "launcher_changed": False}

        return await self.update_game(
            app_id,
            entry.get("title", ""),
            entry.get("core_id", ""),
            added["playlist"],
            entry.get("options") or {},
            entry.get("system", ""),
        )

    async def make_disc_playlist(self, rom_path: str, discs: list):
        """Write the `.m3u` for a set and return the path to add instead.

        Only when Add is pressed: backing out must leave the folder as it was,
        and everything before is worked out from a disc, not a playlist. A
        plain playlist beside the discs, usable without this plugin.
        """
        folder = os.path.dirname(rom_path)
        path, error = await self._run(discset.write_playlist, folder, list(discs or []))
        if error:
            appenv.logger.warning("Could not write a playlist in %s: %s", folder, error)
            return {"ok": False, "path": "", "error": error}
        appenv.logger.info("Wrote %s naming %d disc(s)", path, len(discs))
        return {"ok": True, "path": path, "error": ""}
