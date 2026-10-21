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
_plugin.loop.close()


if __name__ == "__main__":
    summary()
