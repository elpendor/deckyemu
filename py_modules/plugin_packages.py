"""The half of the Plugin class that deals with games arriving as packages.

PlayStation 3, PlayStation 4 and Vita games are not files you point an emulator
at. They arrive as a .pkg, get installed *into* the emulator, and what boots
afterwards lives under a product code inside that emulator's own directory. All
three need the same four things -- read the package, install it, list what is
installed, and delete one -- and none of that resembles adding a ROM.

Mixed into `Plugin` rather than called by it, because decky exposes the methods
it finds on the plugin object and these are endpoints the frontend calls by
name. Inheritance keeps the names where decky looks for them while keeping the
code somewhere a reader can find it: main.py was 3,791 lines and this was 435 of
them, sitting in the middle of the emulator installer.

Everything here may use the rest of the Plugin -- `self._run`,
`self._run_emulator_tool`, `self._parse_percent` -- because the composed class
has them. Nothing here may be instantiated on its own, and nothing tries.
"""

import os

import decky

import plugin_base

import emu_firmware
import emu_install
import emulator_catalog
import emulators
import fileserver
import ps3_games
import ps4_games
import romshelf
import vita_games


class PackagedGames(plugin_base.PluginContext):
    """Endpoints for games that arrive as a package. See the module docstring."""

    async def list_installed_ps3_games(self):
        """PS3 titles RPCS3 has unpacked from packages, ready to add to Steam.

        These never appear in the ROM picker and never could: what boots is
        `dev_hdd0/game/<TITLE_ID>/USRDIR/EBOOT.BIN`, buried inside a flatpak's
        data directory under a name that is a product code rather than a title.
        Reading each game's own PARAM.SFO is what turns that into "Braid".
        """
        games = await self._run(ps3_games.installed_games)
        return {"ok": True, "games": games}

    def _ps3_package_dirs(self):
        """Every folder a sent .pkg could have landed in."""
        # The transfer folder is where a sent one lands. The firmware folder is
        # where somebody who used the PS3 firmware row's send button put one,
        # and a file that disappears because it was sent from the wrong row is
        # exactly the friction this removes.
        #
        # Not the filed library: a package is consumed by installing it and the
        # game that comes out lives inside RPCS3, so a .pkg is never something
        # that gets filed under a system.
        return [fileserver.default_dir(), emu_install.firmware_dir()]

    async def list_ps3_packages(self):
        """PS3 packages waiting to be installed, and whether each already is."""
        directories = await self._run(self._ps3_package_dirs)
        packages = await self._run(ps3_games.packages, directories)
        return {"ok": True, "packages": packages}

    async def install_ps3_package(self, path: str):
        """Unpack a .pkg into RPCS3, with no window and nothing to press.

        Awaited rather than started and reported on: the caller's promise
        resolving *is* the completion signal, so a lost event costs a progress
        bar rather than an install that finished with the UI still showing it
        running. That happened -- the package unpacked in five seconds, the
        backend said so, and the panel sat on "Unpacking" because the one
        message that ended it went by a channel nothing else depended on.

        Progress events are still emitted, and are now decoration: they fill the
        bar while this runs, and nothing breaks if they never arrive.
        """
        entry = emulator_catalog.find("rpcs3")
        emulator = await self._run(emulators.find, "rpcs3")
        if not entry or not emulator:
            return {"ok": False, "error": "RPCS3 is not set up yet. Install it first."}

        # The path arrives from the frontend and is about to become a subprocess
        # argument, so it is checked against the list rather than trusted: only
        # a package this plugin just offered can be installed.
        directories = await self._run(self._ps3_package_dirs)
        packages = await self._run(ps3_games.packages, directories)
        package = next((item for item in packages if item["path"] == path), None)
        if not package:
            return {"ok": False, "error": "That package is no longer in the transfer folder."}

        return await self._install_ps3_package(emulator, package)

    async def _install_ps3_package(self, emulator, package):
        name = package["name"]
        await decky.emit("ps3_install_progress", name, "Unpacking %s" % name, -1)

        before = await self._run(ps3_games.installed_title_ids)

        async def on_line(text):
            await decky.emit("ps3_install_progress", name, text, self._parse_percent(text))

        ok, error = await self._run_emulator_tool(
            emulator,
            ["--headless", "--installpkg", package["path"]],
            allow=[os.path.dirname(package["path"])],
            # A package can be several gigabytes, and RPCS3 unpacks at roughly
            # 50MB a second, so this is about ten times the worst realistic case.
            seconds=1800,
            on_line=on_line,
        )

        # What appeared, not what RPCS3 said. This is load-bearing rather than
        # belt-and-braces: on a Deck this exact run printed "Verification
        # failed" and "Emulation object is unavailable (process teardown)" on
        # its way out, and the package had installed perfectly. Judging by the
        # exit code would have called a good install a failure.
        games = await self._run(ps3_games.installed_games)
        added = [game for game in games if game["title_id"] not in before]
        title = added[0]["title"] if added else ""

        if not added:
            return {
                "ok": False,
                "error": error or "RPCS3 finished but no new game appeared.",
            }

        # Recorded before the package goes, because the package is the only
        # place the content id exists: an installed game's PARAM.SFO has a
        # TITLE_ID and no CONTENT_ID, and the licence that decrypts it is found
        # by content id alone. Without this the panel could only warn about a
        # missing licence in the window before installing.
        content_id = await self._run(ps3_games.package_content_id, package["path"])
        await self._run(ps3_games.remember_content_id, added[0]["title_id"], content_id)

        # And its licence, if one came with it. Sending a game and its .rap
        # together is the obvious thing to do and is what the Vita flow already
        # expects, so the same gesture works here: beside the package first,
        # then the transfer folder. Renamed to the content id on the way in,
        # which is the only name RPCS3 will read it under.
        licence = await self._run(
            ps3_games.install_licence,
            content_id,
            ps3_games.licence_dirs(package["path"], emu_install.firmware_dir()),
            package["path"],
        )

        # Same reasoning as the firmware PUP: the package is a couple of hundred
        # megabytes, the game is now unpacked, and RPCS3 never reads the .pkg
        # again. Only after the game has been seen, so a failure keeps the file.
        removed = await self._run(
            emu_firmware.remove, [name], os.path.dirname(package["path"])
        )
        decky.logger.info(
            "Installed %s as %s (deleted %s, licence %s)",
            name, title, removed.get("removed", []), licence or "none",
        )
        return {
            "ok": True,
            "title": title,
            "title_id": added[0]["title_id"],
            "licence": licence,
        }

    async def install_ps4_package(self, path: str):
        """Unpack a PS4 .pkg with the standalone extractor, fetching it first.

        shadPS4 cannot do this itself and no fork of it can: the extraction code
        was taken out of shadPS4 and published as a command-line tool, which is
        what runs here. Awaited rather than started, for the same reason as the
        PS3 one -- the promise resolving is what ends the step, so a lost event
        cannot leave the panel claiming to still be working.
        """
        entry = emulator_catalog.find("shadps4")
        helper = (entry or {}).get("helper") or {}
        if not helper:
            return {"ok": False, "error": "No package extractor is configured."}

        if not await self._run(ps4_games.is_package, path):
            return {"ok": False, "error": "That file is not a PlayStation 4 package."}

        title_id = await self._run(ps4_games.package_title_id, path)
        target = await self._run(ps4_games.target_dir, title_id)
        if not target:
            return {
                "ok": False,
                "error": "That package does not name a title id, so there is "
                "nowhere obvious to unpack it. Install it from shadPS4's own "
                "interface instead.",
            }

        tool, error = await self._ensure_helper(helper)
        if error:
            return {"ok": False, "error": error}

        await decky.emit(
            "ps4_install_progress", os.path.basename(path), "Unpacking %s" % title_id, -1
        )

        async def on_line(text):
            await decky.emit(
                "ps4_install_progress", os.path.basename(path), text,
                self._parse_percent(text),
            )

        ok, run_error = await self._run_emulator_tool(
            # The extractor is a plain binary, so it is described as one: the
            # tool runner only needs `kind` and `target` to build a command.
            {"kind": "path", "target": tool, "name": helper["label"]},
            [path, target],
            seconds=3600,
            on_line=on_line,
        )

        # What appeared, not what the tool said -- the same rule the PS3 side
        # needed when RPCS3 printed a crash on its way out of a good install.
        # `settle` also flattens the folder the extractor names after the title,
        # which otherwise leaves the game one level too deep for both this
        # plugin's listing and shadPS4's own.
        game_dir, settle_error = await self._run(ps4_games.settle, target)
        if not game_dir:
            return {
                "ok": False,
                "error": run_error or "The extractor finished but no game appeared.",
            }
        if settle_error:
            return {"ok": False, "error": settle_error}

        games = await self._run(ps4_games.installed_games)
        game = next((item for item in games if item["title_id"] == title_id), None)

        # Same as the PS3 side, and for the same two reasons: the package is
        # hundreds of megabytes to tens of gigabytes, and nothing reads it again
        # once the game is unpacked. Only after the game has been seen, so a
        # failed extraction keeps the only copy.
        removed = await self._run(
            emu_firmware.remove, [os.path.basename(path)], os.path.dirname(path)
        )
        decky.logger.info(
            "Unpacked %s to %s (deleted %s)", path, game_dir, removed.get("removed", [])
        )
        return {
            "ok": True,
            "title": (game or {}).get("title") or title_id,
            "title_id": title_id,
        }

    async def _ensure_helper(self, helper):
        """The helper binary's path, downloading it if this is the first time."""
        existing = await self._run(emu_install.installed_tool, helper["name"])
        if existing:
            return existing, ""

        await decky.emit(
            "ps4_install_progress", "", "Fetching the %s" % helper["label"], -1
        )
        asset, error = await self._run(
            emu_install.resolve_github_asset, helper["repo"], helper["asset"]
        )
        if error:
            return "", error
        return await self._run(emu_install.install_tool, helper["name"], asset)

    async def list_installed_ps4_games(self):
        """PS4 titles that have been unpacked, ready to add to Steam."""
        games = await self._run(ps4_games.installed_games)
        return {"ok": True, "games": games}

    async def save_vita_key(self, pkg_path: str, key: str):
        """Save a licence key pasted from the clipboard beside its package.

        The other way in for the one thing this console needs and the plugin
        will never carry. A zRIF is a few hundred characters of base64, so
        typing it on the on-screen keyboard is not a route anybody would take --
        but pasting is, if the key is open in Steam's own browser on the Deck.

        It lands where a key sent by transfer would land, named after the title
        id, so both routes end at the same search.
        """
        if not await self._run(vita_games.is_package, pkg_path):
            return {"ok": False, "error": "That file is not a PlayStation Vita package."}

        title_id = await self._run(vita_games.package_title_id, pkg_path)
        saved, error = await self._run(vita_games.write_zrif, pkg_path, key, title_id)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "name": os.path.basename(saved)}


    async def install_vita_package(self, path: str, key_name: str = ""):
        """Install a Vita .pkg with the key that came with it. No window at all.

        Mirrors the PS3 one: the emulator does its own installing, so there is
        no helper to fetch. What differs is the key -- Vita3K needs a zRIF to
        decrypt the content and cannot derive it, so the package travels with
        one and this looks beside the file rather than in a bundled table.

        `key_name` is a file in the same folder that the *user* said was this
        game's, for the case where nothing about its name says so. Chosen there
        rather than guessed here: picking the only key lying around installed a
        gigabyte and a half under another game's licence once, and every symptom
        of it pointed at the package instead. A name, never a path -- this is
        reachable from anything running in Steam's JS context, and joining a
        caller's string to a folder is how that becomes a file read anywhere.
        """
        emulator = await self._run(emulators.find, "vita3k")
        if not emulator:
            return {"ok": False, "error": "Vita3K is not set up yet. Install it first."}

        if not await self._run(vita_games.is_package, path):
            return {"ok": False, "error": "That file is not a PlayStation Vita package."}

        title_id = await self._run(vita_games.package_title_id, path)
        zrif, key_file = await self._run(vita_games.locate_zrif, path, title_id)

        if not zrif and key_name:
            chosen = os.path.basename(key_name)
            if chosen in await self._run(vita_games.zrif_candidates, os.path.dirname(path)):
                key_file = os.path.join(os.path.dirname(path), chosen)
                zrif = await self._run(vita_games.zrif_from, key_file)

        if not zrif:
            return {
                "ok": False,
                "error": "No licence key found for this package. Send its .zrif "
                "or .txt file to the same folder and try again -- Vita3K cannot "
                "decrypt a package without one.",
            }

        await decky.emit(
            "vita_install_progress", os.path.basename(path),
            "Installing %s" % (title_id or "package"), -1,
        )

        # Vita3K says why it failed and then exits 0, so the only account of a
        # wrong key is a line in the middle of the output. Without this the
        # install ends on "no new game appeared", which describes the symptom
        # and points at the package -- the one thing that was not at fault.
        mismatch = []

        async def on_line(text):
            if "header signature is invalid" in text.lower():
                mismatch.append(text)
            await decky.emit(
                "vita_install_progress", os.path.basename(path), text,
                self._parse_percent(text),
            )

        before = {game["title_id"] for game in await self._run(vita_games.installed_games)}
        ok, error = await self._run_emulator_tool(
            emulator,
            ["--pkg", path, "--zrif", zrif],
            allow=[os.path.dirname(path)],
            seconds=3600,
            on_line=on_line,
            # Same as the firmware: Vita3K's Qt aborts without a display even
            # for a run that draws nothing.
            display=True,
        )

        # What appeared, not what it said -- the rule every console here needed.
        games = await self._run(vita_games.installed_games)
        game = next(
            (item for item in games
             if item["title_id"] == title_id or item["title_id"] not in before),
            None,
        )
        if not game:
            if mismatch:
                return {
                    "ok": False,
                    "error": "That licence key is not this game's. Vita3K read the "
                    "key and then could not decrypt the content with it (%s). Send "
                    "the key that came with this package, named after its title id."
                    % os.path.basename(key_file or "the key used"),
                }
            return {
                "ok": False,
                "error": error or "Vita3K finished but no new game appeared.",
            }

        # The key goes with the package it unlocked. It is spent -- the content
        # is decrypted and installed -- and a key left behind is one more
        # unnamed candidate the next package has to be asked about.
        spent = [os.path.basename(path)]
        if key_file and os.path.dirname(key_file) == os.path.dirname(path):
            spent.append(os.path.basename(key_file))
        removed = await self._run(emu_firmware.remove, spent, os.path.dirname(path))
        decky.logger.info(
            "Installed %s as %s (deleted %s, exit ok=%s)",
            os.path.basename(path), game["title"], removed.get("removed", []), ok,
        )
        return {"ok": True, "title": game["title"], "title_id": game["title_id"]}

    async def list_installed_vita_games(self):
        """PS Vita titles Vita3K has installed, ready to add to Steam.

        The one console here this plugin cannot install for you -- Vita3K
        decrypts content as it installs -- so this reads what its interface
        produced rather than what the panel unpacked.
        """
        games = await self._run(vita_games.installed_games)
        return {"ok": True, "games": games}

    async def prepare_vita_game(self, title_id: str):
        """Everything Steam needs for one installed PS Vita game.

        Launching is by title id, not by path: `-Fr PCSA00011` boots a game and
        handing Vita3K a path does not. The ROM recorded in the library is
        still the game's `eboot.bin`, because every health check in this plugin
        asks whether a game's file is still there -- and because the title id
        can be derived back out of it when a launcher is rebuilt.
        """
        games = await self._run(vita_games.installed_games)
        game = next((item for item in games if item["title_id"] == title_id), None)
        if not game:
            return {"ok": False, "error": "Vita3K no longer has a game with that id."}

        emulator = await self._run(emulators.find, "vita3k")
        if not emulator:
            return {"ok": False, "error": "Vita3K is not set up yet. Install it first."}

        core_id = emulators.to_core_entry(emulator)["id"]
        prepared = await self.prepare_shortcut(
            game["title"], core_id, game["eboot"], "Sony - PlayStation Vita",
            title_id=title_id,
        )
        if not prepared.get("ok"):
            return prepared

        prepared["rom_path"] = game["eboot"]
        prepared["core_id"] = core_id
        prepared["title_id"] = title_id
        return prepared

    async def vita_core_id(self):
        """The core id the add flow should use for a PS Vita game."""
        emulator = await self._run(emulators.find, "vita3k")
        if not emulator:
            return {"ok": False, "error": "Vita3K is not set up yet. Install it first."}
        return {"ok": True, "core_id": emulators.to_core_entry(emulator)["id"]}

    async def ps4_core_id(self):
        """The core id the add flow should use for a PlayStation 4 game."""
        emulator = await self._run(emulators.find, "shadps4")
        if not emulator:
            return {"ok": False, "error": "shadPS4 is not set up yet. Install it first."}
        return {"ok": True, "core_id": emulators.to_core_entry(emulator)["id"]}

    # The two consoles whose games are unpacked from a package rather than
    # pointed at where they lie. Everything below asks both, because a library
    # entry does not say which one it came from and the remove dialog should not
    # have to care.
    _PACKAGED = {"ps3": ps3_games, "ps4": ps4_games, "vita": vita_games}

    async def packaged_game_info(self, rom_path: str):
        """What removing this game could also delete, and how much that is.

        Two kinds of thing, answered by one call because the dialog asks one
        question. A PS3, PS4 or Vita game was unpacked by this plugin and lives
        inside the emulator under a product code; a ROM was sent here and filed
        under its system. Both are gigabytes the panel put on the disk, both
        are re-obtainable only from another machine, and there is no reason for
        the dialog to treat them differently -- so it does not.

        `{"ok": False}` for anything else, which includes every ROM the user
        keeps somewhere of their own. Those were never moved by this plugin and
        are not offered for deletion by it.
        """
        for system, module in self._PACKAGED.items():
            info = await self._run(module.game_info, rom_path)
            if info.get("ok"):
                info["system"] = system
                info["kind"] = "packaged"
                return info

        library = await self._run(romshelf.library_dir)
        if await self._run(romshelf.owned, rom_path, library):
            total, group = await self._run(romshelf.footprint, rom_path)
            return {
                "ok": True,
                "kind": "rom",
                "bytes": total,
                # Named so the dialog can say "and its two tracks" rather than
                # deleting them silently alongside.
                "files": group,
                "folder": os.path.basename(os.path.dirname(rom_path)),
            }
        return {"ok": False}

    async def delete_rom(self, rom_path: str):
        """Delete a filed ROM and whatever has to go with it."""
        library = await self._run(romshelf.library_dir)
        freed, error = await self._run(romshelf.delete_rom, rom_path, library)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "freed": freed}

    async def delete_packaged_game(self, system: str, title_id: str):
        """Delete an unpacked PS3 or PS4 game.

        The one place this plugin deletes something playable. Removing a game
        leaves the ROM alone everywhere else, and rightly: the ROM is the user's
        own file. One of these is neither -- this plugin unpacked it -- so what
        removal would otherwise leave behind is gigabytes that nothing in the
        panel can see or remove.
        """
        module = self._PACKAGED.get(system)
        if not module:
            return {"ok": False, "error": "Unknown system %r." % system}
        freed, error = await self._run(module.delete_game, title_id)
        if error:
            return {"ok": False, "error": error}
        return {"ok": True, "freed": freed}

    async def ps3_core_id(self):
        """The core id the add flow should use for a PlayStation 3 game.

        Resolved here rather than assumed in the UI: the id is whatever RPCS3
        registered as, and `emulators.save` will suffix it if something else got
        there first.
        """
        emulator = await self._run(emulators.find, "rpcs3")
        if not emulator:
            return {"ok": False, "error": "RPCS3 is not set up yet. Install it first."}
        return {"ok": True, "core_id": emulators.to_core_entry(emulator)["id"]}
