#!/usr/bin/env python3
"""That an update check survives the backend being restarted.

    python scripts/tests/test_release_cache.py

The check is cached for an hour, but the cache was module state and decky
restarts this backend whenever the plugin's files change. So the hour only ever
lasted as long as the process, and every restart spent one of the sixty
unauthenticated requests an hour the whole address shares.

That was affordable while the only caller was a button somebody pressed. The
panel asks on every open now, which is what makes the disk half worth having --
and worth being careful about, because a cache that keeps the wrong thing is
worse than no cache: it answers instantly and it answers wrongly.
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402
import net  # noqa: E402
import releases  # noqa: E402

_real_get_json = net.get_json
_real_level = decky.logger.level

#: One release, in the shape the API answers with.
_PAYLOAD = [
    {
        "tag_name": "v9.9.9",
        "body": "Notes.\nsha256: " + ("a" * 64),
        "assets": [{"name": "deckyemu.zip",
                    "browser_download_url": "https://example.com/deckyemu.zip"}],
    },
]

_asked = [0]


def _fake_get_json(url, headers=None, failure=None):
    _asked[0] += 1
    return list(_PAYLOAD)


def _refuse(url, headers=None, failure=None):
    """GitHub answering with something unusable, e.g. a rate limit."""
    _asked[0] += 1
    if failure is not None:
        failure["status"] = 403
        failure["rate_remaining"] = "0"
    return None


def _restart():
    """The same plugin coming back after decky reloaded it.

    A new process keeps nothing but the file, which is the whole point of the
    file -- so anything else surviving here would make the checks below pass for
    the wrong reason.
    """
    releases._cache.update({"releases": [], "at": 0.0, "ok": False,
                            "error": "Not checked yet.", "failed_at": 0.0})
    releases._loaded = False
    _asked[0] = 0


try:
    net.get_json = _fake_get_json
    releases.clear_cache()

    section("a check that worked is still there after a restart")

    _restart()
    check("the first check asks GitHub", (bool(releases.fetch_releases()), _asked[0]), (True, 1))
    check("and leaves an answer on disk", os.path.exists(releases.CACHE_PATH), True)

    _restart()
    _found = releases.fetch_releases()
    check("the restarted plugin still knows the release",
          [entry["version"] for entry in _found], ["9.9.9"])
    check("without asking GitHub again", _asked[0], 0)
    # `checked` is what the panel reads to tell "nothing published" apart from
    # "could not look". A cached answer is an older successful check, not a
    # failed one, and reporting it as unchecked would put an error in the panel.
    check("and reports it as a check that succeeded",
          releases.check("1.0.0")["checked"], True)

    section("but a check that failed is not kept")

    releases.clear_cache()
    net.get_json = _refuse
    decky.logger.level = logging.CRITICAL  # the failure is deliberate
    _restart()
    releases.fetch_releases()
    check("a refusal writes nothing", os.path.exists(releases.CACHE_PATH), False)
    # An hour of "GitHub is rate-limiting you" that outlived the process would
    # be this cache making a temporary problem permanent. (How soon the *same*
    # process tries again is a separate question, below.)
    _restart()
    releases.fetch_releases()
    check("so a restart tries again rather than serving the failure back",
          _asked[0], 1)
    decky.logger.level = _real_level

    section("and neither is a file that cannot be trusted")

    net.get_json = _fake_get_json

    def _write_cache(**fields):
        body = {"format": releases.CACHE_FORMAT, "at": time.time(), "releases": _PAYLOAD}
        body.update(fields)
        os.makedirs(os.path.dirname(releases.CACHE_PATH), exist_ok=True)
        with open(releases.CACHE_PATH, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        _restart()
        releases.fetch_releases()
        return _asked[0]

    # Written by a version that stored a different shape. Reading it would put
    # keys the panel expects out of reach, which is a crash rather than a stale
    # answer -- and this is a cache, so throwing it away costs one request.
    check("an older format is ignored, not read", _write_cache(format=0), 1)
    check("and so is a file that is not the right shape at all",
          _write_cache(releases="all of them"), 1)
    # A clock that has not caught up after a suspend, or a settings folder
    # restored from another machine, would otherwise hold an answer well past
    # the hour it was entitled to.
    check("a timestamp from the future does not buy extra hours",
          _write_cache(at=time.time() + 86400), 1)
    check("while an ordinary one is used", _write_cache(), 0)

    section("and a failure is not retried straight away")

    # The hole the panel opened. Nothing recorded a failure, so the next call
    # went straight back out -- and with a check on every panel open, somebody
    # being rate-limited would spend a request each time, which is what keeps
    # them rate-limited. 60 an hour is shared by a whole address; a household,
    # or a Deck beside the machine its developer is working on, reaches it
    # without anybody doing anything wrong.
    releases.clear_cache()
    net.get_json = _refuse
    decky.logger.level = logging.CRITICAL  # the failures are deliberate
    _restart()
    releases.fetch_releases()
    _asked[0] = 0
    releases.fetch_releases()
    check("a second check straight after a failure does not go back out", _asked[0], 0)

    # Waiting must not cost the explanation: the Updates tab reads these, and
    # "not checked yet" in place of "GitHub is rate-limiting this network" sends
    # somebody to look at their wifi.
    _result = releases.check("1.0.0")
    check("while the reason for the failure is still there to show",
          (_result["checked"], bool(_result["error"])), (False, True))

    _asked[0] = 0
    releases.fetch_releases(force=True)
    check("pressing check now ignores the wait, because someone asked", _asked[0], 1)

    releases._cache["failed_at"] = time.time() - releases.FAILURE_BACKOFF_SECONDS - 1
    _asked[0] = 0
    releases.fetch_releases()
    check("and once the wait is over it tries again on its own", _asked[0], 1)

    net.get_json = _fake_get_json
    releases._cache["failed_at"] = time.time()
    releases.fetch_releases(force=True)
    check("a check that works clears the wait rather than serving it out",
          releases._cache["failed_at"], 0.0)
    decky.logger.level = _real_level

    section("clearing it clears both halves")

    releases.clear_cache()
    check("the file is gone", os.path.exists(releases.CACHE_PATH), False)
    _asked[0] = 0
    releases.fetch_releases()
    check("and the next check goes to the network", _asked[0], 1)

finally:
    # The suite shares one of everything. A stub left on `net`, or an hour of
    # cached releases left behind, is a failure in whichever file runs next.
    net.get_json = _real_get_json
    decky.logger.level = _real_level
    releases.clear_cache()


if __name__ == "__main__":
    summary()
