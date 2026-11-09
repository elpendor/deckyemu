#!/usr/bin/env python3
"""The DeckyEmu service: the backend, and its place inside Steam's UI.

Run by launcher.py under a systemd user unit, as the user, on SteamOS's own
Python. It

  - carries an older install's state over, once (migrate.py);
  - runs the backend -- main.Plugin, every method the panel calls -- on an
    asyncio loop;
  - keeps the panel in Steam's UI and answers its calls (injector.py);
  - serves the rescue page the library tile opens (rescue.py);
  - and, after an update, tells the launcher the new version works.

Stopping is the unit's job: SIGTERM unloads the backend and exits, and the unit
starts the service again, which is also how an update takes effect.
"""

import asyncio
import inspect
import json
import logging
import os
import signal
import sys
import threading
import time

# Resolved: the unit starts this through the `current` link, and Python resolves
# the script's own folder anyway, so the two have to agree on which path is
# ours.
APP_DIR = os.path.dirname(os.path.realpath(__file__))
os.environ.setdefault("DECKYEMU_APP_DIR", APP_DIR)
sys.path.insert(0, os.path.join(APP_DIR, "py_modules"))

import appenv  # noqa: E402
import migrate  # noqa: E402

#: Logs kept, newest first; one per start.
KEEP_LOGS = 10

#: Also kept: the newest few from runs that lasted, so a crash loop restarting
#: every two seconds cannot push out the log of what came before it.
KEEP_LIVED_LOGS = 3
LIVED_SECONDS = 60

#: How long a new version must run, with Steam's UI absent, before it counts as
#: healthy. With Steam's UI present, loading the panel is the test instead.
HEALTHY_WITHOUT_STEAM_SECONDS = 90

#: rescue.sh stamps this before starting the service. Found fresh while the
#: plugin is in use, the service stays up as the tile's page instead of off.
TILE_MARKER = os.path.join(appenv.ROOT, "run", "tile-launch")
TILE_MARKER_SECONDS = 60

#: How long that standby lasts if nothing is pressed.
STANDBY_SECONDS = 600


def _lived(path):
    """Whether the run that wrote this log lasted LIVED_SECONDS."""
    try:
        started = time.mktime(time.strptime(os.path.basename(path)[:-4], "%Y-%m-%d %H.%M.%S"))
        return os.path.getmtime(path) - started >= LIVED_SECONDS
    except (OSError, ValueError, OverflowError):
        return False


def _prune_logs():
    logs = sorted(
        (name for name in os.listdir(appenv.LOG_DIR) if name.endswith(".log")),
        reverse=True,
    )
    lived = 0
    for old in logs[KEEP_LOGS - 1:]:
        path = os.path.join(appenv.LOG_DIR, old)
        if lived < KEEP_LIVED_LOGS and _lived(path):
            lived += 1
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _logging():
    os.makedirs(appenv.LOG_DIR, exist_ok=True)
    _prune_logs()
    path = os.path.join(appenv.LOG_DIR, time.strftime("%Y-%m-%d %H.%M.%S") + ".log")
    formatter = logging.Formatter("[%(asctime)s][%(levelname)s]: %(message)s")
    to_file = logging.FileHandler(path, encoding="utf-8")
    to_file.setFormatter(formatter)
    to_journal = logging.StreamHandler(sys.stderr)
    to_journal.setFormatter(logging.Formatter("[%(levelname)s]: %(message)s"))
    appenv.logger.addHandler(to_file)
    appenv.logger.addHandler(to_journal)
    appenv.logger.setLevel(logging.INFO)
    appenv.logger.propagate = False


