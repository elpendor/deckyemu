import asyncio
import functools
import inspect
import os
import posixpath
import re
import sys
from typing import Optional

import appenv

import cheevos
import claim
import emulator_catalog
import emulators
import fileserver
import findfiles
import gameicon
import installer
import launchers
import libretro_meta
import net
import platforms
import buildhost
import discset
import plugin_accounts
import plugin_audit
import plugin_collections
import plugin_devreset
import plugin_emulators
import plugin_firmware
import plugin_library
import plugin_packages
import plugin_probe
import plugin_retroarch
import plugin_startup
import plugin_switching
import plugin_transfers
import plugin_updates
import ra_cores
import hardware
import ra_detect
import gamecontent
import rompatch
import romshelf
import savedata
import sgdb
import store
import switch_content
import sysenv
import vita_games

def own_module_names(root):
    """The module names py_modules/ provides, imported on this run or not.

    Read off the directory: a hand-kept list drifts, and a guard missing names
    looks exactly like a clean run.
    """
    names = set()
    package = os.path.join(root, "py_modules")
    try:
        entries = os.listdir(package)
    except OSError:
        # Startup must go on: nothing to check is not an error.
        return names
    for entry in entries:
        if entry.startswith((".", "_")):
            continue
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif os.path.isfile(os.path.join(package, entry, "__init__.py")):
            names.add(entry)
    return names


def _title_id_for(rom_path):
    """The title id a launcher needs, or "" for a game that launches by path.

    Empty for all but Vita3K's games, which are installed rather than opened:
    their launcher runs `-r <TITLE_ID>` with no path. Derived from the ROM, so
    older libraries rebuild correctly. Every launcher writer gets it from here.
    """
    return vita_games.title_of(rom_path or "")


