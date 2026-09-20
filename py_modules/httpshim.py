"""A small stand-in for `http.server`, built from what the sandbox does carry.

**The standard library a plugin gets is decky's bundle, not Python's.** decky
ships as a PyInstaller executable and a frozen build carries only the modules
its analysis saw imported. SteamOS's own stdlib does sit on `sys.path` behind
it, so a *top-level* module missing from the bundle can still resolve there --
`glob` does -- but a submodule cannot: `http` comes from the bundle, so
`http.server` is looked for only in the bundle's `http/`, and the system's copy
is unreachable. `http.server` is in every Python 3.11 -- the Deck's own `python3` has it --
and it was in decky's bundle by way of a dependency, until v3.2.9 bumped those
and the path that pulled it in went. `fileserver` imported it at the top, so
`ModuleNotFoundError` took the whole plugin down before a single endpoint
existed: the library, the launchers and every settings page, over a module only
the transfer server needs.

**So what it provided is rebuilt, and used even where it imports.** Read out
of both released binaries: v3.2.8 packs 642 modules including `http.server`,
v3.2.9 packs 398 and does not -- the 258 that went are mostly `distutils` and
setuptools' own, which is what had been dragging `http.server` in. `socket`,
`threading`, `email` and `ssl` are all still packed, and this is built on
those. `_Request` below is the part of `BaseHTTPRequestHandler` this
plugin uses, which is seven names: `command`, `path`, `headers`, `rfile`,
`wfile`, `send_response`, `send_header`, `end_headers`, plus `log_message` for
the subclass to override.

One request per connection, answered as HTTP/1.0. That is the one real
difference from the real thing, and it costs a browser page a few extra
connections rather than anything a user can see; an upload is one long PUT
either way.
"""

import email.parser
import email.utils
import os
import socket
import threading
from typing import Any

import decky

#: Enough of the reason phrases to read a log; anything else says "Status".
REASONS = {
    200: "OK", 204: "No Content", 206: "Partial Content", 301: "Moved Permanently",
    302: "Found", 304: "Not Modified", 400: "Bad Request", 401: "Unauthorized",
    403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
    409: "Conflict", 413: "Payload Too Large", 416: "Range Not Satisfiable",
    500: "Internal Server Error", 501: "Not Implemented", 503: "Service Unavailable",
}

#: The longest request line or header line accepted, as http.server's own limit.
MAX_LINE = 65536


