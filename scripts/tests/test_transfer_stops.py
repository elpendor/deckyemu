#!/usr/bin/env python3
"""When a transfer stops, and the two ways it stopped when it should not have.

    python scripts/tests/test_transfer_stops.py

Both faults were the same shape: the Deck and the sending device disagreeing
about what was happening, because one of them was working from something stale.

**Cancel restarted the transfer.** Cancel flags the upload, shuts the socket
down and deletes the half-file. From the sender that is a dropped connection --
exactly what a flaky network looks like, and the page is built to survive one --
so it waited a second and sent the file again from the beginning. Nothing
outlived the request to say the user had said no.

**Then cancel worked and the sender did not know.** Refusing the upload stops
the bytes but cannot explain itself: a PUT carries the whole file, and a reply
sent without reading it reaches the sender as a reset connection. The page
showed "reconnecting" and then "connection lost" on a transfer somebody had
deliberately cancelled. The answer belongs on the probe, which is a GET.

**And closing the dialog stopped a transfer that had just begun.** Whether to
stop the server was decided in the dialog, from its last poll -- up to a few
seconds old. Sending a file and closing straight after read "nothing is
uploading" from a snapshot taken before the upload started.

The half with the real cost, checked hardest below: a cancellation must not stop
the same file from ever being sent again, and the dialog going away must never
end a transfer.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary, REPO_ROOT, TMP  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import fileserver  # noqa: E402

PARTIAL = os.path.join(TMP, "Some Game.iso.deckyemu-part-abc123")
OTHER = os.path.join(TMP, "Another Game.iso.deckyemu-part-def456")


def _in_flight(upload_id, partial):
    """Register an upload the way a PUT handler does, minus the socket."""
    fileserver._in_flight[upload_id] = {
        "name": os.path.basename(partial),
        "received": 0,
        "total": 100,
        "at": fileserver._now(),
        # No socket: `cancel` skips a connection of None, which is the same path
        # a sender that has already gone takes.
        "connection": None,
        "partial": partial,
        "cancelled": False,
        "superseded": False,
    }


section("a cancellation outlives the request it cancelled")

fileserver._cancelled.clear()
fileserver._in_flight.clear()

_in_flight(1, PARTIAL)
check("the upload is live before anything happens",
      fileserver._was_cancelled(1), False)

check("cancelling reports what it signalled", fileserver.cancel(1), 1)
check("and the handler is told to stop", fileserver._was_cancelled(1), True)

# The check that matters. Without this the sender's retry is indistinguishable
# from a resume, and the file starts over.
check("the file is remembered as cancelled after the request has gone",
      PARTIAL in fileserver._cancelled, True)

# Only that file. Cancelling one upload must not refuse the others.
check("and only that file", OTHER in fileserver._cancelled, False)


section("cancelling everything remembers everything")

fileserver._cancelled.clear()
fileserver._in_flight.clear()
_in_flight(2, PARTIAL)
_in_flight(3, OTHER)
check("both are signalled", fileserver.cancel(), 2)
check("and both are remembered",
      (PARTIAL in fileserver._cancelled, OTHER in fileserver._cancelled), (True, True))


section("what is remembered is bounded")

fileserver._cancelled.clear()
fileserver._in_flight.clear()
for _n in range(fileserver._CANCELLED_REMEMBERED + 20):
    _in_flight(1000 + _n, os.path.join(TMP, "file-%d.part" % _n))
fileserver.cancel()
check("a long session does not grow a list nobody reads",
      len(fileserver._cancelled), fileserver._CANCELLED_REMEMBERED)
# The newest are the ones worth keeping: a sender retries within seconds, so the
# cancellation that still has to be enforced is the most recent one.
check("and it is the most recent that are kept",
      os.path.join(TMP, "file-%d.part" % (fileserver._CANCELLED_REMEMBERED + 19))
      in fileserver._cancelled,
      True)


section("a new server session starts clean")

fileserver._cancelled.clear()
fileserver._in_flight.clear()
_in_flight(4, PARTIAL)
fileserver.cancel(4)
check("something is remembered", len(fileserver._cancelled), 1)

_session_dir = os.path.join(TMP, "cancel-session")
os.makedirs(_session_dir, exist_ok=True)
_started = fileserver.start(_session_dir)
# Asserted, because `start` reports a bad folder by returning an error rather
# than raising -- and a check that runs against a server which never started
# passes for the wrong reason.
check("the server actually started", _started.get("error", ""), "")
try:
    # Nothing cancelled against the previous server should refuse a send to this
    # one -- the same reasoning `_in_flight` is cleared here for.
    check("starting a server forgets what the last one refused",
          fileserver._cancelled, {})
finally:
    fileserver.stop()


section("the sender learns about a cancel before it sends a body")

# Against a real server, because the half that failed on the device passed every
# check that did not involve one: refusing the upload was correct and the sender
# never saw the refusal. A PUT carries the whole file, and a reply sent without
# reading it reaches the sender as a reset connection -- so what it displayed was
# "reconnecting", then "connection lost" once the retries ran out, on a transfer
# somebody had deliberately cancelled.
#
# The probe is the fix and the thing worth checking: a GET with no body, whose
# answer always arrives, asked before every attempt.

_dir = os.path.join(TMP, "cancel-http")
os.makedirs(_dir, exist_ok=True)
_state = fileserver.start(_dir)
check("the server started", _state.get("error", ""), "")

_BASE = "http://127.0.0.1:%d/%s" % (_state["port"], fileserver._token)
_NAME = "Big Game.iso"
_FP = "12345-67890"


def _pending(restart):
    """What the page asks before every attempt."""
    url = "%s/pending/%s?fp=%s&restart=%s" % (
        _BASE, urllib.parse.quote(_NAME), _FP, "1" if restart else "0")
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def _put(restart):
    """A small upload, standing in for the sender's next attempt."""
    request = urllib.request.Request(
        "%s/upload/%s" % (_BASE, urllib.parse.quote(_NAME)), data=bytes(1024),
        method="PUT")
    request.add_header("X-Upload-Id", _FP)
    request.add_header("X-Upload-Offset", "0")
    if restart:
        request.add_header("X-Upload-Restart", "1")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


