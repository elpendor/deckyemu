"""What the plugin build does its own way, mixed into `Plugin`.

Ships in place of the service's `buildhost.py`, with the same four methods,
plus the calls behind the panel's offer to move to the standalone service.
"""

import hashlib
import os
import shutil

import appenv

import plugin_base

import handoff
import migrate
import releases
import runtime_report
import service_switch


class BuildHost(plugin_base.PluginContext):
    async def _install_release(self, path, release, digest):
        """Offer the downloaded, verified zip to the loader over loopback.

        The loader runs as root and installs from a URL it fetches itself;
        this backend cannot write its own folder. Serving the bytes already
        checked means the digest the loader verifies is from the file actually
        obtained. The panel passes the URL on (src/updater.ts).
        """
        url = await self._run(handoff.serve, path)
        if not url:
            return {"ok": False, "error": "Could not offer the download to the loader."}
        appenv.logger.info("Staged %s for the loader at %s", release["version"], url)
        return {"ok": True, "url": url, "version": release["version"], "sha256": digest}

    async def _host_claimed(self):
        # State lives under appenv.ROOT, and nothing has read it yet.
        for note in await self._run(migrate.carry_over):
            appenv.logger.info("Migration: %s", note)

    async def _host_started(self):
        await self._run(runtime_report.report)

    async def _host_stopping(self):
        await self._run(handoff.stop)

    async def service_offer(self):
        """The standalone version the panel offers a switch to, if one is out."""
        release = await self._run(releases.other_release, "service")
        if not release:
            return {"available": False}
        return {"available": True, "version": release["version"]}

    async def switch_to_service(self):
        """Install the standalone service and hand it the state.

        This plugin stops first and releases the lock, since the service takes
        it as it starts. If the install fails, the plugin starts again.
        """
        release = await self._run(releases.other_release, "service")
        if not release:
            return {"ok": False, "error": "No standalone release is published yet."}
        try:
            payload = await self._run(releases.download, release)
        except Exception as error:  # noqa: BLE001 - reported, not raised, to the UI
            appenv.logger.exception("Could not download the service")
            return {"ok": False, "error": "Could not download it: %s" % error}
        if not payload:
            return {"ok": False, "error": "The release could not be downloaded."}
        expected = release.get("sha256") or ""
        if expected and hashlib.sha256(payload).hexdigest() != expected:
            return {"ok": False, "error": "The download did not match its published digest."}

        work = os.path.join(appenv.DATA_DIR, "service-switch")
        try:
            folder = await self._run(service_switch.unpack, payload, work)
        except service_switch.Refused as refusal:
            return {"ok": False, "error": "Not installed: %s" % refusal}

        await self._unload()
        self._blocked = {"reason": "switched", "version": release["version"]}
        worked, said = await self._run(service_switch.install, folder)
        await self._run(shutil.rmtree, work, True)
        if not worked:
            appenv.logger.error("The service did not install: %s", said)
            await self._main()
            return {"ok": False, "error": "The service did not install: %s" % (said[-300:] or "no output")}
        appenv.logger.info("Switched to the service %s: %s", release["version"], said)
        return {"ok": True, "version": release["version"]}