class _Request:
    """The part of `BaseHTTPRequestHandler` this plugin actually uses.

    Built on `socket` rather than on `socketserver`, which is the same reason
    this file exists at all: measured on a Deck, `socketserver` resolves to
    `/usr/lib/python3.13/socketserver.py` -- SteamOS's own Python, reached
    because its stdlib sits on `sys.path` behind the bundle. That works until
    SteamOS moves or drops it, and it means running 3.13 source under the
    bundle's 3.11. `socket` and `threading` are in decky's bundle, so this
    borrows nothing.
    """

    server_version = "DeckyEmu"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    #: A stalled client must not hold a thread for ever. Long enough for a slow
    #: upload to keep sending between reads.
    timeout = 300
    #: Buffered reads, unbuffered writes -- `BaseHTTPRequestHandler`'s own
    #: choice: a response is written once and must not sit in a buffer.
    rbufsize = -1
    wbufsize = 0

    def __init__(self, connection, address, server):
        self.connection = connection
        self.client_address = address
        self.server = server
        self.connection.settimeout(self.timeout)
        self.rfile = self.connection.makefile("rb", self.rbufsize)
        self.wfile = self.connection.makefile("wb", self.wbufsize)
        try:
            self.setup()
            self.handle()
        finally:
            self.finish()

    def setup(self):
        """Overridden by a handler that wants the socket configured."""

    def finish(self):
        for stream in (self.wfile, self.rfile):
            try:
                if not stream.closed:
                    stream.flush()
                stream.close()
            except OSError:
                pass
        try:
            self.connection.close()
        except OSError:
            pass

    def handle(self):
        try:
            self.handle_one_request()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as error:
            # A phone that walked out of range mid-upload is ordinary, and the
            # handler that was writing has already stopped.
            self.log_message("connection ended: %s", error)

    def handle_one_request(self):
        line = self.rfile.readline(MAX_LINE + 1)
        if not line or len(line) > MAX_LINE:
            return
        parts = line.decode("iso-8859-1").rstrip("\r\n").split()
        if len(parts) < 2:
            self.send_response(400)
            self.end_headers()
            return
        self.command, self.path = parts[0], parts[1]
        self.request_version = parts[2] if len(parts) > 2 else "HTTP/1.0"

        headers = []
        while True:
            raw = self.rfile.readline(MAX_LINE + 1)
            if not raw or raw in (b"\r\n", b"\n") or len(raw) > MAX_LINE:
                break
            headers.append(raw.decode("iso-8859-1"))
        # `email.parser` is how http.server reads them too, and it gives the
        # same case-insensitive `.get()` the handlers already call.
        self.headers = email.parser.Parser().parsestr("".join(headers))

        method = getattr(self, "do_" + self.command, None)
        if method is None:
            self.send_response(501)
            self.end_headers()
            return
        method()

    def send_response(self, code, message=None):
        self.log_request(code)
        reason = message or REASONS.get(code, "Status")
        self.wfile.write(("HTTP/1.0 %d %s\r\n" % (code, reason)).encode("latin-1"))
        self.send_header("Server", self.server_version)
        self.send_header("Date", email.utils.formatdate(usegmt=True))
        # Said outright rather than left to the client to infer, because this
        # answers one request per connection and nothing here is keep-alive.
        self.send_header("Connection", "close")

    def send_header(self, key, value):
        self.wfile.write(("%s: %s\r\n" % (key, value)).encode("latin-1"))

    def end_headers(self):
        self.wfile.write(b"\r\n")

    def send_error(self, code, message=None):
        self.send_response(code, message)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_request(self, code):
        self.log_message('"%s %s" %s', getattr(self, "command", "?"),
                         getattr(self, "path", "?"), code)

    def log_message(self, fmt, *args):
        decky.logger.info(fmt, *args)


#: How long a stop waits for the accept loop to notice. It polls twice a second,
#: so this is ten chances -- long enough that only a wedged loop reaches it, and
#: short enough that nobody watches the plugin hang on a server nobody is using.
_STOP_SECONDS = 5.0


class _Server:
    """`ThreadingHTTPServer` in the twenty lines this plugin uses of it.

    One thread per connection, as `ThreadingHTTPServer` does, and the same five
    names the callers reach for: `serve_forever`, `shutdown`, `server_close`,
    `server_address` and `server_port`.
    """

    #: Kept for the callers that set it; every thread here is a daemon anyway.
    daemon_threads = True

    def __init__(self, address, handler):
        self.handler = handler
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bound here rather than by a caller so a failure to bind raises from
        # the constructor, which is what `ThreadingHTTPServer` does and what
        # `fileserver._bind` catches to try the next port.
        self.socket.bind(address)
        self.socket.listen(16)
        self.server_address = self.socket.getsockname()
        # The port the OS actually gave us, since the caller usually asks for 0.
        # The transfer URL is built from this.
        self.server_name, self.server_port = self.server_address[:2]
        self._running = threading.Event()
        # Set while no accept loop is running, which is the state a fresh server
        # is in: `shutdown` on one that never served must not wait for a loop
        # that was never started.
        self._stopped = threading.Event()
        self._stopped.set()

    def serve_forever(self, poll_interval=0.5):
        self._running.set()
        self._stopped.clear()
        self.socket.settimeout(poll_interval)
        try:
            while self._running.is_set():
                try:
                    connection, address = self.socket.accept()
                except TimeoutError:
                    continue
                except OSError:
                    # The listening socket went while we were waiting on it,
                    # which is `server_close` from another thread and not an
                    # error.
                    break
                thread = threading.Thread(
                    target=self._serve_one, args=(connection, address), daemon=True
                )
                thread.start()
        finally:
            self._stopped.set()

    def _serve_one(self, connection, address):
        try:
            self.handler(connection, address, self)
        except Exception:  # noqa: BLE001 -- one bad request must not end the server
            decky.logger.exception("Unhandled error serving a request")
            try:
                connection.close()
            except OSError:
                pass

    def shutdown(self):
        """Stop serving, and **do not return until the accept loop has.**

        The waiting is the whole of it, and leaving it out cost the one feature
        that depends on it. `socketserver.shutdown` blocks until its loop has
        exited; this cleared a flag and returned, so `server_close` ran while
        another thread sat inside `accept()` on that socket -- and a closed
        file descriptor that a blocked call still holds keeps the port
        LISTENing until that call returns. The next bind to it got EADDRINUSE
        with `SO_REUSEADDR` already set, which reads as the port being taken by
        something else, so a remembered transfer link came back on a different
        port every time: the address somebody bookmarked, silently not theirs
        any more. Measured on the Deck, eight rebinds out of eight, and never
        on Windows -- which is why a suite that passed there said nothing.

        Bounded rather than indefinite: a loop that will not end must not take
        the plugin's shutdown with it, and the caller closes the socket next
        either way.
        """
        self._running.clear()
        self._stopped.wait(_STOP_SECONDS)

    def server_close(self):
        # The same wait, because closing is what the port hangs on: a caller
        # that closes without shutting down first is the case this is for.
        self._running.clear()
        self._stopped.wait(_STOP_SECONDS)
        try:
            self.socket.close()
        except OSError:
            pass


