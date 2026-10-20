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

#: How long a new version must run, with Steam's UI absent, before it counts as
#: healthy. With Steam's UI present, loading the panel is the test instead.
HEALTHY_WITHOUT_STEAM_SECONDS = 90


def _logging():
    os.makedirs(appenv.LOG_DIR, exist_ok=True)
    logs = sorted(
        (name for name in os.listdir(appenv.LOG_DIR) if name.endswith(".log")),
        reverse=True,
    )
    for old in logs[KEEP_LOGS - 1:]:
        try:
            os.remove(os.path.join(appenv.LOG_DIR, old))
        except OSError:
            pass
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
        self.injector = injector.Injector(APP_DIR, self.dispatch)
        self.injector.on_bundle_started = self.mark_healthy
        self.host = hostcalls.HostCalls(self)
        self.rescue = rescue.Rescue(self.rescue_status, {
            "update": self.rescue_update,
            "rollback": self.rescue_rollback,
            "restart": self.rescue_restart,
        })
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

    def rescue_status(self):
        state = self.injector.state
        versions = self.selfupdate.status()
        rows = [
            ("Version", "%s (%s)" % (appenv.VERSION, versions["current"])),
            ("Steam's UI", state.get("steam")),
            ("Quick Access tab", "showing" if state.get("rendered") else "not showing"),
            ("Panel", state.get("bundle")),
            ("Patches", ", ".join("%s: %s" % kv for kv in (state.get("patches") or {}).items()) or "none yet"),
        ]
        if versions.get("pending"):
            rows.append(("Update", "not yet confirmed working"))
        rolled = os.path.join(appenv.ROOT, "rolled-back.json")
        if os.path.exists(rolled):
            rows.append(("Last update", "rolled back after failing to start"))
        return {"rows": rows, "previous": versions.get("previous"), "versions": versions,
                "injector": state, "frontend": self.frontend_report}

    def rescue_update(self):
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

    def rescue_restart(self):
        self.request_restart()
        return True, "DeckyEmu is restarting."

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
            await self.plugin._main()
            self.injector.start()
            self.rescue.start()
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
    for argv in (["systemctl", "--user", "daemon-reload"],
                 ["systemctl", "--user", "enable", "deckyemu.service"],
                 ["systemctl", "--user", "restart", "deckyemu.service"]):
        subprocess.run(argv, check=True)
    print("DeckyEmu %s installed at %s and started." % (appenv.VERSION, here))
    return 0


def main():
    if "--install" in sys.argv:
        return install()
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
