#!/usr/bin/env python3
"""Start the installed version of DeckyEmu -- or the one before it.

This is what the systemd unit runs, from the service's root folder rather than
from any version, so that a version too broken to start at all cannot stop it
running. It counts the starts of a version not yet proven healthy (the service
removes `pending.json` once it is), and after MAX_STARTS puts the previous
version back. Standard library only, and nothing from py_modules: it has to
work when the version it would import from is the broken one.
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CURRENT = os.path.join(ROOT, "current")
PREVIOUS = os.path.join(ROOT, "previous")
PENDING = os.path.join(ROOT, "pending.json")

#: Starts allowed for a version that has not yet reported healthy.
MAX_STARTS = 3


def say(message):
    print("[deckyemu launcher] " + message, flush=True)


def point(link, target):
    temp = link + ".new"
    if os.path.lexists(temp):
        os.remove(temp)
    os.symlink(target, temp)
    os.replace(temp, link)


def check_pending():
    try:
        with open(PENDING, encoding="utf-8") as handle:
            pending = json.load(handle)
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        pending = {"attempts": MAX_STARTS}
    pending["attempts"] = int(pending.get("attempts", 0)) + 1
    if pending["attempts"] <= MAX_STARTS:
        with open(PENDING + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(pending, handle)
        os.replace(PENDING + ".tmp", PENDING)
        say("start %d of %d for %s" % (pending["attempts"], MAX_STARTS, os.path.realpath(CURRENT)))
        return
    back = os.path.realpath(PREVIOUS) if os.path.islink(PREVIOUS) else None
    failed = os.path.realpath(CURRENT)
    if back and os.path.isdir(back):
        point(CURRENT, back)
        # Not kept as `previous`: a version that never started is nowhere
        # anybody should be offered to go back to.
        os.remove(PREVIOUS)
        say("%s never reported healthy; back to %s" % (failed, back))
    else:
        say("%s never reported healthy and there is nothing to go back to" % failed)
    os.remove(PENDING)
    with open(os.path.join(ROOT, "rolled-back.json"), "w", encoding="utf-8") as handle:
        json.dump({"failed": failed, "restored": back, "at": time.time()}, handle)


def rollback():
    """Put the previous version back now; the rescue tile's last resort."""
    back = os.path.realpath(PREVIOUS) if os.path.islink(PREVIOUS) else None
    if not back or not os.path.isdir(back):
        say("nothing to roll back to")
        return 1
    failed = os.path.realpath(CURRENT)
    point(CURRENT, back)
    point(PREVIOUS, failed)
    if os.path.exists(PENDING):
        os.remove(PENDING)
    say("rolled back from %s to %s" % (failed, back))
    return 0


def main():
    if "--rollback-only" in sys.argv:
        return rollback()
    check_pending()
    service = os.path.join(CURRENT, "service.py")
    if not os.path.isfile(service):
        say("no version installed at %s" % CURRENT)
        return 1
    os.execv(sys.executable, [sys.executable, service])


if __name__ == "__main__":
    sys.exit(main())