#: The stand-ins, always, even where `http.server` imports. decky has said it
#: will pack it again, and preferring it then would switch every Deck back to a
#: server nothing has been tested against since v3.2.9, on decky's schedule.
BASE: Any = _Request
SERVER: Any = _Server


def available():
    """Whether a server can be started at all. Always true now, and asked
    anyway: the next runtime to lose a module should cost one feature, not the
    plugin."""
    return SERVER is not None


#: What to tell the user when it cannot. Names decky rather than the plugin: it
#: is decky's runtime that decides, and no plugin update can add a module to it.
UNAVAILABLE = (
    "This version of Decky Loader bundles no way for this plugin to serve "
    "files, so the transfer server cannot start."
)


def borrowed():
    """Log every module loaded from outside decky's bundle.

    decky's executable carries only the standard library its build saw
    imported, and SteamOS's own Python sits on `sys.path` behind it -- so an
    import can quietly resolve to `/usr/lib/python3.13/...`, work for a year,
    and fail the day either side changes. `http.server` was that failure, and it
    stopped the whole plugin loading.

    Nothing here acts on it. It is one line in the log, so a later breakage can
    be read rather than investigated.
    """
    import sys

    inside = getattr(sys, "_MEIPASS", "")
    outside = []
    for name, module in sorted(sys.modules.items()):
        if name.startswith("_") or "." in name:
            continue
        origin = getattr(module, "__file__", None)
        if not origin or (inside and origin.startswith(inside)):
            continue
        # A bare name is how the bundle reports its own: `struct.py` rather than
        # a path. Measured on a Deck -- `struct` reads as bundled this way, and
        # `difflib` as `/usr/lib/python3.13/difflib.py`, which is the case this
        # line exists to name.
        if not os.path.isabs(origin):
            continue
        # The plugin's own modules live outside the bundle by definition.
        if decky.DECKY_PLUGIN_DIR and origin.startswith(decky.DECKY_PLUGIN_DIR):
            continue
        outside.append("%s=%s" % (name, origin))
    if outside:
        decky.logger.info("Loaded from outside decky's bundle: %s", "; ".join(outside))


def report():
    """One log line saying what this Python is and what it carries.

    Written at every start. When a decky build changes its runtime again, the
    first question is which modules went, and the answer should already be in
    the log rather than needing a build to find out.
    """
    import sys

    carried = []
    for name in ("http.server", "socketserver", "email", "urllib.request",
                 "aiohttp", "ssl", "ctypes", "sqlite3", "xml.etree.ElementTree"):
        try:
            # `find_spec`, not an import: asking must not answer the question.
            # Importing each name put `socketserver` into `sys.modules` from
            # SteamOS's Python, and `borrowed` below then reported a module
            # nothing in the plugin uses. `importlib` is frozen into every
            # CPython, so it is here whatever decky bundled.
            import importlib.util

            if importlib.util.find_spec(name) is None:
                continue
        except Exception:  # noqa: BLE001 -- a parent that will not import counts as missing
            continue
        carried.append(name)
    decky.logger.info(
        "Python %s in this sandbox carries: %s",
        sys.version.split()[0], ", ".join(carried) or "none of the ones checked",
    )
    borrowed()
