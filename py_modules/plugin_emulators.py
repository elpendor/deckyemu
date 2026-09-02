"""The part of the Plugin class that gets an emulator onto the Deck.

The one-click catalog -- install from Flathub or a project's own AppImage
release, register what is already there, and remove it again -- plus the CRUD
for an emulator somebody registered by hand, and the route to an emulator's own
window for the jobs it will only do there.

Two channels because the catalog has two kinds of entry, and they fail
differently: a flatpak installed system-wide cannot be removed without root,
and an AppImage has to be matched by an anchored asset pattern or the aarch64
build installs and dies at exec time.

Mixed into `Plugin` rather than called by it -- see plugin_firmware for why.
"""

import asyncio
import os

import decky

import plugin_base

import emu_config
import emu_install
import emu_patch
import emulator_catalog
import emulators
import fileserver
import installer
import launchers
import platforms
import procout
import ps3_games
import ra_detect
import store


def _unavailable_fixes(entry, emulator):
    """{workaround id: why} for fixes this install could not take.

    Asked of the files rather than only the record `emu_patch.refresh` wrote:
    the record says what happened at install, and what the panel has to report
    is what is true now. A patched build that exists is a fix that runs,
    whatever the record remembers, and the reverse is the case worth catching.
    """
    stock = emu_patch.stock_path((emulator.get("target") or "").strip(), entry)
    return {
        row["id"]: row["error"] or "This build would not take that fix."
        for row in emu_patch.unapplied(entry, stock)
    }


def _discard(path):
    """Delete a file that has served its purpose. True if it is gone."""
    try:
        os.remove(path)
        return True
    except OSError:
        return not os.path.exists(path)


