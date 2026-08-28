import asyncio
import functools
import glob
import inspect
import os
import posixpath
import re
import sys
from typing import Optional

import decky

import cheevos
import emulator_catalog
import emulators
import fileserver
import installer
import handoff
import launchers
import libretro_meta
import model3_games
import net
import platforms
import ps4_games
import plugin_accounts
import plugin_audit
import plugin_collections
import plugin_devreset
import plugin_emulators
import plugin_firmware
import plugin_library
import plugin_packages
import plugin_retroarch
import plugin_startup
import plugin_transfers
import plugin_updates
import ra_cores
import hardware
import ra_detect
import romshelf
import savedata
import sgdb
import store
import sysenv
import vita_games
import vita_release
import xbox360_content
import xbox_disc

ROM_EXTENSION_BLOCKLIST = {"srm", "state", "sav", "png", "jpg", "cfg", "txt", "xml"}


def own_module_names(root):
    """The module names py_modules/ provides, imported on this run or not.

    Read off the directory rather than listed by hand. The list this replaces was
    written out in full and drifted twice: eight modules the first time,
    `diagnostics` the second. Both went unnoticed for the same reason -- a guard
    that covers some of the names produces exactly the output of a clean run, so
    there is nothing to notice.
    """
    names = set()
    package = os.path.join(root, "py_modules")
    try:
        entries = os.listdir(package)
    except OSError:
        # Nothing to check is not a failure worth raising during startup; the
        # caller is one step of `_main` and the plugin has to come up regardless.
        return names
    for entry in entries:
        # Dotfiles, `.keep` and `__pycache__`: not modules anyone imports.
        if entry.startswith((".", "_")):
            continue
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif os.path.isfile(os.path.join(package, entry, "__init__.py")):
            names.add(entry)
    return names


def _title_id_for(rom_path):
    """The title id a launcher needs, or "" for a game that launches by path.

    Derived from the recorded ROM rather than stored beside it, so a library
    written before any of this still rebuilds correctly. Empty for every game
    but Vita3K's, which are installed rather than opened: their launcher runs
    `-r <TITLE_ID>` and must carry no path at all.

    One function because two callers both need it and only one of them had it.
    `rebuild_launchers` derived it; `update_game` passed `write_launcher` its
    arguments positionally and stopped one short of `title_id`, so saving an
    edit rewrote a Vita launcher to open the eboot by path -- which starts
    Vita3K's own interface and no game. Anything that writes a launcher gets
    the id from here, and nothing has to remember that Vita is different.
    """
    return vita_games.title_of(rom_path or "")


