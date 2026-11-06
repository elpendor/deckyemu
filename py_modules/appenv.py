"""Where DeckyEmu lives on the device, its log, and its line to the frontend.

Everything is read from the environment once, at import, so the test harness
and the diagnose tool can point the whole backend at another tree by setting a
few variables before the first import. The service sets none of them and gets
the defaults below.
"""

import json
import logging
import os

NAME = "DeckyEmu"

BUILD = "The DeckyEmu service"
"""How another build names this one when this one holds the state."""

KIND = "service"
"""Which build this is: "service" or "plugin"."""


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


USER_HOME = _env("DECKYEMU_USER_HOME", os.path.expanduser("~"))
"""The account the service acts for."""

ROOT = _env("DECKYEMU_ROOT", os.path.join(USER_HOME, ".local", "share", "deckyemu"))
"""Everything DeckyEmu owns: the installed versions and the state below."""

APP_DIR = _env("DECKYEMU_APP_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""The version that is running: main.py, py_modules, assets, bin, dist."""

SETTINGS_DIR = os.path.join(ROOT, "settings")
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")

PREVIOUS_ROOT = _env("DECKYEMU_PREVIOUS_ROOT", os.path.join(USER_HOME, "homebrew"))
"""Where installs before the standalone service kept their state. Read only to
carry it over (see migrate.py) and to adopt a library an older build left."""


def _version() -> str:
    try:
        with open(os.path.join(APP_DIR, "package.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "0")
    except (OSError, ValueError):
        return "0"


VERSION = _version()

logger = logging.getLogger("deckyemu")

_listeners: list = []


def listen(callback) -> None:
    """Have every `emit` delivered to `callback(event, *args)`, a coroutine."""
    _listeners.append(callback)


async def emit(event: str, *args) -> None:
    """Send an event to the frontend. Nobody listening is not an error."""
    for callback in list(_listeners):
        try:
            await callback(event, *args)
        except Exception:
            logger.exception("Could not deliver %s", event)
