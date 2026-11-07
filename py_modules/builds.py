"""Which build of DeckyEmu is in use, when more than one is installed.

Each build records itself under `appenv.ROOT` every time it starts, and the
one in use is named in IN_USE. The other one stays off (see claim.py) until
the user switches. A preference naming a build that is no longer installed
counts for nothing, so uninstalling one never strands the other.
"""

import json
import os

import appenv

IN_USE = "in-use.json"
RECORDS = "builds"


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
    os.replace(temp, path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_path(kind):
    return os.path.join(appenv.ROOT, RECORDS, kind + ".json")


def record_self(app_dir=None):
    """Say this build is installed, and where."""
    _write(_record_path(appenv.KIND), {
        "build": appenv.BUILD,
        "version": appenv.VERSION,
        "app_dir": app_dir or appenv.APP_DIR,
    })


def record(kind):
    """What the build of `kind` said of itself, or None if it is not installed."""
    found = _read(_record_path(kind))
    app_dir = found.get("app_dir")
    if not isinstance(app_dir, str) or not os.path.isdir(app_dir):
        return None
    return found


def in_use():
    """The kind of build in use, or None if no installed build is named."""
    kind = _read(os.path.join(appenv.ROOT, IN_USE)).get("kind")
    if not isinstance(kind, str) or not record(kind):
        return None
    return kind


def use(kind):
    _write(os.path.join(appenv.ROOT, IN_USE), {"kind": kind})


def switched_to(kind):
    """What a build that stays off for the `kind` build says about it."""
    other = record(kind) or {}
    return {"reason": "switched", "kind": kind,
            "build": str(other.get("build") or "Another DeckyEmu"),
            "version": str(other.get("version") or "")}


def other_kind():
    return "plugin" if appenv.KIND == "service" else "service"
