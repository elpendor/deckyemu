"""Whether this backend may use the state under `appenv.ROOT` at all.

Two checks, both run first thing at start. Another DeckyEmu build may hold the
state already: two backends writing the same JSON files lose each other's
changes. And the state may have been written by a newer build, whose files this
one could misread. Either way the backend stays off and the panel says why.

The lock is a file naming its holder. A holder that died without removing it is
told apart by its process start time, so a reused pid does not keep it held.
"""

import json
import os

try:
    import fcntl
except ImportError:  # Windows, where only the tests run
    fcntl = None  # type: ignore[assignment]

import appenv
import builds

#: The format of what is stored under appenv.ROOT. Raise it when a stored file
#: changes in a way the previous build would misread; never lower it.
FORMAT = 1

LOCK = "running.json"
STAMP = "format.json"


def _path(name):
    return os.path.join(appenv.ROOT, name)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _started(pid):
    """The process's start time in clock ticks since boot, or "" if unknown."""
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as f:
            # The command name may hold spaces; the fields after it do not.
            return f.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError, ValueError):
        return ""


def _boot():
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _alive(holder):
    pid = holder.get("pid")
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    if holder.get("boot") != _boot():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return holder.get("started") == _started(pid)


def held():
    """What the live build holding the lock says of itself, or None."""
    holder = _read(_path(LOCK))
    return holder if _alive(holder) else None


def take():
    """Hold the lock. Returns None, or what the build holding it says of itself."""
    os.makedirs(appenv.ROOT, exist_ok=True)
    me = {
        "pid": os.getpid(),
        "boot": _boot(),
        "started": _started(os.getpid()),
        "build": appenv.BUILD,
        "version": appenv.VERSION,
    }
    # Every taker reads and replaces the lock under this guard, so two builds
    # starting together cannot both clear a stale lock and both take it.
    with open(_path(LOCK + ".guard"), "a", encoding="utf-8") as guard:
        if fcntl:
            fcntl.flock(guard, fcntl.LOCK_EX)
        holder = _read(_path(LOCK))
        if _alive(holder):
            return {"build": str(holder.get("build") or "Another DeckyEmu"),
                    "version": str(holder.get("version") or "")}
        if os.path.exists(_path(LOCK)):
            appenv.logger.info("Lock: %s left by %s, which is gone", LOCK, holder or "nobody")
        # Replaced whole, so `held()` never reads a half-written lock.
        temp = _path(LOCK + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(me, f)
        os.replace(temp, _path(LOCK))
        return None


def release():
    """Give the lock up, if it is ours."""
    if _read(_path(LOCK)).get("pid") == os.getpid():
        try:
            os.remove(_path(LOCK))
        except FileNotFoundError:
            pass


def check_format():
    """None if this build can read the stored state, else the newer format found.

    Stamps the state with FORMAT when it is older or has no stamp yet, so call it
    only while holding the lock.
    """
    found = _read(_path(STAMP)).get("format")
    if isinstance(found, int) and found > FORMAT:
        return found
    if found != FORMAT:
        temp = _path(STAMP + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({"format": FORMAT}, f)
        os.replace(temp, _path(STAMP))
    return None


def blocked():
    """The checks, in order. None, or why this backend has to stay off.

    First, whether the user switched to the other build (builds.py). With no
    build named, the first to take the lock becomes the one in use.
    """
    os.makedirs(appenv.ROOT, exist_ok=True)
    builds.record_self()
    using = builds.in_use()
    if using and using != appenv.KIND:
        return builds.switched_to(using)
    holder = take()
    if holder:
        return dict(holder, reason="running")
    if not using:
        builds.use(appenv.KIND)
    try:
        newer = check_format()
    except Exception:
        release()
        raise
    if newer:
        release()
        return {"reason": "format", "found": newer, "supported": FORMAT}
    return None
