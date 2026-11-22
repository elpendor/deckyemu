"""The platform a sender picked for a file, kept until the file is checked.

The upload page can say "these are PS2 games", which matters only for formats
several systems share -- a `.chd` or `.iso`. The answer is stored by path and
read by `probe_rom` in the same place a system-named folder would be.
"""

import os
import threading

import appenv
import emulators
import jsonstore
import platforms

PATH = os.path.join(appenv.DATA_DIR, "system-hints.json")

_lock = threading.Lock()


# The Received list asks once a second while the dialog is open, so the file is
# read again only when it has changed.
_cache: dict = {"mtime": None, "hints": {}}


def _read():
    try:
        mtime = os.path.getmtime(PATH)
    except OSError:
        return {}
    if _cache["mtime"] != mtime:
        data = jsonstore.read_json(PATH, {})
        _cache["hints"] = {k: v for k, v in data.items()
                           if isinstance(k, str) and isinstance(v, str)}
        _cache["mtime"] = mtime
    return dict(_cache["hints"])


def remember(path, system):
    """Record `system` for the file at `path`, dropping hints for files now gone."""
    if not path or not system:
        return
    with _lock:
        hints = {k: v for k, v in _read().items() if os.path.exists(k)}
        hints[os.path.realpath(path)] = system
        jsonstore.write_json(PATH, hints)
        # Two writes inside one clock tick share an mtime; never trust that.
        _cache["mtime"] = None


def hint_for(path):
    """The system a sender named for `path`, or ""."""
    if not path:
        return ""
    with _lock:
        return _read().get(os.path.realpath(path), "")


def label_for(path):
    """The short label of the platform picked for `path` ("SNES"), or ""."""
    system = hint_for(path)
    return _label(system) if system else ""


def _label(database):
    """The short name people know a system by, else its full name.

    "Apple - II" cut to its last word is "II", which names nothing.
    """
    if database in platforms.SHORT_NAMES:
        return platforms.SHORT_NAMES[database]
    for label, full, short in platforms.NO_LIBRETRO_PLATFORMS:
        if database in (label, full):
            return short
    return database


def systems_for(cores):
    """[(database, label)] the upload page offers: every system an installed
    core or emulator covers, ports left out since each plays one game."""
    seen = {}
    for core in cores or []:
        if emulators.core_is_port(core.get("id")):
            continue
        for database in core.get("databases") or []:
            if database and database not in seen:
                seen[database] = _label(database)
    # Two systems under one label ("Arcade") would be one choice that is two.
    counts: dict = {}
    for label in seen.values():
        counts[label] = counts.get(label, 0) + 1
    for database, label in seen.items():
        if counts[label] > 1:
            seen[database] = database
    return sorted(seen.items(), key=lambda item: item[1].lower())


# Every system something DeckyEmu can install covers, learned in the
# background: the core catalog can need a download, and the page must not wait.
_catalog: list = []


def learn_catalog(cores):
    """Keep `cores` (core-shaped dicts) as what could be installed."""
    global _catalog
    _catalog = list(cores or [])


def offered(installed):
    """[(database, label, installed)]: installed systems first, then the rest.

    The rest are offered because games are often sent before their emulator is
    installed; the pick waits with the file and counts once it is.
    """
    have = systems_for(installed)
    known = {database for database, _label in have}
    rest = [one for one in systems_for(_catalog) if one[0] not in known]
    return ([(db, label, True) for db, label in have]
            + [(db, label, False) for db, label in rest])
