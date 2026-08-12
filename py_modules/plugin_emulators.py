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
import re

import decky

import plugin_base

import emu_config
import emu_install
import emulator_catalog
import emulators
import fileserver
import installer
import launchers
import platforms
import ps3_games
import store


def _read_text(path, limit):
    """The file's text, or None when it is larger than `limit`."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(limit + 1)
    return None if len(text) > limit else text


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
        sent = await self._run(fileserver.received_files)
        match = next((item for item in sent if item["name"] == name), None)
        if not match:
            return {"ok": False, "error": "%s is not in the transfer folder." % name}

        try:
            text = await self._run(_read_text, match["path"],
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
        sent = await self._run(fileserver.received_files)
        match = next((item for item in sent if item["name"] == name), None)
        if not match:
            return {"ok": False, "error": "%s is not in the transfer folder." % name}

        try:
            text = await self._run(_read_text, match["path"],
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

        await self._run(emulator_catalog.reload_imported)
        decky.logger.info("Imported emulator definition %s (%s)", entry["id"], name)
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


    async def _install_emulator_flatpak(self, entry, steps):
        env = self._subprocess_env()
        try:
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
                    await decky.emit(
                        "emulator_install_done", entry["id"], False,
                        "Could not run flatpak: %s" % error,
                    )
                    return

                # Same buffering as the RetroArch install: flatpak redraws its
                # progress line with carriage returns, and a percentage split
                # across two reads yields a nonsense number.
                tail = []
                buffer = ""
                while True:
                    chunk = await process.stdout.read(256)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    segments = re.split(r"[\r\n]+", buffer)
                    buffer = segments.pop()
                    for segment in segments:
                        text = segment.strip()
                        if not text:
                            continue
                        decky.logger.info("flatpak: %s", text)
                        tail.append(text)
                        del tail[:-5]
                        await decky.emit(
                            "emulator_install_progress",
                            entry["id"],
                            text,
                            self._parse_percent(text),
                        )

                code = await process.wait()
                # remote-add is allowed to fail; the remote usually exists.
                if code != 0 and "install" in argv:
                    reason = " ".join(tail).strip() or "no output"
                    await decky.emit(
                        "emulator_install_done", entry["id"], False,
                        "flatpak exited with code %d: %s" % (code, reason),
                    )
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
        extensions = await self._run(installer.database_extensions)
        definition = await self._run(emulator_catalog.to_emulator, entry, target, extensions)

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

        # Some emulators are not playable as they ship -- Azahar binds a
        # keyboard and starts windowed -- so the recommended settings go in
        # here, while it is certainly not running and cannot save over them.
        result = await self._run(emu_config.apply_setup, entry)
        if not result.get("ok"):
            return "%s was installed, but its settings could not be written: %s" % (
                entry["name"],
                result.get("error", ""),
            )
        return ""


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


    async def uninstall_emulator(self, entry_id: str):
        """Remove a catalog emulator and forget its registration.

        Games already added to Steam keep their launcher scripts, exactly as with
        RetroArch: reinstalling makes every one of them work again, and deleting
        them here would be an unrelated irreversible act behind a button that
        does not say so.
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

            removed = await self._flatpak_uninstall(app_id)
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


    async def _flatpak_uninstall(self, app_id):
        """Run `flatpak uninstall` for one application id.

        Shared rather than written twice, which is the lesson rather than a
        preference: the dev-reset tab grew its own copy of this and left out
        `env=` -- and without that, Steam's runtime libraries are still on the
        path and flatpak dies on `libcrypto.so.3: version OPENSSL_3.4.0 not
        found` before it does anything. The copy also logged nothing, so the
        failure arrived as a toast and left no trace to read afterwards.

        Every line flatpak prints is logged. A removal that fails needs the
        reason kept somewhere the user is not required to have been looking.
        """
        argv = await self._run(emu_install.flatpak_uninstall_argv, app_id)
        if not argv:
            return {"ok": False, "error": "flatpak is not available on this system."}

        decky.logger.info("Running: %s", " ".join(argv))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                # Steam's runtime libraries break system binaries. Without this
                # the command never gets as far as uninstalling anything.
                env=self._subprocess_env(),
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=180)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "flatpak did not finish within three minutes."}
        except (OSError, NotImplementedError) as error:
            decky.logger.exception("Could not run flatpak")
            return {"ok": False, "error": "Could not run flatpak: %s" % error}

        text = (output or b"").decode("utf-8", errors="replace").strip()
        for line in text.splitlines():
            decky.logger.info("flatpak: %s", line)
        if process.returncode != 0:
            tail = [line for line in text.splitlines() if line.strip()][-2:]
            return {
                "ok": False,
                "error": " | ".join(tail) or "flatpak exited with %s" % process.returncode,
            }
        return {"ok": True}


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
        known = settings.get("emulator_gui_apps") or {}
        return {
            "ok": True,
            # Named for what it does rather than after the emulator alone: this
            # sits in the Steam library next to the games, where "RPCS3" on its
            # own would read as a game somebody added.
            "title": "%s (setup)" % entry["name"],
            "exe": script,
            "start_dir": os.path.dirname(script),
            "app_id": known.get(entry_id, 0),
        }


    async def record_emulator_gui(self, entry_id: str, app_id: int):
        """Remember the shortcut made for an emulator's interface."""
        settings = await self._run(store.get_settings)
        known = dict(settings.get("emulator_gui_apps") or {})
        if app_id:
            known[entry_id] = int(app_id)
        else:
            known.pop(entry_id, None)
        await self._run(store.set_settings, {"emulator_gui_apps": known})
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


    async def remove_emulator(self, emulator_id: str):
        removed = await self._run(emulators.remove, emulator_id)
        await self._refresh_emulators()
        if not removed:
            return {"ok": False, "error": "That emulator is no longer registered."}
        return {"ok": True}
