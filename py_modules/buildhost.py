"""What the service build does its own way, mixed into `Plugin`.

The plugin build ships a `buildhost.py` of its own in this one's place, with
the same methods. Everything else in the backend is the same file in
both builds.
"""

import os
import signal
import subprocess
import threading
import time

import appenv
import builds

import plugin_base

import selfupdate

UNIT = "deckyemu.service"

#: Set by the service when the library tile started it while the other build
#: is in use; it then stays up to serve the tile's page (service.py).
STANDBY = False

#: Called once the backend starts as the build in use; the service ends its
#: standby on it.
ON_STARTED = None


def _restart_soon(delay=2.0):
    """Ask the service to stop, after the reply has had time to reach the panel.
    The unit starts it again, from the version just switched to."""
    def later():
        time.sleep(delay)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=later, daemon=True).start()


def _turn_off_soon(delay=2.0):
    """Stop the service and keep it from starting at login, after the reply
    has had time to reach the panel. Switching back turns it on again."""
    def later():
        time.sleep(delay)
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT], check=False)

    threading.Thread(target=later, daemon=True).start()


class BuildHost(plugin_base.PluginContext):
    async def _install_release(self, path, release, digest):
        """Install the downloaded, verified release at `path` beside this one,
        and restart into it. The launcher goes back if it never reports
        healthy."""
        try:
            installed = await self._run(selfupdate.install, path, release["version"])
        except selfupdate.Refused as refusal:
            return {"ok": False, "error": "Not installed: %s" % refusal}
        finally:
            await self._run(os.remove, path)

        appenv.logger.info("Installed %s at %s; restarting into it", release["version"], installed)
        _restart_soon()
        return {"ok": True, "version": release["version"], "sha256": digest, "restarting": True}

    async def _host_claimed(self):
        """Once `_main` holds the state, before anything reads it. The service
        carried older state over already, before its log was opened."""

    async def _host_started(self):
        """Once `_main` has run its startup steps."""
        if ON_STARTED:
            ON_STARTED()

    async def _host_stopping(self):
        """Early in `_unload`."""

    async def _host_stepped_aside(self):
        """The other build is in use: this service stays off, at login too."""
        if STANDBY:
            return
        appenv.logger.info("Turning the service off")
        _turn_off_soon()

    async def _host_switch_offer(self):
        found = await self._run(builds.record, "plugin")
        if not found:
            return {"available": False}
        return {"available": True, "to": "plugin", "installed": True,
                "version": str(found.get("version") or "")}

    async def _host_switch(self):
        found = await self._run(builds.record, "plugin")
        if not found:
            return {"ok": False, "error": "The plugin version is not installed."}
        await self._run(builds.use, "plugin")
        await self._step_aside("plugin")
        return {"ok": True, "version": str(found.get("version") or "")}
