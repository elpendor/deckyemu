import asyncio
import functools
import inspect
import os
import posixpath
import re
import sys

import appenv

import claim
import emulator_catalog
import emulators
import fileserver
import installer
import launchers
import platforms
import buildhost
import plugin_accounts
import plugin_artwork
import plugin_audit
import plugin_collections
import plugin_compress
import plugin_devreset
import plugin_discs
import plugin_emulators
import plugin_firmware
import plugin_fullbackup
import plugin_library
import plugin_packages
import plugin_probe
import plugin_retroarch
import plugin_romfiles
import plugin_shortcuts
import plugin_startup
import plugin_switching
import plugin_transfers
import plugin_updates
import ra_cores
import hardware
import ra_detect
import savedata
import store
import sysenv

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
    plugin_artwork.Artwork,
    plugin_audit.Audit,
    plugin_collections.Collections,
    plugin_compress.Compress,
    plugin_devreset.DevReset,
    plugin_discs.Discs,
    plugin_emulators.Emulators,
    plugin_firmware.Firmware,
    plugin_fullbackup.FullBackup,
    plugin_library.Library,
    plugin_packages.PackagedGames,
    plugin_probe.Probe,
    plugin_retroarch.RetroArchInstall,
    plugin_romfiles.RomFiles,
    plugin_shortcuts.Shortcuts,
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


    # ---------------------------------------------------------------- shortcuts


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