def _check_own_modules():
    """Warn if one of our modules was shadowed by another of the same name.

    A generic name can resolve to another package's module, silently, breaking
    only what uses it. Every name py_modules offers is checked, since a module
    reached indirectly can be shadowed as quietly.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(own_module_names(here)):
        module = sys.modules.get(name)
        if module is None:
            continue  # not imported, so not resolved wrongly
        path = os.path.abspath(getattr(module, "__file__", "") or "")
        if not path.startswith(here):
            appenv.logger.error(
                "Module %r is %s, not ours -- the name collides with something "
                "already imported. Rename it.", name, path or "built in",
            )


def _log_failures(cls):
    """Make every method the panel can call log why it failed.

    An exception handed back to the panel is otherwise written nowhere, and the
    log is what a bug report carries. Applied to the class, so no method can
    forget it; public coroutines only, since `_main` and `_unload` catch their
    own steps. Logged and re-raised, so the panel still hears of it.
    `CancelledError` is not an `Exception` and passes through untouched.
    """
    def wrap(name, method):
        @functools.wraps(method)
        async def logged(*args, **kwargs):
            try:
                return await method(*args, **kwargs)
            except Exception:
                appenv.logger.exception("%s() failed", name)
                raise

        return logged

    # Wrapped on the class that defines each method: setting them all on
    # Plugin would shadow the mixins' (see test_plugin_mixins).
    for klass in cls.__mro__:
        if klass is object:
            continue
        for name, method in list(vars(klass).items()):
            if name.startswith("_") or not inspect.iscoroutinefunction(method):
                continue
            setattr(klass, name, wrap(name, method))
    return cls


#: Methods that answer even on hardware the plugin does not support: enough to
#: show why, turn on the override, log errors, update, and report a wrong
#: verdict. An allowlist, because a method wrongly missing from it fails
#: visibly, while one missing from a denylist would run untested.
UNGATED_METHODS = frozenset({
    "get_status",
    "list_added",
    "shortcut_health",
    "get_settings",
    "set_settings",
    "log_frontend_error",
    "plugin_version",
    "check_for_update",
    "stage_update",
    "start_report",
    "end_report",
    "file_server_status",
    "stop_file_server",
})


#: What a backend that stays off still answers: enough for the panel to say why,
#: and to update, since a newer build is the way past a newer data format.
WHILE_BLOCKED = frozenset({
    "get_status",
    "log_frontend_error",
    "plugin_version",
    "check_for_update",
    "stage_update",
    "take_over",
})


class Blocked(Exception):
    """Raised by the block gate. The panel explains it; see claim.py."""


def _refuse_while_blocked(cls):
    """Refuse everything but WHILE_BLOCKED when `_main` found it must stay off."""
    def wrap(name, method):
        @functools.wraps(method)
        async def refused(self, *args, **kwargs):
            if getattr(self, "_blocked", None):
                raise Blocked("%s is not available: %s" % (name, self._blocked))
            return await method(self, *args, **kwargs)

        return refused

    for klass in cls.__mro__:
        if klass is object:
            continue
        for name, method in list(vars(klass).items()):
            if name.startswith("_") or not inspect.iscoroutinefunction(method):
                continue
            if name in WHILE_BLOCKED:
                continue
            setattr(klass, name, wrap(name, method))
    return cls


class UnsupportedDevice(Exception):
    """Raised by the gate. Never shown -- the panel explains it properly."""


def _require_supported_device(cls):
    """Refuse the methods that change things when this is not a Steam Deck.

    Anywhere else is untested. The hardware is asked on every call, not cached,
    since two sysfs reads are cheap and a cached answer can go stale. The inner
    wrapper, so `_log_failures` logs a refusal like any other failure.
    """
    def wrap(name, method):
        @functools.wraps(method)
        async def gated(self, *args, **kwargs):
            if not hardware.detect()["supported"]:
                allowed = await self._run(store.get_settings)
                if not allowed.get("allow_unsupported_device"):
                    raise UnsupportedDevice(
                        "%s is not available: this is not a Steam Deck." % name
                    )
            return await method(self, *args, **kwargs)

        return gated

    for klass in cls.__mro__:
        if klass is object:
            continue
        for name, method in list(vars(klass).items()):
            if name.startswith("_") or not inspect.iscoroutinefunction(method):
                continue
            if name in UNGATED_METHODS:
                continue
            setattr(klass, name, wrap(name, method))
    return cls


@_log_failures
@_refuse_while_blocked
@_require_supported_device
class Plugin(
    plugin_accounts.Accounts,
    plugin_audit.Audit,
    plugin_collections.Collections,
    plugin_devreset.DevReset,
    plugin_emulators.Emulators,
    plugin_firmware.Firmware,
    plugin_library.Library,
    plugin_packages.PackagedGames,
    plugin_probe.Probe,
    plugin_retroarch.RetroArchInstall,
    plugin_startup.Startup,
    plugin_switching.Switching,
    plugin_transfers.Transfers,
    plugin_updates.Updates,
    buildhost.BuildHost,
):
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self._install = None
        self._cores = []
        self._emulators = []
        appenv.logger.info("DeckyEmu starting")
        # Watches which build is in use, on or off: see plugin_switching.py.
        self._watch_in_use()
        # Before anything reads or writes the state: see claim.py.
        self._blocked = await self._run(claim.blocked)
        if self._blocked:
            appenv.logger.warning("Staying off: %s", self._blocked)
            if self._blocked.get("reason") == "switched":
                await self._host_stepped_aside()
            return
        # Then, before anything reads the state: see buildhost.py.
        await self._host_claimed()
        _check_own_modules()
        # First in the log, so a report from other hardware explains itself.
        hardware.log_once()

        # A save backup leaves the ROM inbox on arrival; see
        # savedata.take_delivery. Set here as the server also starts on its own.
        fileserver.set_arrival_handler(savedata.take_delivery)

        # Before the startup steps, as a task, so a hanging migration cannot
        # stop the update that fixes it from being found. Any earlier watch
        # stops first.
        previous = getattr(self, "_update_task", None)
        if previous is not None:
            previous.cancel()
        self._update_task = self.loop.create_task(self._watch_for_updates())

        # Answers a launcher holding its game for saves to arrive. Here, not in
        # the panel, which hears of a launch only after it has started.
        previous_launch = getattr(self, "_launch_task", None)
        if previous_launch is not None:
            previous_launch.cancel()
        self._launch_task = self.loop.create_task(self._watch_launches())

        # In order (the steps are in plugin_startup.py), each caught on its own:
        # one failing step costs only itself, not every step after it. The
        # catalog loads first because the rest read it.
        for label, step in (
            # Before the load, which would report each as clashing with a
            # built-in.
            ("drop definitions the plugin now ships", self._drop_superseded_definitions),
            ("load imported emulator definitions",
             lambda: self._run(emulator_catalog.reload_imported)),
            ("detect RetroArch and scan cores", self.refresh_retroarch),
            ("backfill the library", self._backfill_library),
            ("adopt the menu shortcut", self._adopt_menu_combo),
            ("keep an existing library's collection layout", self._pin_collection_layout),
            ("claim the collections already filed into", self._claim_filed_collections),
            ("write the gyro layout template", self._write_gyro_layout),
            ("upgrade launchers", self._upgrade_launchers),
            ("upgrade emulator recipes", self._upgrade_emulator_recipes),
            ("upgrade emulator setups", self._upgrade_emulator_setups),
            ("re-file split firmware records", self._resplit_firmware_records),
            # Before sharing, which matches by content once this is loaded.
            ("load the BIOS checksum list", self._refresh_bios_dat),
            # Every start; a share somebody removed is left alone.
            ("share firmware already on the Deck", self._share_firmware_with_library),
            ("fetch the cloud transfer tool", self._fetch_cloud_tool),
            ("forget settings that no longer exist", self._forget_removed_settings),
            # A helper left by a launcher killed outright would type into
            # whatever opens next.
            ("stop stray hotkey helpers",
             lambda: self._run(launchers.stop_stray_helpers)),
            ("trim oversized launch logs",
             lambda: self._run(launchers.sweep_launch_logs)),
        ):
            try:
                await step()
            except Exception:  # not CancelledError: shutting down must work
                appenv.logger.exception("Startup: could not %s -- carrying on", label)
        try:
            await self._host_started()
        except Exception:
            appenv.logger.exception("Startup: this build's own steps failed -- carrying on")

    async def _unload(self):
        # Each step on its own, as at startup: a socket left bound because an
        # unrelated step raised would stop the next start from binding.
        try:
            await self._host_stopping()
        except Exception:
            appenv.logger.exception("Unload: this build's own steps failed")
        try:
            await self._stop_watching_in_use()
        except Exception:
            appenv.logger.exception("Unload: could not stop the in-use watch")
        task = getattr(self, "_update_task", None)
        if task is not None:
            task.cancel()
            # Waited for, so asyncio does not log it as destroyed while
            # pending; bounded, as a check inside the executor can take 20s.
            try:
                await asyncio.wait({task}, timeout=2)
            except Exception:
                appenv.logger.exception("Unload: could not stop the update watch")
            self._update_task = None

        launch_task = getattr(self, "_launch_task", None)
        if launch_task is not None:
            launch_task.cancel()
            try:
                await asyncio.wait({launch_task}, timeout=2)
            except Exception:
                appenv.logger.exception("Unload: could not stop the launch watch")
            self._launch_task = None

        for label, step in (
            ("cancel transfers in flight", fileserver.cancel),
            ("stop the transfer server", fileserver.stop),
        ):
            try:
                await self._run(step)
            except Exception:
                appenv.logger.exception("Unload: could not %s", label)
        try:
            await self._run(claim.release)
        except Exception:
            appenv.logger.exception("Unload: could not release the lock")
        appenv.logger.info("DeckyEmu unloading")

    async def _uninstall(self):
        # Settings and launchers are deliberately kept: added games go on
        # launching, and a reinstall finds the library as it was.
        appenv.logger.info("DeckyEmu uninstalled")

    async def _run(self, func, *args, **kwargs):
        return await self.loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

    def _detach(self, coro, event, *args, once=False):
        """Run `coro` in the background, guaranteeing `event` fires either way.

        The done event is the panel's only sign the work ended, so an unexpected
        exception still emits `event(*args, False, message)` instead of leaving
        a progress bar forever.

        `once=True` allows one run per event and arguments: a second start
        returns the running task. The panel forgets "running" when Quick Access
        closes, so its button can be pressed again mid-install.

        Returns the task, for tests to await.
        """
        tasks = self._detached_tasks()
        key = (event,) + args
        running = tasks.get(key) if once else None
        if running is not None and not running.done():
            coro.close()  # never awaited, so close it rather than warn later
            appenv.logger.info("%s is already running; not starting a second", event)
            return running

        async def guarded():
            try:
                await coro
            except asyncio.CancelledError:
                raise  # unload; the loop is closing
            except Exception as error:
                appenv.logger.exception("Background work for %s failed", event)
                try:
                    await appenv.emit(
                        event, *args, False,
                        "%s: %s" % (type(error).__name__, error),
                    )
                except Exception:
                    # Logged, not raised, so the first failure stays logged.
                    appenv.logger.exception("Could not report the failure of %s", event)

        task = self.loop.create_task(guarded())
        if once:
            tasks[key] = task
            # Only its own entry, never a newer start's.
            task.add_done_callback(
                lambda finished, key=key: tasks.pop(key, None)
                if tasks.get(key) is finished else None
            )
        return task

    def _detached_tasks(self):
        """The running `once` work, by (event, *args). Made on first use."""
        tasks = self.__dict__.get("_detached")
        if tasks is None:
            tasks = self._detached = {}
        return tasks

    async def running_work(self):
        """What is still running in the background, for a panel that just opened.

        The panel forgets running work when Steam closes it; asking on mount
        brings its progress bar back. Each item is `{"event", "args"}`, the pair
        the work's done event will carry.
        """
        return [
            {"event": key[0], "args": list(key[1:])}
            for key, task in list(self._detached_tasks().items())
            if not task.done()
        ]

    # ------------------------------------------------- running other programs
    #
    # Shared by several mixins, through plugin_base.

    @staticmethod
    def _subprocess_env():
        """Environment for flatpak, with HOME guaranteed to be the user's.

        No login shell's environment is inherited, and `flatpak --user` finds
        its installation from HOME/XDG_DATA_HOME.
        """
        # Without Steam's runtime libraries, which break flatpak (OpenSSL).
        env = sysenv.clean_env()
        home = env.get("DECKYEMU_USER_HOME") or ra_detect.user_home()
        if home:
            env["HOME"] = home
            env.setdefault("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
            env.setdefault("XDG_CACHE_HOME", os.path.join(home, ".cache"))
        env.setdefault("PATH", "/usr/bin:/bin:/usr/local/bin")

        # The session bus, for `flatpak uninstall --delete-data`: a service
        # inherits no bus address. Set only when the socket exists, never over
        # an inherited one.
        runtime = env.get("XDG_RUNTIME_DIR")
        if not runtime and hasattr(os, "getuid"):
            runtime = "/run/user/%d" % os.getuid()
        if runtime and os.path.exists(os.path.join(runtime, "bus")):
            env.setdefault("XDG_RUNTIME_DIR", runtime)
            env.setdefault(
                "DBUS_SESSION_BUS_ADDRESS",
                "unix:path=%s" % posixpath.join(runtime, "bus"),
            )
        return env

    async def _run_flatpak(self, argv):
        """Run one flatpak command to completion and report what it said.

        For commands with no progress to show, such as removals;
        `_stream_flatpak` drives a progress bar. Use this rather than calling
        flatpak directly, so the environment and logging are right. Every line
        is logged, and the last two come back as the error, where flatpak puts
        the reason.
        """
        appenv.logger.info("Running: %s", " ".join(argv))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._subprocess_env(),
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=180)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "flatpak did not finish within three minutes."}
        except (OSError, NotImplementedError) as error:
            appenv.logger.exception("Could not run flatpak")
            return {"ok": False, "error": "Could not run flatpak: %s" % error}

        text = (output or b"").decode("utf-8", errors="replace").strip()
        for line in text.splitlines():
            appenv.logger.info("flatpak: %s", line)

        if process.returncode != 0:
            tail = [line for line in text.splitlines() if line.strip()][-2:]
            return {
                "ok": False,
                "error": " | ".join(tail) or "flatpak exited with %s" % process.returncode,
            }
        return {"ok": True}

    # `(?<!\d)`: output arrives in chunks, and a number split across two must
    # not read as a bigger one ("1425%" as 425).
    _PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3})\s*%")

    @classmethod
    def _parse_percent(cls, text):
        """The last sane percentage in `text`, or -1 when there is none."""
        best = -1
        for match in cls._PERCENT_RE.finditer(text):
            value = int(match.group(1))
            if 0 <= value <= 100:
                best = value
        return best

    # ---------------------------------------------------------------- discovery

    async def refresh_retroarch(self):
        """Re-detect RetroArch and re-scan cores. Returns the status payload."""
        self._install = await self._run(ra_detect.detect)
        self._cores = await self._run(ra_cores.list_cores, self._install) if self._install else []
        await self._refresh_emulators()
        return await self.get_status()

    async def get_status(self):
        blocked = getattr(self, "_blocked", None)
        # The other build may be gone by now, or the user switched back to
        # this one: try again, so the panel opening then is a working one.
        retry = ("running", "switched")
        if blocked and blocked.get("reason") in retry and not getattr(self, "_retrying", False):
            self._retrying = True
            try:
                await self._main()
            finally:
                self._retrying = False
            blocked = self._blocked
        if blocked:
            return {"blocked": blocked}
        # An emulator's first run rewrites its config, often between two
        # starts, so the panel opening is when to check; see
        # `_recheck_emulator_setups`.
        await self._recheck_emulator_setups()

        # Asked together, as the panel makes this call on every mount.
        home, default_dir, waiting, device = await asyncio.gather(
            self._run(ra_detect.user_home),
            self._run(ra_detect.default_rom_dir),
            # Where the picker opens while a transferred file waits; else "".
            self._run(fileserver.waiting_dir),
            # On this call because the panel renders nothing until it knows.
            self._device_state(),
        )
        if not self._install:
            return {
                "found": False,
                "kind": "",
                "exe": "",
                "config_dir": "",
                "core_count": 0,
                "core_dirs": [],
                "emulator_count": len(self._emulators),
                "port_count": self._port_count(),
                "default_rom_dir": default_dir,
                "waiting_rom_dir": waiting,
                "home_dir": home,
                "device": device,
            }
        return {
            "found": True,
            "kind": self._install["kind"],
            "exe": self._install["exe"],
            "config_dir": self._install["config_dir"],
            "core_count": len(self._cores),
            "core_dirs": self._install["core_dirs"],
            "emulator_count": len(self._emulators),
            "port_count": self._port_count(),
            "default_rom_dir": default_dir,
            "waiting_rom_dir": waiting,
            "home_dir": home,
            "device": device,
        }

    async def _device_state(self):
        """What the hardware is, plus whether the user has waived the answer.

        `supported` picks the panel's message and `allowed` whether anything
        works, so "unsupported, and you chose to continue" is its own state.
        """
        found = await self._run(hardware.detect)
        settings = await self._run(store.get_settings)
        waived = bool(settings.get("allow_unsupported_device"))
        return dict(found, allowed=found["supported"] or waived, waived=waived)

    async def list_cores(self):
        """Every way to run a ROM: libretro cores plus custom emulators.

        Emulators are shaped like cores on purpose, so ROM probing, extension
        matching, artwork lookup and collection naming need no special cases.
        """
        if not self._cores and self._install:
            self._cores = await self._run(ra_cores.list_cores, self._install)

        settings = await self._run(store.get_settings)
        short = settings.get("platform_names", "short") == "short"

        custom = []
        for emulator in self._emulators:
            databases = emulator.get("databases") or []
            if databases:
                label = platforms.short_name(databases[0], "") if short else ""
            else:
                # No libretro database, so the label was stored directly.
                label = (
                    emulator.get("platform", "")
                    if short
                    else (emulator.get("platform_full") or emulator.get("platform", ""))
                )
            # `to_core_entry` marks a port, which the picker groups apart.
            custom.append(emulators.to_core_entry(emulator, label))

        # A short label per database, so the picker can offer each system a
        # multi-system core covers without its own name table.
        return [
            dict(core, database_labels=[
                platforms.short_name(database, "")
                for database in core.get("databases") or []
            ])
            for core in self._cores + custom
        ]

    def _port_count(self):
        """How many registered entries are ports rather than emulators.

        A port registers exactly as an emulator does; only its catalog entry
        tells them apart.
        """
        return sum(1 for entry in self._emulators
                   if emulators.is_port(entry.get("id") or ""))

    async def _refresh_emulators(self):
        self._emulators = await self._run(emulators.list_emulators)
        return self._emulators

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
            os.path.basename(rom_path) if rom_path.lower().endswith(".m3u") else "",
        )
        if error:
            return {"ok": False, "playlist": "", "discs": [], "error": error}

        appenv.logger.info("Added %s to %s; playlist now names %d discs",
                          name, entry.get("title"), len(discs))
        return {"ok": True, "playlist": written, "discs": discs, "error": ""}

    async def join_disc_to_game(self, app_id: int, disc_path: str):
        """Add a disc to a game and repoint its shortcut, in one press.

        For the transfer dialog. The shortcut moves to the playlist only for a
        core that declares `m3u`; others keep starting their disc. Returns
        {ok, error, title, exe, launcher_changed}.
        """
        added = await self.add_disc_to_game(app_id, disc_path)
        if not added["ok"]:
            return {"ok": False, "error": added["error"], "title": "",
                    "exe": "", "launcher_changed": False}

        library = await self._run(store.get_library)
        entry = library.get(str(app_id)) or {}
        core = self._core_by_id(entry.get("core_id", ""))
        reads_playlist = "m3u" in [
            text.lower() for text in (core or {}).get("extensions", [])
        ]
        if not added["playlist"] or not reads_playlist:
            # The set is on disk and the shortcut already starts a disc of it.
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

    def _core_by_id(self, core_id):
        if emulators.is_emulator_id(core_id):
            for emulator in self._emulators:
                if emulator.get("id") == emulators.emulator_id(core_id):
                    return emulators.to_core_entry(emulator)
            return None

        for core in self._cores:
            if core["id"] == core_id:
                return core
        return None

    def _emulator_for_core_id(self, core_id):
        """The raw emulator definition behind a core id, if it is one."""
        if not emulators.is_emulator_id(core_id):
            return None
        wanted = emulators.emulator_id(core_id)
        for emulator in self._emulators:
            if emulator.get("id") == wanted:
                return emulator
        return None

    # ----------------------------------------------------------------- metadata

    async def list_art_candidates(self, rom_path: str, core_id: str, query: str = ""):
        """Alternative artwork matches, for when the automatic one is wrong.

        `query` lets the user search by a name of their own choosing, which is
        the only way out when both sources mis-identify a ROM.
        """
        core = self._core_by_id(core_id)
        databases = core["databases"] if core else []
        # The ROM set's real name, not its short filename (`racer2`). The
        # search hint over the full title: a subtitle SteamGridDB lacks would
        # rank the right game lower.
        _set_title, _set_hint = await self._romset_names(rom_path)
        term = (query or "").strip() or _set_hint or _set_title or (
            libretro_meta.display_title(libretro_meta.rom_stem(rom_path))
        )

        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()

        libretro_hits = await self._run(libretro_meta.index_candidates, databases, term)
        sgdb_hits = []
        if api_key:
            sgdb_hits = await self._run(sgdb.search_candidates, api_key, term, databases, "", 10)

        appenv.logger.info(
            "list_art_candidates(%r): %d libretro, %d steamgriddb",
            term,
            len(libretro_hits),
            len(sgdb_hits),
        )
        return {
            "query": term,
            "libretro": libretro_hits,
            "steamgriddb": sgdb_hits,
            "sgdb_available": bool(api_key),
        }

    async def apply_art_candidate(
        self, source: str, ref: str, system: str = "", picked_name: str = ""
    ):
        """Fetch artwork for a candidate the user picked by hand.

        Picking one says which game this is, so a `suggested_title` comes back;
        the caller decides whether to rename. `picked_name` is the pressed row's
        label, the fallback when the name lookup fails.
        """
        # Logged first, so a report shows what was actually picked.
        appenv.logger.info(
            "apply_art_candidate: source=%s ref=%r system=%r row=%r",
            source, ref, system, picked_name,
        )

        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()

        if source == "steamgriddb":
            if not api_key:
                return {"ok": False, "error": "No SteamGridDB API key is set."}
            try:
                game_id = int(ref)
            except (TypeError, ValueError):
                return {"ok": False, "error": "Invalid SteamGridDB game id."}
            urls = await self._run(sgdb.art_urls, api_key, game_id)
            art = await self._download_art(urls)
            if not art:
                return {"ok": False, "error": "That game has no usable artwork on SteamGridDB."}
            # The database's spelling, else the row's.
            name = await self._run(sgdb.game_name, api_key, game_id)
            name = name or (picked_name or "").strip()[:120]
            appenv.logger.info(
                "apply_art_candidate -> %d image(s), named %r (database) / %r (row)",
                len(art), name, picked_name,
            )
            return {
                "ok": True,
                "art": art,
                "art_source": "steamgriddb",
                "art_game_name": name,
                "suggested_title": libretro_meta.display_title(name),
            }

        if source == "libretro":
            if not system:
                return {"ok": False, "error": "No system was supplied for that thumbnail."}
            url = libretro_meta.boxart_url(system, ref)
            art = await self._download_art({"capsule": url})
            if not art:
                return {"ok": False, "error": "That thumbnail could not be downloaded."}
            appenv.logger.info(
                "apply_art_candidate -> %d image(s), named %r (thumbnail)", len(art), ref,
            )
            return {
                "ok": True,
                "art": art,
                "art_source": "libretro",
                "art_game_name": ref,
                # Tidied like a filename: thumbnails carry tags like "(USA)".
                "suggested_title": libretro_meta.display_title(ref),
            }

        return {"ok": False, "error": "Unknown artwork source %r." % source}

    # ---------------------------------------------------------------- shortcuts

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
        launch_path = rom_path
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

    async def games_without_icon(self) -> list:
        """Tracked games wearing the shipped icon, or none at all.

        A found icon is saved under the game's app id, so a missing file says
        which games fell back.
        """
        library = await self._run(store.get_library)
        rows = []
        for entry in library.values():
            app_id = entry.get("app_id")
            if not app_id or await self._run(gameicon.has_own, app_id):
                continue
            rows.append({"app_id": app_id, "title": entry.get("title", "")})
        return rows

    async def fetch_game_icon(self, app_id: int) -> dict:
        """Look one game up on SteamGridDB and give it the icon it finds.

        Three requests (search, icon, download), not `art_urls`' five, as this
        runs per game across a library. No icon is `found: False`, not an
        error, and `path` then falls back to the shipped picture.
        """
        library = await self._run(store.get_library)
        entry = library.get(str(app_id))
        if not entry:
            return {"ok": False, "error": "That game is no longer tracked."}

        settings = await self._run(store.get_settings)
        api_key = (settings.get("sgdb_api_key") or "").strip()
        if not api_key:
            return {"ok": False, "error": "No SteamGridDB API key is set."}

        async def nothing_found():
            return {"ok": True, "found": False,
                    "path": await self._run(gameicon.for_game, app_id, "")}

        system = (entry.get("system") or "").strip()
        game_id = await self._run(
            sgdb.search_game, api_key, entry.get("title", ""),
            [system] if system else None, "")
        if not game_id:
            return await nothing_found()

        url = await self._run(sgdb.icon_url, api_key, game_id)
        if not url:
            return await nothing_found()

        # Raw bytes, as many are `.ico`; `gameicon.save` names the file by them.
        payload, _content_type = await self._run(net.get_bytes, url)
        if not payload:
            return await nothing_found()

        path = (await self._run(gameicon.save, app_id, payload)
                or await self._run(gameicon.for_game, app_id, ""))
        found = await self._run(gameicon.has_own, app_id)
        appenv.logger.info("fetch_game_icon: app_id=%s found=%s", app_id, found)
        return {"ok": True, "found": found, "path": path}

    async def game_icon(self, app_id: int, data: str = "") -> dict:
        """Where to point Steam for this game's icon.

        `data` is the artwork lookup's icon as a data URI, saved under the
        game's app id; without it, the shipped picture. Always a file that
        exists, or nothing.
        """
        return {"path": await self._run(gameicon.for_game, app_id, data)}

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
            extension = await self._run(ra_cores.content_extension, rom_path)
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
                rom_path,
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
                    # Per game, as in `prepare_shortcut`: it keeps each game's
                    # workarounds and picks which binary runs.
                    "emulator": emulators.for_game(
                        self._emulator_for_core_id(core_id), entry.get("options")),
                    "hide_osd": launch["hide_osd"],
                    "fullscreen": launch["fullscreen"],
                    "extra_args": launch["extra_args"],
                    "title_id": _title_id_for(entry.get("rom_path", "")),
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
                    job["rom_path"],
                    job["hide_osd"],
                    job["emulator"],
                    job["fullscreen"],
                    job["extra_args"],
                    menu_combo,
                    settings,
                    job.get("title_id", ""),
                )
                rebuilt += 1
            except OSError as error:
                appenv.logger.warning(
                    "Could not rebuild launcher for %r: %s", job["label"], error
                )
                skipped.append(job["label"])
        return rebuilt, skipped


    # ------------------------------------------------------- custom emulators

    async def list_emulators(self):
        """Registered emulators, each marked with where its definition came from.

        `from_catalog`: a catalog install keeps `catalog_recipe` through edits,
        unlike one described by hand. Copies, as `self._emulators` is shared.
        """
        entries = await self._refresh_emulators()
        return [
            dict(entry,
                 from_catalog="catalog_recipe" in entry,
                 # Ports and emulators register alike; the catalog tells.
                 port=emulators.is_port(entry["id"]))
            for entry in entries
        ]

    async def list_systems(self):
        """libretro system names an emulator can be mapped to, for artwork.

        Artwork lookup keys on the libretro database name, so an emulator that
        declares one gets boxart like a core. Taken from the core catalog.
        """
        names = set(platforms.SHORT_NAMES.keys())
        for core in self._cores:
            names.update(core.get("databases") or [])
        for entry in await self._run(installer.core_catalog):
            names.update(entry.get("databases") or [])

        # Sorted on the full "Maker - System" label, keeping each maker's
        # systems together.
        options = [
            {
                "id": name,
                "database": name,
                "label": name,
                "short": platforms.short_name(name),
                "full": name,
                "libretro": True,
            }
            for name in names
        ]

        # Systems libretro lacks (Switch, PS3...), named for collections, with
        # artwork from SteamGridDB; skipped if libretro has them after all.
        for label, full, short in platforms.NO_LIBRETRO_PLATFORMS:
            if label in names:
                continue
            options.append(
                {
                    "id": "~%s" % short,
                    "database": "",
                    "label": label,
                    "short": short,
                    "full": full,
                    "libretro": False,
                }
            )

        options.sort(key=lambda option: option["label"].lower())
        return options

    # ----------------------------------------------------------------- settings

    #: How much of a frontend error to keep; component stacks are long.
    _FRONTEND_ERROR_LIMIT = 2000

    async def log_frontend_error(self, where: str, message: str, detail: str = ""):
        """Write a frontend failure into the plugin log.

        The frontend's console is unreadable in Game Mode, so its errors join
        the backend's log, which the diagnostic report carries. Truncated, and
        only logged, as anything in Steam's JS context can call this.
        """
        where = (where or "the interface")[:120]
        message = (message or "")[:self._FRONTEND_ERROR_LIMIT]
        detail = (detail or "")[:self._FRONTEND_ERROR_LIMIT]
        appenv.logger.error(
            "frontend: %s: %s%s", where, message, ("\n" + detail) if detail else ""
        )
        return {"ok": True}

    async def get_settings(self):
        settings = await self._run(store.get_settings)
        # Never ship the key itself to the UI; only whether one is set.
        settings = dict(settings)
        settings["sgdb_api_key_set"] = bool((settings.pop("sgdb_api_key", "") or "").strip())
        # The username is shown; the token is a password and stays here.
        settings["cheevos_token_set"] = bool((settings.pop("cheevos_token", "") or "").strip())
        return settings

    async def set_settings(self, patch: dict):
        # Filtered here, the one entry point taking a dict from outside.
        patch, dropped = await self._run(store.known_only, patch)
        if dropped:
            appenv.logger.warning(
                "Ignoring unknown setting(s): %s", ", ".join(sorted(dropped))
            )
        await self._run(store.set_settings, patch)
        # These are baked into each launcher, so existing ones are rewritten.
        if patch and any(
            key in patch
            for key in (
                "hide_osd",
                "emulator_fullscreen",
                "menu_combo",
                "cheevos_enable",
                "cheevos_hardcore",
                "cheevos_username",
                "cheevos_token",
            )
        ):
            await self.rebuild_launchers()
        # Launchers read from a file whether to wait for saves, so it is
        # rewritten whenever the answer can change.
        if "cloud_before_play" in patch:
            await self._run(self._note_cloud_state)
        # Turning cloud saves on fetches its tool; a failure is retried at
        # startup.
        if patch.get("cloud_saves"):
            await self._fetch_cloud_tool()
        if "cloud_saves" in patch or "cloud_remote" in patch:
            await self._run(self._note_cloud_state)
        return await self.get_settings()
