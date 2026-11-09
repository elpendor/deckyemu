"""The service's own methods, called from the panel as `host.<name>`.

Kept apart from main.Plugin: these are about the service and the device --
listing a folder for the file picker, reporting how the panel found Steam --
not about games, and they must answer even on hardware the Plugin's gate
refuses.
"""

import base64
import hashlib
import json
import os

import appenv


class HostCalls:
    def __init__(self, service):
        self._service = service

    def list_dir(self, path, include_files=True, show_hidden=False, extensions=None):
        """One folder, folders first, for the file picker."""
        wanted = tuple("." + e.lower().lstrip(".") for e in (extensions or []) if e)
        path = os.path.expanduser(path or "/") or "/"
        real = os.path.realpath(path)
        try:
            names = os.listdir(real)
        except OSError as error:
            return {"path": path, "realpath": real, "parent": os.path.dirname(real) if real != "/" else None,
                    "entries": [], "error": error.strerror or str(error)}
        entries = []
        for name in names:
            if not show_hidden and name.startswith("."):
                continue
            full = os.path.join(real, name)
            is_dir = os.path.isdir(full)
            if not is_dir:
                if not include_files:
                    continue
                if wanted and not name.lower().endswith(wanted):
                    continue
            entries.append({"name": name, "is_dir": is_dir})
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return {"path": path, "realpath": real, "parent": os.path.dirname(real) if real != "/" else None,
                "entries": entries}

    def report_frontend(self, report):
        """What the panel found in Steam, and what it did not."""
        self._service.frontend_report = report
        missing = sorted(name for name, found in (report.get("lookups") or {}).items() if not found)
        if missing:
            appenv.logger.error("Steam components not found: %s", ", ".join(missing))
        appenv.logger.info("Panel report: %s", json.dumps(report, default=str))
        return True

    def status(self):
        return self._service.rescue_status()

    def tile(self):
        """What the library tile runs, for the panel to add to Steam.

        `art` is the tile's artwork from assets/tile, and `art_version` changes
        whenever it does, so an existing tile is given the new set.
        """
        assets = os.path.join(appenv.ROOT, "current", "assets")
        art, digest = {}, hashlib.sha256()
        for slot in ("capsule", "header", "hero", "logo"):
            try:
                with open(os.path.join(assets, "tile", slot + ".png"), "rb") as handle:
                    data = handle.read()
            except OSError:
                continue
            digest.update(data)
            art[slot] = {"data": "data:image/png;base64," + base64.b64encode(data).decode(),
                         "kind": "png"}
        return {
            "name": "DeckyEmu",
            "exe": os.path.join(appenv.ROOT, "rescue.sh"),
            "start_dir": appenv.ROOT,
            "icon": os.path.join(assets, "game-icon.png"),
            "art": art,
            "art_version": digest.hexdigest()[:16] if art else "",
        }
