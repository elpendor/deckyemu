"""The injector attaches again to a page it lost while Steam kept it.

    python scripts/tests/test_injector_retry.py

It remembered the last page it attached to and skipped it from then on, so an
attach that timed out, or a connection that dropped while the page stayed,
left the panel missing until Steam made a new page. A new page must still be
attached at once: its boot is the race the injector has to win.
"""

import http.client
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import appenv  # noqa: E402
import cdp  # noqa: E402
import injector  # noqa: E402

injector.RETRY_SECONDS = 0.2
injector.RETRY_MAX_SECONDS = 0.8

_listed = [{"type": "page", "title": "SharedJSContext", "id": "A"}]
_tended = []


def _run(tend, seconds):
    """Run the injector against a fake Steam; `tend(injector, target)`."""
    real_targets = cdp.targets
    cdp.targets = lambda timeout=0.5: list(_listed)
    running = injector.Injector(".", lambda *_: None)
    running._tend = lambda target: tend(running, target)
    running.start()
    try:
        time.sleep(seconds)
    finally:
        running.stop()
        cdp.targets = real_targets
        time.sleep(0.05)


def _attached(running, target):
    """Attaches, then the connection drops while Steam keeps the page."""
    _tended.append((target["id"], time.monotonic()))
    running.state["attached_at"] = time.time()


def _fails(_running, target):
    _tended.append((target["id"], time.monotonic()))
    raise TimeoutError("no reply from Steam")


def _gaps():
    return [round(b[1] - a[1], 1) for a, b in zip(_tended, _tended[1:])]


section("a page whose connection dropped is attached again, after a pause")

_tended.clear()
_run(_attached, 0.5)
check("the same page is attached more than once", len(_tended) >= 2, True)
check("but not straight away", min(_gaps()) >= injector.RETRY_SECONDS, True)

section("one that keeps failing is tried less and less often")

# Quiet: a traceback per failed attach is the point here, not news.
appenv.logger.setLevel(logging.CRITICAL)
_tended.clear()
_run(_fails, 2.5)
appenv.logger.setLevel(logging.NOTSET)
check("the pauses double, up to the most", _gaps()[:4], [0.2, 0.4, 0.8, 0.8])

section("a new page is attached at once")

_tended.clear()
_listed[0] = dict(_listed[0], id="A")
threading.Timer(0.1, lambda: _listed.__setitem__(0, dict(_listed[0], id="B"))).start()
_run(_attached, 0.3)
check("the new page follows the old without the pause", [t[0] for t in _tended][:2], ["A", "B"])
check("within a poll or two", _gaps()[0], 0.1)

section("a listing cut short does not stop the injector")

_tended.clear()
_cut = [True]


def _listing(timeout=0.5):
    if _cut[0]:
        _cut[0] = False
        raise http.client.IncompleteRead(b"")
    return list(_listed)


_real_targets = cdp.targets
cdp.targets = _listing
_running = injector.Injector(".", lambda *_: None)
_running._tend = lambda target: _attached(_running, target)
_running.start()
time.sleep(0.2)
_running.stop()
cdp.targets = _real_targets
check("it goes on to attach", len(_tended) >= 1, True)

section("Steam reloading its UI while the panel waits for the backend")


class _Page:
    """A page whose document is replaced once, while the panel waits."""

    def __init__(self):
        self.closed = threading.Event()
        self.documents = 1
        self.rendered = True
        self.loaded_into = []

    def evaluate(self, expression, timeout=5):
        if expression.startswith("JSON.stringify"):
            return '{"rendered": %s}' % ("true" if self.rendered else "false")
        if expression.startswith("(window.__deckyemu.status"):
            return ""
        if expression == "BUNDLE":
            self.loaded_into.append((self.documents, self.rendered))
        return True


_ready = threading.Event()
_page = _Page()
_running = injector.Injector(".", lambda *_: None, _ready)
_running._read = lambda name: "BUNDLE"
_loading = threading.Event()
_running._load_bundle_soon(_page, _loading)
time.sleep(0.2)
# What the clear event does: a new document, and the bundle asked for again.
_page.documents, _page.rendered = 2, False
_running._load_bundle_soon(_page, _loading)
_ready.set()
time.sleep(0.2)
_page.rendered = True
for _ in range(50):
    if not _loading.is_set():
        break
    time.sleep(0.1)
check("the bundle waits for the new document's tab, and goes in once",
      _page.loaded_into, [(2, True)])
_page.closed.set()


if __name__ == "__main__":
    summary()