def _read_text(path, limit):
    """The file's text, or None when it is larger than `limit`."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(limit + 1)
    return None if len(text) > limit else text


#: RetroArch shaped as a catalog entry, for the endpoints that change an
#: installed flatpak's build.
#:
#: It is not in the catalog and should not be -- cores run inside it rather than
#: beside it, and it has its own tab, its own installer and its own uninstall
#: rules. But it is a Flathub app installed exactly the way the catalog's flatpaks
#: are, so "update it", "go back" and "hold it there" are the same three
#: operations on a different id. One implementation, reached with this, beats a
#: parallel set of retroarch_* endpoints that would drift from it -- which is the
#: lesson `emulators.LAUNCH_HINTS` already taught this project once.
#: Annotated, or the literal's value type is inferred narrowly enough that
#: `entry["source"]["id"]` stops type-checking where a catalog entry does not.
_RETROARCH_ENTRY: dict = {
    "id": "retroarch",
    "name": "RetroArch",
    "source": {"kind": "flatpak", "id": ra_detect.FLATPAK_ID},
}


class Emulators(plugin_base.PluginContext):
    """Emulator install and registration endpoints. See the module docstring."""

    async def list_emulator_catalog(self):
        """Emulators that can be installed from here, with what they run.

        Extensions are derived from libretro's own metadata rather than stored,
        so this is the same info.zip the RetroArch tab already warms and it is
        cached between calls.
        """
        extensions = await self._run(installer.database_extensions)
        entries = await self._run(emulator_catalog.listing, extensions)

        # "Installed" means the emulator is actually present, not merely that a
        # registration exists. Those drift apart: a user can remove the flatpak
        # from Discover, and offering "Remove" for something already gone --
        # while hiding "Install" for it -- is a dead end with no way out.
        registered = {emulator.get("id") for emulator in self._emulators}
        for item in entries:
            entry = emulator_catalog.find(item["id"])
            # Whether the second file this emulator needs for motion is here.
            # Said out loud for the same reason firmware is: a requirement that
            # can be absent has to be visible, or its absence reads as the
            # feature not existing.
            item["motion"] = await self._run(emu_install.motion_state, entry)
            if item["kind"] == "flatpak":
                item["present"] = await self._run(
                    emu_install.flatpak_installed, entry["source"]["id"]
                )
                item["scope"] = await self._run(emu_install.flatpak_scope, entry["source"]["id"])
            elif item["kind"] == "byo":
                # Nothing to look for on disk: this plugin never put it there.
                # A bring-your-own emulator is present exactly when the user has
                # pointed at a binary and that binary is still where they said.
                target = next(
                    (emulator.get("target") for emulator in self._emulators
                     if emulator.get("id") == item["id"]),
                    "",
                )
                item["present"] = bool(target) and await self._run(os.path.isfile, target)
                item["target"] = target
                item["scope"] = "user"
            else:
                item["present"] = bool(
                    await self._run(emu_install.installed_appimage, item["id"])
                )
                item["scope"] = "user"
            item["installed"] = item["present"]
            item["registered"] = item["id"] in registered

        return entries


    async def imported_emulators(self):
        """The user-supplied definitions, and why any were refused.

        The refusals matter as much as the successes. A definition that fails to
        load produces an emulator that simply never appears, which is
        indistinguishable from having imported the wrong file.
        """
        await self._run(emulator_catalog.reload_imported)
        return {
            "entries": [
                {
                    "id": entry["id"],
                    "name": entry.get("name", entry["id"]),
                    "summary": entry.get("summary", ""),
                    "file": entry.get("source_file", ""),
                }
                for entry in emulator_catalog.CATALOG
                if entry.get("imported")
            ],
            "problems": list(emulator_catalog.import_problems),
            "suffix": emulator_catalog.imported.SUFFIX,
        }


    async def list_emulator_definitions(self):
        """Definition files waiting in the transfer folder.

        Read off the folder, so a file sent in an earlier session is still
        offered -- the received list the transfer dialog shows is this session's
        and does not survive a reload, which left a definition already on the
        device with no route into the plugin at all.
        """
        waiting = await self._run(
            fileserver.inbox_files, emulator_catalog.imported.SUFFIX
        )
        return {
            "ok": True,
            "suffix": emulator_catalog.imported.SUFFIX,
            "path": await self._run(fileserver.default_dir, False),
            "files": [
                {"name": item["name"], "size": item["size"], "at": item["at"]}
                for item in waiting
            ],
        }


    async def preview_emulator_definition(self, name: str):
        """What a definition says it will do, without storing it.

        The panel shows this and makes the user confirm. A definition is not
        data the plugin reads, it is a list of actions the plugin performs, and
        the person importing one is the only person in a position to judge
        whether they trust it -- so they are told, in plain terms, what it will
        install and where it will write, before any of it happens.

        Deliberately the same parse the import does. A preview produced by
        different code could describe something other than what runs, which
        would be worse than no preview at all.
        """
        path = await self._run(fileserver.inbox_path, name)
        if not path:
            return {"ok": False, "error": "%s is not in the transfer folder." % name}

        try:
            text = await self._run(_read_text, path,
                                   emulator_catalog.imported.MAX_BYTES)
        except OSError as failure:
            return {"ok": False, "error": "Could not read %s: %s" % (name, failure)}
        if text is None:
            return {"ok": False, "error": "%s is too large to be a definition." % name}

        known = [label for label, _full, _short in platforms.NO_LIBRETRO_PLATFORMS]
        entry, error = await self._run(emulator_catalog.imported.parse, text, known)
        if error:
            return {"ok": False, "error": error}

        source = entry.get("source") or {}
        kind = source.get("kind", "")
        if kind == "flatpak":
            installs = "Flathub: %s" % source.get("id", "")
        elif kind == "github":
            installs = "%s (%s)" % (source.get("repo", ""),
                                    source.get("host") or "github.com")
        else:
            installs = ""

        return {
            "ok": True,
            "error": "",
            "id": entry["id"],
            "name": entry.get("name", entry["id"]),
            "summary": entry.get("summary", ""),
            "system": entry.get("platform") or ", ".join(entry.get("databases") or []),
            # The two things worth reading before agreeing: what it will
            # download, and everywhere it can write.
            "installs": installs,
            "writes": [root for root in (
                [entry["root"]] if isinstance(entry.get("root"), str)
                else list(entry.get("root") or ())
            )],
            "replaces": await self._run(
                os.path.isfile, emulator_catalog.imported.path_for(entry["id"])
            ),
        }


    async def import_emulator_definition(self, name: str, replace: bool = False):
        """Import a definition the user sent, named as it appears in the inbox.

        Taken from the transfer folder rather than a path the frontend supplies,
        so the file has to be one the user actually sent. Firmware arrives the
        same way, which is the point: adding an emulator this plugin does not
        ship is the same gesture as supplying a BIOS.
        """
        path = await self._run(fileserver.inbox_path, name)
        if not path:
            return {"ok": False, "error": "%s is not in the transfer folder." % name}

        try:
            text = await self._run(_read_text, path,
                                   emulator_catalog.imported.MAX_BYTES)
        except OSError as failure:
            return {"ok": False, "error": "Could not read %s: %s" % (name, failure)}
        if text is None:
            return {"ok": False, "error": "%s is too large to be a definition." % name}

        known = [label for label, _full, _short in platforms.NO_LIBRETRO_PLATFORMS]
        entry, error = await self._run(
            emulator_catalog.imported.save, text, known, replace
        )
        if error:
            return {"ok": False, "error": error}

        # The transfer folder is a staging post, not a store: a definition that
        # has been imported is a duplicate of one the plugin now keeps under
        # `emulators.d`, and leaving it means the Import list grows by one every
        # time somebody uses it and never shrinks. Firmware settled this the same
        # way and for the same reason -- one file in one place.
        #
        # Only after the save succeeded. A definition that was refused is still
        # the user's only copy, and consuming it would leave them with the
        # reasons it was refused and nothing to fix.
        removed = await self._run(_discard, path)
        if not removed:
            # Not a failure: the import happened, and the plugin has its copy.
            # Worth a line because the Import list will go on offering it.
            decky.logger.warning("Imported %s but could not clear it from %s", name, path)

        await self._run(emulator_catalog.reload_imported)
        decky.logger.info("Imported emulator definition %s (%s)", entry["id"], name)
        # The catalog changed, and whoever is looking at it may not be whoever
        # imported it: the transfer dialog can do this with the Emulators tab
        # open behind it. Emitted rather than returned so the list reloads
        # wherever it is, instead of only where the button was pressed.
        await decky.emit("emulator_catalog_changed")
        return {"ok": True, "error": "", "id": entry["id"], "name": entry["name"]}


    async def remove_imported_emulator(self, entry_id: str):
        """Forget a user-supplied definition, and anything it installed.

        The emulator goes first, and it has to: once the definition is gone
        there is no catalog entry, so no row, so no button, and an emulator this
        plugin downloaded would sit in `~/deckyemu/emulators` with nothing able
        to reach it. Removing the definition and leaving the install behind is
        how a hundred megabytes becomes unreachable through the UI that put it
        there.

        The registration goes too. Leaving it would keep the emulator in the
        add-game picker with no entry behind it, which is the state that makes a
        game unlaunchable rather than merely absent.
        """
        entry = emulator_catalog.find(entry_id)
        if entry and not entry.get("imported"):
            return {
                "ok": False,
                "error": "%s is built in, so there is no definition to remove."
                % entry.get("name", entry_id),
            }

        # Uninstall while the entry still exists, and only when something is
        # actually installed -- uninstalling nothing reports a failure, which
        # would block the removal of a definition that never installed anything.
        # A real failure here is reported rather than pressed through: removing
        # the definition anyway is exactly what strands the install.
        kind = (entry or {}).get("source", {}).get("kind", "")
        if kind == "flatpak":
            installed = await self._run(emu_install.flatpak_installed,
                                        entry["source"]["id"])
        elif kind and kind != "byo":
            installed = bool(await self._run(emu_install.installed_appimage, entry_id))
        else:
            installed = False

        if installed:
            result = await self.uninstall_emulator(entry_id)
            if not result.get("ok"):
                return result

        removed, error = await self._run(emulator_catalog.imported.remove, entry_id)
        if not removed:
            return {"ok": False, "error": error}

        await self._run(emulators.remove, entry_id)
        await self._run(emulator_catalog.reload_imported)
        await self._refresh_emulators()
        # Same reason as the import: the catalog is shorter than it was, and a
        # list already on screen should say so.
        await decky.emit("emulator_catalog_changed")
        return {"ok": True, "error": ""}


    async def locate_emulator(self, entry_id: str, path: str):
        """Register a bring-your-own emulator against a binary the user picked.

        The same tail as an install -- system, extensions, arguments and seeded
        settings -- for an emulator this plugin did not and will not install.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "Unknown emulator %r." % entry_id}
        if (entry.get("source") or {}).get("kind") != "byo":
            return {
                "ok": False,
                "error": "%s is installed from here, so it does not need locating."
                % entry["name"],
            }
        if not path or not await self._run(os.path.isfile, path):
            return {"ok": False, "error": "There is no file at %s." % path}

        notice = await self._register_installed_emulator(entry, path)
        return {"ok": not notice, "error": notice, "notice": notice}


    async def tools_status(self):
        """The helper binaries this plugin fetches, and whether they are here.

        Its own section rather than a row under BIOS and firmware, and that is
        not cosmetic: the firmware list makes one promise -- everything on it is
        the user's own dump and is never downloaded -- and a binary fetched from
        somebody else's releases is the exact inverse. Two lists, each able to
        say plainly where its contents come from.
        """
        present = [
            emulator.get("id") for emulator in self._emulators if emulator.get("id")
        ]
        return {"tools": await self._run(emu_install.tools_report, present)}

    async def install_helper_tool(self, name: str):
        """Fetch one tool by name, for the row that offers it."""
        path, error = await self._run(emu_install.install_named_tool, name)
        if error:
            return {"ok": False, "error": error}
        # A launcher names the server it starts, so a tool arriving after games
        # were added reaches none of them until they are rewritten. Same reason
        # the startup fetch does it; here the user pressed the button and would
        # otherwise see nothing change.
        await self.rebuild_launchers()
        return {"ok": True, "path": path}

    async def remove_helper_tool(self, name: str):
        """Delete one tool, and take it back out of the launchers."""
        removed, error = await self._run(emu_install.remove_tool, name)
        if error:
            return {"ok": False, "error": error}
        if removed:
            await self.rebuild_launchers()
        return {"ok": True}

    async def install_emulator(self, entry_id: str):
        """Install a catalog emulator and register it. Progress is streamed."""
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog."}

        if entry["source"]["kind"] == "byo":
            return {
                "ok": False,
                "error": "%s is not installed from here -- point it at a binary "
                         "you already have." % entry["name"],
            }

        if entry["source"]["kind"] == "flatpak":
            steps = await self._run(emu_install.flatpak_install_steps, entry["source"]["id"])
            if not steps:
                return {
                    "ok": False,
                    "error": "flatpak is not available on this system, so %s cannot be "
                    "installed automatically." % entry["name"],
                }
            # Detached through `_detach` rather than create_task: the panel's only
            # way to learn this ended is the done event, so an unexpected failure
            # has to produce one instead of dying into decky's log.
            self._detach(
                self._install_emulator_flatpak(entry, steps),
                "emulator_install_done", entry["id"],
            )
        else:
            self._detach(
                self._install_emulator_appimage(entry),
                "emulator_install_done", entry["id"],
            )

        return {"ok": True, "started": True}


    # ------------------------------------------------------- versions and builds

    async def emulator_builds(self):
        """Which installed emulators can move to a different build, and where they are.

        One flatpak query for what is pending and one for what is held, however
        many emulators there are -- `remote-info` costs about two seconds a call,
        so per emulator would be fourteen seconds to draw a tab.

        AppImage entries answer from the last update check rather than from the
        network, which is why they cost nothing here. `update_state` carries the
        difference: `unknown` until somebody presses the button, and after that
        whatever the check found. Absent from this list still means "not
        installed", which is a third thing again.
        """
        pending = await self._run(emu_install.flatpak_updates)
        held = await self._run(emu_install.flatpak_held)
        # Read once for the whole list rather than per row: it is one small file
        # and the loop below runs over the entire catalog.
        checked = await self._run(emu_install.read_latest_tags)

        rows = []
        # RetroArch first, and included even though it is not in the catalog: it
        # is installed from Flathub exactly as these are, and its own tab has no
        # other way to say a newer build exists. The RetroArch tab picks it out by
        # id; the Emulators tab has no row with that id, so it simply never
        # matches there.
        for entry in (_RETROARCH_ENTRY,) + tuple(emulator_catalog.CATALOG):
            source = entry.get("source") or {}

            if source.get("kind") == "github":
                # Whether a newer release exists is a network call per emulator,
                # and this runs when a tab opens -- so this reads the *last
                # answer* rather than asking again. `check_emulator_updates` is
                # what asks, from a button, and it is the only thing that does.
                path = await self._run(emu_install.installed_appimage, entry["id"])
                if not path:
                    continue
                record = await self._run(emu_install.read_build_record, entry["id"])
                installed = record.get("tag", "")
                published = checked.get(entry["id"]) or ""
                rows.append({
                    "id": entry["id"],
                    "name": entry["name"],
                    "app_id": "",
                    "channel": "github",
                    # Empty for anything installed before the record existed.
                    # Reported as unknown rather than guessed from the filename,
                    # which for two of these three identifies nothing.
                    "build": installed,
                    # Three states, not two. Nobody has checked, this build is
                    # the newest published, or it is not -- and the first is not
                    # a quieter way of saying the second. See
                    # `emu_install.update_state`.
                    "update_state": emu_install.update_state(installed, published),
                    # Nothing outside this plugin updates an AppImage it
                    # downloaded, so there is nothing for a hold to protect
                    # against and none is offered.
                    "held": False,
                    "reason": "",
                })
                continue

            if source.get("kind") != "flatpak":
                continue
            app_id = source.get("id", "")
            if not await self._run(emu_install.flatpak_installed, app_id):
                continue

            scope = await self._run(emu_install.flatpak_scope, app_id)
            commit = await self._run(emu_install.flatpak_installed_commit, app_id)
            rows.append({
                "id": entry["id"],
                "name": entry["name"],
                "app_id": app_id,
                "channel": "flatpak",
                # Shown rather than the full hash, which is 64 characters of
                # nothing anybody can read. The full value stays server-side and
                # in `emulator_build_list`, which is what a rollback quotes back.
                "build": commit[:12],
                # flatpak was asked, above, so this side is never unknown: one
                # `remote-ls --updates` covers every emulator at once, which is
                # exactly what the AppImage side cannot do.
                "update_state": "available" if app_id in pending else "current",
                "held": app_id in held,
                # A system-scope install is root-owned and the plugin cannot
                # answer a password prompt, so the row says why instead of
                # showing a button that can only fail -- the same rule
                # `can_uninstall_retroarch` follows.
                "reason": (
                    "" if scope == "user"
                    else "Installed system-wide, so changing its version needs a password "
                         "this plugin cannot give."
                ),
            })
        return rows

    async def check_emulator_updates(self):
        """Ask each installed AppImage emulator's project what it has published.

        **The only thing that makes this network call, and it is never made on
        the way to drawing something.** One call per installed AppImage emulator
        -- four entries in the catalog install from a release, so at worst four
        -- against other people's repositories, and a tab that did this on open
        would spend somebody's rate limit every time they walked past it.

        Flatpak emulators are not asked. `flatpak_updates` already answers for
        all of them in one query, cheaply enough that `emulator_builds` does it
        on open, so there is nothing here for them to gain.

        Returns {ok, checked, available, error}. A repository that could not be
        reached leaves its previous answer alone rather than overwriting it with
        an empty one -- a failed check should cost the row nothing, and blanking
        it would turn "there is an update" back into "nobody knows".
        """
        tags = await self._run(emu_install.read_latest_tags)
        checked = 0
        available = 0
        failures = []

        for entry in emulator_catalog.CATALOG:
            source = entry.get("source") or {}
            if source.get("kind") != "github":
                continue
            if not await self._run(emu_install.installed_appimage, entry["id"]):
                continue

            tag, error = await self._run(emu_install.latest_tag, entry)
            if not tag:
                failures.append(entry["name"])
                decky.logger.warning(
                    "Could not check %s for updates: %s", entry["id"], error
                )
                continue

            checked += 1
            tags[entry["id"]] = tag
            record = await self._run(emu_install.read_build_record, entry["id"])
            if emu_install.update_state(record.get("tag", ""), tag) == "available":
                available += 1

        await self._run(emu_install.write_latest_tags, tags)

        # Named, not counted. "1 emulator could not be checked" sends the reader
        # to open four dialogs to find out which; the name is the whole of what
        # makes the sentence actionable, and there are never more than a few.
        error = ""
        if failures:
            error = "Could not reach %s." % ", ".join(failures)

        return {
            "ok": True,
            "checked": checked,
            "available": available,
            "error": error,
        }

    async def emulator_build_list(self, entry_id: str):
        """Past builds of one emulator, newest first, for going back to.

        Costs a network round trip, so it is asked for when somebody opens the
        list rather than for every row of the tab.
        """
        entry = _RETROARCH_ENTRY if entry_id == "retroarch" else emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog.", "builds": []}
        source = entry.get("source") or {}

        if source.get("kind") == "github":
            releases, error = await self._run(
                emu_install.resolve_release_list,
                source["repo"], source["asset"], source.get("host", ""),
            )
            if error:
                return {"ok": False, "error": error, "builds": []}
            record = await self._run(emu_install.read_build_record, entry["id"])
            installed = record.get("tag", "")
            return {
                "ok": True,
                "error": "",
                # Shaped like the flatpak builds so one dialog renders both. The
                # tag stands in for the commit, `published` for the date, and the
                # download size is known here without a second call -- the release
                # listing carries it.
                "builds": [
                    {
                        "commit": release["tag"],
                        "date": release["published"],
                        # The tag, not the asset name. `subject` is the row's
                        # human label -- a commit message for a flatpak build --
                        # and every release here carries the same filename, so
                        # naming the asset printed `Vita3K-x86_64.AppImage`
                        # twelve times and never said which build any of them
                        # was. Harmless while every Vita3K release was tagged
                        # `continuous`; useless the moment they were numbered.
                        "subject": release["tag"],
                        "size": release["size"],
                        "prerelease": release["prerelease"],
                        # False for every row when nothing was recorded, which is
                        # honest: an install predating the record cannot be
                        # matched to a release, and marking one "current" on a
                        # guess would hide the build actually in use.
                        "current": bool(installed) and release["tag"] == installed,
                    }
                    for release in releases
                ],
            }

        if source.get("kind") != "flatpak":
            return {
                "ok": False,
                "error": "%s is not installed from Flathub, so its past builds are not "
                         "listed here." % entry["name"],
                "builds": [],
            }

        builds = await self._run(emu_install.flatpak_history, source["id"])
        if not builds:
            return {
                "ok": False,
                "error": "No build history came back for %s. It needs the network."
                         % entry["name"],
                "builds": [],
            }
        current = await self._run(emu_install.flatpak_installed_commit, source["id"])
        for build in builds:
            build["current"] = build["commit"] == current
        return {"ok": True, "builds": builds}

    async def emulator_build_details(self, entry_id: str, commit: str):
        """What flatpak knows about one build, for the row that asked.

        A call per build, made when somebody opens a row rather than for the
        whole list -- twelve of these to draw a dialog would be twenty seconds.

        There is no changelog behind this. A Flathub commit carries a one-line
        subject describing a packaging change and nothing more, so what is worth
        showing is the subject in full plus the facts the list has no room for --
        and `download` above all, since switching build re-fetches the entire
        app and that is a few hundred megabytes on a handheld.
        """
        entry = _RETROARCH_ENTRY if entry_id == "retroarch" else emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog.", "details": {}}
        source = entry.get("source") or {}
        if source.get("kind") != "flatpak":
            return {"ok": False, "error": "That emulator has no Flathub builds.", "details": {}}
        if not emu_install.valid_commit(commit):
            return {"ok": False, "error": "That is not a build.", "details": {}}

        details = await self._run(emu_install.flatpak_build_details, source["id"], commit)
        if not details:
            return {
                "ok": False,
                "error": "Could not read that build. It needs the network.",
                "details": {},
            }
        return {"ok": True, "error": "", "details": details}

    async def update_emulator(self, entry_id: str):
        """Move an emulator to the newest build on its remote. Streams progress."""
        appimage = self._appimage_entry(entry_id)
        if appimage:
            # An empty tag means "whatever is newest", which is what the install
            # path already resolves.
            return await self._start_appimage_build(appimage, "")

        entry, app_id, error = await self._flatpak_entry(entry_id)
        if error:
            return {"ok": False, "error": error}

        argv = await self._run(emu_install.flatpak_update_argv, app_id)
        if not argv:
            return {"ok": False, "error": "flatpak is not available on this system."}

        self._detach(
            self._change_emulator_build(entry, [argv], "Updating"),
            "emulator_build_done", entry["id"],
        )
        return {"ok": True, "started": True}

    async def rollback_emulator(self, entry_id: str, commit: str):
        """Put an emulator back on a past build, and hold it there.

        Held as part of the same action rather than as a second button, because a
        downgrade that is not held is undone by the next update -- and the person
        it is undone for has no way to connect a game that broke a week later to
        an update they did not ask for. Releasing the hold is its own control, so
        the state is visible and reversible; it is being *silently* moved that is
        the problem.
        """
        appimage = self._appimage_entry(entry_id)
        if appimage:
            # `commit` carries a release tag here. One parameter for "which
            # build", because from the panel's side it is one question.
            if not emu_install.valid_tag(commit):
                return {"ok": False, "error": "That is not a build this can move to."}
            return await self._start_appimage_build(appimage, commit)

        entry, app_id, error = await self._flatpak_entry(entry_id)
        if error:
            return {"ok": False, "error": error}
        # Pure, so not worth an executor round trip.
        if not emu_install.valid_commit(commit):
            return {"ok": False, "error": "That is not a build this can move to."}

        argv = await self._run(emu_install.flatpak_downgrade_argv, app_id, commit)
        if not argv:
            return {"ok": False, "error": "flatpak is not available on this system."}

        self._detach(
            # Held after the move, not before: masking first can stop flatpak
            # deploying the very commit it was asked for, and a hold on a version
            # that was never reached is the worst of both outcomes.
            self._change_emulator_build(entry, [argv], "Going back", hold_after=True),
            "emulator_build_done", entry["id"],
        )
        return {"ok": True, "started": True}

    async def hold_emulator(self, entry_id: str, held: bool = True):
        """Pin an emulator at its current build, or let it move again."""
        entry, app_id, error = await self._flatpak_entry(entry_id)
        if error:
            return {"ok": False, "error": error}

        ok, reason = await self._run(emu_install.flatpak_hold, app_id, bool(held))
        if not ok:
            return {"ok": False, "error": reason}
        # Read back rather than assumed: this is the state a row displays, and a
        # mask that did not take would otherwise show as held forever.
        return {
            "ok": True,
            "held": app_id in await self._run(emu_install.flatpak_held),
        }

    @staticmethod
    def _appimage_entry(entry_id):
        """The catalog entry when this emulator is an AppImage, else None.

        `retroarch` is never one: it is the reserved id for the Flathub app, and
        an AppImage RetroArch is one this plugin did not install and will not
        move.
        """
        if entry_id == "retroarch":
            return None
        entry = emulator_catalog.find(entry_id)
        if not entry or (entry.get("source") or {}).get("kind") != "github":
            return None
        return entry

    async def _start_appimage_build(self, entry, tag):
        """Download a specific release of an AppImage emulator, or the newest.

        Nothing is held afterwards, unlike the flatpak path, and nothing needs to
        be: an AppImage this plugin downloaded is one only this plugin updates.
        There is no Discover, no `flatpak update`, nothing else on the device that
        knows the file exists -- so a build stays where it was put until somebody
        asks for another.
        """
        if not await self._run(emu_install.installed_appimage, entry["id"]):
            return {"ok": False, "error": "%s is not installed." % entry["name"]}

        self._detach(
            self._change_appimage_build(entry, tag),
            "emulator_build_done", entry["id"],
        )
        return {"ok": True, "started": True}

    async def _change_appimage_build(self, entry, tag):
        """Resolve a release, download it over the old one, and re-register.

        Re-registered afterwards, which the flatpak path deliberately does not
        do -- and the difference is not an inconsistency. A flatpak's launch
        command is the same whatever version is deployed; an AppImage's is a path
        to a file whose name carries the version, so a build change that did not
        rewrite the registration would leave every game pointing at a binary that
        is no longer there.
        """
        source = entry["source"]
        try:
            await decky.emit(
                "emulator_build_progress", entry["id"],
                "Looking up %s" % (tag or "the newest release"), -1,
            )

            if tag:
                releases, error = await self._run(
                    emu_install.resolve_release_list,
                    source["repo"], source["asset"], source.get("host", ""),
                )
                asset = None
                if not error:
                    match = next((r for r in releases if r["tag"] == tag), None)
                    if match is None:
                        error = "That build is no longer published."
                    else:
                        asset = {"name": match["name"], "url": match["url"],
                                 "tag": match["tag"], "size": match["size"]}
            else:
                asset, error = await self._run(
                    emu_install.resolve_release_asset,
                    source["repo"], source["asset"], source.get("host", ""),
                )

            if error or not asset:
                await decky.emit("emulator_build_done", entry["id"], False,
                                 error or "No download was found.")
                return

            loop = self.loop
            last = [-1]

            def on_progress(done, total):
                if not total:
                    return
                percent = int(done * 100 / total)
                # One event per whole percent, as the install does: a 90MB
                # download at 256KB a chunk is ~360 callbacks and the panel
                # cannot use that many.
                if percent == last[0]:
                    return
                last[0] = percent
                asyncio.run_coroutine_threadsafe(
                    decky.emit(
                        "emulator_build_progress", entry["id"],
                        "Downloading %s" % asset["name"], percent,
                    ),
                    loop,
                )

            path, error = await self._run(
                emu_install.install_appimage, entry, asset, on_progress
            )
            if error:
                await decky.emit("emulator_build_done", entry["id"], False, error)
                return

            notice = await self._register_installed_emulator(entry, path)
            await decky.emit("emulator_build_done", entry["id"], True, notice)
        except OSError as error:
            decky.logger.exception("Changing the build of %s failed", entry["id"])
            await decky.emit("emulator_build_done", entry["id"], False, str(error))

    async def _flatpak_entry(self, entry_id):
        """(entry, app_id, error) for an installed user-scope flatpak emulator.

        `retroarch` is accepted as well as a catalog id. RetroArch is not in the
        catalog -- it is the thing cores run inside rather than one of them -- but
        it is a Flathub app installed the same way, so updating it, going back and
        holding it are the same three operations on a different id. Shaped as a
        catalog entry here so there is one implementation rather than a parallel
        set of RetroArch endpoints that would drift from it.
        """
        entry = _RETROARCH_ENTRY if entry_id == "retroarch" else emulator_catalog.find(entry_id)
        if not entry:
            return None, "", "That emulator is not in the catalog."
        source = entry.get("source") or {}
        if source.get("kind") != "flatpak":
            return None, "", (
                "%s is not installed from Flathub, so its version cannot be changed "
                "from here." % entry["name"]
            )
        app_id = source.get("id", "")
        scope = await self._run(emu_install.flatpak_scope, app_id)
        if scope == "system":
            return None, "", (
                "%s was installed system-wide, so changing its version needs a "
                "password this plugin cannot give." % entry["name"]
            )
        if scope != "user":
            return None, "", "%s is not installed." % entry["name"]
        return entry, app_id, ""

    async def _change_emulator_build(self, entry, steps, label, hold_after=False):
        """Update or roll back, reporting on the same events an install uses.

        Deliberately does not re-register the emulator afterwards. A flatpak's
        launch command does not change with its version, so there is nothing to
        rewrite -- and re-registering would overwrite launch arguments somebody
        corrected by hand in the editor, which is a worse outcome than anything
        this was asked to fix.
        """
        app_id = entry["source"]["id"]
        try:
            await decky.emit(
                "emulator_build_progress", entry["id"], "%s %s" % (label, entry["name"]), -1
            )
            ok, reason = await self._stream_flatpak(
                entry["id"], steps, must_succeed=("update",)
            )
            if not ok:
                await decky.emit("emulator_build_done", entry["id"], False, reason)
                return

            notice = ""
            if hold_after:
                # Reported, not assumed. An unheld rollback is undone by the next
                # update, so "went back but could not hold it" is a different
                # outcome from success and has to say so -- otherwise the version
                # moves again later and nothing connects the two.
                held, hold_error = await self._run(emu_install.flatpak_hold, app_id, True)
                if not held:
                    notice = (
                        "Moved to that build, but it could not be held there, so an "
                        "update may move it again: %s" % hold_error
                    )

            build = await self._run(emu_install.flatpak_installed_commit, app_id)
            decky.logger.info("%s is now on %s", entry["id"], build[:12] or "an unknown build")
            await decky.emit("emulator_build_done", entry["id"], True, notice)
        except OSError as error:
            decky.logger.exception("Changing the build of %s failed", entry["id"])
            await decky.emit("emulator_build_done", entry["id"], False, str(error))

    async def _stream_flatpak(self, entry_id, steps, must_succeed=("install",)):
        """Run flatpak commands in order, streaming their output as progress.

        Returns (ok, reason). Shared by installing, updating and going back to a
        past build, which are the same operation to flatpak and differ here only
        in which verb is allowed to fail: `remote-add` is expected to when the
        remote already exists, while an `install` or `update` that fails is the
        whole answer.

        Progress goes out on `emulator_install_progress` for all three, because
        the panel draws one bar and does not care which verb is filling it.
        """
        env = self._subprocess_env()
        for argv in steps:
            decky.logger.info("Running: %s", " ".join(argv))
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                )
            except (OSError, NotImplementedError) as error:
                decky.logger.exception("Could not start %s", argv[0])
                return False, "Could not run flatpak: %s" % error

            output = procout.Output()
            async for text in output.segments(process.stdout):
                decky.logger.info("flatpak: %s", text)
                await decky.emit(
                    "emulator_install_progress",
                    entry_id,
                    text,
                    self._parse_percent(text),
                )

            code = await process.wait()
            if code != 0 and any(verb in argv for verb in must_succeed):
                # The last lines are where flatpak puts the reason; the exit code
                # alone has cost a debugging round before.
                return False, "flatpak exited with code %d: %s" % (code, output.reason)

        return True, ""

    async def _install_emulator_flatpak(self, entry, steps):
        try:
            ok, reason = await self._stream_flatpak(entry["id"], steps)
            if not ok:
                await decky.emit("emulator_install_done", entry["id"], False, reason)
                return

            if not await self._run(emu_install.flatpak_installed, entry["source"]["id"]):
                await decky.emit(
                    "emulator_install_done", entry["id"], False,
                    "flatpak reported success but %s was still not found." % entry["name"],
                )
                return

            notice = await self._register_installed_emulator(entry, entry["source"]["id"])
            await decky.emit("emulator_install_done", entry["id"], True, notice)
        # Not CancelledError: this runs detached, and `_detach` re-raises a
        # cancellation rather than swallowing it into an emit over a socket that
        # is closing. Everything unexpected is reported there too.
        except OSError as error:
            decky.logger.exception("Installing %s failed", entry["id"])
            await decky.emit("emulator_install_done", entry["id"], False, str(error))


    async def _install_emulator_appimage(self, entry):
        source = entry["source"]
        await decky.emit(
            "emulator_install_progress", entry["id"], "Looking up the latest release", -1
        )

        # `host` is empty for a project on GitHub and set for one that left it,
        # whose old repository answers 451 there rather than 404 -- so no asset
        # pattern reaches it and only the address can differ.
        asset, error = await self._run(
            emu_install.resolve_release_asset,
            source["repo"], source["asset"], source.get("host", ""),
        )
        if error:
            await decky.emit("emulator_install_done", entry["id"], False, error)
            return

        # Progress arrives from a worker thread, so the emit has to be handed
        # back to the loop rather than awaited where it is produced.
        loop = self.loop
        last = [-1]

        def on_progress(done, total):
            if not total:
                return
            percent = int(done * 100 / total)
            # One event per whole percent: a 90MB download at 256KB a chunk is
            # ~360 callbacks, and the panel cannot use that many.
            if percent == last[0]:
                return
            last[0] = percent
            asyncio.run_coroutine_threadsafe(
                decky.emit(
                    "emulator_install_progress",
                    entry["id"],
                    "Downloading %s" % asset["name"],
                    percent,
                ),
                loop,
            )

        path, error = await self._run(emu_install.install_appimage, entry, asset, on_progress)
        if error:
            await decky.emit("emulator_install_done", entry["id"], False, error)
            return

        notice = await self._register_installed_emulator(entry, path)
        await decky.emit("emulator_install_done", entry["id"], True, notice)


    async def _register_installed_emulator(self, entry, target):
        """Turn a freshly installed emulator into a selectable one.

        This is the whole payoff: the emulator appears in the add-game picker
        with the right system, extensions and arguments without the user typing
        any of them. Failing here means the emulator is on the device but
        invisible, so it is reported rather than swallowed.
        """
        # On every exit, including the ones that report the install as only
        # half-registered. Every launcher of this emulator names the binary to
        # exec, and which binary that is can change on an install without the
        # emulator's own path changing at all: a workaround that patches picks a
        # build beside the stock one, and whether that build exists is decided
        # by whether the release just downloaded still fits the patch.
        #
        # Without this, an update the patch no longer fits deletes the file
        # every launcher names and every game of that emulator stops starting --
        # the exact opposite of the guarantee, which is that a refused patch
        # costs the fix and never the emulator. The files on disk have already
        # changed by the time this runs, so rebuilding is right whether or not
        # anything below succeeded.
        try:
            return await self._register_emulator_record(entry, target)
        finally:
            await self.rebuild_launchers()

    async def _register_emulator_record(self, entry, target):
        """The registration itself. See `_register_installed_emulator`."""
        extensions = await self._run(installer.database_extensions)
        definition = await self._run(emulator_catalog.to_emulator, entry, target, extensions)
        # This install came from wherever `source` names now, so whatever was
        # said about the old one is finished. Both flags, because a user who
        # never saw the message still gets a clean record out of updating.
        definition["stale_source"] = False
        definition["source_notice_shown"] = False

        # An update is not a new install. `to_emulator` records the catalog's
        # *defaults* for the corrections, which is right for a first install and
        # wrong for every later one: it threw away whatever the user had chosen,
        # so updating an emulator silently switched motion back off. `save`
        # cannot rescue it either -- it carries a key only when the caller sends
        # nothing, and this caller sends the defaults.
        previous = await self._run(emulators.find, entry["id"])
        if previous and previous.get("workarounds_off") is not None:
            definition["workarounds_off"] = previous["workarounds_off"]

        if not definition["extensions"]:
            return (
                "%s was installed, but the libretro catalog could not be read, so its "
                "file extensions are unknown. Open it in the editor and add them."
                % entry["name"]
            )

        saved, error = await self._run(emulators.save, definition)
        if error:
            return "%s was installed but could not be registered: %s" % (entry["name"], error)

        await self._refresh_emulators()
        decky.logger.info(
            "Registered %s for %s (%d extensions)",
            saved["name"],
            emulator_catalog.system_label(entry) or saved.get("platform_full"),
            len(saved["extensions"]),
        )

        # Before anything else, because it is not configuration -- it is the
        # package being incomplete, and Supermodel does not reach its first
        # frame without it. See `emu_install.seed_bundled_files`.
        _seeded, seed_error = await self._run(
            emu_install.seed_bundled_files,
            (entry.get("source") or {}).get("id", ""),
            entry.get("seed"),
        )
        if seed_error:
            return "%s was installed, but files it needs could not be placed: %s" % (
                entry["name"], seed_error)

        # Some emulators are not playable as they ship -- Azahar binds a
        # keyboard and starts windowed -- so the recommended settings go in
        # here, while it is certainly not running and cannot save over them.
        #
        # First the emulator writes its own config, because settings written
        # into a file it has never made do not survive its first run.
        # Motion, for the emulators that reach the Deck's gyro over a socket.
        # Fetched here rather than at first launch: the launcher names the
        # binary when it is written, so a server arriving after a game was
        # added reaches that game only when its launcher is rewritten.
        _server, motion_error = await self._run(emu_install.ensure_motion_server, entry)
        if motion_error:
            # Never fatal. The emulator is installed and every game will run;
            # what is missing is gyro, in an emulator that has never had it.
            decky.logger.warning(
                "Could not fetch the motion server for %s: %s", entry["id"], motion_error
            )

        await self._prime_emulator_config(entry, saved)
        result = await self._run(emu_config.apply_setup, entry)
        if not result.get("ok"):
            return "%s was installed, but its settings could not be written: %s" % (
                entry["name"],
                result.get("error", ""),
            )
        return ""


    #: What makes a windowed emulator start, write its config and stop trying.
    #:
    #: Qt gets `offscreen`, SDL gets `dummy`. Between them nothing needs a
    #: display, so the emulator runs far enough to write its defaults and then
    #: has nothing to show. Measured rather than assumed: DuckStation with these
    #: two set authored a complete 8392-byte `settings.ini` -- `SettingsVersion
    #: = 3`, `SetupWizardIncomplete = true` -- before the timeout stopped it.
    _OFFSCREEN = {"QT_QPA_PLATFORM": "offscreen", "SDL_VIDEODRIVER": "dummy"}

    #: The second attempt, for an emulator whose Qt build ships only the `xcb`
    #: platform plugin: `offscreen` is not among its options, so it aborts
    #: before writing anything -- Azahar's AppImage prints "Available platform
    #: plugins are: xcb" and dumps core. gamescope's headless backend gives it
    #: a real display with no output attached, and under that same AppImage
    #: wrote its whole 32658-byte config. Already on every Deck; it is what
    #: Game Mode itself runs.
    _HEADLESS_WRAPPER = ("gamescope", "--backend", "headless", "--")

    #: Long enough for an emulator to reach the point where it writes its
    #: config, which every one measured does during startup. It is never long
    #: enough for the emulator to *finish*, because it is being asked to start
    #: with nowhere to draw -- so a timeout here is the expected ending, not a
    #: failure, and what actually happened is judged from the file.
    _PRIME_SECONDS = 25

    async def _prime_emulator_config(self, entry, emulator):
        """Make an emulator write its own config before this plugin edits it.

        Recommended settings used to go into a file that did not exist, so the
        plugin authored it. That does not work, and the way it fails is the
        worst one available: the emulator does not recognise a config it did not
        write -- DuckStation checks `SettingsVersion`, Azahar checks
        `firstStart` -- so its first run regenerates the file from its own
        defaults and the settings vanish. The first launch of the first game is
        exactly when that lands: a setup wizard no gamepad can dismiss, or a
        3DS game with the controls unbound, on an install the plugin reported
        configuring correctly. Repairing it afterwards, which this plugin now
        also does, still costs the user that launch -- and a first launch that
        looks broken is indistinguishable from a plugin that is.

        So the emulator is started once here, with nowhere to draw, and left to
        write its own config. What follows then merges into a file it made
        itself, which is the case that has always worked.

        Best effort by design. Some emulators refuse to start without a real
        display and write nothing -- GTK ones especially -- and for those this
        changes nothing: `apply_setup` authors the file as before and the
        repair on the next panel open catches what the first run undoes.
        """
        setup = entry.get("setup")
        if not await self._run(emu_config.needs_priming, entry):
            return False

        # "Not there" and "there because we put it there" both land here, and
        # the second is why reinstalling an emulator did not help: `flatpak
        # uninstall` leaves `~/.var/app/<id>` alone, so the config survives the
        # emulator and the next install saw a file and asked for nothing.
        decky.logger.info(
            "Letting %s write its own config first", entry["id"]
        )
        # Two attempts, cheapest first, and the second one drops the offscreen
        # environment rather than keeping it. That is not tidiness: an emulator
        # reaches the second attempt *because* it has no offscreen platform to
        # use, so asking again for one under gamescope fails identically. Azahar
        # did exactly that -- gamescope came up, its headless backend and
        # XWayland started, and the AppImage was gone a second later, logged as
        # "Primary child shut down!" and reported as an emulator that writes no
        # config. Under gamescope there is a real display; the point is that
        # nothing is attached to the other end of it.
        for wrapper, environment in (
            ((), self._OFFSCREEN),
            (self._HEADLESS_WRAPPER, None),
        ):
            await self._run_emulator_tool(
                emulator, [], seconds=self._PRIME_SECONDS,
                env_overrides=environment, wrapper=wrapper,
            )
            if not await self._run(emu_config.missing_files, setup):
                break

        left = await self._run(emu_config.missing_files, setup)
        if left:
            decky.logger.warning(
                "%s wrote no config with no display; settings will be written into a "
                "new file and re-applied after its first run (%s)",
                entry["id"], ", ".join(left),
            )
            return False
        decky.logger.info("%s wrote its own config; applying settings into it", entry["id"])
        return True

    async def register_emulator(self, entry_id: str):
        """Register a catalog emulator that is already on the device.

        Installing and registering are two different things, and they come apart
        constantly: Discover installs exactly these flatpaks, so do the usual
        emulation setup scripts, and anyone who set one up before finding this
        plugin already has it. In every case the catalog row showed "installed"
        with only a Remove button, so there was no way to reach the registration
        -- and without that the emulator has no extensions and never appears when
        adding a game.

        Same work as the tail of an install, so an emulator registered this way
        gets the same system, extensions, arguments and settings as one this
        plugin installed itself.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "Unknown emulator %r." % entry_id}

        source = entry["source"]
        if source["kind"] == "flatpak":
            target = source["id"]
            present = await self._run(emu_install.flatpak_installed, target)
        else:
            target = await self._run(emu_install.installed_appimage, entry_id)
            present = bool(target)

        if not present:
            return {
                "ok": False,
                "error": "%s is not installed, so there is nothing to register."
                % entry["name"],
            }

        notice = await self._register_installed_emulator(entry, target)
        return {"ok": not notice, "error": notice, "notice": notice}


    async def uninstall_emulator(self, entry_id: str, delete_data: bool = False):
        """Remove a catalog emulator and forget its registration.

        Games already added to Steam keep their launcher scripts, exactly as with
        RetroArch: reinstalling makes every one of them work again, and deleting
        them here would be an unrelated irreversible act behind a button that
        does not say so.

        `delete_data` is the emulator's own directory -- saves, configuration,
        memory cards, whatever it unpacked into itself -- and it is off unless
        the person removing it said otherwise. It applies to a flatpak, which is
        the kind whose data outlives it: `flatpak uninstall` leaves
        `~/.var/app/<id>` alone, so a reinstall inherits the last install's
        state, which is how an emulator comes back with a config nobody wanted.
        An AppImage keeps its data in ordinary folders and is untouched by this;
        the catalog knows where they are, but deleting them is not wired up and
        pretending otherwise would be worse than the gap.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "That emulator is not in the catalog."}

        if entry["source"]["kind"] == "flatpak":
            app_id = entry["source"]["id"]
            scope = await self._run(emu_install.flatpak_scope, app_id)
            if scope == "system":
                return {
                    "ok": False,
                    "error": "%s was installed system-wide, most likely by EmuDeck or "
                    "Discover. Removing it needs root, which the plugin cannot supply."
                    % entry["name"],
                }

            removed = await self._flatpak_uninstall(app_id, bool(delete_data))
            if not removed["ok"]:
                return removed
        else:
            removed, error = await self._run(emu_install.remove_appimage, entry_id)
            if not removed:
                return {"ok": False, "error": error}

        # The registration goes whether or not it was there, so a half-removed
        # state cannot leave an emulator selectable with nothing behind it.
        await self._run(emulators.remove, entry_id)
        await self._refresh_emulators()
        return {"ok": True}


    async def _flatpak_uninstall(self, app_id, delete_data=False):
        """Run `flatpak uninstall` for one application id.

        `--delete-data` additionally needs the session bus, which
        `_subprocess_env` supplies for every flatpak run for exactly this
        reason -- without it the application goes and its data silently stays.

        The argv is built here because only this side knows the id; running it
        and reading its output is `_run_flatpak` on the composed Plugin, which
        the RetroArch removal shares. That sharing is the point rather than a
        tidiness preference -- see its docstring for the three copies this had
        and what each of them got wrong.

        Two recoveries after it runs, and between them they are the way out of a
        removal that could never work. Nothing installed is success: the button
        exists to end up without the emulator, and answering "no installed refs
        found" as a failure told somebody their removal had failed while showing
        them the emulator was still there. And whatever flatpak disowned is
        swept, because that leftover is what made the row claim an install in
        the first place -- without it the button unsticks but the row does not,
        and two full deploys stay on the disk.
        """
        argv = await self._run(emu_install.flatpak_uninstall_argv, app_id, delete_data)
        if not argv:
            return {"ok": False, "error": "flatpak is not available on this system."}

        result = await self._run_flatpak(argv)
        if not result.get("ok") and emu_install.nothing_to_uninstall(result.get("error")):
            decky.logger.info("%s was already gone; treating the removal as done", app_id)
            result = {"ok": True}
        if result.get("ok"):
            await self._run(emu_install.remove_flatpak_husk, app_id)
        return result


    async def prepare_emulator_gui(self, entry_id: str):
        """Write the launcher that opens an emulator's interface, for Steam.

        Several emulators will only do certain jobs through their own windows:
        RPCS3 installs PS3 firmware and PKG games that way, Ryujinx imports
        Switch firmware. There is no command line equivalent -- RPCS3's
        --installfw opens a modal dialog and waits forever -- and a window is
        only ever composited if Steam launched the process, so running it from
        the plugin shows nothing at all. A Steam shortcut is the only door.

        Returns the same fields as `prepare_shortcut`, plus any shortcut already
        made for this emulator so pressing the button twice reuses it.
        """
        entry = emulator_catalog.find(entry_id)
        if not entry:
            return {"ok": False, "error": "Unknown emulator %r." % entry_id}

        emulator = await self._run(emulators.find, emulators.emulator_id(entry_id))
        if not emulator:
            return {
                "ok": False,
                "error": "%s is not set up yet. Install or register it first."
                % entry["name"],
            }

        try:
            script = await self._run(launchers.write_gui_launcher, emulator, entry["name"])
        except OSError as error:
            decky.logger.exception("Failed writing GUI launcher")
            return {"ok": False, "error": "Could not write launcher script: %s" % error}

        # Refreshed every time rather than once at setup, because a package
        # sent after the emulator was configured still has to show up in the
        # picker the next time it opens.
        if entry_id == "rpcs3":
            await self._run(ps3_games.stage_packages, fileserver.default_dir())

        settings = await self._run(store.get_settings)
        return {
            "ok": True,
            # One name for one shortcut. It used to be "<emulator> (setup)", one
            # per emulator, which put a permanent library entry there for
            # something opened once to install firmware. This is repointed at
            # whichever emulator is being opened and hidden from the library, so
            # the name only has to be findable if hiding fails.
            "title": launchers.SETUP_SHORTCUT_TITLE,
            "exe": script,
            "start_dir": os.path.dirname(script),
            "app_id": int(settings.get("setup_app_id") or 0),
        }


    async def record_setup_shortcut(self, app_id: int):
        """Remember the one shortcut used to open any emulator's own window."""
        await self._run(store.set_settings, {"setup_app_id": int(app_id or 0)})
        return {"ok": True}


    async def suggest_launch_options(self, target: str):
        """Likely rom arguments and fullscreen switch, offered as defaults.

        Suggested together because they interact: a flag before a positional ROM
        path can swallow it, so some emulators need an explicit -g as soon as any
        other argument is present.
        """
        return await self._run(emulators.suggest_launch_options, target)


    async def save_emulator(self, emulator: dict):
        emulator = emulator or {}
        notice = ""

        # A browser-downloaded AppImage has no execute bit, which makes the game
        # exit instantly with nothing to show why. Fix it before saving so the
        # emulator is never registered in a state that cannot launch.
        if emulator.get("kind") == "path":
            ok, changed, exec_error = await self._run(
                emulators.ensure_executable, (emulator.get("target") or "").strip()
            )
            if not ok:
                return {"ok": False, "error": exec_error}
            if changed:
                notice = "That file was not executable, so the execute bit was added."

        saved, error = await self._run(emulators.save, emulator)
        if error:
            return {"ok": False, "error": error}
        await self._refresh_emulators()
        return {"ok": True, "emulator": saved, "notice": notice}


    async def list_workarounds(self, emulator_id: str):
        """The corrections this emulator carries, and whether each is on.

        Almost every emulator has none -- see `schema.WORKAROUND_FIELDS` for
        what makes one -- so this is empty for all but the two with motion, and
        the panel shows nothing at all for the rest.
        """
        emulator = await self._run(emulators.find, emulator_id)
        if not emulator:
            return {"ok": False, "error": "That emulator is no longer registered."}
        # A catalog install keeps the entry's own id, which is the only way
        # back to it -- nothing stores the pairing. A hand-registered
        # emulator matches nothing and has no corrections, which is an empty
        # list rather than an error.
        entry = emulator_catalog.find(emulator_id)
        if not entry:
            return {"ok": True, "workarounds": []}
        return {
            "ok": True,
            "workarounds": emulator_catalog.workaround_state(
                entry, emulator.get("workarounds_off") or (),
                await self._run(_unavailable_fixes, entry, emulator),
                await self._run(emu_install.installed_build, entry)),
        }

    async def set_workaround(self, emulator_id: str, workaround_id: str, enabled: bool):
        """Switch one correction on or off, and rewrite what depends on it.

        Both halves matter. The emulator record carries the choice, and every
        launcher already written has the old environment baked into its argv --
        so without the rebuild the setting would appear to take and change
        nothing until each game was re-added.
        """
        emulator = await self._run(emulators.find, emulator_id)
        if not emulator:
            return {"ok": False, "error": "That emulator is no longer registered."}
        entry = emulator_catalog.find(emulator_id)
        if not entry:
            return {"ok": False, "error": "That emulator has nothing to configure."}
        if workaround_id not in {
            item.get("id") for item in emulator_catalog.workarounds_for(entry)
        }:
            return {"ok": False, "error": "No such setting for this emulator."}

        off = set(emulator.get("workarounds_off") or ())
        off.discard(workaround_id) if enabled else off.add(workaround_id)
        emulator["workarounds_off"] = sorted(off)

        effective = emulator_catalog.resolve_workarounds(entry, emulator["workarounds_off"])
        emulator["env"] = dict(effective.get("env") or {})
        emulator["layout"] = effective.get("layout", "")

        saved, error = await self._run(emulators.save, emulator)
        if error:
            return {"ok": False, "error": error}
        await self._refresh_emulators()
        # The launchers carry the old argv until they are written again.
        await self.rebuild_launchers()
        return {"ok": True, "emulator": saved}

    async def remove_emulator(self, emulator_id: str):
        removed = await self._run(emulators.remove, emulator_id)
        await self._refresh_emulators()
        if not removed:
            return {"ok": False, "error": "That emulator is no longer registered."}
        return {"ok": True}