class Service:
    def __init__(self):
        import cdp
        import hostcalls
        import injector
        import main
        import rescue
        import selfupdate

        self.selfupdate = selfupdate
        self.loop = asyncio.new_event_loop()
        self.plugin = main.Plugin()
        self.started = time.time()
        self.healthy = False
        self.frontend_report = None
        # Set once the backend's `_main` is done. The injector and the rescue
        # page start before it, so a slow start neither misses Steam's boot nor
        # looks to the library tile like a service that is not answering.
        self.ready = threading.Event()
        self.injector = injector.Injector(APP_DIR, self.dispatch, self.ready)
        self.injector.on_bundle_started = self.mark_healthy
        self.host = hostcalls.HostCalls(self)
        self.rescue = rescue.Rescue(self.rescue_status, {
            "update": self.rescue_update,
            "rollback": self.rescue_rollback,
            "restart": self.rescue_restart,
            "take_over": self.rescue_take_over,
        })
        self.standby = self._tile_standby()
        steam_dir = os.path.join(appenv.USER_HOME, ".local", "share", "Steam")
        if os.path.isdir(steam_dir) and cdp.ensure_enabled(steam_dir):
            appenv.logger.warning("Turned on Steam's debugging port; it takes effect when Steam next starts")

    # --- calls from the panel -----------------------------------------------

    def dispatch(self, method, args, done):
        """Run one call from the panel; `done(ok, value)` when it finishes."""
        if method.startswith("host."):
            target = getattr(self.host, method[5:], None)
        elif not method.startswith("_"):
            target = getattr(self.plugin, method, None)
        else:
            target = None
        if target is None or not callable(target):
            done(False, "No such method: %s" % method)
            return

        async def run():
            result = target(*args)
            if inspect.isawaitable(result):
                result = await result
            return result

        future = asyncio.run_coroutine_threadsafe(run(), self.loop)

        def finished(f):
            try:
                done(True, f.result())
            except Exception as error:  # noqa: BLE001 - the panel shows it
                done(False, str(error) or type(error).__name__)

        future.add_done_callback(finished)

    async def _emit(self, event, *args):
        self.injector.emit(event, args)

    # --- health ---------------------------------------------------------------

    def mark_healthy(self):
        if self.healthy:
            return
        self.healthy = True
        try:
            self.selfupdate.commit()
            appenv.logger.info("Running version is healthy: %s", json.dumps(self.selfupdate.status()))
        except OSError:
            appenv.logger.exception("Could not record this version as healthy")

    def _health_without_steam(self):
        time.sleep(HEALTHY_WITHOUT_STEAM_SECONDS)
        if not self.healthy and self.injector.state.get("steam") == "not running":
            self.mark_healthy()

    # --- the rescue page
    # ------------------------------------------------------------

    def _tile_standby(self):
        """Whether the tile started this service while the other build is in use."""
        import builds

        try:
            fresh = time.time() - os.path.getmtime(TILE_MARKER) < TILE_MARKER_SECONDS
            os.remove(TILE_MARKER)
        except OSError:
            return False
        using = builds.in_use()
        return fresh and using not in (None, appenv.KIND)

    def rescue_status(self):
        if self.standby:
            blocked = getattr(self.plugin, "_blocked", None) or {}
            using = "%s %s" % (blocked.get("build") or "The other version", blocked.get("version") or "")
            return {"version": appenv.VERSION, "standby": True,
                    "checks": [("In use", using.strip(), "warn"),
                               ("This version", "off", "warn")]}
        state = self.injector.state
        versions = self.selfupdate.status()
        steam = state.get("steam") or "unknown"
        bundle = state.get("bundle") or "not loaded"
        # (label, what it is, "ok" | "bad" | "warn") for the page's status card.
        checks = [
            ("Service", "running", "ok"),
            ("Steam's UI", steam, "ok" if steam == "running" else "bad"),
            ("Quick Access tab", "showing" if state.get("rendered") else "not showing",
             "ok" if state.get("rendered") else "bad"),
            ("Panel", bundle, "ok" if bundle == "loaded" else "bad"),
        ]
        if versions.get("pending"):
            checks.append(("Update", "not yet confirmed", "warn"))
        rolled = os.path.join(appenv.ROOT, "rolled-back.json")
        if os.path.exists(rolled):
            checks.append(("Last update", "rolled back", "warn"))
        return {"version": "%s (%s)" % (appenv.VERSION, versions["current"]), "checks": checks,
                "patches": state.get("patches") or {}, "previous": versions.get("previous"),
                "versions": versions, "injector": state, "frontend": self.frontend_report}

    def rescue_update(self):
        if not self.ready.is_set():
            return False, "DeckyEmu is still starting. Try again in a moment."
        future = asyncio.run_coroutine_threadsafe(self.plugin.stage_update(), self.loop)
        result = future.result(timeout=600)
        if not result.get("ok"):
            return False, result.get("error") or "The update did not install."
        return True, "Installed %s. DeckyEmu is restarting into it." % result.get("version")

    def rescue_rollback(self):
        back = self.selfupdate.rollback()
        if not back:
            return False, "There is no earlier version to go back to."
        self.request_restart()
        return True, "Going back to %s. DeckyEmu is restarting." % os.path.basename(back)

    def rescue_take_over(self):
        """From standby: make this build the one in use, then restart Steam."""
        import subprocess

        import builds
        import claim

        if not self.standby:
            return False, "This version is already the one in use."
        # This process restarts below; its own in-use watcher must not start
        # the backend here first.
        self.plugin._switching = True
        builds.use(appenv.KIND)
        subprocess.run(["systemctl", "--user", "enable", "deckyemu.service"], check=False)
        appenv.logger.info("Taking over from the other build, from the library tile")
        # The other build polls every few seconds and lets go of the state.
        for _ in range(45):
            if not claim.held():
                break
            time.sleep(1)
        else:
            return False, "The other version did not stop. Restart the Deck and try again."
        threading.Thread(target=self._restart_steam_and_self, daemon=True).start()
        return True, "Switched to this version. Steam restarts now so its tab shows."

    def _restart_steam_and_self(self):
        import cdp

        time.sleep(2)
        try:
            page = cdp.Page(cdp.ui_page(cdp.targets())["webSocketDebuggerUrl"])
            page.evaluate("SteamClient.User.StartRestart(false)")
            page.close()
        except Exception:  # noqa: BLE001 - the switch already happened
            appenv.logger.exception("Could not restart Steam")
        self.request_restart(0.5)

    def rescue_restart(self):
        self.request_restart()
        return True, "DeckyEmu is restarting."

    def _standby_over(self):
        import subprocess

        appenv.logger.info("Nothing chosen on the tile's page; turning the service off")
        subprocess.run(["systemctl", "--user", "disable", "--now", "deckyemu.service"], check=False)

    def request_restart(self, delay=1.0):
        """Exit soon; the unit starts the service again."""
        def later():
            time.sleep(delay)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=later, daemon=True).start()

    # --- lifetime
    # ----------------------------------------------------------------

    def run(self):
        asyncio.set_event_loop(self.loop)
        appenv.listen(self._emit)
        stopping = asyncio.Event()

        def stop(*_):
            self.loop.call_soon_threadsafe(stopping.set)

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        async def lifetime():
            if self.standby:
                # Only the page: a second panel beside the other build's tab
                # would be two DeckyEmus.
                import buildhost

                buildhost.STANDBY = True
                appenv.logger.info("Started from the library tile while the other build is in use")
                timer = threading.Timer(STANDBY_SECONDS, self._standby_over)
                timer.daemon = True
                timer.start()
            else:
                self.injector.start()
            self.rescue.start()
            try:
                await self.plugin._main()
            except Exception:  # noqa: BLE001 - the panel and the rescue page stay up to say so
                appenv.logger.exception("The backend did not start")
            self.ready.set()
            threading.Thread(target=self._health_without_steam, daemon=True).start()
            await stopping.wait()
            appenv.logger.info("Stopping")
            self.injector.stop()
            self.rescue.stop()
            try:
                await asyncio.wait_for(self.plugin._unload(), 30)
            except Exception:  # noqa: BLE001
                appenv.logger.exception("Unload did not finish cleanly")

        self.loop.run_until_complete(lifetime())


