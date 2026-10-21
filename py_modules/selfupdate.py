"""Installing a release beside the running one, and stepping back from it.

    ~/.local/share/deckyemu/
        app/<version>/      every installed version, complete
        current  -> app/<version>   what the service runs
        previous -> app/<version>   what a rollback goes back to
        pending.json        a switch not yet proven healthy
        launcher.py         starts `current`; see launcher.py

An update never touches the version that is running. It is unpacked and
checked in a staging folder, renamed into `app/`, and the links are switched
in one rename each. The service then restarts into it, and only once the new
version reports healthy is `pending.json` removed. Until then the launcher
counts its starts, and too many puts `current` back.
"""

import json
import os
import shutil
import tarfile
import time

import appenv

APP = os.path.join(appenv.ROOT, "app")
CURRENT = os.path.join(appenv.ROOT, "current")
PREVIOUS = os.path.join(appenv.ROOT, "previous")
PENDING = os.path.join(appenv.ROOT, "pending.json")

#: What a version must have to be worth switching to.
REQUIRED = ("service.py", "main.py", "launcher.py", "py_modules/appenv.py",
            "dist/preload.js", "dist/deckyemu.js", "package.json")

#: Files copied out of a healthy version to the root, so they outlive it.
STABLE = ("launcher.py", "rescue.sh")


class Refused(Exception):
    """The release is not one to switch to; the message says why."""


def _target(link):
    return os.path.realpath(link) if os.path.islink(link) else None


def _point(link, target):
    """Make `link` point at `target`, replacing what was there in one rename."""
    temp = link + ".new"
    if os.path.lexists(temp):
        os.remove(temp)
    os.symlink(target, temp)
    os.replace(temp, link)


def _extract(archive, into):
    """Unpack a release tarball without letting any member land outside `into`
    or be anything but a file or a folder. Permission bits are kept."""
    root = os.path.realpath(into)
    try:
        tarred = tarfile.open(archive, "r:gz")
    except (tarfile.TarError, OSError) as error:
        raise Refused("the release is not a tarball: %s" % error) from error
    with tarred:
        members = tarred.getmembers()
        for member in members:
            dest = os.path.realpath(os.path.join(into, member.name))
            if dest != root and not dest.startswith(root + os.sep):
                raise Refused("the archive names a path outside itself: %s" % member.name)
            if not (member.isfile() or member.isdir()):
                raise Refused("the archive holds something that is not a file: %s" % member.name)
        tarred.extractall(into, members=members, filter="data")


def _validate(version_dir):
    missing = [name for name in REQUIRED if not os.path.isfile(os.path.join(version_dir, name))]
    if missing:
        raise Refused("the release is missing %s" % ", ".join(missing))
    for top, _dirs, files in os.walk(version_dir):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(top, name)
                # Compiled in memory: py_compile insists on writing a file, and
                # refuses /dev/null as the place to write it.
                try:
                    with open(path, "rb") as handle:
                        compile(handle.read(), path, "exec")
                except (SyntaxError, ValueError) as error:
                    raise Refused("%s does not compile: %s" % (name, error)) from error


def install(archive, version):
    """Unpack `archive` (a release tarball) as `version` and switch to it.

    Returns the new version's folder. Raises Refused, leaving the running
    version exactly as it was, if anything about the release is wrong.
    """
    os.makedirs(APP, exist_ok=True)
    staging = os.path.join(APP, ".staging-%d" % int(time.time() * 1000))
    try:
        _extract(archive, staging)
        # Releases keep everything under one top-level folder.
        entries = os.listdir(staging)
        inner = os.path.join(staging, entries[0]) if len(entries) == 1 else staging
        _validate(inner)
        name = "%s-%d" % ("".join(c for c in version if c.isalnum() or c in ".-_") or "release", int(time.time()))
        final = os.path.join(APP, name)
        os.replace(inner, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    switch(final)
    return final


def switch(target):
    """Run `target` from the next start, keeping what runs now as `previous`."""
    running = _target(CURRENT)
    if running and running != os.path.realpath(target):
        _point(PREVIOUS, running)
    _point(CURRENT, target)
    with open(PENDING + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"from": running, "to": os.path.realpath(target), "attempts": 0, "since": time.time()}, handle)
    os.replace(PENDING + ".tmp", PENDING)


def rollback():
    """Put `previous` back as `current`. Returns what is now current, or None."""
    back = _target(PREVIOUS)
    if not back or not os.path.isdir(back):
        return None
    now = _target(CURRENT)
    _point(CURRENT, back)
    if now:
        _point(PREVIOUS, now)
    if os.path.exists(PENDING):
        os.remove(PENDING)
    return back


def commit():
    """The running version is healthy: forget the switch, keep two versions,
    and refresh the files that start it."""
    if os.path.exists(PENDING):
        os.remove(PENDING)
        # A switch has now worked, so an earlier rollback is old news.
        rolled = os.path.join(appenv.ROOT, "rolled-back.json")
        if os.path.exists(rolled):
            os.remove(rolled)
    keep = {_target(CURRENT), _target(PREVIOUS)}
    if os.path.isdir(APP):
        for name in os.listdir(APP):
            path = os.path.realpath(os.path.join(APP, name))
            if path not in keep and not name.startswith(".staging-"):
                shutil.rmtree(path, ignore_errors=True)
    running = _target(CURRENT) or appenv.APP_DIR
    for name in STABLE:
        source = os.path.join(running, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(appenv.ROOT, name + ".new"))
            os.replace(os.path.join(appenv.ROOT, name + ".new"), os.path.join(appenv.ROOT, name))


def status():
    pending = None
    if os.path.exists(PENDING):
        try:
            with open(PENDING, encoding="utf-8") as handle:
                pending = json.load(handle)
        except (OSError, ValueError):
            pending = {"unreadable": True}
    versions = sorted(n for n in os.listdir(APP) if not n.startswith(".")) if os.path.isdir(APP) else []
    return {
        "current": os.path.basename(_target(CURRENT) or appenv.APP_DIR),
        "previous": os.path.basename(_target(PREVIOUS) or "") or None,
        "pending": pending,
        "versions": versions,
    }