try:
    check("nothing is refused before anything is cancelled",
          _pending(False), {"received": 0, "cancelled": False})

    # Cancel a live upload the way the panel does.
    _partial = fileserver._partial_path(os.path.join(_dir, _NAME), _FP)
    _in_flight(9001, _partial)
    check("the cancel is signalled", fileserver.cancel(9001), 1)

    # The check the device needed. Told here, the page shows "cancelled on the
    # Deck" instead of starting a body it is not allowed to send.
    check("a retry is told the file was cancelled, before it sends anything",
          _pending(False)["cancelled"], True)
    check("and the upload itself is refused as well, for a sender that did not ask",
          _put(False), 410)

    # The half with the real cost. A cancellation that could not be undone would
    # make the file unsendable for the rest of the session.
    check("picking the file again clears it", _pending(True)["cancelled"], False)
    check("and the upload then goes through", _put(True), 200)
    check("with nothing left refusing it", _pending(False)["cancelled"], False)
finally:
    fileserver.stop()


section("closing the dialog never stops a transfer that has started")

# The dialog decided this itself, from its last poll -- and a poll is up to a
# few seconds old. Sending a file and closing the dialog straight after read
# "nothing is uploading" from a snapshot taken before the upload began, and
# stopped the server on top of it. The sending device went on filling a socket
# that was closing, and the Deck never showed the transfer at all.
#
# Asked of the backend, the answer is the live one, so these check the decision
# where it is now made rather than the shape the dialog used to compute.

_idle_dir = os.path.join(TMP, "stop-if-idle")
os.makedirs(_idle_dir, exist_ok=True)

fileserver._in_flight.clear()
_state = fileserver.start(_idle_dir)
check("a server to test against", _state.get("error", ""), "")
check("and it is running", fileserver.status()["running"], True)

# An upload registered but not yet seen by any poll: the exact window.
_in_flight(7001, os.path.join(_idle_dir, "Arriving.iso.deckyemu-part-zz"))
_after = fileserver.stop_if_idle()
check("a transfer in flight keeps the server up", _after["running"], True)
check("and it is still the same server, not a restarted one",
      fileserver.status()["running"], True)

# The handler owns its entry, so this is what finishing looks like.
del fileserver._in_flight[7001]
_after = fileserver.stop_if_idle()
check("and once nothing is arriving it stops", _after["running"], False)

check("stopping something already stopped is not an error",
      fileserver.stop_if_idle()["running"], False)

# The unconditional Stop is a different promise and must stay one: it is the
# user ending the transfer rather than the dialog going away.
fileserver._in_flight.clear()
_state = fileserver.start(_idle_dir)
check("a server again", _state.get("error", ""), "")
_in_flight(7002, os.path.join(_idle_dir, "Arriving.iso.deckyemu-part-yy"))
check("Stop stops it even with something arriving",
      fileserver.stop()["running"], False)
fileserver._in_flight.clear()


if __name__ == "__main__":
    summary()
