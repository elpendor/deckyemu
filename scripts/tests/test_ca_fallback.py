#!/usr/bin/env python3
"""Discovering the OS trust store once, with several requests already failing.

    python scripts/tests/test_ca_fallback.py

Decky's frozen interpreter carries a CA bundle older than the machine's, and
thumbnails.libretro.com is served under a chain it does not know. The answer is
to retry against the OS trust store -- but artwork probes several candidate
names at once, and the flag saying "this has been looked into" went up before
the context it produces was assigned.

So every thread already inside a certificate failure read the flag, concluded
somebody had dealt with it, and gave up with the context still unset. Five
thumbnail probes died that way on the first lookup of every session -- in every
log on the device, reported as "no artwork found" and nothing else.

Nothing here touches the network.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import net  # noqa: E402


section("a discovery in progress is waited for, not read past")

_made = []


def _slow_context():
    """Stand in for reading a CA bundle off the disk, slowly enough to race."""
    time.sleep(0.05)
    context = object()
    _made.append(context)
    return context


_real = net._system_ca_context
net._system_ca_context = _slow_context
net._fallback_context = None
net._fallback_checked = False
try:
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(net._ensure_fallback_context()))
               for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    check("every caller is handed a context", [a is not None for a in answers], [True] * 6)
    check("and all of them the same one", len(set(map(id, answers))), 1)
    # The point of the flag: the bundle is read once however many probes fail
    # together, because reading it per request would be a file read per
    # thumbnail.
    check("the trust store is read once, not once per caller", len(_made), 1)
finally:
    net._system_ca_context = _real


section("a machine with no usable bundle is not asked twice")

_calls = []


def _no_context():
    _calls.append(1)
    return None


net._system_ca_context = _no_context
net._fallback_context = None
net._fallback_checked = False
try:
    check("the answer is that there is none", net._ensure_fallback_context(), None)
    check("and it stays that answer", net._ensure_fallback_context(), None)
    check("without reading the disk again", len(_calls), 1)
finally:
    net._system_ca_context = _real
    net._fallback_context = None
    net._fallback_checked = False


if __name__ == "__main__":
    summary()
