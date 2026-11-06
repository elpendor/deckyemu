"""One log line at every start saying what the loader's Python carries.

The loader ships as a PyInstaller executable, and a frozen build carries only
the standard library its analysis saw imported. SteamOS's own Python sits on
`sys.path` behind it, so an import can quietly resolve outside the bundle, work
for a year, and fail the day either side changes: `http.server` went missing
from the bundle in v3.2.9 and took the whole plugin down. When the runtime
changes again, the log should already say which modules went.
"""

import os
import sys

import appenv


def borrowed():
    """Log every module loaded from outside the loader's bundle. Nothing acts
    on it; a later breakage can be read rather than investigated."""
    inside = getattr(sys, "_MEIPASS", "")
    outside = []
    for name, module in sorted(sys.modules.items()):
        if name.startswith("_") or "." in name:
            continue
        origin = getattr(module, "__file__", None)
        if not origin or (inside and origin.startswith(inside)):
            continue
        # A bare name is how the bundle reports its own: `struct.py` rather
        # than a path. Measured on a Deck.
        if not os.path.isabs(origin):
            continue
        # Our own modules live outside the bundle by definition.
        if appenv.APP_DIR and origin.startswith(appenv.APP_DIR):
            continue
        outside.append("%s=%s" % (name, origin))
    if outside:
        appenv.logger.info("Loaded from outside the loader's bundle: %s", "; ".join(outside))


def report():
    """What this Python is and which of the modules worth knowing about it has."""
    import importlib.util

    carried = []
    for name in ("http.server", "socketserver", "email", "urllib.request",
                 "aiohttp", "ssl", "ctypes", "sqlite3", "xml.etree.ElementTree"):
        # `find_spec`, not an import: importing each put it into `sys.modules`
        # from SteamOS's Python, and `borrowed` then reported a module nothing
        # uses.
        try:
            if importlib.util.find_spec(name) is None:
                continue
        except Exception:  # noqa: BLE001 -- a parent that will not import counts as missing
            continue
        carried.append(name)
    appenv.logger.info(
        "Python %s in this sandbox carries: %s",
        sys.version.split()[0], ", ".join(carried) or "none of the ones checked",
    )
    borrowed()
