#!/usr/bin/env python3
"""Serving files where the sandbox has no http.server.

    python scripts/tests/test_httpshim.py

Decky Loader v3.2.9 shipped a Python without `http.server`, and `fileserver`
imported it at the top -- so the whole plugin failed to load, library and
launchers and all, over a module only the transfer server needs. The import is
allowed to fail now, and what it gave us is rebuilt from `socketserver` and
`email`, which that same Python does carry.

These checks run against the stand-in directly, whatever the host happens to
have, because the host always has the real one and would never exercise it.
"""

import os
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

import http.client as _http_client  # noqa: E402
import httpshim  # noqa: E402

section("the stand-in HTTP server, for a sandbox without http.server")

UPLOAD = b"x" * 100_000


class _Handler(httpshim._Request):  # noqa: SLF001 -- the stand-in under test
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):  # noqa: N802 -- the name the dispatcher looks for
        body = b"got " + self.path.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("X-Sent-Header", self.headers.get("X-Ask-For") or "none")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):  # noqa: N802
        # Refused without reading a byte of it, which is what the upload server
        # does to a PUT it will not take -- and the case the connection has to
        # survive being closed in.
        if self.path.startswith("/refuse"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        sent = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = b"whole" if sent == UPLOAD else b"short"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_server = httpshim._Server(("127.0.0.1", 0), _Handler)  # noqa: SLF001
_serving = threading.Thread(target=_server.serve_forever, daemon=True)
_serving.start()
_url = "http://127.0.0.1:%d" % _server.server_address[1]

try:
    # The query string stays on the path: the token and the filename a transfer
    # is addressed to both live there.
    _answer = urllib.request.urlopen(_url + "/token/pending/game.zip?fp=1")
    check("a GET reaches the handler with the whole path",
          _answer.read(), b"got /token/pending/game.zip?fp=1")
    check("with the status and headers it set",
          (_answer.status, _answer.headers.get("Content-Type")), (200, "text/plain"))

    # Request headers are what an upload carries its offset and id in.
    _request = urllib.request.Request(_url + "/x", headers={"X-Ask-For": "resume"})
    check("a request header reaches the handler",
          urllib.request.urlopen(_request).headers.get("X-Sent-Header"), "resume")

    # The whole point: a phone sending a ROM, read from the body by length.
    _put = urllib.request.Request(_url + "/upload/game.zip", data=UPLOAD, method="PUT")
    check("a PUT body arrives whole", urllib.request.urlopen(_put).read(), b"whole")

    # **A refusal has to reach the sender.** The upload server answers 404 to a
    # PUT it will not take -- a report-only session, a path outside the token --
    # and it answers without reading the body, which is the point of refusing
    # early. Close the socket with those bytes still unread and the kernel
    # sends RST instead of the response: on CI the client lost the 404 it was
    # reading and raised ConnectionResetError, while the same code answered
    # every time on Windows and on a Deck that was not busy. Reproduced on
    # Linux at a megabyte, two refusals in six.
    # Through `http.client` rather than `urlopen`, because that is the client
    # the upload page's own transfers use and the one that lost the answer:
    # `urlopen` reads the response as it goes and can have it in hand before the
    # reset lands, which hides exactly what is being checked.
    _refusing = _http_client.HTTPConnection("127.0.0.1", _server.server_port, timeout=5)
    try:
        _refusing.request("PUT", "/refuse/sneaky.sfc", body=b"x" * (1024 * 1024))
        _status = _refusing.getresponse().status
    except (ConnectionResetError, OSError) as error:
        _status = repr(error)
    finally:
        _refusing.close()
    check("a body the handler never read still gets its answer", _status, 404)

    # A method nothing implements is refused rather than hanging the connection.
    try:
        urllib.request.urlopen(urllib.request.Request(_url + "/x", method="DELETE"))
        _code = 0
    except urllib.error.HTTPError as error:
        _code = error.code
    check("a method the handler does not implement is refused", _code, 501)

    # The URL a phone is given is built from this, and the port asked for is 0
    # -- "any free one" -- so without it the server started and every read of
    # its status raised AttributeError. Which is what shipped.
    check("the port it actually got is published, as HTTPServer does",
          _server.server_port, _server.server_address[1])
    check("and it reports itself as ready", httpshim.available(), True)
finally:
    _server.shutdown()
    _server.server_close()

# **A stop has to have stopped before it returns**, which is what
# `socketserver.shutdown` guarantees and what this did not: it cleared a flag
# and returned while another thread sat inside `accept()`. A socket closed
# under a blocked call keeps the port LISTENing until that call comes back, so
# the next bind to it fails with SO_REUSEADDR already set -- and the transfer
# link somebody bookmarked came back on a different port. Checked here rather
# than by rebinding, because a rebind succeeds on Windows either way: this is
# the thing that was wrong, and it is wrong on every platform.
check("a stop does not return until the accept loop has", _serving.is_alive(), False)

# And then the port is free immediately, which is the feature this holds up: a
# remembered address is only worth keeping if it can be served again.
_again = httpshim._Server(("127.0.0.1", _server.server_port), _Handler)  # noqa: SLF001
check("so the same port takes a server again straight away",
      _again.server_port, _server.server_port)
_again.server_close()


if __name__ == "__main__":
    summary()
