"""The part of the Plugin class that works out what a file is.

Everything between the picker landing on a path and the add flow starting: what
the file reads as, which cores can run it, what it should be called, and what
artwork belongs to it. The add flow itself -- launcher, shortcut, collection,
record -- stays in main.py, because that is one act in an order that matters
and this is the question asked before it.

The two halves are `probe_rom`, which answers "what is this and what could run
it" for a file nobody has chosen a core for yet, and `resolve_game`, which
answers "what is this called and what does it look like" once one is chosen.

Mixed into `Plugin` rather than called by it, like the others: decky exposes
the methods it finds on the plugin object, so the names have to stay there
while the code lives somewhere findable. Nothing here may be instantiated
alone.
"""

import asyncio
import os

import decky

import plugin_base

import discset
import emulator_catalog
from emulator_catalog import ports as port_lists
import emulators
import fileserver
import gamecontent
import libretro_meta
import model3_games
import net
import platforms
import ps4_games
import ra_cores
import rompatch
import romshelf
import savedata
import sgdb
import store
import switch_nsz
import vita_games
import vita_release
import xbox360_content
import xbox_disc

#: Extensions that are never a game. The panel says so rather than offering
#: cores for a save file somebody picked by mistake.
ROM_EXTENSION_BLOCKLIST = {"srm", "state", "sav", "png", "jpg", "cfg", "txt", "xml"}


def _sift_ports(cores, rom_path):
    """(cores, ids), dropping the ports whose game this file cannot be.

    `ids` are the ports the file itself identified as its game, and the third
    answer names the ports that play this game but not this dump of it. Asked of
    the catalog rather than of the registered emulator: what a port wants is a
    property of the recipe, and the record holds only what launching needs.
    """
    kept, identified, refused = [], set(), []
    for core in cores:
        if not emulators.core_is_port(core["id"]):
            kept.append(core)
            continue
        entry = emulator_catalog.find(emulators.emulator_id(core["id"])) or {}
        verdict = port_lists.verdict(entry, rom_path)
        if verdict == port_lists.NOT_ITS_GAME:
            continue
        if verdict == port_lists.ITS_GAME:
            identified.add(core["id"])
        elif verdict == port_lists.WRONG_DUMP:
            # Still offered. The port is the right one for this game and the
            # user may know better than we do; what it is not is the confident
            # answer, and the warning below is the half worth reading.
            refused.append(entry.get("name") or core["id"])
        kept.append(core)
    return kept, identified, refused