UNIT = """[Unit]
Description=DeckyEmu
# An update restarts the service by stopping it; never give up on it.
StartLimitIntervalSec=0

[Service]
ExecStart=/usr/bin/python3 %h/.local/share/deckyemu/launcher.py
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
"""


def install():
    """Make the version this file is in the one that runs, and start it.

    For a first install and for a development deploy; a release installed
    from inside DeckyEmu goes through selfupdate instead. Run as the user,
    never root: everything it touches is under the user's home.
    """
    import shutil
    import subprocess

    import builds
    import selfupdate

    os.makedirs(selfupdate.APP, exist_ok=True)
    here = os.path.realpath(APP_DIR)
    if os.path.dirname(here) != os.path.realpath(selfupdate.APP):
        dest = os.path.join(selfupdate.APP, "%s-%d" % (appenv.VERSION, int(time.time())))
        shutil.copytree(here, dest, symlinks=True)
        here = dest
    selfupdate.switch(here)
    for name in selfupdate.STABLE:
        shutil.copy2(os.path.join(here, name), os.path.join(appenv.ROOT, name))
    os.chmod(os.path.join(appenv.ROOT, "rescue.sh"), 0o755)
    unit_dir = os.path.join(appenv.USER_HOME, ".config", "systemd", "user")
    os.makedirs(unit_dir, exist_ok=True)
    with open(os.path.join(unit_dir, "deckyemu.service"), "w", encoding="utf-8") as handle:
        handle.write(UNIT)
    # Installing it is choosing it: a plugin build, if installed, steps aside.
    builds.record_self(here)
    builds.use("service")
    for argv in (["systemctl", "--user", "daemon-reload"],
                 ["systemctl", "--user", "enable", "deckyemu.service"],
                 ["systemctl", "--user", "restart", "deckyemu.service"]):
        subprocess.run(argv, check=True)
    print("DeckyEmu %s installed at %s and started." % (appenv.VERSION, here))
    return 0


