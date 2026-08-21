import asyncio
import functools
import glob
import hashlib
import inspect
import json
import os
import posixpath
import re
import sys
from typing import Optional

import decky

import cheevos
import devreset
import diagnostics
import emu_install
import emulator_catalog
import emulators
import fileserver
import installer
import handoff
import launchers
import libretro_meta
import net
import platforms
import ps4_games
import plugin_accounts
import plugin_audit
import plugin_emulators
import plugin_firmware
import plugin_packages
import plugin_startup
import ra_cores
import hardware
import ra_detect
import releases
import romshelf
import sgdb
import store
import sysenv
import vita_games
import vita_release
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

# Where package.json and CI's build.json live. A module constant rather than an
# expression inside the reader, so a test can point it somewhere harmless instead
# of writing a build stamp into the working tree.
PLUGIN_ROOT = os.path.dirname(os.path.abspath(__file__))


def _log_failures(cls):
    """Make every method decky can call write down why it failed.

    Decky hands an exception back to whoever called the method and nothing
    writes it anywhere. So the frontend gets a message, shows the user its own
    wording for "that did not work", and the plugin log -- the one place anybody
    looks afterwards, and the only thing a bug report can carry -- has nothing
    in it. What the log does get is asyncio complaining about the wreckage,
    which names neither the method nor the line.

    That has cost this project twice. Six rounds went into a module-shadowing
    bug whose exception never reached the log (a module in py_modules shadowing one of the standard library's), and `_installed_catalog_ids` returning a coroutine instead of a
    list surfaced only as "The report could not be prepared" beside a log full
    of "Task was destroyed but it is pending".

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
    plugin_emulators.Emulators,
    plugin_firmware.Firmware,
    plugin_packages.PackagedGames,
    plugin_startup.Startup,
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
        matching = ra_cores.cores_for_extension(cores, match_extension)

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
                core["id"] != remembered,
            )
        )

        result = {
            "extension": extension,
            "match_extension": match_extension,
            "is_archive": extension in ra_cores.ARCHIVE_EXTENSIONS,
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
            "probe_rom -> ext=%s match_ext=%s matching=%s suggested=%s",
            extension,
            match_extension,
            [core["id"] for core in matching],
            result["suggested_core_id"],
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

    # -------------------------------------------------------------- collections

    @staticmethod
    def _platform_label(core=None, system="", short=False):
        """A human system name for use in a collection title.

        `short` gives the name people actually use -- SNES rather than "Super
        Nintendo Entertainment System", which is 46 characters of shelf header.
        Otherwise the core's own `systemname` is preferred over the libretro
        database name, which reads badly once appended to a collection name.
        """
        database = system
        if not database and core and core.get("databases"):
            database = core["databases"][0]

        if short:
            label = platforms.short_name(database, (core or {}).get("system_name", ""))
            if label:
                return label

        if core:
            if core.get("system_name"):
                return core["system_name"]
            if core.get("databases"):
                return core["databases"][0].split(" - ")[-1]
        if system:
            return system.split(" - ")[-1]
        return ""

    @staticmethod
    def _system_for(core, resolved="", fallback=""):
        """Which of a core's databases a game actually belongs to.

        Only interesting when a core covers more than one system, which Dolphin
        does: it declares GameCube *and* Wii, and taking `databases[0]` filed
        every Wii game under GameCube. `libretro_meta.resolve` already works the
        real one out -- it probes each database's boxart directory and reports
        which one had the game -- and that answer was being thrown away here.

        `resolved` is only believed when the core actually claims it, so a stale
        value cannot survive a core change.
        """
        databases = (core or {}).get("databases") or []
        if not databases:
            return ""
        for candidate in (resolved, fallback):
            if candidate and candidate in databases:
                return candidate
        return databases[0]

    @classmethod
    def _entry_platform(cls, settings, core, entry=None):
        """The platform label for a game under the current naming style.

        Computed rather than read back from the entry, so switching between short
        and full names re-labels games that were already added.
        """
        entry = entry or {}
        short = settings.get("platform_names", "short") == "short"
        label = cls._platform_label(core, entry.get("system", ""), short)
        return label or entry.get("platform", "")

    @classmethod
    def _collection_name(cls, settings, platform):
        """The collection a game belongs in under the current settings.

        Empty means "nowhere", which is a real answer rather than a missing one:
        collections switched off, or a name cleared to nothing. The switch is
        read here rather than at each call site because it was read at four of
        them and missed at the fifth -- `plan_collection_migration` computed
        targets as though collections were on, so turning them off planned no
        moves and the setting appeared to do nothing.
        """
        if not settings.get("add_to_collection", True):
            return ""
        base = (settings.get("collection_name") or "").strip()
        if not base:
            return ""
        if not (settings.get("collection_per_platform") and platform):
            return base

        template = settings.get("collection_template") or store.DEFAULT_COLLECTION_TEMPLATE
        return cls._render_collection(template, base, platform)

    #: The naming formats offered in the UI.
    #:
    #: Here rather than in the frontend so that the thing which *renders* a
    #: collection name is also the thing that previews one. There were three
    #: renderers of this template across two languages -- the one below, the
    #: pattern that recognises a name, and a preview in the settings panel --
    #: and they did not agree: the preview substituted only the first occurrence
    #: of a placeholder, and neither of the other two applied the trailing
    #: separator strip. They agreed on the seven formats offered and would have
    #: parted company on the first one added.
    COLLECTION_TEMPLATES = (
        "[{name}] {platform}",
        "{platform}",
        "{name}: {platform}",
        "{name} · {platform}",
        "{name} - {platform}",
        "{platform} ({name})",
        "{name}\\n{platform}",
    )

    @staticmethod
    def _render_collection(template, base, platform):
        """One template, one name. The only thing that turns one into the other."""
        # Stored as an escape so the template survives a round trip through JSON
        # and the settings UI as one line.
        name = template.replace("\\n", "\n")
        name = name.replace("{name}", base).replace("{platform}", platform)
        # Collapse runs of spaces and tabs, but keep any newline the user asked
        # for; trailing separators are left over when a placeholder is unused.
        name = re.sub(r"[ \t]+", " ", name)
        return name.strip(" \t-:·|/,")

    async def collection_templates(self):
        """Every offered naming format, with the name it would actually produce.

        The preview is rendered here, by the same function that names a real
        collection, so the dropdown cannot promise a format the filing does not
        use. `{platform}` is filled with a stand-in system for the sake of the
        example; everything else is the user's own settings.
        """
        settings = await self._run(store.get_settings)
        base = (settings.get("collection_name") or "").strip() or "Collection"
        return {
            "templates": [
                {
                    "template": template,
                    "preview": self._render_collection(template, base, "Nintendo 64"),
                }
                for template in self.COLLECTION_TEMPLATES
            ]
        }

    # Per-game launch overrides. Only explicit overrides are stored, so a game
    # left alone keeps following the global setting when that setting changes.
    _OSD_MODES = ("keep", "startup", "all")

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
        return cleaned

    async def collection_name_for(self, core_id: str):
        """What collection a game on `core_id` should go into right now.

        Empty when collections are off; `_collection_name` owns that rule.
        """
        settings = await self._run(store.get_settings)
        core = self._core_by_id(core_id)
        return self._collection_name(settings, self._entry_platform(settings, core))

    async def plan_collection_migration(self, previous: Optional[dict] = None):
        """Moves needed to bring existing games in line with current settings.

        Renaming the collection or toggling per-platform naming has to move games
        that were already added, otherwise the setting appears to do nothing
        until the next ROM is added.

        `previous` carries the settings as they were before the change. It matters
        for games added by an older version of this plugin, which did not record
        which collection they went into: without it their old collection is
        unknown, so they would be added to the new one and never removed from the
        old -- leaving the old collection sitting there, still populated.
        """
        settings = await self._run(store.get_settings)
        library = await self._run(store.get_library)

        moves = []
        for entry in library.values():
            app_id = entry.get("app_id")
            if not app_id:
                continue
            core = self._core_by_id(entry.get("core_id", ""))
            platform = self._entry_platform(settings, core, entry)
            target = self._collection_name(settings, platform)

            current = entry.get("collection", "")
            if not current and previous:
                # Derive the old name entirely from the old settings -- the
                # platform style may have changed too, so reusing the label
                # computed above would name a collection that never existed.
                current = self._collection_name(
                    previous, self._entry_platform(previous, core, entry)
                )

            # An empty `to` means "take it out and put it nowhere" -- collections
            # switched off, or the name cleared. This used to require a target,
            # so the one setting that removes games from collections planned
            # nothing at all and looked inert on an existing library. The
            # frontend removes, then deletes the collection only if it is left
            # empty, since one of ours can hold games dragged in by hand.
            if target != current:
                moves.append(
                    {
                        "app_id": app_id,
                        "title": entry.get("title", ""),
                        "from": current,
                        "to": target,
                    }
                )

        decky.logger.info(
            "plan_collection_migration: %d move(s)%s",
            len(moves),
            "" if not previous else " (using previous settings for unrecorded games)",
        )
        return {"moves": moves}

    async def collection_shape(self):
        """What a collection name made by this plugin looks like.

        For finding the ones it left behind empty. Every other way of knowing
        which collections are ours goes through a registered game -- and an
        empty collection is precisely one with no game left to ask.

        The pattern rather than a list of names: the platform half can be any
        system label the plugin has ever produced, including for a core since
        uninstalled, and enumerating those is guesswork where the template is
        exactly what was used to build the name in the first place.
        """
        settings = await self._run(store.get_settings)
        base = (settings.get("collection_name") or "").strip()
        per_platform = bool(settings.get("collection_per_platform"))
        template = settings.get("collection_template") or store.DEFAULT_COLLECTION_TEMPLATE
        return {
            "base": base,
            "per_platform": per_platform,
            "template": template.replace("\\n", "\n"),
            # What was actually done, as opposed to what the current settings
            # would do. The pattern above can only recognise shelves this naming
            # would produce today, so every one made under a naming since
            # changed fell out of it -- and an empty shelf is reached long after
            # the settings that made it moved on. These are the answer; the
            # pattern stays as the answer for anything filed before this record
            # existed.
            "known": await self._run(store.known_collections),
        }

    async def forget_collections(self, names: list):
        """Stop claiming collections that no longer exist.

        Called after they are deleted. Without it the record only grows, and a
        name this plugin once used would go on being claimed if the user later
        made a collection of their own by that name -- which is the one way
        recording ownership could be worse than deriving it.
        """
        dropped = await self._run(store.forget_collections, names or [])
        if dropped:
            decky.logger.info("No longer claiming collection(s): %s", ", ".join(dropped))
        return {"ok": True, "forgotten": dropped}

    async def collection_targets(self):
        """{app_id: collection} for every registered game, under current settings.

        Used to find games missing from the collection they belong to, and games
        sitting in one they do not.

        Nothing at all when collections are switched off, which is part of "under
        current settings" and not a special case: a game belongs nowhere then, so
        neither of those questions has an answer. It went unnoticed while the
        only callers were buttons on a panel that hides itself when the switch is
        off -- the library check has no such gate and would have reported every
        game as missing from a collection nobody asked for.
        """
        settings = await self._run(store.get_settings)
        if not settings.get("add_to_collection"):
            return {"targets": {}, "titles": {}}

        library = await self._run(store.get_library)

        targets = {}
        titles = {}
        for entry in library.values():
            app_id = entry.get("app_id")
            if not app_id:
                continue
            core = self._core_by_id(entry.get("core_id", ""))
            platform = self._entry_platform(settings, core, entry)
            targets[str(app_id)] = self._collection_name(settings, platform)
            titles[str(app_id)] = entry.get("title", "")
        return {"targets": targets, "titles": titles}

    async def record_collections(self, assignments: dict):
        """Persist which collection each game now lives in."""
        library = await self._run(store.get_library)
        updated = {}
        for app_id, name in (assignments or {}).items():
            entry = library.get(str(app_id))
            if not entry:
                continue
            entry["collection"] = name
            updated[app_id] = entry
        await self._run(store.remember_games, updated)
        return {"ok": True, "recorded": len(assignments or {})}

    # ----------------------------------------------------------------- metadata

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
        term = (query or "").strip() or libretro_meta.display_title(
            libretro_meta.rom_stem(rom_path)
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
        rom_path = await self._run(
            romshelf.file_rom,
            rom_path,
            self._system_for(core, system),
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
                emulator,
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
                emulator,
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

    async def unregister_game(self, app_id: int):
        """Forget a game and delete its launcher. Steam removal is done frontend-side."""
        entry = await self._run(store.forget_game, app_id)
        if entry:
            await self._run(launchers.remove_launcher, entry.get("launcher_path", ""))
        return entry

    async def list_added(self):
        library = await self._run(store.get_library)
        return sorted(library.values(), key=lambda entry: entry.get("title", "").lower())

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
                    "emulator": self._emulator_for_core_id(core_id),
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

    # ---------------------------------------------------------------- installing

    async def list_installable_cores(self, refresh: bool = False):
        """The full buildbot catalog, annotated with what is already installed."""
        catalog = await self._run(installer.core_catalog, refresh)
        installed = {core["id"] for core in await self.list_cores()}
        for entry in catalog:
            entry["installed"] = entry["id"] in installed
        return catalog

    async def suggest_cores_for_extension(self, extension: str):
        """Installable cores that claim `extension`, for ROMs with no local core."""
        ext = (extension or "").lower().lstrip(".")
        if not ext:
            return []
        catalog = await self.list_installable_cores()
        return [entry for entry in catalog if ext in entry["extensions"]]

    async def install_core(self, core_id: str):
        if not self._install:
            return {"ok": False, "error": "RetroArch was not found on this system."}

        await decky.emit("core_install_progress", core_id, "downloading", 0)
        result = await self._run(installer.install_core, self._install, core_id)

        if result.get("ok"):
            # Re-scan so the new core is immediately selectable.
            self._cores = await self._run(ra_cores.list_cores, self._install)
            result["core_count"] = len(self._cores)
            await decky.emit("core_install_progress", core_id, "done", 100)
        else:
            await decky.emit("core_install_progress", core_id, "failed", 0)

        return result

    async def uninstall_core(self, core_id: str):
        if not self._install:
            return {"ok": False, "error": "RetroArch was not found on this system."}
        result = await self._run(installer.uninstall_core, self._install, core_id)
        if result.get("ok"):
            self._cores = await self._run(ra_cores.list_cores, self._install)
            result["core_count"] = len(self._cores)
        return result

    async def can_install_retroarch(self):
        return {"flatpak_available": bool(await self._run(installer.flatpak_binary))}

    async def can_uninstall_retroarch(self):
        """Whether removing RetroArch is something this plugin may attempt.

        Reported rather than decided in the UI so the reason can be shown: a
        greyed-out button with no explanation is worse than no button.
        """
        if not self._install:
            return {"ok": False, "reason": "RetroArch is not installed."}

        kind = self._install.get("kind")
        if kind != "flatpak":
            return {
                "ok": False,
                "kind": kind,
                "reason": (
                    "This is a native package install, which belongs to the system's package "
                    "manager and would need SteamOS's read-only filesystem unlocked."
                    if kind == "native"
                    else "This is a loose AppImage that DeckyEmu did not install, so it is not "
                    "DeckyEmu's to delete. Remove the file yourself if you want it gone."
                ),
            }

        scope = await self._run(ra_detect.flatpak_scope)
        if scope == "system":
            return {
                "ok": False,
                "kind": kind,
                "scope": scope,
                "reason": (
                    "This flatpak was installed system-wide, most likely by EmuDeck or Discover. "
                    "Removing it needs root, which the plugin cannot supply. Uninstall it from "
                    "Discover in desktop mode."
                ),
            }

        return {"ok": True, "kind": kind, "scope": scope or "user"}

    async def uninstall_retroarch(self, delete_data: bool = False):
        """Remove the user-scope RetroArch flatpak.

        Deliberately synchronous, unlike the install: removal takes a couple of
        seconds and has nothing worth streaming, and a result the UI can act on
        beats a progress bar here.

        Games already added to Steam keep their shortcuts and launcher scripts.
        Nothing is rewritten, because reinstalling RetroArch makes every one of
        them work again -- and deleting them here would be an unrelated,
        irreversible act hidden behind a button labelled "uninstall RetroArch".
        """
        allowed = await self.can_uninstall_retroarch()
        if not allowed.get("ok"):
            return {"ok": False, "error": allowed.get("reason", "RetroArch cannot be removed.")}

        argv = await self._run(installer.retroarch_uninstall_argv, bool(delete_data))
        if not argv:
            return {"ok": False, "error": "flatpak is not available on this system."}

        result = await self._run_flatpak(argv)

        # Re-detected whether or not that succeeded, and the failure case is the
        # one that needs it. `--delete-data` removes the application first and
        # its data second, so a failure in the second half leaves RetroArch
        # already gone -- and returning the error without re-detecting left every
        # tab still showing it as installed, which is a worse answer than the
        # error. It is also how a failed-but-zero-exit removal gets caught.
        await self.refresh_retroarch()
        if not result.get("ok"):
            return dict(result, still_installed=bool(self._install))
        return {
            "ok": True,
            "still_installed": bool(self._install),
            "deleted_data": bool(delete_data),
        }

    async def install_retroarch(self):
        """Kick off a user-scope flatpak install, streaming progress as events."""
        if self._install:
            return {"ok": False, "error": "RetroArch is already installed."}

        steps = await self._run(installer.retroarch_install_argv)
        if not steps:
            return {
                "ok": False,
                "error": "flatpak is not available on this system, so RetroArch cannot be installed automatically.",
            }

        self._detach(self._run_retroarch_install(steps), "retroarch_install_done")
        return {"ok": True, "started": True}

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

    async def _run_retroarch_install(self, steps):
        """RetroArch is a large download, so progress is streamed to the UI."""
        env = self._subprocess_env()
        decky.logger.info(
            "Install environment: HOME=%s XDG_DATA_HOME=%s",
            env.get("HOME"),
            env.get("XDG_DATA_HOME"),
        )

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
                    # NotImplementedError happens when the event loop cannot
                    # spawn children, which is not obvious from an exit code.
                    decky.logger.exception("Could not start %s", argv[0])
                    await decky.emit(
                        "retroarch_install_done", False, "Could not run flatpak: %s" % error
                    )
                    return

                # Kept so a failure can be explained rather than reduced to a
                # number -- flatpak writes the actual reason here.
                tail = []
                # flatpak redraws its progress line with carriage returns, so
                # output is split on those as well as newlines. Buffering whole
                # segments keeps numbers intact across chunk boundaries.
                buffer = ""
                while True:
                    chunk = await process.stdout.read(256)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")

                    segments = re.split(r"[\r\n]+", buffer)
                    # The final piece may be incomplete; hold it back.
                    buffer = segments.pop()

                    for segment in segments:
                        text = segment.strip()
                        if not text:
                            continue
                        decky.logger.info("flatpak: %s", text)
                        tail.append(text)
                        del tail[:-5]
                        await decky.emit(
                            "retroarch_install_progress", text, self._parse_percent(text)
                        )

                if buffer.strip():
                    text = buffer.strip()
                    decky.logger.info("flatpak: %s", text)
                    tail.append(text)
                    del tail[:-5]
                    await decky.emit(
                        "retroarch_install_progress", text, self._parse_percent(text)
                    )

                code = await process.wait()
                decky.logger.info("%s exited with %d", argv[1] if len(argv) > 1 else argv[0], code)

                # remote-add is allowed to fail: the remote usually already exists.
                if code != 0 and "install" in argv:
                    reason = " ".join(tail).strip() or "no output"
                    await decky.emit(
                        "retroarch_install_done",
                        False,
                        "flatpak exited with code %d: %s" % (code, reason),
                    )
                    return

            status = await self.refresh_retroarch()
            await decky.emit(
                "retroarch_install_done",
                bool(status["found"]),
                "" if status["found"] else "Install finished but RetroArch was still not found.",
            )
        # Only the expected failure, and deliberately not CancelledError: this
        # runs detached, so `_detach` re-raises a cancellation properly and
        # reports anything else. Catching it here swallowed an unload, then tried
        # to emit over the socket that was closing.
        except OSError as error:
            decky.logger.exception("RetroArch install failed")
            await decky.emit("retroarch_install_done", False, str(error))

    # ---------------------------------------------------------- file transfer

    async def file_server_status(self):
        status = await self._run(fileserver.status)
        status["received"] = await self._run(fileserver.received_files)
        # Its own folder, not wherever ROMs are browsed from -- see
        # fileserver.default_dir.
        status["suggested_dir"] = await self._run(fileserver.default_dir)
        return status

    async def start_report(self):
        """Gather a diagnostic report and put it where another device can read it.

        The plugin logs plenty and none of it is reachable from Game Mode, so the
        best report a user can give is "it didn't work" -- which is also the
        least useful one. This is the same problem the transfer server already
        solves in the other direction, so it is the same server: a QR code for a
        camera, six digits for anything with a keyboard.

        What is gathered and what is struck out of it is `diagnostics`, and the
        striking out is the part that matters -- the settings hold a
        RetroAchievements token that is password-equivalent, and this text is
        going into a public issue.
        """
        # The session's own transfer token is struck by value: it is minted per
        # session so no settings file holds it, it reaches the log as a bare
        # request path that no URL rule catches, and it is live on the network
        # at the moment somebody reads the report.
        serving = await self._run(fileserver.status)
        report = await self._run(
            diagnostics.build,
            await self.plugin_version(),
            self._install,
            self._emulators,
            await self._run(store.get_library),
            await self._run(self._installed_catalog_ids),
            [serving.get("url", "").rstrip("/").rsplit("/", 1)[-1]],
            await self._run(fileserver.default_dir, False),
        )

        if not serving.get("running"):
            # Started to hand a report out, and nothing else: a server brought up
            # for this does not accept files. Showing somebody a report should
            # not also hand them somewhere to write, and they could not tell
            # they had been given one.
            started = await self._run(
                fileserver.start, await self._run(fileserver.default_dir), 0, "", False
            )
            if started.get("error"):
                return {"ok": False, "error": started["error"]}

        await self._run(fileserver.offer_report, report)
        decky.logger.info("Diagnostic report ready (%d characters)", len(report))
        return {"ok": True, **await self._run(fileserver.status)}

    async def end_report(self):
        """Withdraw the report, and stop the server if it was only serving that.

        Pressing Done means done: the report is the tail of a log, and leaving it
        on the network afterwards is exposure nobody asked for. The page already
        open on the other device keeps working -- it is one load, and its text is
        in that browser rather than fetched again -- so ending this costs the
        reader nothing they are looking at.

        The server itself only stops when nothing is arriving. `start_report`
        will have started it if it was down, but it may equally have been up for
        a transfer that is still running, and cutting a multi-gigabyte ROM off
        because somebody closed an unrelated dialog is the failure this guard
        exists for. The transfer's own dialog uses the same rule.
        """
        await self._run(fileserver.offer_report, "")
        status = await self._run(fileserver.status)
        if status.get("running") and not (status.get("uploading") or status.get("paused")):
            return await self.stop_file_server()
        return {"ok": True, **await self._run(fileserver.status)}

    @staticmethod
    def _installed_catalog_ids():
        """Which catalog emulators are actually on the device, as `id (channel)`.

        Deliberately not async. It goes through `_run` because probing a flatpak
        shells out, and handing `_run` a coroutine function does not run it --
        the executor calls it, gets a coroutine object back, and nothing ever
        awaits it. What reaches the caller is that object rather than a list,
        and the first thing done with it raises somewhere else entirely.
        """
        found = []
        for entry in emulator_catalog.CATALOG:
            source = entry.get("source") or {}
            kind = source.get("kind")
            if kind == "flatpak" and emu_install.flatpak_installed(source.get("id", "")):
                found.append("%s (flatpak)" % entry["id"])
            elif kind == "github" and emu_install.installed_appimage(entry["id"]):
                found.append("%s (appimage)" % entry["id"])
        return found

    async def start_file_server(self, target_dir: str = ""):
        # Empty means the default folder. Lets a caller start receiving in one call
        # without first asking where that is.
        target_dir = (target_dir or "").strip() or await self._run(fileserver.default_dir)

        settings = await self._run(store.get_settings)
        remember = bool(settings.get("transfer_remember"))
        result = await self._run(
            fileserver.start,
            target_dir,
            int(settings.get("transfer_port") or 0) if remember else 0,
            (settings.get("transfer_token") or "") if remember else "",
        )
        if result.get("error"):
            return {"ok": False, "error": result["error"]}

        # The server may already have been up to hand out a report, which does
        # not accept files. This is a transfer, so it does now.
        await self._run(fileserver.allow_uploads)

        if remember:
            # Whatever was actually bound and minted, not what was asked for: a
            # remembered port can be taken by something else and fallen back from,
            # and recording the request rather than the outcome would hand out a
            # link to an address nothing is listening on.
            await self._run(
                store.set_settings,
                {
                    "transfer_port": result.get("port", 0),
                    "transfer_token": await self._run(fileserver.current_token),
                },
            )

        result["received"] = await self._run(fileserver.received_files)
        return {"ok": True, **result}

    async def reset_transfer_link(self):
        """Invalidate every saved link. The next start issues a fresh one.

        All or nothing by design: the link is the credential, so there is nothing
        per-device to revoke. Refused while a transfer is running, because taking
        the address away mid-upload would cut off the very device that is using it.
        """
        status = await self._run(fileserver.status)
        if status.get("uploading"):
            return {
                "ok": False,
                "error": "A transfer is still running. Wait for it to finish, or cancel it first.",
            }

        await self._run(store.set_settings, {"transfer_port": 0, "transfer_token": ""})
        decky.logger.info("Reset the transfer link; saved bookmarks no longer work")

        # Restarted rather than left running, so the old link stops working now
        # instead of at the end of a session the user thinks they have revoked.
        if status.get("running"):
            await self._run(fileserver.stop)
            return await self.start_file_server(status.get("target_dir", ""))
        return {"ok": True, "running": False}

    async def stop_file_server(self):
        result = await self._run(fileserver.stop)
        result["received"] = await self._run(fileserver.received_files)
        return {"ok": True, **result}

    async def cancel_upload(self, upload_id: int = 0):
        """Abandon a transfer in progress. 0 means every one of them.

        The half-written file goes with it, and this is the one thing that
        deletes one. An interrupted upload keeps its partial so the sender can
        carry on from it; a cancelled one is the user saying they do not want
        this file, which is a different answer. The handler deletes its own,
        being the only thread that can do it safely while the file is open.
        """
        cancelled = await self._run(fileserver.cancel, upload_id or None)
        status = await self._run(fileserver.status)
        status["received"] = await self._run(fileserver.received_files)
        return {"ok": True, "cancelled": cancelled, **status}

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

    # --------------------------------------------------------------- dev reset

    async def dev_reset_available(self):
        """Whether the reset tab may do anything. See py_modules/devreset.py.

        The frontend tab is compiled out of a release build entirely, so this is
        the second of two independent gates rather than the only one. It exists
        because "compiled out" is a property of one artifact and these endpoints
        are reachable by anything that can talk to the plugin.
        """
        return {"ok": True, "available": devreset.available(PLUGIN_ROOT)}

    async def dev_reset_inventory(self):
        """What each reset would delete, with sizes, before anything happens."""
        if not devreset.available(PLUGIN_ROOT):
            return {"ok": False, "error": "Not a development build."}
        return {"ok": True, "groups": await self._run(devreset.inventory)}

    async def dev_reset(self, action: str):
        """Run one reset. One action per press, named, never bundled.

        Separate because what they cost differs by orders of magnitude: state
        is rebuilt by using the plugin, a download is twenty minutes, and sent
        dumps and save games mean a trip to another machine. A single "reset
        everything" would hide the third behind the first.
        """
        if not devreset.available(PLUGIN_ROOT):
            return {"ok": False, "error": "Not a development build."}

        decky.logger.warning("Dev reset requested: %s", action)

        if action == "retroarch":
            return await self._dev_reset_retroarch()
        if action == "emulators":
            return await self._dev_reset_emulators()

        simple = {
            "emulator_data": devreset.clear_emulator_data,
            "transfers": devreset.clear_transfers,
            "downloads": devreset.clear_downloads,
            "state": devreset.clear_state,
        }
        if action not in simple:
            return {"ok": False, "error": "Unknown reset %r." % action}

        freed = await self._run(simple[action])
        # Whatever was just deleted, this backend is still holding what it
        # detected before -- which RetroArch is installed, which cores it has,
        # which emulators are registered. Re-detected here rather than left to
        # whoever asks next, because the answer they would get is wrong and
        # nothing about it looks stale.
        await self.refresh_retroarch()
        decky.logger.warning("Dev reset %s freed %d bytes", action, freed)
        return {"ok": True, "freed": freed}

    async def _dev_reset_emulators(self):
        """Uninstall every catalog emulator this plugin can remove, data and all.

        Through the same endpoint the Emulators tab uses, so a system-wide
        flatpak is refused here for the same reason and with the same words --
        removing one needs root, which the plugin has not got.

        The data goes with it, and that is the difference between this and the
        tab's own Remove, where keeping it is a question worth asking. Here it
        is not: the reset exists so the next run is a first run, and an emulator
        whose `~/.var/app/<id>` survived comes back already configured, already
        holding its firmware, and reports itself set up -- which is the exact
        state this is for getting rid of.

        Two passes because neither alone covers it. `--delete-data` is
        flatpak's own and is the only thing that reaches a flatpak's data before
        the application id stops existing; the sweep afterwards is what reaches
        an AppImage's, which lives in ordinary folders the catalog has to name.

        Only for what actually came off: an emulator whose removal was refused
        is still installed, so deleting its saves would take data from an
        emulator this reset could not touch.
        """
        removed, failed, cleared = [], [], []
        for entry in emulator_catalog.CATALOG:
            present = (
                await self._run(emu_install.flatpak_installed, entry["source"]["id"])
                if entry["source"]["kind"] == "flatpak"
                else bool(await self._run(emu_install.installed_appimage, entry["id"]))
            )
            if not present:
                # Not installed, but its data can still be sitting there from an
                # install some earlier reset took away -- which is the leftover
                # that makes a reinstall arrive pre-configured.
                cleared.append(entry["id"])
                continue
            result = await self.uninstall_emulator(entry["id"], True)
            if result.get("ok"):
                removed.append(entry["name"])
                cleared.append(entry["id"])
            else:
                failed.append("%s (%s)" % (entry["name"], result.get("error", "")))
        freed = await self._run(devreset.clear_emulator_data, cleared)
        await self.refresh_retroarch()
        decky.logger.warning(
            "Dev reset emulators: %d removed, %d refused, %d bytes of data deleted",
            len(removed), len(failed), freed,
        )
        return {"ok": True, "removed": removed, "failed": failed, "freed": freed}

    async def _dev_reset_retroarch(self):
        """Remove RetroArch itself, its cores and its configuration."""
        app_id = "org.libretro.RetroArch"
        scope = await self._run(emu_install.flatpak_scope, app_id)
        if scope == "system":
            return {
                "ok": False,
                "error": "RetroArch was installed system-wide, most likely by EmuDeck. "
                "Removing it needs root, which the plugin cannot supply.",
            }

        # Only if it is there. A reset should be runnable twice, and the second
        # press finding nothing installed is success rather than a flatpak
        # error about an unknown application.
        if scope:
            removed = await self._flatpak_uninstall(app_id)
            if not removed["ok"]:
                return removed

        # The data directory survives a flatpak uninstall, and it is where the
        # cores, the system folder and every config override live -- so leaving
        # it is the difference between "removed" and "removed and forgotten".
        freed = await self._run(devreset.clear_retroarch_data)
        # Not just the emulators: RetroArch itself and its cores were what this
        # deleted, and both are held in this object until something re-detects.
        await self.refresh_retroarch()
        return {"ok": True, "freed": freed}

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

    async def plugin_version(self):
        """What this backend is, for display and for spotting a stale frontend.

        package.json is the source of truth for the version. `build.json` is written
        by CI beside it and names the commit; a local build has none, and reports
        "dev" so the frontend knows not to compare.
        """

        def _read():
            root = PLUGIN_ROOT
            version, build, built_at = "0.0.0", "dev", ""
            # What changed in the build that is actually installed. CI writes it
            # into the stamp so the Updates tab can answer "what did I get?"
            # without a network -- and, while the repository is private, without a
            # token. A local build has none, which reads as "nothing to show".
            notes = ""
            try:
                with open(os.path.join(root, "package.json"), "r", encoding="utf-8") as handle:
                    version = json.load(handle).get("version") or version
            except (OSError, ValueError):
                pass
            try:
                with open(os.path.join(root, "build.json"), "r", encoding="utf-8") as handle:
                    stamp = json.load(handle)
                build = stamp.get("commit") or build
                built_at = stamp.get("built_at") or ""
                notes = (stamp.get("notes") or "").strip()
                # CI writes the version it built, which is authoritative over a
                # package.json that could have been edited since.
                version = stamp.get("version") or version
            except (OSError, ValueError):
                pass
            return {
                "version": version,
                "build": build,
                "built_at": built_at,
                "notes": notes,
            }

        return await self._run(_read)

    async def check_for_update(self, force: bool = False):
        """Whether a newer release exists, and what the frontend needs to install it.

        Only looks. Decky's loader does the installing -- it runs as root and this
        backend runs as `deck`, which cannot write the plugin's own directory.
        """
        current = (await self.plugin_version())["version"]
        result = await self._run(releases.check, current, force, False)
        # Logged either way. When this only spoke up for an available update, a
        # check that never ran looked exactly like one that found nothing.
        decky.logger.info(
            "Update check: current=%s checked=%s releases=%d available=%s%s",
            current,
            result.get("checked"),
            result.get("count", 0),
            result.get("available"),
            (" error=%s" % result["error"]) if result.get("error") else "",
        )
        return result

    #: How long to wait after a check that answered. Decky's own updater uses
    #: six hours, and six hours is four requests a day against a budget of sixty
    #: an hour that every unauthenticated caller on the address shares.
    _UPDATE_INTERVAL = 6 * 60 * 60

    #: How long to wait after a check that did *not* answer, per attempt.
    #:
    #: This replaces the fixed 30-second delay decky puts before its first check
    #: ("Internet might not immediately be up"). That delay is a guess about how
    #: long the network takes to arrive: it covers a wifi association that
    #: finishes in ten seconds and does nothing for one that finishes in four
    #: minutes -- and the cost of guessing short is not a retry, it is six hours
    #: of silence, because the loop's next move is the interval above.
    #:
    #: Climbing instead. The first check happens immediately, and a failure is
    #: retried on this ladder before settling back into the ordinary cadence, so
    #: the answer arrives whenever the network does rather than whenever the
    #: guess said it would.
    #:
    #: Four rungs inside twenty minutes: long enough to outlast a slow boot,
    #: short enough that a device with no network spends five requests every six
    #: hours failing instantly.
    _UPDATE_RETRY_DELAYS = (60, 120, 300, 600)

    async def _watch_for_updates(self):
        """Look for a newer release on a timer, and say so when there is one.

        A task rather than something the panel drives, because of what it feeds:
        the dot on the plugin's icon has to be right *before* the panel is
        opened, and a check that only runs on open can never make it so.

        Nothing here is gated on the device being a Steam Deck. `_watch_` starts
        with an underscore so the gate decorator skips it, and `check_for_update`
        is on the ungated list on purpose -- a machine the gate refuses is
        exactly the machine that may need to hear a newer version exists.

        The result is not returned anywhere. It goes into the same cache the
        panel reads, and out as an event for the icon.
        """
        attempt = 0
        while True:
            answered = False
            try:
                # Forced only on a retry. The first attempt of a cycle is happy
                # with a cached answer -- a reload ten minutes after the last
                # check should not spend a request -- but a retry exists
                # *because* the last attempt failed, and the module's own
                # failure backoff would otherwise turn every rung below fifteen
                # minutes into a call that never leaves the house.
                found = await self.check_for_update(attempt > 0)
                answered = bool(found.get("checked"))

                # Only when there is an answer. Emitting on a failed check would
                # send `available=False` -- indistinguishable from "you are up
                # to date" -- and put out a dot that a working check had lit.
                if answered:
                    # Both directions when it did answer, though: "no longer
                    # available" is a real transition, and an event that only
                    # ever means yes can light the dot but never put it out.
                    await decky.emit(
                        "update_available",
                        bool(found.get("available")),
                        (found.get("latest") or {}).get("version", ""),
                    )
            except asyncio.CancelledError:
                # decky shutting the plugin down. Must be allowed to.
                raise
            except Exception:
                # A failed check is expected here -- no network at a Deck's
                # first boot of the day is the ordinary case -- so it is logged
                # and the loop continues. Raising would end the task and there
                # would be no more checks until the next restart.
                decky.logger.exception("Update watch: could not check")

            if answered:
                attempt = 0
                delay = self._UPDATE_INTERVAL
            elif attempt < len(self._UPDATE_RETRY_DELAYS):
                delay = self._UPDATE_RETRY_DELAYS[attempt]
                attempt += 1
            else:
                # The ladder is for a network still arriving. Past the end of it
                # this is a network that is not coming, so stop climbing and
                # wait like everybody else -- and start the ladder again after,
                # because by then it may well be a different situation.
                attempt = 0
                delay = self._UPDATE_INTERVAL

            await asyncio.sleep(delay)

    async def stage_update(self):
        """Download the newest release and offer it to decky over loopback.

        Decky installs from a URL it fetches itself. Downloading here first and
        re-offering the bytes on 127.0.0.1 means the digest decky verifies is
        computed from the file actually obtained, rather than from a second trip
        to the network that could answer differently.
        """
        current = (await self.plugin_version())["version"]
        found = await self._run(releases.check, current, True, False)

        release = found.get("latest")
        if not release:
            return {"ok": False, "error": "No release to install."}

        try:
            payload = await self._run(releases.download, release)
        except Exception as error:  # noqa: BLE001 - reported, not raised, to the UI
            decky.logger.exception("Could not download the release")
            return {"ok": False, "error": "Could not download it: %s" % error}

        if not payload:
            return {"ok": False, "error": "The release could not be downloaded."}

        def _write():
            os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
            # The asset name is whatever the releases API said, so it decides a
            # path here. A basename cannot climb out of the runtime directory,
            # and an empty one falls back rather than naming the directory
            # itself. `handoff` serves this file back under the same name.
            name = os.path.basename(release.get("asset_name") or "") or "deckyemu.zip"
            path = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, name)
            with open(path, "wb") as handle:
                handle.write(payload)
            return path, hashlib.sha256(payload).hexdigest()

        path, digest = await self._run(_write)

        expected = release.get("sha256") or ""
        if expected and expected != digest:
            await self._run(os.remove, path)
            return {"ok": False, "error": "The download did not match its published digest."}

        url = await self._run(handoff.serve, path)
        if not url:
            return {"ok": False, "error": "Could not offer the download to decky."}

        decky.logger.info("Staged %s for decky at %s", release["version"], url)
        return {"ok": True, "url": url, "version": release["version"], "sha256": digest}

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











