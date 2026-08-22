#!/usr/bin/env python3
"""Cancelling a transfer stops it, instead of restarting it a second later.

    python scripts/tests/test_cancel_stays_cancelled.py

Cancel flags the upload, shuts the socket down and deletes the half-file. From
the sender that is a dropped connection -- which is exactly what a flaky network
looks like, and the page is built to survive one, so it waited a second and sent
the file again from the beginning. The row disappeared off the Deck and came
back at 0%, which reads as Cancel not working at all.

Nothing was wrong with either half on its own. The gap was that a cancellation
did not outlive the request it cancelled, so by the time the sender came back
there was nothing left that knew the user had said no.

The other half of the fix is the part with a real cost if it is got wrong:
a cancellation must not stop the same file from ever being sent again. Only the
sender can tell a retry from a person picking the file a second time, so it says
which one it is, and the checks below cover both.
"""

import os
import sys

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


section("the sender is what tells a retry from a fresh pick")

# Not the header handling itself -- that needs the HTTP server, and
# test_backend.py drives one -- but the contract the two ends share. A page that
# stops sending the header, or a server that stops reading it, breaks the half
# of this with the real cost: the file could never be sent again.
def _module_source(name):
    with open(os.path.join(REPO_ROOT, "py_modules", name), encoding="utf-8") as handle:
        return handle.read()


_source = _module_source("fileserver_page.py")
check("the page announces a first attempt", "X-Upload-Restart" in _source, True)
check("and only on a first attempt, not on a retry",
      "job.tries === 1" in _source, True)
check("and treats the Deck's refusal as final rather than retrying it",
      "request.status === 410" in _source, True)

_server_source = _module_source("fileserver.py")
check("the server reads the same header the page sends",
      "X-Upload-Restart" in _server_source, True)
check("and answers a refused file with the status the page treats as final",
      "self._send(410," in _server_source, True)


if __name__ == "__main__":
    summary()