def _check_own_modules():
    """Warn if one of our modules was shadowed by decky's.

    py_modules is appended to a sys.path that already contains decky_loader's own
    packages, so a generic name can resolve to decky's module instead of ours --
    silently, and only for the parts that use it. `updater.py` did exactly that:
    everything loaded, and one feature failed with "module 'decky_loader.updater'
    has no attribute 'check'". Cheap to check, and it names the problem outright.

    Every name py_modules offers is checked, not only the ones main.py imports:
    a module reached through another module can be shadowed just as quietly, and
    deriving the set means neither list has to be kept.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(own_module_names(here)):
        module = sys.modules.get(name)
        if module is None:
            # Not imported on this run, so nothing has resolved the name yet and
            # there is nothing to have resolved it wrongly.
            continue
        path = os.path.abspath(getattr(module, "__file__", "") or "")
        if not path.startswith(here):
            decky.logger.error(
                "Module %r is %s, not ours -- the name collides with something decky "
                "already imported. Rename it.", name, path or "built in",
            )



def _log_failures(cls):
    """Make every method decky can call write down why it failed.

    Decky hands an exception back to whoever called the method and nothing
    writes it anywhere. So the frontend gets a message, shows the user its own
    wording for "that did not work", and the plugin log -- the one place anybody
    looks afterwards, and the only thing a bug report can carry -- has nothing
    in it. What the log does get is asyncio complaining about the wreckage,
    which names neither the method nor the line.

    That has cost this project twice. Six rounds went into a bug where a module
    in `py_modules` shadowed one of the standard library's and the exception
    never reached the log, and `_installed_catalog_ids` returning a coroutine
    instead of a list surfaced only as "The report could not be prepared"
    beside a log full of "Task was destroyed but it is pending".

    Applied to the class rather than written at each of the hundred-odd methods:
    a rule that has to be remembered at every call site is one that will be
    missing from the method that needs it. Public coroutines only -- `_main` and
    `_unload` catch their own steps deliberately, and a private helper fails
    inside a public one that is already covered.

    The exception is logged and re-raised, never swallowed: the frontend still
    has to hear about it. `except Exception` and not `BaseException`, so an
    `asyncio.CancelledError` from decky unloading the plugin passes through
    without being dressed up as a failure.
    """
    def wrap(name, method):
        @functools.wraps(method)
        async def logged(*args, **kwargs):
            try:
                return await method(*args, **kwargs)
            except Exception:
                decky.logger.exception("%s() failed", name)
                raise

        return logged

    # Each method is replaced on the class that *defines* it, walking the MRO,
    # rather than all of them being set on `Plugin`. Setting them here would
    # give Plugin an attribute for every method its mixins own -- which is
    # exactly the shadowing `test_plugin_mixins` exists to catch, and it caught
    # this. A name defined in two places is a name with two implementations, and
    # nothing about logging should invent one.
    for klass in cls.__mro__:
        if klass is object:
            continue
        for name, method in list(vars(klass).items()):
            if name.startswith("_") or not inspect.iscoroutinefunction(method):
                continue
            setattr(klass, name, wrap(name, method))
    return cls


#: Methods that answer even on hardware the plugin does not support.
#:
#: The gate is a backstop, not the user interface -- the panel shows the
#: explanation and never calls the rest. What survives is therefore only what is
#: needed to *see* that explanation, act on it, and report it if it is wrong:
#:
#: * what the panel asks for on mount, or it renders nothing to explain with
#: * the settings pair, which is how the override is turned on
#: * frontend error logging, which must never be the thing that fails
#: * the updater, so a machine can always be moved to a version that fixes this
#: * the diagnostic report, which is how somebody tells us this gate is wrong
#:
#: An allowlist rather than a denylist because the risk is asymmetric: a
#: mutating method left out of a denylist runs on hardware nothing has tested,
#: while one wrongly left out of this list is a visible, reported failure.
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


class UnsupportedDevice(Exception):
    """Raised by the gate. Never shown -- the panel explains it properly."""


def _require_supported_device(cls):
    """Refuse the methods that change things when this is not a Steam Deck.

    Everything here was built and measured on one, so anywhere else is untested
    rather than merely unusual, and the failures it produces cannot be
    reproduced on hardware the project targets.

    The hardware is asked each time rather than cached at load: a cached answer
    would be one more thing to be wrong after a suspend, an update or a change
    nobody predicted, and reading two small sysfs files is not a cost worth
    optimising against correctness.

    Applied over `_log_failures` -- the gate is the inner wrapper, so a refusal
    is logged with the method that caused it exactly like any other failure.
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
    plugin_retroarch.RetroArchInstall,
    plugin_startup.Startup,
    plugin_transfers.Transfers,
    plugin_updates.Updates,
):
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self._install = None
        self._cores = []
        self._emulators = []
        decky.logger.info("DeckyEmu starting")
        _check_own_modules()
        # Said once, at the top of the log, so a report from unsupported
        # hardware explains itself before anyone reads a line of what went
        # wrong on it.
        hardware.log_once()

        # What to do with a file the moment it finishes arriving. A save backup
        # is moved out of the ROM inbox and everything else is left where it
        # landed -- see `savedata.take_delivery`. Registered here rather than
        # when the server starts, because the server also comes up on its own to
        # hand a report out and the rule is the same either way.
        fileserver.set_arrival_handler(savedata.take_delivery)

        # Before the startup steps rather than after them, and it does not wait:
        # the first check happens straight away and a failure climbs the retry
        # ladder. Nothing here blocks on it -- it is a task -- and one hanging
        # migration must not be the reason nobody is ever told about the fix
        # for it.
        # Whatever was watching before this call stops first. decky calls `_main`
        # once per load, so this should never find anything -- but if it ever
        # did, the old task would keep checking forever against a plugin nobody
        # holds any more, and nothing would ever say so.
        previous = getattr(self, "_update_task", None)
        if previous is not None:
            previous.cancel()
        self._update_task = self.loop.create_task(self._watch_for_updates())

        # Ordered, and each one on its own. The sequence stays here because this
        # is where it is read; the steps themselves are plugin_startup.py.
        #
        # The catalog is loaded first because everything after it reads it: an
        # imported emulator has to be in it by the time launchers are upgraded
        # and the library is backfilled, or a game added against one looks like
        # a game whose emulator vanished.
        #
        # Caught individually because these are independent, and all but the
        # first two are one-time migrations of data already on the device. A
        # single `await` chain made every one of them a single point of failure
        # for the whole of startup: one unreadable launcher, one imported
        # definition that no longer parses, one config file with the wrong owner,
        # and the steps after it never ran -- on this start or any later one,
        # because nothing about the state that broke it would change. Reported
        # per step, and startup continues, so a failure costs the one thing that
        # failed rather than the plugin.
        for label, step in (
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
            ("forget settings that no longer exist", self._forget_removed_settings),
        ):
            try:
                await step()
            except Exception:
                # Not CancelledError, which is a BaseException and so not caught
                # here: a cancelled startup is decky shutting the plugin down,
                # and it must be allowed to.
                decky.logger.exception("Startup: could not %s -- carrying on", label)

    async def _unload(self):
        # Cancelled before stopping, and only here. Stopping deliberately leaves
        # running transfers alone -- dismissing the dialog must not kill a
        # multi-gigabyte upload -- but an unload is the end of the process that
        # was writing them. Their handler threads would otherwise keep going with
        # nothing left to rename the file into place, leaving a .uploading
        # leftover that only the next start() would clear. Cancelling makes each
        # handler delete its own partial on the way out, which is the one thing
        # nothing else can do safely while it still holds the file open.
        #
        # Each independently, for the reason the startup steps are: the two
        # listening sockets must not outlive the plugin, and a socket left bound
        # because an unrelated cancel raised on the way past is exactly the
        # failure that makes the *next* start unable to bind its port.
        # Not in the list below: that one runs sync callables in the executor,
        # and this is a task to cancel. An update watch left running would hold
        # a reference to a plugin decky has finished with, and would wake up six
        # hours later to call methods on it.
        task = getattr(self, "_update_task", None)
        if task is not None:
            task.cancel()
            # Waited for, briefly. A cancel only *requests*, and a task still
            # pending when the loop goes away is logged by asyncio as "Task was
            # destroyed but it is pending!" -- noise in decky's own output that
            # reads like a bug of ours. Sleeping is the state it is in almost
            # always, and that unwinds instantly.
            #
            # Bounded rather than awaited outright: if the cancel lands while the
            # check is inside the executor, the request has to reach its own
            # 20-second timeout before the thread returns, and an unload must not
            # hold decky up for that.
            try:
                await asyncio.wait({task}, timeout=2)
            except Exception:
                decky.logger.exception("Unload: could not stop the update watch")
            self._update_task = None

        for label, step in (
            ("cancel transfers in flight", fileserver.cancel),
            ("stop the transfer server", fileserver.stop),
            ("stop the update handoff server", handoff.stop),
        ):
            try:
                await self._run(step)
            except Exception:
                decky.logger.exception("Unload: could not %s", label)
        decky.logger.info("DeckyEmu unloading")

    async def _uninstall(self):
        # Nothing to clean up, and nothing is cleaned up for us either -- this
        # comment used to say decky removes the runtime dir, which it does not.
        # Checked against the loader's own source at v3.2.6: the only `rmtree`
        # in it takes `~/homebrew/plugins/<name>`, the plugin's code. The
        # settings and runtime directories are left exactly where they are.
        #
        # That turns out to be the behaviour worth having, so it is left alone
        # rather than "fixed": the launcher scripts survive, so every game added
        # goes on working after an uninstall, and a reinstall finds its whole
        # library still recorded. Deleting either would break a shelf of Steam
        # entries as a side effect of removing a plugin.
        decky.logger.info("DeckyEmu uninstalled")

    async def _run(self, func, *args, **kwargs):
        return await self.loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

    def _detach(self, coro, event, *args):
        """Run `coro` in the background, guaranteeing `event` fires either way.

        An install runs detached because it takes minutes and streams progress,
        so the panel's only way to learn it is over is the done event. A
        detached task that raises reaches nobody: asyncio logs "Task exception
        was never retrieved" into decky's own output and the panel keeps its
        progress bar and its disabled button forever, which is the shape of
        every "it just hung" report.

        The handlers inside these coroutines cover the failures that were
        expected -- flatpak missing, a bad exit code. This covers the rest,
        which is the class that has no name yet: a KeyError on an entry field, a
        permission error writing a config, anything from the registration step
        that runs after the download succeeded.

        `event` is emitted as `event(*args, False, message)`, which fits both
        shapes in use: `emulator_install_done(id, ok, message)` when an id is
        passed and `retroarch_install_done(ok, message)` when nothing is.

        Returns the task. Callers discard it -- detached is the point -- but a
        test needs something to await, and polling for an event that is supposed
        to arrive is how a test passes by timing out slowly.
        """
        async def guarded():
            try:
                await coro
            except asyncio.CancelledError:
                # Unload cancels these. Swallowing it would keep the task alive
                # while the loop is trying to close, so it goes back up -- and
                # there is nothing left to emit to in any case.
                raise
            except Exception as error:
                decky.logger.exception("Background work for %s failed", event)
                try:
                    await decky.emit(
                        event, *args, False,
                        "%s: %s" % (type(error).__name__, error),
                    )
                except Exception:
                    # The socket is the only way to report anything, so its
                    # failure ends the matter. Logged rather than raised so the
                    # original exception above stays the one in the log.
                    decky.logger.exception("Could not report the failure of %s", event)

        return self.loop.create_task(guarded())

    # ------------------------------------------------- running other programs
    #
    # Reached by four of the mixins through plugin_base, not only by the
    # RetroArch installer they used to sit inside. They were in the middle of
    # that section, between installing RetroArch and streaming its output,
    # which read as if they belonged to it.

    @staticmethod
    def _subprocess_env():
        """Environment for flatpak, with HOME guaranteed to be the user's.

        The plugin does not inherit a login shell's environment. `flatpak --user`
        resolves its installation from HOME/XDG_DATA_HOME, so a missing or wrong
        HOME makes it fail immediately -- and the exit code alone gives no hint
        why.
        """
        # Steam's runtime libraries make flatpak fail instantly with an
        # OPENSSL symbol error, so they are cleared first.
        env = sysenv.clean_env()
        home = env.get("DECKY_USER_HOME") or ra_detect.user_home()
        if home:
            env["HOME"] = home
            env.setdefault("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
            env.setdefault("XDG_CACHE_HOME", os.path.join(home, ".cache"))
        env.setdefault("PATH", "/usr/bin:/bin:/usr/local/bin")

        # The session bus, which `flatpak uninstall --delete-data` needs and
        # nothing else here does.
        #
        # The plugin is started by a systemd service and inherits no bus
        # address, so flatpak tried to autolaunch one and answered "Cannot
        # autolaunch D-Bus without X11 $DISPLAY" -- on a device that has no X11
        # and does not need one, since the bus is already running and its socket
        # is right there. What made it expensive is where it failed: the app was
        # uninstalled first and the data deletion second, so removing RetroArch
        # *with* its saves reported an error having already removed RetroArch.
        #
        # Set only when the socket exists, and never overriding an inherited
        # one: naming an address for a bus that is not there turns a clear
        # autolaunch message into a connection refused.
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

        For the flatpak operations with nothing worth streaming -- removing
        RetroArch, removing an emulator -- as opposed to `_stream_flatpak`, which
        buffers the carriage-return redraws of a download to drive a progress
        bar. Both exist; this is the one for a verb that either works or does
        not.

        Written once because it has already been written wrongly twice. The
        dev-reset tab grew its own copy and left out `env=` -- and without that,
        Steam's runtime libraries are still on the path and flatpak dies on
        `libcrypto.so.3: version OPENSSL_3.4.0 not found` before it does
        anything. That copy also logged nothing, so the failure arrived as a
        toast and left no trace to read afterwards. Then the emulator uninstall
        and the RetroArch uninstall carried two more copies, identical line for
        line, one of them under a docstring saying this should be shared.

        Every line flatpak prints is logged: a removal that fails needs its
        reason kept somewhere the user was not required to be looking. The last
        two lines come back as the error, because that is where flatpak puts the
        reason and the exit code alone has cost a debugging round before.
        """
        decky.logger.info("Running: %s", " ".join(argv))
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                # Steam's runtime libraries break system binaries. Without this
                # the command never gets as far as doing anything.
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

    # `(?<!\d)` matters: output is read in fixed-size chunks, so a number can be
    # split across two reads. Without the guard, "1425%" yields 425 and the
    # progress bar is driven past 100 and off the right edge of its track.
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
        # The panel opening is the cheapest regular chance to notice that an
        # emulator has rewritten its config since its settings were written --
        # which is what its *first* run does, because a config written into a
        # file the emulator has never made is a config it regenerates. Startup
        # was the only place that asked, and one install-then-play session
        # happens entirely between two startups. See `_recheck_emulator_setups`.
        await self._recheck_emulator_setups()

        # Three separate answers, and they used to be two: `default_rom_dir()`
        # was `user_home()`, so one lookup filled both fields. It is the transfer
        # folder now, and the coupling had to go with it -- `home_dir` is what
        # keeps /home/deck out of the frontend, while the picker default is a
        # place to start browsing, and nothing says those are the same path.
        #
        # Still one executor hop each rather than one per field per call: this is
        # the call the panel makes every time it mounts.
        home, default_dir, waiting, device = await asyncio.gather(
            self._run(ra_detect.user_home),
            self._run(ra_detect.default_rom_dir),
            # Where the picker should open instead, when a transferred file is
            # still sitting unadded. "" the rest of the time, which is most of it.
            self._run(fileserver.waiting_dir),
            # What machine this is. Carried on the call the panel already makes
            # on mount rather than added as a second one: the panel cannot
            # render anything until it knows, so a separate round trip would
            # only be a chance to show the wrong thing first.
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
            "default_rom_dir": default_dir,
            "waiting_rom_dir": waiting,
            "home_dir": home,
            "device": device,
        }

    async def _device_state(self):
        """What the hardware is, plus whether the user has waived the answer.

        Both together because neither is usable alone: `supported` decides the
        message, `allowed` decides whether anything works, and the panel needs
        to say "unsupported, and you chose to continue" as its own state rather
        than as the absence of a warning.
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
            custom.append(emulators.to_core_entry(emulator, label))

        # A short label per declared database, so the picker can offer the
        # systems a multi-system core covers without the frontend needing a
        # copy of the name table. Attached here rather than where each kind of
        # core is built, because this is the one place both kinds meet.
        return [
            dict(core, database_labels=[
                platforms.short_name(database, "")
                for database in core.get("databases") or []
            ])
            for core in self._cores + custom
        ]

    async def _refresh_emulators(self):
        self._emulators = await self._run(emulators.list_emulators)
        return self._emulators

    async def probe_rom(self, rom_path: str):
        """Suggested cores for a ROM, most relevant first, plus a default name."""
        decky.logger.info("probe_rom: %s", rom_path)
        if not os.path.isfile(rom_path):
            decky.logger.warning("probe_rom: not a file: %s", rom_path)
        cores = await self.list_cores()
        extension = os.path.splitext(rom_path)[1].lower().lstrip(".")

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
        matching = [] if archived else ra_cores.cores_for_extension(
            cores, match_extension)
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

        # Evidence about this file beats a preference carried over from the
        # last one. `last_core_by_ext` is keyed on the extension alone, so for
        # `.chd` -- eighteen cores across six systems -- it remembers whichever
        # system was added last and suggests it for the next file whatever that
        # file is. A Dreamcast image suggested SwanStation is a shortcut that
        # cannot work, and it is reported as "the game will not launch".
        #
        # One sort with both terms rather than two passes: the order the two
        # rules apply in is the whole behaviour, and a second `.sort()` silently
        # overrules the first. Ties keep the order list_cores gave them, and
        # when neither term has anything to say the key is constant and the list
        # is left exactly as it was.
        matching.sort(
            key=lambda core: (
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
                core["id"] != remembered,
            )
        )

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

        result = {
            "extension": extension,
            "match_extension": match_extension,
            "is_archive": extension in ra_cores.ARCHIVE_EXTENSIONS,
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
            "can_unpack": (
                extension == "zip"
                and not romset
                and await self._run(fileserver.inbox_path, os.path.basename(rom_path))
                == rom_path
            ),
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

        # A PlayStation 3 package is the one thing the picker can be pointed at
        # that is not a game yet. RPCS3 has to unpack it first, and what boots
        # afterwards is dev_hdd0/game/<TITLE_ID>/USRDIR/EBOOT.BIN -- so the add
        # flow installs it and carries on with that path, and the user never
        # sees either the product code or the word EBOOT.
        # `.pkg` does not say which console it is for. A PS3 package begins
        # \x7fPKG and a PS4 one \x7fCNT, and nothing else about the file tells
        # them apart -- same extension, same rough size, same naming. Sending a
        # PS4 game to RPCS3 gets it reported as a corrupt package.
        # Three consoles now share it. PS4 is `\x7fCNT`; the PS3 and the Vita
        # are both `\x7fPKG` and differ only in a type field at offset 6.
        if extension == "pkg":
            if await self._run(ps4_games.is_package, rom_path):
                result["ps4_package"] = await self._run(self._ps4_package_state, rom_path)
            elif await self._run(vita_games.is_package, rom_path):
                result["vita_package"] = await self._run(self._vita_package_state, rom_path)
            else:
                result["ps3_package"] = await self._run(self._ps3_package_state, rom_path)

        # A PS Vita release, which is a zip like every zipped ROM is a zip -- and
        # a `.vpk` is the same thing under another extension. Detected by the one
        # file every release carries and no ROM archive does.
        #
        # Recognised in order to be *explained*, not offered. Vita3K is given a
        # `.pkg` and its zRIF or nothing: a release handed over as a path is
        # re-split on its spaces by the emulator's own launcher, and even
        # without spaces the content has to be installed and decrypted before
        # A ROM set is named after the MAME set rather than the game, so the
        # panel offered "daytona2" and Steam got a shelf entry called that.
        # It is also what the artwork search is given, and SteamGridDB has a
        # great deal of Daytona USA 2 and nothing whatever under `daytona2`.
        # The full title is in the game list Supermodel ships; see model3_games.
        romset_title, _hint = await self._romset_names(rom_path, romset)
        if romset_title:
            result["provisional_title"] = romset_title

        # anything can start it. This used to suggest Vita3K as the core to run
        # it with, which wrote a Steam shortcut that could never work and said
        # so only when the game was launched.
        if extension in ("zip", "vpk"):
            vita = await self._run(vita_release.inspect, rom_path)
            if vita["vita"]:
                result["vita_release"] = vita
                if vita["title"]:
                    result["provisional_title"] = vita["title"]

        # An Xbox disc image with nothing to boot. Worth saying here because the
        # console says it so badly: "Please insert an Xbox disc" on a black
        # screen reads as a broken emulator, a missing BIOS or a dead pad long
        # before it reads as a bad file. Said only when we are certain -- see
        # xbox_disc, which stays silent about every .iso that is not an Xbox one.
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

    def _core_by_id(self, core_id):
        if emulators.is_emulator_id(core_id):
            for emulator in self._emulators:
                if emulator.get("id") == emulators.emulator_id(core_id):
                    # The platform label is recomputed from `databases` wherever
                    # it matters, so it is not needed here.
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
        # Which game SteamGridDB thinks this is, so a wrong match is visible in
        # the UI rather than silently producing art for another game.
        art_game_name = ""

        want_sgdb = api_key and art_source in ("auto", "sgdb")
        if want_sgdb:
            # The system and the libretro-matched name both help: SteamGridDB's
            # own search happily returns a modern sequel for an 8-bit title.
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
                    art_game_name = await self._run(sgdb.game_name, api_key, game_id)

        if not art and art_source in ("auto", "libretro") and meta["boxart_url"]:
            art = await self._download_art({"capsule": meta["boxart_url"]})
            if art:
                source_used = "libretro"

        decky.logger.info(
            "resolve_game -> title=%r match=%s art=%s via=%s",
            meta["title"],
            meta["match_kind"],
            sorted(art.keys()),
            source_used,
        )

        return {
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

    async def list_art_candidates(self, rom_path: str, core_id: str, query: str = ""):
        """Alternative artwork matches, for when the automatic one is wrong.

        `query` lets the user search by a name of their own choosing, which is
        the only way out when both sources mis-identify a ROM.
        """
        core = self._core_by_id(core_id)
        databases = core["databases"] if core else []
        # The ROM set's own name, for the same reason resolve_game uses it: the
        # picker opened on `daytona2`, which is not a search anybody would type.
        # The search hint rather than the full title, because this list is
        # scored the same way and a subtitle SteamGridDB does not carry pushes
        # the right game down it.
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

        decky.logger.info(
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

        `suggested_title` comes back with it. Reaching for the picker means the
        automatic match was wrong, and choosing an entry there is the user
        saying which game this is -- which is a better answer than the filename
        heuristic that produced the name, and the only answer at all when the
        filename is junk. The caller decides whether to take it; nothing here
        renames anything.

        `picked_name` is the label on the row that was pressed. It exists
        because the SteamGridDB branch used to go and *ask* for the name after
        fetching the art -- a second request, which answers "" on any failure,
        so a flaky moment produced artwork with no name and a rename that
        silently did half of itself. The name was never something to go and
        find: the user read it off the row before choosing it.
        """
        # What was pressed, before anything is done about it. A pick that names
        # the game wrongly and a pick that does not name it at all are the same
        # report from the outside, and telling them apart afterwards meant
        # inferring the choice from the artwork request it caused -- which is
        # not the same thing and read wrongly twice.
        decky.logger.info(
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
            # Asked for, then fallen back to what the user clicked. The
            # request is still worth making -- it is the canonical spelling --
            # but it is no longer the only way to know.
            name = await self._run(sgdb.game_name, api_key, game_id)
            name = name or (picked_name or "").strip()[:120]
            decky.logger.info(
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
            # The thumbnail's own name is the label the row showed, so there
            # is nothing to fall back to and nothing that can fail.
            decky.logger.info(
                "apply_art_candidate -> %d image(s), named %r (thumbnail)", len(art), ref,
            )
            return {
                "ok": True,
                "art": art,
                "art_source": "libretro",
                "art_game_name": ref,
                # Through the same tidier a filename goes through, because a
                # libretro thumbnail is named like one: "Super Mario World
                # (USA)" is the right artwork and the wrong shortcut name.
                "suggested_title": libretro_meta.display_title(ref),
            }

        return {"ok": False, "error": "Unknown artwork source %r." % source}

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

    # ---------------------------------------------------------------- shortcuts

    # How a game runs, as opposed to where it is filed. These sat in the
    # collections block and are not about collections: every caller here is
    # in this section, and plugin_audit and plugin_startup reach them
    # through plugin_base.
    @staticmethod
    def _menu_combo(settings):
        """The RetroArch menu shortcut to bake in, validated before it is used.

        Global rather than per game, so it is read straight from settings here
        instead of going through _launch_options. Validated because an unknown
        key would otherwise reach RetroArch as no combo at all, silently leaving
        the user with no way into the menu.
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
            # Passed through rather than resolved here: `emulators.for_game`
            # needs the emulator to resolve against, and this has only the game.
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
        # `{id: bool}`, and only the ids this game actually decides. An id left
        # out follows the emulator's own setting, which is what "follow" means
        # and why an empty dict is dropped rather than stored.
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
        title_id: str = "",
    ):
        """Write the launcher script and return the fields Steam needs.

        `system` is what resolve_game worked out, and matters only for a core
        covering more than one: it decides the collection the frontend files the
        game into, which is otherwise the core's first database and put every
        Wii game under GameCube.
        """
        decky.logger.info("prepare_shortcut: title=%r core=%s rom=%s", title, core_id, rom_path)
        # The last plugin code that runs before a game exists to be launched, so
        # the last chance to notice that the emulator about to run it has thrown
        # its settings away. This is the sequence that produced the bug: install
        # the emulator, open it once for firmware, add a game, play -- and the
        # controller bindings were gone by the third step.
        await self._recheck_emulator_setups()
        emulator = self._emulator_for_core_id(core_id)
        # A custom emulator does not need RetroArch present at all.
        if not self._install and not emulator:
            return {"ok": False, "error": "RetroArch was not found on this system."}

        core = self._core_by_id(core_id)
        if not core:
            return {"ok": False, "error": "Core '%s' is no longer available." % core_id}

        if not os.path.isfile(rom_path):
            return {"ok": False, "error": "ROM file no longer exists: %s" % rom_path}

        # An emulator that starts installed titles by id has no by-path form to
        # fall back on, whatever `args` says. `launch_argv` would quietly use
        # the path form, which for Vita3K writes a shortcut that cannot work --
        # the content is still encrypted, and its AppImage re-splits the path on
        # any space it contains. Refused here, at the one gate every add goes
        # through, rather than left to fail at launch with nothing on screen
        # naming the cause.
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

        # Filed before the launcher is written, and that ordering is the whole
        # reason this is safe. The ROM path is baked into the launcher's argv,
        # the launcher's own filename is a hash of it, and the library records
        # it -- so moving a ROM afterwards breaks a game in three places at
        # once. Moving it first means nothing has been told the old path yet.
        # `_system_for` answers from the core's libretro databases, and an
        # emulator for a system libretro has no core for -- Xenia, RPCS3,
        # Ryujinx, shadPS4, Vita3K -- has none. It returned "", `folder_name`
        # made "" of that, and `file_rom` did nothing: every one of those
        # consoles left its ROM sitting in the transfer folder forever.
        #
        # Nothing said so. The game worked, launched from the inbox, and the
        # only visible symptom was a folder that never emptied -- until deleting
        # the game left the file behind too, because only ROMs under `roms/`
        # count as this plugin's to delete.
        rom_path = await self._run(
            romshelf.file_rom,
            rom_path,
            self._system_for(core, system) or core.get("platform_full", ""),
            await self._run(fileserver.default_dir),
            await self._run(romshelf.library_dir),
        )

        try:
            script = await self._run(
                launchers.write_launcher,
                self._install,
                clean_title,
                core["path"],
                rom_path,
                settings.get("hide_osd", "startup"),
                # No overrides on a game that does not exist yet, so this simply
                # follows the emulator -- but it goes through the same
                # resolution so there is one answer to how a launcher is built.
                emulators.for_game(emulator),
                settings.get("emulator_fullscreen", True),
                "",
                self._menu_combo(settings),
                settings,
                title_id,
            )
        except OSError as error:
            decky.logger.exception("Failed writing launcher")
            return {"ok": False, "error": "Could not write launcher script: %s" % error}

        return {
            "ok": True,
            "title": clean_title,
            "exe": script,
            "start_dir": os.path.dirname(script),
            "launch_options": "",
            "launcher_path": script,
            "core_path": core["path"],
            # Where the ROM ended up, which is not where the caller sent it if
            # it was just filed. Returned so the library records the path the
            # launcher actually runs -- otherwise every filed game would look
            # like an orphan the moment anything checked.
            "rom_path": rom_path,
            # Resolved here so per-platform naming lives in one place.
            "collection_name": self._collection_name(
                settings,
                self._entry_platform(
                    settings, core, {"system": self._system_for(core, system)}
                ),
            ),
            # Guarded on the install existing at all. The check above lets
            # `_install` be None whenever a standalone emulator was chosen --
            # the plugin is usable with no RetroArch, which is the whole point
            # of the emulator catalog -- and this line then indexed None and
            # raised TypeError. Adding a game to a Deck that had never
            # installed RetroArch failed here, at the last statement before
            # success. Found by a type checker, not by use.
            "warn_flatpak_sdcard": self._install is not None
            and self._install["kind"] == "flatpak"
            and rom_path.startswith("/run/media"),
            # The Steam Input layout this game needs, when the emulator asks for
            # a particular one. Vita3K is the case: the Deck powers its gyro down
            # unless the *running game's* layout binds it, so a Vita game on any
            # ordinary gamepad layout reads a sensor that never moves -- and the
            # setting is one nobody would guess, in a Steam menu three levels
            # from the game. Empty for every other emulator, which leaves Steam's
            # choice alone. See `steam/layout.ts` for what is done with it.
            "layout": (emulator or {}).get("layout", ""),
        }

    @classmethod
    def _entry_for(
        cls, settings, app_id, title, rom_path, core_id, core, launcher_path,
        system="", previous=None,
    ):
        """The registry record for one game, built the one way there is.

        Three places wrote this dict by hand -- adding a game, editing one, and
        adopting a previous install -- and the third built a fresh one rather
        than updating what was there, so every per-game launch override was
        silently reset to the global setting by an adoption. A field added to
        the record later would have gone the same way.

        `previous` is the record being replaced. Everything it holds that is not
        recomputed here survives, which is what carries `options` through.

        `system` is what resolve_game worked out for this add, and only matters
        for a core covering more than one -- Dolphin declares GameCube and Wii.
        Absent, the stored system is kept wherever the core still claims it, so
        editing a Wii game's name does not refile it under GameCube.
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
                # Remembered so a later rename knows which collection to move it
                # out of, rather than guessing from the current settings.
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
        decky.logger.info("register_game: app_id=%s title=%r", app_id, title)
        settings = await self._run(store.get_settings)
        entry = self._entry_for(
            settings, app_id, title, rom_path, core_id, core, launcher_path, system
        )
        # What the caller actually managed, not what the settings say should have
        # happened. Only the frontend can put a game on a shelf, so only the
        # frontend knows whether it went -- and this field is what a later rename
        # moves the game out of and what removing it empties, so a name recorded
        # for a collection the game never reached makes both of those no-ops.
        # Computed here as well until then, which is what said so.
        #
        # None rather than "" for "you decide": an empty string is a real answer
        # meaning the game is on no shelf, which is what a failed filing records.
        if collection is not None:
            entry["collection"] = collection
        await self._run(store.remember_game, app_id, entry)

        # Keyed on the content extension so a zipped SNES ROM remembers the same
        # core as a loose one.
        #
        # Off for a PS3 game, and it has to be: what boots is EBOOT.BIN, so
        # remembering this would file `.bin` under RPCS3 and then suggest a PS3
        # emulator for the next PS1 disc image somebody adds.
        extension = await self._run(ra_cores.content_extension, rom_path) if remember_core else ""
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

        Artwork is handled separately (the picker applies it directly), because it
        needs no launcher or collection work.

        The caller must finish the job on the Steam side: rename the shortcut,
        repoint it if the launcher moved, and move it between collections. This
        returns everything needed for that, including the previous collection --
        recording a new one without moving the app is the inconsistency that bit
        us before.
        """
        decky.logger.info(
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

        # A ROM the chosen core cannot read would produce a launcher that starts
        # the emulator and nothing else, which is a confusing way to find out.
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
                # The argument this list used to stop one short of. It has to be
                # positional -- `_run` forwards *args and no keywords -- which
                # is exactly why it was easy to miss: an eleven-argument call
                # whose last one defaults to "a launcher that opens the eboot by
                # path", and no error anywhere.
                _title_id_for(rom_path),
            )
        except OSError as error:
            decky.logger.exception("Could not rewrite launcher")
            return {"ok": False, "error": "Could not write the launcher: %s" % error}

        # The launcher filename embeds both the title and a hash of the ROM path,
        # so renaming or repointing produces a new file and the old one would
        # otherwise linger and be reported as a stray.
        old_launcher = entry.get("launcher_path", "")
        launcher_changed = bool(old_launcher) and os.path.normpath(old_launcher) != os.path.normpath(
            script
        )
        if launcher_changed:
            await self._run(launchers.remove_launcher, old_launcher)

        previous_collection = entry.get("collection", "")
        # `system` empty means the edit said nothing about it, and the stored
        # answer stands wherever the newly chosen core still claims it --
        # `_entry_for` owns that rule. Given, it is the user answering the one
        # question nothing else can: which of a multi-system core's systems this
        # game is, for the games that were filed under the wrong one before the
        # picker asked. That is the only way to move one without deleting it.
        #
        # The ROM file stays where it is. It was filed under the old system on
        # the way in, and its path is baked into the launcher's argv, hashed
        # into the launcher's filename and recorded here -- moving it is three
        # more things to keep in step for a folder nobody sees in Game Mode.
        entry = self._entry_for(
            settings, app_id, clean_title, rom_path, core_id, core, script,
            system, previous=entry,
        )
        entry["options"] = cleaned_options
        platform = entry["platform"]
        collection = entry["collection"]
        await self._run(store.remember_game, app_id, entry)

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

        The launch gate (`launchers.launch_gate`) is what actually stops a
        second game, because nothing on the Steam side can -- see the comment
        there for the two calls that were tried and what each did instead. The
        script leaves a note; this is the panel collecting it, so the dialog is
        shown for a launch that really was stopped rather than for one this side
        merely predicted would be.

        Consumed by reading, so asking twice answers once.
        """
        others = await self._run(launchers.take_bounce, app_id)
        return {"bounced": bool(others), "others": others}

    async def approve_launch(self, app_id: int) -> dict:
        """Let this game past the gate once, because the user said so."""
        return {"ok": await self._run(launchers.approve_launch, app_id)}

    @staticmethod
    def _stray_launchers(referenced):
        """Launcher scripts in our own directory that no registry entry claims."""
        return sorted(
            path
            for path in glob.glob(os.path.join(launchers.LAUNCHER_DIR, "*.sh"))
            if os.path.normpath(path) not in referenced
        )

    async def rebuild_launchers(self):
        """Regenerate every launcher script from the current settings.

        Not gated on RetroArch. It was, and that made every settings change
        silently do nothing on a Deck running only catalog emulators -- which is
        a configuration this plugin supports on purpose: `prepare_shortcut`
        needs RetroArch only when the chosen core is a libretro one, and the
        whole point of the emulator catalog is that a Deck can have no RetroArch
        at all. The rebuild refused for all of them because one *kind* of game
        needs it.

        A libretro game still cannot be rebuilt without it -- there is no argv
        to write without an install to run -- so those are skipped by name,
        which is what the caller already reports. A standalone emulator's
        launcher never needed it.
        """
        settings = await self._run(store.get_settings)
        library = await self._run(store.get_library)

        # Resolving what each game needs is all in-memory, so it happens here;
        # only the filesystem work is handed over, and in one pass rather than
        # one per game. `_launch_options` is per game so a global change does not
        # quietly discard the overrides someone set on one title.
        jobs = []
        for entry in library.values():
            core_id = entry.get("core_id", "")
            core = self._core_by_id(core_id)
            launch = self._launch_options(settings, entry)
            jobs.append(
                {
                    "title": entry.get("title", "Game"),
                    "label": entry.get("title", "?"),
                    "core_path": core["path"] if core else entry.get("core_path", ""),
                    "rom_path": entry.get("rom_path", ""),
                    # Resolved for this game, exactly as `prepare_shortcut` and
                    # `update_game` do. This was the one launcher writer that
                    # did not, and it is the one `set_workaround` calls -- so
                    # toggling a workaround for an emulator rewrote every one of
                    # its launchers from the emulator's own record and discarded
                    # whatever each game had chosen. It also decides *which
                    # binary* runs now, and the patched build is only ever named
                    # per game, so without this a fix that edits the emulator
                    # could be switched on and never reach a launcher.
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

        decky.logger.info("Rebuilt %d launcher(s), skipped %d", rebuilt, len(skipped))
        return {"ok": True, "rebuilt": rebuilt, "skipped": skipped}

    @staticmethod
    def _write_launchers(install, menu_combo, settings, jobs):
        """Write every launcher in `jobs`. Returns (rebuilt, skipped titles).

        The ROM check lives here rather than at the call site because it is the
        one piece of blocking filesystem work that was being done on the event
        loop, where every other file operation in this class goes through the
        executor.
        """
        rebuilt = 0
        skipped = []
        for job in jobs:
            if not job["core_path"] or not job["rom_path"] or not os.path.isfile(job["rom_path"]):
                skipped.append(job["label"])
                continue
            # A libretro core is run *by* RetroArch, so with no install there is
            # no argv to write. Skipped by name rather than refused for the
            # whole library: a standalone emulator's launcher does not involve
            # RetroArch and must still be rebuilt on a Deck that has none.
            if not install and not job["emulator"]:
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
                decky.logger.warning(
                    "Could not rebuild launcher for %r: %s", job["label"], error
                )
                skipped.append(job["label"])
        return rebuilt, skipped



    # ------------------------------------------------------- custom emulators

    async def list_emulators(self):
        """Registered emulators, each marked with where its definition came from.

        Derived rather than stored. `catalog_recipe` is written by `to_emulator`
        when a catalog install is registered, and `emulators.save` carries it
        through every later edit, so its presence is what separates an emulator
        that arrived by pressing Install from one described by hand.

        Sent because the panel shows both together and the rows are otherwise
        identical -- same name, same system -- with nothing to say why some of
        them also appear in the catalog list above.

        Copied rather than annotated in place: the list is `self._emulators`,
        which the launcher and recipe-upgrade passes both read.
        """
        entries = await self._refresh_emulators()
        return [dict(entry, from_catalog="catalog_recipe" in entry) for entry in entries]

    async def list_systems(self):
        """libretro system names an emulator can be mapped to, for artwork.

        This is the field that matters: artwork lookup and the SteamGridDB era
        check both key on the libretro database name, so a custom emulator that
        declares one gets boxart exactly like a core does. Sourced from the core
        catalog so the list covers everything libretro knows, not a hand-written
        subset.
        """
        names = set(platforms.SHORT_NAMES.keys())
        for core in self._cores:
            names.update(core.get("databases") or [])
        for entry in await self._run(installer.core_catalog):
            names.update(entry.get("databases") or [])

        # `label` is the full "Manufacturer - System" name and is what the picker
        # shows. Sorting on it keeps each manufacturer's systems together, which
        # short names cannot do -- they scatter Nintendo across 3DS, GBA, N64,
        # SNES, Switch and Wii.
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

        # Switch, Wii U, PS3 and friends are absent from libretro entirely, so
        # they would otherwise be unselectable. They get a label for collection
        # naming and rely on SteamGridDB for artwork.
        #
        # Skipped when libretro turns out to know the system after all: the Vita
        # is in the catalog, and listing it twice offered the same name twice,
        # once able to find boxart and once not.
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

    #: How much of a frontend error to keep. A component stack is long, and the
    #: log is a shared resource read two hundred lines at a time.
    _FRONTEND_ERROR_LIMIT = 2000

    async def log_frontend_error(self, where: str, message: str, detail: str = ""):
        """Write a frontend failure into the plugin log.

        The two halves of this plugin fail into different places and only one of
        them is reachable. A backend exception lands in the log, and now names
        its own method; a frontend one goes to a CEF console that needs a second
        machine, an IP address and a port to read -- so in Game Mode nobody sees
        it, including the person it happened to and the person they report it
        to. There were eighty-odd `console.error` calls on that side.

        The same log, so the diagnostic report carries both halves. Truncated,
        because a component stack is long and this is reachable by anything
        running in Steam's JS context; and logged rather than acted on, because
        nothing here should be steered by a string from that side.
        """
        where = (where or "the interface")[:120]
        message = (message or "")[:self._FRONTEND_ERROR_LIMIT]
        detail = (detail or "")[:self._FRONTEND_ERROR_LIMIT]
        decky.logger.error(
            "frontend: %s: %s%s", where, message, ("\n" + detail) if detail else ""
        )
        return {"ok": True}

    async def get_settings(self):
        settings = await self._run(store.get_settings)
        # Never ship the key itself to the UI; only whether one is set.
        settings = dict(settings)
        settings["sgdb_api_key_set"] = bool((settings.pop("sgdb_api_key", "") or "").strip())
        # The username is shown -- it is the whole point of saying who is signed
        # in -- but the Connect token is password-equivalent and stays here.
        settings["cheevos_token_set"] = bool((settings.pop("cheevos_token", "") or "").strip())
        return settings

    async def set_settings(self, patch: dict):
        # Filtered here rather than in `store.set_settings`: this is the one
        # entry point that takes a dict from outside, and the internal callers
        # write keys of their own choosing knowingly.
        patch, dropped = await self._run(store.known_only, patch)
        if dropped:
            decky.logger.warning(
                "Ignoring unknown setting(s): %s", ", ".join(sorted(dropped))
            )
        await self._run(store.set_settings, patch)
        # Launch behaviour is baked into each game's launcher script, so a
        # change here has to be written back out or it would only affect games
        # added from now on.
        if patch and any(
            key in patch
            for key in (
                "hide_osd",
                "emulator_fullscreen",
                "menu_combo",
                # Achievements are written into the same override file, so
                # switching them on has to reach launchers that already exist --
                # otherwise it would only apply to games added afterwards.
                "cheevos_enable",
                "cheevos_hardcore",
                "cheevos_username",
                "cheevos_token",
            )
        ):
            await self.rebuild_launchers()
        return await self.get_settings()