class Probe(plugin_base.PluginContext):
    """What a file is, and what it is called."""

    async def _match_extension(self, rom_path, extension):
        """What this file reads as, and what is inside it when nothing can run that.

        Returns `(match_extension, archived)`. `archived` is the header of an
        archive's contents -- "stfs", "xex" -- and is set only when nothing can
        be offered for it, which is what empties the core list.
        """
        # A zipped ROM is matched on what is inside it, since RetroArch unpacks
        # archives itself and no core advertises `zip`.
        match_extension = await self._run(ra_cores.content_extension, rom_path)
        # An archive whose contents could not be named. `content_extension`
        # falls back to "zip", and twenty-two libretro cores legitimately claim
        # that -- Amstrad CPC, arcade, C64 -- so a zipped Xbox 360 title was
        # offered every one of them with `cap32` suggested. Each is a confident
        # wrong answer to "what runs this".
        #
        # Reading the header of what is inside settles it. Nothing gains an
        # emulator by this: Xenia refuses an archive outright, so the honest
        # answer stays "nothing installed can run this as it stands" -- but that
        # sentence, with the Unpack button under it, is the one that leads
        # somewhere.
        archived = ""
        if extension in ra_cores.ARCHIVE_EXTENSIONS and match_extension == extension:
            archived = await self._run(xbox360_content.inside_archive, rom_path)
        # And a file with no extension is matched on its header. Only Xbox 360
        # content packages arrive that way -- an XBLA title is a hash with no
        # suffix -- and without this there is no extension to match on, so the
        # panel offers no emulator for a file Xenia would boot from the path it
        # was given. Deliberately after the archive case and never instead of
        # it: a zipped XBLA container is one Xenia refuses outright, and it
        # should stay unmatched rather than be paired with an emulator that
        # will show an invisible error box.
        if not match_extension:
            match_extension = await self._run(
                xbox360_content.extension_from_header, rom_path
            )
        return match_extension, archived

    @staticmethod
    def _rank_cores(matching, identified, folder_system, romset, remembered):
        """Order the cores that claim this file, best answer first. Sorts in place.

        Evidence about this file beats a preference carried over from the last
        one. `last_core_by_ext` is keyed on the extension alone, so for `.chd`
        -- eighteen cores across six systems -- it remembers whichever system
        was added last and suggests it for the next file whatever that file is.
        A Dreamcast image suggested SwanStation is a shortcut that cannot work,
        and it is reported as "the game will not launch".

        One sort with every term rather than a pass each: the order the rules
        apply in is the whole behaviour, and a second `.sort()` silently
        overrules the first. Ties keep the order list_cores gave them, and when
        no term has anything to say the key is constant and the list is left
        exactly as it was.
        """
        matching.sort(
            key=lambda core: (
                # The file said which game it is, and exactly one thing here
                # plays that game. Nothing below this is evidence about this
                # file rather than about its shape, so nothing below outranks
                # it.
                core["id"] not in identified,
                bool(folder_system)
                and folder_system not in (core.get("databases") or []),
                # Only for a ROM set, and then decisive. The cores that read one
                # *as* the cartridge are the only ones that can run it; the rest
                # claim `zip` because they unpack archives, and one of them
                # being suggested is a confident wrong answer -- Amstrad CPC was
                # preselected for Daytona USA 2. Below the folder term, which is
                # evidence about this particular file rather than about the
                # shape of it.
                romset and not platforms.reads_rom_sets(core),
                # A port that got this far on its extension alone is offered
                # and not preselected: it claims a format, while the emulator
                # above it plays the game as it was released. The port that
                # named this file is already above, and never reaches here.
                emulators.core_is_port(core["id"]),
                core["id"] != remembered,
            )
        )

    async def probe_rom(self, rom_path: str):
        """Suggested cores for a ROM, most relevant first, plus a default name."""
        decky.logger.info("probe_rom: %s", rom_path)
        if not os.path.isfile(rom_path):
            decky.logger.warning("probe_rom: not a file: %s", rom_path)
        cores = await self.list_cores()
        extension = os.path.splitext(rom_path)[1].lower().lstrip(".")

        match_extension, archived = await self._match_extension(rom_path, extension)
        matching = [] if archived else ra_cores.cores_for_extension(
            cores, match_extension)
        # A port plays one game. Its extensions already narrow it to that game's
        # format, and where the recipe says what the file itself should read as,
        # this is where a disc of a different game drops out -- and where one
        # that reads as the right game is recognised. See `ports.verdict`.
        matching, identified, wrong_dump = await self._run(
            _sift_ports, matching, rom_path)
        # An arcade ROM set is matched on `zip`, which twenty-two cores claim
        # because most of them simply unpack an archive to reach the one game
        # inside. Asked once and used twice below: for the ordering, and for
        # whether the Unpack row belongs in the panel at all.
        romset = await self._run(ra_cores.is_romset, rom_path)

        settings = await self._run(store.get_settings)
        remembered = settings.get("last_core_by_ext", {}).get(match_extension, "")

        # What the folder holding the ROM says the system is, which for a disc
        # image is the only evidence there is. See platforms.SYSTEM_FOLDERS.
        folder_system = await self._run(platforms.system_for_folder, rom_path)

        self._rank_cores(matching, identified, folder_system, romset, remembered)

        # A save backup this plugin wrote, recognised by the manifest inside it
        # rather than by its name -- the name is the user's to change the moment
        # it lands in their downloads folder, and a zip called anything else is
        # still one of ours if the manifest is there.
        #
        # Probed here so the panel can offer restoring *instead of* the core
        # list: an archive of save files is not a ROM, and "Run with" over it is
        # the same confident wrong answer that a zipped Xbox 360 title being
        # offered Amstrad CPC was.
        save_backup = None
        if extension == "zip":
            described = await self._run(savedata.describe, rom_path)
            if described.get("ok") and described.get("sources"):
                save_backup = described["sources"]

        # Whether this file is already a game in the library, asked here rather
        # than left to be discovered afterwards. The cleanup screen has
        # classified duplicates for a long time, but only once two of them
        # exist -- and by then the fix is removing a shortcut instead of not
        # making one. Everything needed to say it is in front of us at the one
        # moment it is still cheap.
        #
        # Reported, never enforced. Adding the same ROM twice is a reasonable
        # thing to want -- the same disc under two cores, or one entry per
        # region -- so this changes what the panel says and not what it allows.
        already_added = await self._run(
            store.already_added, await self._run(store.get_library), rom_path
        )

        # The other discs of this game, when the file picked is one of a set.
        # Detected here and written nowhere: the playlist is created when the
        # user presses Add, so backing out of the flow leaves the folder exactly
        # as it was, and probing still happens on the disc -- which is what
        # keeps core matching correct. `.m3u` is claimed by one system in the
        # catalog, so matching cores against the playlist would offer a Saturn
        # set nothing at all.
        discs = await self._run(discset.find_set, rom_path)

        # One track of a disc whose `.cue` never arrived. Worth saying because
        # nothing else will: the panel offers cores for a `.bin` exactly as it
        # does for a cartridge, and the game that comes out is missing its audio
        # track at best. See `romshelf.track_without_a_sheet`.
        lone_track = await self._run(romshelf.track_without_a_sheet, rom_path)

        # And the layout a Redump download arrives in: one folder per disc. The
        # plugin cannot make a playlist out of that -- see
        # `discset.discs_in_sibling_folders` -- so what it can do is say what it
        # is looking at, rather than showing nothing and reading as a failure to
        # notice the other three discs sitting right there.
        #
        # Only asked when no set was found, which is always: the two are
        # mutually exclusive by construction.
        in_folders = [] if discs else await self._run(
            discset.discs_in_sibling_folders, rom_path
        )

        result = {
            "extension": extension,
            "match_extension": match_extension,
            "is_archive": extension in ra_cores.ARCHIVE_EXTENSIONS,
            # The game already added for this file, or None. See
            # `store.already_added` for why a name match and a path match are
            # different answers.
            "already_added": already_added,
            # The discs of the set this file belongs to, in order, or []. Names
            # rather than paths -- they are all in the folder the picked file is
            # in. Empty for the ordinary single-file game, which is almost
            # every game.
            "disc_set": discs,
            # Set when this is one track of a disc and no sheet in the folder
            # describes it. A sentence rather than a flag, for the same reason
            # `disc_warning` is one: what to do about it is the useful half.
            "track_warning": (
                "This is one track of a disc, and there is no .cue file beside "
                "it saying where the tracks are. Send the .cue as well and pick "
                "that instead — without it the audio track is invisible and the "
                "game may not start."
                if lone_track else ""
            ),
            # What the playlist would be called. Shown before it is written, so
            # the panel can name the file it is about to create rather than
            # describing one.
            # Set when the discs are each in a folder of their own, which is
            # how a Redump download arrives and is a layout no playlist can
            # name. A sentence, like the other two warnings, because what to do
            # about it is the useful half.
            "disc_folder_warning": (
                "The other %d discs are each in a folder of their own, and a "
                "playlist can only name files beside it. Send every disc's "
                "files to the Deck together — they arrive in one folder — or "
                "move them beside each other, and they can be added as one "
                "game." % (len(in_folders) - 1)
                if in_folders else ""
            ),
            "disc_playlist": (
                await self._run(discset.playlist_name, discs) if discs else ""
            ),
            # What restoring this would put back, per emulator, or None when the
            # file is not one of ours.
            "save_backup": save_backup,
            # Whether the Unpack row belongs in the panel. All three halves
            # matter: `.zip` because nothing on a stock SteamOS reads .7z or
            # .rar; *in the transfer folder* because that is the only directory
            # this plugin will write an archive's contents into -- see
            # `unpack_transferred_file` -- so a zip on an SD card is left alone,
            # and saying so by not offering the button beats offering one that
            # refuses; and *not a ROM set*, because unpacking one destroys it.
            #
            # That last is the only case here where the button would have done
            # real damage rather than nothing. An arcade ROM set is the
            # cartridge, not a wrapper around it: Supermodel and MAME both open
            # the `.zip` and read the chip dumps out of it by name, so unpacking
            # scatters forty files nothing can load and then consumes the one
            # file that could be played.
            #
            # A Switch `.nsz` is the other kind. Ryujinx cannot open one, and
            # `switch_nsz` turns it into the `.nsp` it can -- offered only where
            # the libraries that takes are present, so it is never a button that
            # refuses.
            "can_unpack": (
                (extension == "zip" and not romset
                 or extension == "nsz" and await self._run(switch_nsz.available))
                and await self._run(fileserver.inbox_path, os.path.basename(rom_path))
                == rom_path
            ),
            # What unpacking does, so the panel can say: a zip comes apart, an
            # `.nsz` becomes an `.nsp`.
            "unpack_kind": "nsz" if extension == "nsz" else "zip",
            # What to call this file in the panel. Normally its extension, which
            # is what every one of those sentences was written around -- but a
            # file matched on its header has no extension to show, and ".stfs"
            # names a format rather than anything the user can see on disk.
            # Saying "Xbox 360 content packages" is the only version of those
            # sentences that is true of the file they are about.
            # What is inside an archive that nothing can run as it stands, by
            # its header: "stfs", "xex", or "" when it is an ordinary zip or
            # could not be read. The panel uses it to say why there is no
            # emulator rather than leaving an empty list to be read as a fault.
            "archived_content": archived,
            "what": (
                "Xbox 360 content packages"
                if match_extension == "stfs" and not extension
                else ".%s" % match_extension if match_extension else ""
            ),
            "provisional_title": libretro_meta.display_title(libretro_meta.rom_stem(rom_path)),
            "matching_cores": matching,
            "all_cores": cores,
            "suggested_core_id": (matching[0]["id"] if matching else ""),
            "unsupported_extension": extension in ROM_EXTENSION_BLOCKLIST,
            # Which of its systems each core would take this file as, keyed by
            # core id. Only a core covering several has anything to say, and
            # only the file can say it: `.md` is a Mega Drive cartridge, while
            # the core that reads it declares six systems and lists Game Gear
            # first. The frontend uses this to preselect the system row, so the
            # answer is a visible default the user can change rather than a
            # guess made behind them.
            "system_for_core": {
                core["id"]: platforms.system_for_extension(
                    core.get("databases") or [], match_extension
                )
                for core in cores
            },
        }

        await self._probe_kinds(result, rom_path, extension, romset)
        await self._probe_warnings(result, rom_path, extension, wrong_dump)
        decky.logger.info(
            "probe_rom -> ext=%s match_ext=%s matching=%s suggested=%s backup=%s",
            extension,
            match_extension,
            [core["id"] for core in matching],
            result["suggested_core_id"],
            # Whether this was recognised as a save backup, and for whom. A zip
            # of saves matches on whatever extension happens to be inside it --
            # `.rtc` for a RetroArch backup -- so without this the log of a
            # backup being probed is indistinguishable from a ROM nothing runs.
            [entry["id"] for entry in save_backup] if save_backup else None,
        )
        return result

    async def _probe_kinds(self, result, rom_path, extension, romset):
        """What this file is, where that is not simply "a ROM". Fills `result`.

        Each of these either renames the game or empties the core list, because
        what was picked belongs to a game rather than being one.
        """
        # A PlayStation 3 package is the one thing the picker can be pointed at
        # that is not a game yet. RPCS3 has to unpack it first, and what boots
        # afterwards is dev_hdd0/game/<TITLE_ID>/USRDIR/EBOOT.BIN -- so the add
        # flow installs it and carries on with that path, and the user never
        # sees either the product code or the word EBOOT.
        #
        # `.pkg` does not say which console it is for, and three consoles share
        # it. PS4 is `\x7fCNT`; the PS3 and the Vita are both `\x7fPKG` and
        # differ only in a type field at offset 6. Sending a PS4 game to RPCS3
        # gets it reported as a corrupt package.
        if extension == "pkg":
            if await self._run(ps4_games.is_package, rom_path):
                result["ps4_package"] = await self._run(self._ps4_package_state, rom_path)
            elif await self._run(vita_games.is_package, rom_path):
                result["vita_package"] = await self._run(self._vita_package_state, rom_path)
            else:
                result["ps3_package"] = await self._run(self._ps3_package_state, rom_path)

            # The library records what boots, not the package it came out of,
            # so the path match above asked about the `.pkg` and found nothing
            # -- picking one already added said nothing at all. Asked again on
            # what was installed, which is the path a record would carry.
            state = (result.get("ps4_package") or result.get("vita_package")
                     or result.get("ps3_package") or {})
            if not result["already_added"] and state.get("installed") and state.get("eboot"):
                result["already_added"] = await self._run(
                    store.already_added,
                    await self._run(store.get_library),
                    state["eboot"],
                )

        # A ROM set is named after the MAME set rather than the game, so the
        # panel offered "daytona2" and Steam got a shelf entry called that.
        # It is also what the artwork search is given, and SteamGridDB has a
        # great deal of Daytona USA 2 and nothing whatever under `daytona2`.
        # The full title is in the game list Supermodel ships; see model3_games.
        romset_title, _hint = await self._romset_names(rom_path, romset)
        if romset_title:
            result["provisional_title"] = romset_title

        # A PS Vita release, which is a zip like every zipped ROM is a zip --
        # and a `.vpk` is the same thing under another extension. Detected by
        # the one file every release carries and no ROM archive does.
        #
        # Recognised in order to be *explained*, not offered. Vita3K is given a
        # `.pkg` and its zRIF or nothing: a release handed over as a path is
        # re-split on its spaces by the emulator's own launcher, and even
        # without spaces the content has to be installed and decrypted before
        # anything can start it. This used to suggest Vita3K as the core to run
        # it with, which wrote a Steam shortcut that could never work and said
        # so only when the game was launched.
        if extension in ("zip", "vpk"):
            vita = await self._run(vita_release.inspect, rom_path)
            if vita["vita"]:
                result["vita_release"] = vita
                if vita["title"]:
                    result["provisional_title"] = vita["title"]

        # A ROM hack, which belongs to a game rather than being one. Read from
        # the bytes, like the editor does, and only for something small enough
        # to be a patch: a ROM is what people pick by mistake, and no ROM opens
        # with a patch's magic. The core list is emptied the way it is for
        # a save backup, and the panel offers Install instead.
        try:
            small = os.path.getsize(rom_path) <= rompatch.MAX_PATCH_BYTES
        except OSError:
            small = False
        patch_kind = await self._run(rompatch.kind_of, rom_path) if small else ""
        if patch_kind:
            result["rom_patch"] = {"kind": patch_kind.lstrip(".")}
            result["matching_cores"] = []
            result["suggested_core_id"] = ""

        # A Switch update or DLC, which belongs to a game rather than being one.
        # Adding it would make a Steam entry that boots nothing, so the core
        # list is emptied the way it is for a save backup, and the panel offers
        # Install into the game it names instead.
        if "." + extension in gamecontent.SUFFIXES:
            owner = await self._run(
                gamecontent.owner, rom_path, await self._run(store.get_library))
            if owner:
                result["game_content"] = owner
                result["matching_cores"] = []
                result["suggested_core_id"] = ""
        # And the other way round: a game whose updates and DLC were sent with
        # it, waiting beside it. Installed straight after the game is added, so
        # sending a game and its update together ends in one Add.
        if "." + extension in gamecontent.GAME_SUFFIXES and not result.get("game_content"):
            result["content_waiting"] = await self._run(gamecontent.waiting_for, rom_path)

    async def _probe_warnings(self, result, rom_path, extension, wrong_dump):
        """What is wrong with this file, said before it is added. Fills `result`."""
        # A port that plays this game but refuses this dump of it. Said here
        # rather than left to the port, which says it after the game has been
        # added and a first launch has spent minutes building an archive from a
        # file it will not accept.
        if wrong_dump:
            result["dump_warning"] = (
                "%s plays this game but not this dump of it -- its own list of "
                "supported dumps does not have this one. You can still add it, "
                "and it will refuse the file when it starts."
                % (", ".join(sorted(wrong_dump)))
            )

        # An Xbox disc image with nothing to boot. Worth saying because the
        # console says it so badly: "Please insert an Xbox disc" on a black
        # screen reads as a broken emulator, a missing BIOS or a dead pad long
        # before it reads as a bad file. Said only when we are certain -- see
        # xbox_disc, silent about every .iso that is not an Xbox one.
        if extension in ("iso", "xiso"):
            disc = await self._run(xbox_disc.inspect, rom_path)
            # `certain` matters: a root that could not be read to the end proves
            # nothing about what is missing from it, and this answer is allowed
            # to stop the game being added.
            if disc["xbox"] and disc["certain"] and not disc["bootable"]:
                result["disc_warning"] = (
                    "This is an Xbox disc image, but there is no default.xbe at "
                    "its root, so there is nothing for the console to start. It "
                    "will boot to \"Please insert an Xbox disc\"."
                )

    async def _romset_names(self, rom_path, romset=None):
        """(name, artwork search hint) for an arcade ROM set, or ("", "").

        Two names because the sources disagree about how long a title is.
        Supermodel's game list gives the full one -- "Daytona USA 2 - Battle on
        the Edge" -- and that is the right thing to see on a shelf. SteamGridDB
        catalogues the same game as "Daytona USA 2", and the search is scored
        against the name it is given: the full title scored the correct answer
        at 0.65, under the cutoff, so a game that used to find its artwork under
        the wrong name stopped finding it under the right one.

        So the subtitle is dropped for the search and kept for the name. Only
        two of the sixty-three sets have one, both of them Daytona USA 2, and
        for both the part before the dash is exactly SteamGridDB's title.

        `romset` is passed in where the caller has already asked, so probing a
        file does not open the same archive twice.
        """
        if romset is None:
            romset = await self._run(ra_cores.is_romset, rom_path)
        if not romset:
            return "", ""
        named = await self._run(
            model3_games.title_for, libretro_meta.rom_stem(rom_path))
        if not named:
            return "", ""
        title = libretro_meta.display_title(named)
        hint = libretro_meta.display_title(named.split(" - ")[0])
        return title, (hint if hint and hint != title else "")

    async def resolve_game(
        self, rom_path: str, core_id: str, title: str = "", system: str = ""
    ):
        """Canonical name + artwork for a ROM/core pair.

        Artwork comes back as data URIs so the frontend can both preview it and
        hand it straight to the Steam client without a second download.

        `title` overrides the name derived from the filename, for the cases where
        the file is not named after the game at all. A PS3 game installed from a
        package boots `USRDIR/EBOOT.BIN`, so every one of them would search
        SteamGridDB for "EBOOT" -- its PARAM.SFO says "Braid".
        """
        decky.logger.info("resolve_game: core=%s rom=%s title=%r", core_id, rom_path, title)
        core = self._core_by_id(core_id)
        databases = core["databases"] if core else []
        # The system the user picked goes to the front of the search.
        #
        # `resolve` takes the first database whose thumbnail directory has a
        # matching name, so the order of this list decides which system's cover
        # a game gets. Left alone it is libretro's order, which is alphabetical:
        # a Mega Drive ROM run on Genesis Plus GX was matched against Game Gear
        # first and came back with the Game Gear cover of a different regional
        # release -- "Sonic The Hedgehog (USA, Europe)" answered by
        # "Sonic The Hedgehog (Japan, USA)".
        #
        # Moved rather than narrowed to the one system: this call also settles
        # the game's *name*, and a name matched on a sibling system is usually
        # still the right name. Nothing is filed on the strength of it any more
        # -- the picker's answer is what decides that -- so a stray match here
        # costs a cover, not a shelf.
        if system and system in databases:
            databases = [system] + [other for other in databases if other != system]
        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()
        art_source = settings.get("art_source", "auto")

        meta = await self._run(libretro_meta.resolve, rom_path, databases)

        # A ROM set is named after the MAME set, and this is the only place that
        # matters: `probe_rom` already puts the real title in the panel, but the
        # panel hands it back only on some paths -- changing the "Run with" core
        # deliberately passes no title, because for an ordinary ROM the name
        # should be re-derived from the file. So a game added the usual way went
        # to Steam as `daytona2` with the right name sitting one call away.
        #
        # Settled here instead, where every caller arrives: the add flow, the
        # core dropdown, the editor, and the re-lookup after an API key is
        # entered. It also improves the SteamGridDB query, which is handed
        # `meta["title"]` and was searching for `daytona2`.
        #
        # `is_romset` gates it rather than the name alone. Sixty-three set names
        # are short lowercase words -- `scud`, `harley`, `eca` -- and a console
        # ROM that happened to be called one of them should not be renamed.
        if not title:
            title, hint = await self._romset_names(rom_path)
            if hint:
                meta = dict(meta, matched_name=hint)

        if title:
            # Both, because they are used differently below: `title` is what the
            # search asks for and what the UI shows, `matched_name` is the hint
            # that keeps SteamGridDB from answering with a modern sequel.
            meta = dict(meta, title=title, matched_name=meta.get("matched_name") or title)

        art = {}
        source_used = "none"
        port_id = 0
        port_entry = (emulator_catalog.find(emulators.emulator_id(core_id))
                      if emulators.core_is_port(core_id) else None)
        # Which game SteamGridDB thinks this is, so a wrong match is visible in
        # the UI rather than silently producing art for another game.
        art_game_name = ""

        want_sgdb = api_key and art_source in ("auto", "sgdb")
        if want_sgdb:
            # **A port is looked up under its own name first.** It has an entry
            # of its own, with artwork drawn for the port rather than scanned
            # from the original box, and that is what is actually running.
            # Exact-match only -- see `sgdb.search_exact` -- so a port with no
            # entry falls through to the game below rather than taking whatever
            # its name half-matched.
            if port_entry:
                port_id = await self._run(
                    sgdb.search_exact, api_key, port_entry.get("name", "")
                )

            if port_id:
                urls = await self._run(sgdb.art_urls, api_key, port_id)
                art = await self._download_art(urls)
                if art:
                    # One of the three values the panel knows. It compares this
                    # string exactly, so a fourth spelling -- "steamgriddb
                    # (port)", which read better in the log -- fell through to
                    # the libretro branch and labelled SteamGridDB art libretro.
                    source_used = "steamgriddb"
                    art_game_name = (port_entry or {}).get("name", "")
                else:
                    # **An entry with no artwork is not an answer.** A port
                    # named after an ordinary word gets one: "Lighthouse" and
                    # "Starship" each matched a game nobody here has heard of,
                    # both artless, and taking the id as final meant the game
                    # itself was never looked up at all -- so Banjo wore a
                    # libretro box scan while SteamGridDB had a capsule for it.
                    # Preferring the port is the rule; excluding the
                    # game is not.
                    port_id = 0

            # The system and the libretro-matched name both help: SteamGridDB's
            # own search happily returns a modern sequel for an 8-bit title.
            if not art:
                game_id = await self._run(
                    sgdb.search_game,
                    api_key,
                    meta["title"],
                    databases,
                    meta["matched_name"],
                )
                if game_id:
                    urls = await self._run(sgdb.art_urls, api_key, game_id)
                    art = await self._download_art(urls)
                    if art:
                        source_used = "steamgriddb"
                        art_game_name = await self._run(
                            sgdb.game_name, api_key, game_id
                        )

        if not art and art_source in ("auto", "libretro") and meta["boxart_url"]:
            art = await self._download_art({"capsule": meta["boxart_url"]})
            if art:
                source_used = "libretro"

        # **Whoever identified the game supplies the name.**
        #
        # A libretro `exact` match means the filename *is* a known ROM name,
        # which no search can beat, so it wins. But when libretro matched
        # nothing, the title was the filename tidied up -- and if SteamGridDB
        # went on to identify the game well enough to fetch four pieces of
        # artwork for it, that identification is better evidence than the
        # filename. Trusting it for the picture and not for the name was an
        # asymmetry with nothing behind it: a wrong SteamGridDB match produces
        # wrong artwork either way.
        #
        # Measured over a real library before writing this: of twelve games,
        # eight names were identical, three were better from SteamGridDB
        # (accents, capitalisation, a stray trademark symbol), and one was a
        # different game in the same series. That last one is why the source is
        # reported rather than the name silently swapped -- see `title_source`,
        # which the panel shows beside a field that stays editable.
        # The port's name is shown beside its artwork but never becomes the
        # game's: a cover drawn for Ship of Harkinian does not make the game
        # "Ship of Harkinian". It is still whatever the disc holds.
        chosen, title_source = libretro_meta.choose_title(
            meta["match_kind"], meta["title"], "" if port_id else art_game_name
        )

        # A port's shortcut says both: the game, because that is what somebody
        # looks for, and the port, because that is what runs and what the
        # artwork is of. It also keeps two dumps on one port apart, which the
        # port's name alone would not.
        #
        # Unless nothing identified the file, and the name is the filename
        # tidied up. A port plays one known game, so its own name beats a stem:
        # a data file called `spawn.mpq` was named "spawn", not for its game.
        port_name = (port_entry or {}).get("name", "") if port_entry else ""
        if port_name and title_source == "filename":
            # The entry may name the game it plays, and then the shortcut reads
            # like every other port's -- "Diablo (DevilutionX)" rather than the
            # port on its own, which is what a data file with no game in its
            # name would otherwise give.
            plays = (port_entry or {}).get("plays", "")
            chosen = "%s (%s)" % (plays, port_name) if plays else port_name
            title_source = "port"
        elif port_name and port_name.lower() not in chosen.lower():
            chosen = "%s (%s)" % (chosen, port_name)

        meta = dict(meta, title=chosen)

        decky.logger.info(
            "resolve_game -> title=%r match=%s art=%s via=%s name_from=%s",
            meta["title"],
            meta["match_kind"],
            sorted(art.keys()),
            source_used,
            title_source,
        )

        return {
            "title_source": title_source,
            "title": meta["title"],
            "system": meta["system"],
            "matched_name": meta["matched_name"],
            "match_kind": meta["match_kind"],
            "art": art,
            "art_source": source_used,
            "art_game_name": art_game_name,
            "core_id": core_id,
            "rom_path": rom_path,
        }

    async def _download_art(self, urls):
        """{slot: url} -> {slot: {data, kind}} for whatever downloaded cleanly.

        Concurrently, because these are up to four independent images of a
        megabyte or so each and nothing about one informs another. Downloading
        them one after another put four round trips end to end in front of the
        cover the user is waiting to see.
        """
        wanted = [(slot, url) for slot, url in (urls or {}).items() if url]
        if not wanted:
            return {}

        downloaded = await asyncio.gather(
            *(self._run(net.get_data_uri, url) for _slot, url in wanted)
        )

        art = {}
        for (slot, _url), (data_uri, kind) in zip(wanted, downloaded):
            if data_uri:
                art[slot] = {"data": data_uri, "kind": kind}
        return art
