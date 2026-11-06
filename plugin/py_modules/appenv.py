"""Where DeckyEmu lives on the device, its log, and its line to the frontend.

The plugin build's: the same names as the service's `appenv`, read from the
loader's `decky` module, so every shared file runs unchanged in either build.
State lives under the service's root, not the loader's folders, so either build
finds what the other left; migrate.py leaves links at the loader's paths.
Outside the loader (tests, diagnose) the environment decides.
"""

import json
import logging
import os

try:
    import decky
except ImportError:
    decky = None  # type: ignore[assignment]

BUILD = "The DeckyEmu plugin"
"""How another build names this one when this one holds the state."""

KIND = "plugin"
"""Which build this is: "service" or "plugin"."""


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def _loader(name: str, default: str = "") -> str:
    return getattr(decky, name, None) or default


NAME = _loader("DECKY_PLUGIN_NAME", "DeckyEmu")

USER_HOME = _env("DECKYEMU_USER_HOME", _loader("DECKY_USER_HOME", os.path.expanduser("~")))
"""The account the plugin acts for."""
# sysenv.user_home() reads the variable, not this module.
os.environ.setdefault("DECKYEMU_USER_HOME", USER_HOME)

ROOT = _env("DECKYEMU_ROOT", os.path.join(USER_HOME, ".local", "share", "deckyemu"))
"""DeckyEmu's state, shared with the standalone service."""

APP_DIR = _env(
    "DECKYEMU_APP_DIR",
    _loader("DECKY_PLUGIN_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
"""The plugin folder: main.py, py_modules, assets, bin, dist."""

SETTINGS_DIR = os.path.join(ROOT, "settings")
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")

PREVIOUS_ROOT = _env("DECKYEMU_PREVIOUS_ROOT", _loader("DECKY_HOME", os.path.join(USER_HOME, "homebrew")))
"""The loader's own root, where its folders for this plugin are."""


def _version() -> str:
    try:
        with open(os.path.join(APP_DIR, "package.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "0")
    except (OSError, ValueError):
        return "0"


VERSION = _loader("DECKY_PLUGIN_VERSION") or _version()

logger = decky.logger if decky else logging.getLogger("deckyemu")


async def emit(event: str, *args) -> None:
    """Send an event to the frontend. Outside the loader, nobody is listening."""
    if decky:
        await decky.emit(event, *args)
