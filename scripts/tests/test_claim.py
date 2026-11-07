"""The lock on the state, the format stamp, and the backend staying off.

    python scripts/tests/test_claim.py

Needs /proc, as on the Deck: a lock is told live or stale by its holder's start
time there.
"""

import asyncio
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- points appenv at scratch

if not os.path.isdir("/proc/self"):
    print("SKIPPED test_claim.py: needs /proc")
    sys.exit(0)

import appenv  # noqa: E402
import claim  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import main as plugin_main  # noqa: E402

LOCK = os.path.join(appenv.ROOT, claim.LOCK)
STAMP = os.path.join(appenv.ROOT, claim.STAMP)


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f)


def _held_by(pid, **changes):
    holder = {"pid": pid, "boot": claim._boot(), "started": claim._started(pid),
              "build": "The other build", "version": "9.9.9"}
    holder.update(changes)
    _write(LOCK, holder)


section("the lock")

check("free, it is taken", claim.take(), None)
with open(LOCK, encoding="utf-8") as f:
    check("and names this process", json.load(f)["pid"], os.getpid())
claim.release()
check("and released, it is gone", os.path.exists(LOCK), False)

other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    _held_by(other.pid)
    check("held by a live process, it is refused with what that one says of itself",
          claim.take(), {"build": "The other build", "version": "9.9.9"})
    check("and release leaves somebody else's lock alone",
          (claim.release(), os.path.exists(LOCK))[1], True)

    _held_by(other.pid, started="1")
    check("a reused pid is not the holder", claim.take(), None)
    claim.release()

    _held_by(other.pid, boot="another-boot")
    check("nor is one from before a reboot", claim.take(), None)
    claim.release()
finally:
    other.kill()
    other.wait()

_held_by(other.pid)
check("a holder that died leaves a lock that is taken over", claim.take(), None)
claim.release()

_write(LOCK, ["not", "a", "lock"])
check("as does one that cannot be read", claim.take(), None)
claim.release()


section("the format stamp")

if os.path.exists(STAMP):
    os.remove(STAMP)
check("no stamp yet is fine", claim.check_format(), None)
with open(STAMP, encoding="utf-8") as f:
    check("and stamps the state", json.load(f), {"format": claim.FORMAT})

_write(STAMP, {"format": claim.FORMAT - 1})
check("an older stamp is fine", claim.check_format(), None)
with open(STAMP, encoding="utf-8") as f:
    check("and is raised to this build's", json.load(f)["format"], claim.FORMAT)

_write(STAMP, {"format": claim.FORMAT + 1})
check("a newer one is refused", claim.check_format(), claim.FORMAT + 1)
check("and blocks, without holding the lock",
      (claim.blocked(), os.path.exists(LOCK)),
      ({"reason": "format", "found": claim.FORMAT + 1, "supported": claim.FORMAT}, False))
_write(STAMP, {"format": claim.FORMAT})


section("the build in use")

import builds  # noqa: E402

IN_USE = os.path.join(appenv.ROOT, builds.IN_USE)
OTHER_APP = os.path.join(appenv.ROOT, "other-app")
os.makedirs(OTHER_APP, exist_ok=True)
OTHER = builds.other_kind()


def _other_installed(app_dir=OTHER_APP):
    _write(os.path.join(appenv.ROOT, builds.RECORDS, OTHER + ".json"),
           {"build": "The other build", "version": "9.9.9", "app_dir": app_dir})


for path in (IN_USE, STAMP):
    if os.path.exists(path):
        os.remove(path)
check("with none named, the first to start is the one in use",
      (claim.blocked(), builds.in_use()), (None, appenv.KIND))
claim.release()
check("and it recorded itself", builds.record(appenv.KIND)["app_dir"], appenv.APP_DIR)

_other_installed()
builds.use(OTHER)
check("the other one named, this one stays off, without the lock",
      (claim.blocked(), os.path.exists(LOCK)),
      ({"reason": "switched", "kind": OTHER, "build": "The other build", "version": "9.9.9"}, False))

_other_installed(os.path.join(appenv.ROOT, "uninstalled"))
check("a named build that is gone counts for nothing", (claim.blocked(), builds.in_use()),
      (None, appenv.KIND))
claim.release()

builds.use(appenv.KIND)


section("a backend that stays off")

_plugin = plugin_main.Plugin()
_plugin.loop = asyncio.new_event_loop()
_plugin._blocked = {"reason": "format", "found": claim.FORMAT + 1, "supported": claim.FORMAT}


def _call(method):
    try:
        return _plugin.loop.run_until_complete(method())
    except plugin_main.Blocked:
        return "refused"


check("refuses what reads or writes the state", _call(_plugin.list_systems), "refused")
check("and answers status with why, and nothing else", _call(_plugin.get_status),
      {"blocked": _plugin._blocked})
check("every method it still answers exists",
      sorted(name for name in plugin_main.WHILE_BLOCKED if not hasattr(_plugin, name)), [])

other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    _held_by(other.pid)
    _plugin._blocked = {"reason": "running", "build": "The other build", "version": "9.9.9"}
    check("asks again on status, and stays off while the other runs",
          _call(_plugin.get_status)["blocked"]["reason"], "running")
finally:
    other.kill()
    other.wait()
    os.remove(LOCK)


section("switching")

_plugin._blocked = None
_steps = []


async def _aside():
    _steps.append("aside")


async def _main():
    _steps.append("main")
    _plugin._blocked = None


async def _unload():
    _steps.append("unload")


_plugin._host_stepped_aside = _aside
_plugin._main = _main
_plugin._unload = _unload

_other_installed()
builds.use(OTHER)
_plugin.loop.run_until_complete(_plugin._check_in_use())
check("running, it steps aside when the other is named",
      (_steps, _plugin._blocked["reason"]), (["unload", "aside"], "switched"))

_steps.clear()
_plugin.loop.run_until_complete(_plugin._check_in_use())
check("and stays off while it is", _steps, [])

builds.use(appenv.KIND)
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    _held_by(other.pid)
    _plugin.loop.run_until_complete(_plugin._check_in_use())
    check("named again, it waits for the other to let go", _steps, [])
finally:
    other.kill()
    other.wait()
    os.remove(LOCK)
_plugin.loop.run_until_complete(_plugin._check_in_use())
check("then starts", (_steps, _plugin._blocked), (["main"], None))

_steps.clear()
_plugin._blocked = builds.switched_to(OTHER)
builds.use(OTHER)
check("taking over names this one and starts",
      (_plugin.loop.run_until_complete(_plugin.take_over()), builds.in_use(), _steps),
      ({"ok": True}, appenv.KIND, ["main"]))
_plugin._in_use_task.cancel()
_plugin.loop.run_until_complete(asyncio.sleep(0))
_plugin.loop.close()


if __name__ == "__main__":
    summary()