def uninstall():
    """Stop and remove the service and every installed version.

    Settings, records, logs and launcher scripts stay: the games already in
    Steam launch through those scripts, and a reinstall picks up where this
    left off. `rm -rf ~/.local/share/deckyemu` afterwards removes the rest.
    """
    import shutil
    import subprocess

    import selfupdate

    subprocess.run(["systemctl", "--user", "disable", "--now", "deckyemu.service"], check=False)
    unit = os.path.join(appenv.USER_HOME, ".config", "systemd", "user", "deckyemu.service")
    if os.path.exists(unit):
        os.remove(unit)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    for link in (selfupdate.CURRENT, selfupdate.PREVIOUS, selfupdate.PENDING):
        if os.path.lexists(link):
            os.remove(link)
    shutil.rmtree(selfupdate.APP, ignore_errors=True)
    shutil.rmtree(os.path.join(appenv.ROOT, "run"), ignore_errors=True)
    for name in selfupdate.STABLE + ("rolled-back.json",):
        path = os.path.join(appenv.ROOT, name)
        if os.path.exists(path):
            os.remove(path)
    print("DeckyEmu is uninstalled. Its tab leaves the Quick Access menu when Steam next starts.")
    return 0


def main():
    if "--install" in sys.argv:
        return install()
    if "--uninstall" in sys.argv:
        return uninstall()
    os.makedirs(appenv.ROOT, exist_ok=True)
    # Before the log is opened: opening it creates the folder the old logs move
    # into.
    notes = migrate.carry_over()
    _logging()
    appenv.logger.info("DeckyEmu service %s from %s", appenv.VERSION, APP_DIR)
    for note in notes:
        appenv.logger.info("Migration: %s", note)
    Service().run()
    appenv.logger.info("Stopped")
    logging.shutdown()
    # Not a normal exit: that waits for every worker thread, and one can sit in
    # a `flatpak remote-ls` for minutes -- seen holding a restart for over two.
    # The backend has unloaded by here, so there is nothing left to wait for.
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
