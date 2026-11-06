"""What the service build does its own way, mixed into `Plugin`.

The plugin build ships a `buildhost.py` of its own in this one's place, with
the same four methods. Everything else in the backend is the same file in
both builds.
"""

import os
import signal
import threading
import time

import appenv

import plugin_base

import selfupdate


def _restart_soon(delay=2.0):
    """Ask the service to stop, after the reply has had time to reach the panel.
    The unit starts it again, from the version just switched to."""
    def later():
        time.sleep(delay)
        os.kill(os.getpid(), signal.SIGTERM)

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

    async def _host_stopping(self):
        """Early in `_unload`."""
