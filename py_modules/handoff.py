"""Serve one downloaded file to decky, over loopback, once.

Named `handoff` rather than something generic: py_modules is appended to a
sys.path that already holds decky_loader's own packages, so a common name can
resolve to decky's module instead of this one. `updater.py` did, and only the
feature that used it failed.

Decky's loader installs a plugin by fetching a URL itself, and holds no
credentials while it does. So the backend downloads the release, then offers the
file to decky at `http://127.0.0.1:<port>/<token>/<name>`: decky fetches from
loopback, has nothing to authenticate with, and installs exactly as it would
from GitHub.

One path for every release, which is the point of it. Decky checks a digest
computed from bytes already in hand rather than trusting the network twice, and
a build aimed at a private repository keeps working -- that asset needs an
Authorization header decky would never send, and 404s for it.

Kept deliberately small:

* Bound to 127.0.0.1, so nothing off the machine can reach it at all.
* A random token in the path, compared with compare_digest.
* One file, one name. Any other path is a 404.
* Stops after the file has been served, and after a short timeout regardless --
  an install that never happens must not leave a server running.
"""

import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import decky

TOKEN_BYTES = 16

# Long enough for decky to show its confirmation dialog and for the user to read
# it, short enough that a forgotten dialog does not leave this listening.
IDLE_TIMEOUT = 10 * 60

_lock = threading.Lock()
_server = None
_token = ""
_path = ""
_name = ""
_served = False
_started = 0.0


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeckyEmuRelay"
    sys_version = ""

    def log_message(self, fmt, *args):
        decky.logger.info("relay: " + fmt, *args)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        global _served
        with _lock:
            token, path, name = _token, _path, _name

        raw = self.path.split("?", 1)[0]
        segments = [urllib.parse.unquote(part) for part in raw.split("/") if part]
        if (
            not token
            or len(segments) != 2
            or not secrets.compare_digest(segments[0], token)
            or segments[1] != name
            or not os.path.isfile(path)
        ):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

        with _lock:
            _served = True
        decky.logger.info("relay: served %s (%d bytes)", name, size)


def _watch():
    """Stop once the file has gone out, or when the window closes."""
    while True:
        time.sleep(2)
        with _lock:
            running = _server is not None
            done = _served
            expired = time.time() - _started > IDLE_TIMEOUT
        if not running:
            return
        if done:
            # A moment for the response to finish flushing before the socket goes.
            time.sleep(2)
            stop()
            return
        if expired:
            decky.logger.info("relay: nothing collected it, stopping")
            stop()
            return


def serve(path):
    """Offer `path` on loopback. Returns its URL, or "" if it cannot be served."""
    global _server, _token, _path, _name, _served, _started

    if not path or not os.path.isfile(path):
        return ""

    stop()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as error:
        decky.logger.warning("relay: could not listen: %s", error)
        return ""
    server.daemon_threads = True

    with _lock:
        _server = server
        _token = secrets.token_urlsafe(TOKEN_BYTES)
        _path = path
        _name = os.path.basename(path)
        _served = False
        _started = time.time()
        url = "http://127.0.0.1:%d/%s/%s" % (
            server.server_port,
            _token,
            urllib.parse.quote(_name),
        )

    threading.Thread(target=server.serve_forever, name="deckyemu-relay", daemon=True).start()
    threading.Thread(target=_watch, name="deckyemu-relay-watch", daemon=True).start()
    decky.logger.info("relay: offering %s on port %d", _name, server.server_port)
    return url


def stop():
    global _server, _token
    with _lock:
        server = _server
        _server = None
        _token = ""

    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except OSError as error:
            decky.logger.warning("relay: did not stop cleanly: %s", error)


def running():
    with _lock:
        return _server is not None
