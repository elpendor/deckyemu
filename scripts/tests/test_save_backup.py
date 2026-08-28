#!/usr/bin/env python3
"""Reading a save backup off the device, on the server that already sends files in.

    python scripts/tests/test_save_backup.py
"""

import io
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import fileserver  # noqa: E402

section("a staged file is offered, and withdrawing it takes it away")

_staged = os.path.join(TMP, "backup-staging")
os.makedirs(_staged, exist_ok=True)
_archive = os.path.join(_staged, "deckyemu-saves-20260828-120000.zip")
with io.open(_archive, "wb") as _handle:
    _handle.write(b"PK\x03\x04 pretend archive")

_incoming = os.path.join(TMP, "backup-incoming")
os.makedirs(_incoming, exist_ok=True)

# `uploads=False`: a server that exists to hand something out must not also be a
# writable inbox. Anyone shown the QR code would otherwise be able to write into
# the ROM folder, which is not what handing over a backup offers and not
# something they could tell they had been given.
_served = fileserver.start(_incoming, uploads=False)

if _served.get("error"):
    print("SKIP file server (%s)" % _served["error"])
else:
    _root = "http://127.0.0.1:%d" % _served["port"]
    _token = fileserver.current_token()

    def _get(path):
        try:
            with urllib.request.urlopen(_root + path, timeout=5) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, b"", {}

    check("nothing is offered before anything is staged",
          fileserver.status()["download_url"], "")
    check("and asking for one is a 404 rather than an empty file",
          _get("/%s/download" % _token)[0], 404)

    fileserver.offer_download(_archive, os.path.basename(_archive), 21, ["RetroArch"])
    _status = fileserver.status()
    check("offering one puts a whole address in the status",
          _status["download_url"].endswith("/%s/download" % _token), True)
    check("with the name, which carries the date it was taken",
          _status["download_name"], "deckyemu-saves-20260828-120000.zip")

    _code, _body, _headers = _get("/%s/download" % _token)
    check("the file itself comes back", (_code, _body), (200, b"PK\x03\x04 pretend archive"))
    # Without this the browser saves it as "download", and a second backup then
    # silently replaces the first in somebody's downloads folder.
    check("named by the server rather than by the link",
          _headers.get("Content-Disposition"),
          'attachment; filename="deckyemu-saves-20260828-120000.zip"')

    # Whoever came in by the six-digit code lands on the index, and on a server
    # that only hands a backup over, the backup is the page.
    _page = _get("/%s/" % _token)[1].decode()
    check("the index is the download page", "<h1>Save backup</h1>" in _page, True)
    check("which says what is in it", "RetroArch" in _page, True)
    check("and links at the file", ("/%s/download" % _token) in _page, True)

    # The file is the caller's to delete, and it may do so while an offer stands.
    # Answering 404 is the same answer as never having offered it.
    os.remove(_archive)
    check("a backup deleted underneath the offer is a 404, not a traceback",
          _get("/%s/download" % _token)[0], 404)

    fileserver.offer_download("")
    check("withdrawing clears the address", fileserver.status()["download_url"], "")

    section("a server handing a file out does not accept files")

    _put = urllib.request.Request(_root + "/%s/upload/rom.sfc" % _token,
                                  data=b"rom", method="PUT")
    try:
        with urllib.request.urlopen(_put, timeout=5) as _response:
            _refused = _response.status
    except urllib.error.HTTPError as _error:
        _refused = _error.code
    check("a PUT is refused", _refused, 404)

    section("a download in flight keeps the server up")

    # The other direction of the guard that protects an upload. It was missing:
    # the report this borrowed its shape from is one page load, so nothing could
    # be interrupted, and a 75MB save backup over wifi is not that.
    check("nothing streaming means nothing to protect",
          fileserver.status()["downloading"], 0)

    import threading  # noqa: E402 - only this check needs it

    _slow = os.path.join(_staged, "slow.zip")
    with io.open(_slow, "wb") as _handle:
        _handle.write(b"x" * (4 * 1024 * 1024))
    fileserver.offer_download(_slow, "slow.zip", 4 * 1024 * 1024, ["RetroArch"])

    _seen = []

    def _read_slowly():
        with urllib.request.urlopen(_root + "/%s/download" % _token, timeout=10) as response:
            # Read one chunk, then let the main thread look before finishing.
            response.read(1024)
            _seen.append(fileserver.stop_if_idle().get("running"))
            response.read()

    _reader = threading.Thread(target=_read_slowly)
    _reader.start()
    _reader.join(timeout=15)
    check("stop_if_idle leaves it running while a file is going out", _seen, [True])
    check("and it is idle again once the download finishes",
          fileserver.status()["downloading"], 0)
    fileserver.offer_download("")
    os.remove(_slow)

    section("stopping the server forgets what it was offering")

    with io.open(_archive, "wb") as _handle:
        _handle.write(b"PK\x03\x04 second")
    fileserver.offer_download(_archive, os.path.basename(_archive), 15, ["Vita3K"])
    fileserver.stop()
    check("a stopped server offers nothing", fileserver.status()["download_url"], "")
    # Forgotten, not deleted: whoever built it owns removing it, and the address
    # it was offered at has stopped existing anyway.
    check("but the file it was offering is left where it was",
          os.path.isfile(_archive), True)

if __name__ == "__main__":
    summary()
