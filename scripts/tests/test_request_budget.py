#!/usr/bin/env python3
"""Every request against a rationed host is written down, spent or refused.

    python scripts/tests/test_request_budget.py

GitHub allows 60 unauthenticated requests an hour **per address**, and this
plugin has several callers on that one budget: the update check, every
non-Flatpak emulator's release listing, the xemu disk image, each firmware
fetch -- plus anything else on the same network, including a second Deck or the
machine a developer is working from.

Until this, only *failures* were logged. So the plugin could spend the whole
hour's budget leaving no record, and "why am I rate-limited when I pressed the
button twice" could only be answered by inference from what happened to fail.
The day this was added, a burst of 23 requests in fifteen seconds went unnoticed
until somebody saw a 504 in the panel, and even then the count came from the
error lines rather than from the spending.

The two things worth holding to: a *successful* request is logged too, since
that is the half that was missing, and a failed one is logged as well, because
a refused answer is charged for exactly like any other.
"""

import io
import logging
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402
import net  # noqa: E402


class _Recorder(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


_recorder = _Recorder()
_previous_level = decky.logger.level
decky.logger.addHandler(_recorder)
decky.logger.setLevel(logging.INFO)


class _Response:
    """Just enough of an HTTP response for get_bytes to read one."""

    def __init__(self, headers, payload=b"{}"):
        self.headers = headers
        self._payload = payload

    def read(self, _size=None):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


_real_urlopen = net._urlopen
try:
    section("a request that works is written down, with what is left")

    _recorder.lines.clear()
    net._urlopen = lambda request: _Response({"X-RateLimit-Remaining": "47"})
    net.get_bytes("https://api.github.com/repos/x/y/releases")
    _noted = [line for line in _recorder.lines if "GitHub request" in line]
    check("the successful request is logged", len(_noted), 1)
    # The number comes from GitHub's own header rather than a tally kept here,
    # which would drift the moment anything else on the address spent one.
    check("and says how much budget is left", "47 of the hourly budget left" in _noted[0], True)

    section("so is one that fails, because it was charged for too")

    # The 504s that started this were counted like any other request: the
    # rate limiter sits in front of the backend that timed out.
    _recorder.lines.clear()

    def _fail(request):
        raise urllib.error.HTTPError(
            request.full_url, 504, "Gateway Time-out",
            {"X-RateLimit-Remaining": "12"}, None,
        )

    net._urlopen = _fail
    decky.logger.setLevel(logging.INFO)
    net.get_bytes("https://api.github.com/repos/x/y/releases")
    _noted = [line for line in _recorder.lines if "GitHub request" in line]
    check("the failed request is logged as spending", len(_noted), 1)
    check("with the budget it left behind", "12 of the hourly budget left" in _noted[0], True)

    section("and the rest of the web is left alone")

    # One line per rationed request, nothing for anything else. Artwork,
    # thumbnails and the libretro buildbot are not on this budget and logging
    # each of them would bury the ones that matter.
    _recorder.lines.clear()
    net._urlopen = lambda request: _Response({})
    net.get_bytes("https://thumbnails.libretro.com/x/y.png")
    net.get_bytes("https://raw.githubusercontent.com/x/y/main/z")
    check("a thumbnail is not logged as budget",
          [line for line in _recorder.lines if "GitHub request" in line], [])

    section("a request is never lost to its own log line")

    _recorder.lines.clear()

    class _Hostile:
        """Headers that raise for the budget header and behave for the rest.

        Narrow on purpose: raising for everything breaks `get_bytes` at its own
        Content-Type read instead, which would pass this check while testing
        nothing about the log line.
        """

        def get(self, name, default=None):
            if "RateLimit" in name:
                raise RuntimeError("no")
            return default

    net._urlopen = lambda request: _Response(_Hostile(), b"payload")
    _body, _kind = net.get_bytes("https://api.github.com/repos/x/y/releases")
    check("the answer still comes back", _body, b"payload")
finally:
    net._urlopen = _real_urlopen
    decky.logger.removeHandler(_recorder)
    decky.logger.setLevel(_previous_level)

summary()
