#!/usr/bin/env python3
"""One update check at a time, however many callers ask at once.

    python scripts/tests/test_update_single_flight.py

The release cache already had two guards and neither covered this. A success is
kept for an hour; a failure is not retried for fifteen minutes. Both are written
when a request *finishes*, so they say nothing about one still in flight -- and
callers that overlap each saw an empty backoff and each went out.

That is measured, not imagined. While GitHub was returning 504 for this
repository, one backend process made **23 requests in about fifteen seconds**,
against an unauthenticated budget of sixty an hour. The panel wraps the check in
a retry whose per-attempt timeout is two seconds, which is right for a backend
call that takes milliseconds and wrong for one that crosses the network; decky
cannot cancel work, so every abandoned attempt left its request running and
started another. Being slow turned into being rate-limited.

So the check is single-flight. A caller that cannot have the lock takes the
cached answer rather than waiting -- an update check is not worth blocking an
executor thread for thirty seconds.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import net  # noqa: E402
import releases  # noqa: E402


def _reset():
    """Back to a cache that has answered nothing.

    `clear_cache` rather than a hand-written dict of keys. The hand-written
    version listed five of them and went stale the moment a sixth was added --
    a rate-limit window left by an earlier file then refused every check here,
    and the failure looked like the lock rather than the fixture.
    """
    releases.clear_cache()
    releases._loaded = True          # do not read the developer's own cache file


section("a caller that cannot have the lock makes no request")

# The lock is taken here rather than by racing a real request for it. The suite
# leaves `_watch_for_updates` running as a background task, so "start a slow
# request and see who else gets through" is a race this test can lose -- and it
# did, passing alone and failing in the suite. Holding the lock outright is the
# same condition without the race: it *is* what an outstanding request looks
# like to every other caller.

_calls = []


def _counting_get(url, headers=None, failure=None):
    _calls.append(url)
    return []


_reset()
_real_get = net.get_json
_real_save = releases._save_cache
net.get_json = _counting_get
releases._save_cache = lambda: None

# Wait for the background task to be out of it, so what is held is ours.
_got = releases._fetch_lock.acquire(timeout=10)
check("the lock is available to take", _got, True)
try:
    callers = [threading.Thread(target=releases.fetch_releases) for _ in range(8)]
    for thread in callers:
        thread.start()
    for thread in callers:
        thread.join(timeout=5)

    # Before the lock this was eight requests: the cache guard and the failure
    # backoff are both written when a request *finishes*, so neither says
    # anything about one still in flight.
    check("eight callers arriving mid-request add no requests", len(_calls), 0)
    # Not blocked either. An update check is not worth holding an executor
    # thread for the thirty seconds a slow GitHub can take.
    check("and none of them waited for it",
          [thread.is_alive() for thread in callers], [False] * 8)
finally:
    if _got:
        releases._fetch_lock.release()


section("with the lock free, a caller does reach the network")

_reset()
_calls.clear()
try:
    releases.fetch_releases()
    check("the request happens", len(_calls), 1)
    check("and the lock is given back",
          releases._fetch_lock.acquire(blocking=False), True)
    releases._fetch_lock.release()
finally:
    net.get_json = _real_get
    releases._save_cache = _real_save


section("and the guards it does not replace still hold")

_reset()
_calls.clear()
net.get_json = _counting_get
releases._save_cache = lambda: None
try:
    releases.fetch_releases()
    check("a first check asks", len(_calls), 1)

    # A success is good for an hour, so the second caller must not ask again --
    # this is the guard the lock sits in front of, not one it replaces.
    releases._cache["releases"] = [{"version": "1.0.0"}]
    releases._cache["at"] = time.time()
    releases.fetch_releases()
    check("a cached success is reused", len(_calls), 1)

    # `force` is somebody pressing "check now" having seen it fail. It goes
    # past the cache, and past the lock only because nothing else holds it.
    releases.fetch_releases(force=True)
    check("but force still asks", len(_calls), 2)

    # A failure is not retried for fifteen minutes.
    _reset()
    _calls.clear()
    releases._cache["failed_at"] = time.time()
    releases.fetch_releases()
    check("a recent failure is not retried", len(_calls), 0)
    check("and the lock was released, not left held",
          releases._fetch_lock.acquire(blocking=False), True)
    releases._fetch_lock.release()
finally:
    net.get_json = _real_get
    releases._save_cache = _real_save
    _reset()

summary()
