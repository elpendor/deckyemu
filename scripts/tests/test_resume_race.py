#!/usr/bin/env python3
"""A resume never appends after bytes it did not count.

    python scripts/tests/test_resume_race.py

Measured on a Deck: a 6.4GB NSP finished 506,113 bytes too long. A request for
the file was still writing on a connection the sender had given up on, the
resume measured the partial, the old request wrote one more piece, and the
resume appended after it -- duplicating those bytes in the middle of the game
while the log said it had arrived whole.

Against a real server, with a stand-in for the old request that appends to the
partial *after* the resume arrives, which is the order that broke it.
"""

import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import fileserver  # noqa: E402

_DIR = os.path.join(TMP, "resume-race")
os.makedirs(_DIR, exist_ok=True)
_NAME = "Big Game.nsp"
_FP = "4000-1"
_PARTIAL = fileserver._partial_path(os.path.join(_DIR, _NAME), _FP)


def _put(base, offset, body):
    request = urllib.request.Request(
        "%s/upload/%s" % (base, urllib.parse.quote(_NAME)), data=body, method="PUT")
    request.add_header("X-Upload-Id", _FP)
    request.add_header("X-Upload-Offset", str(offset))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


section("the request a resume replaces finishes before the file is measured")

_state = fileserver.start(_DIR)
check("the server started", _state.get("error", ""), "")
_BASE = "http://127.0.0.1:%d/%s" % (_state["port"], fileserver._token)

try:
    with open(_PARTIAL, "wb") as handle:
        handle.write(b"a" * 1000)

    # The old request: registered as holding the partial, with no socket to shut
    # down, so the only way it lets go is by finishing on its own -- one more
    # write, a moment after the resume has arrived.
    fileserver._in_flight[77001] = {
        "name": _NAME, "received": 1000, "total": 4000, "at": fileserver._now(),
        "connection": None, "partial": _PARTIAL,
        "cancelled": False, "superseded": False,
    }

    def _old_request_finishes():
        time.sleep(0.4)
        with open(_PARTIAL, "ab") as late:
            late.write(b"b" * 500)
        with fileserver._state_lock:
            fileserver._in_flight.pop(77001, None)

    _old = threading.Thread(target=_old_request_finishes)
    _old.start()

    # The resume, sent believing the Deck has 1000 bytes -- which was true when
    # it asked, and stops being true before the old request lets go.
    _status = _put(_BASE, 1000, b"c" * 3000)
    _old.join()

    check("the resume is told the Deck has more than it thought, not accepted",
          _status, 409)
    check("so nothing was appended after bytes nobody counted",
          os.path.getsize(_PARTIAL), 1500)
    check("and no finished file was made out of it",
          os.path.exists(os.path.join(_DIR, _NAME)), False)

    # The sender's next attempt asks again, gets the true size, and finishes.
    check("the retry that follows, from the true size, completes",
          _put(_BASE, 1500, b"c" * 2500), 200)
    with open(os.path.join(_DIR, _NAME), "rb") as finished:
        _data = finished.read()
    check("with every byte where it belongs",
          (len(_data), _data[:1000] == b"a" * 1000, _data[1000:1500] == b"b" * 500,
           _data[1500:] == b"c" * 2500),
          (4000, True, True, True))
finally:
    fileserver._in_flight.pop(77001, None)
    fileserver.stop()


if __name__ == "__main__":
    summary()
