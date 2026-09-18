#!/usr/bin/env python3
"""A definition fetched by address, typed where there is a keyboard.

    python scripts/tests/test_fetch_definition.py

Getting a definition onto the Deck meant sending it from another device. The
address of one is a line of text, and the only keyboard worth typing it on is
the one already in the flow -- the phone or laptop the transfer page is open on.
Game Mode's is a trackpad and an on-screen grid.

**It downloads, it does not import.** The file lands in the transfer folder and
stops, so the preview and the confirmation stay the only way in.

**Definitions only, judged by what arrives.** The suffix on the address was the
first test, and it refused every shortened link -- `bit.ly/abc123` says nothing
about what it redirects to. What is fetched is capped at a definition's size and
then has to be one, which also catches a file named like a definition that is
not.

Nothing here touches the network.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import fileserver  # noqa: E402
import net  # noqa: E402

_INBOX = os.path.join(TMP, "fetch-inbox")
os.makedirs(_INBOX, exist_ok=True)

_BODY = '{"id": "fetched", "name": "Fetched"}'


#: What a given address answers with, standing in for the network.
_ANSWERS = {}


def _fake_download(url, dest, headers=None, max_bytes=0, on_progress=None):
    if "missing" in url:
        return False, "That address answered 404."
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with io.open(dest, "w", encoding="utf-8") as handle:
        handle.write(_ANSWERS.get(url, _BODY))
    return True, ""


_real_download = net.download
net.download = _fake_download
fileserver._target_dir = _INBOX
fileserver._uploads = True
try:
    section("a link to a definition")

    _name, _error = fileserver.fetch_definition(
        "https://example.test/lists/ports.deckyemu.json")
    check("is fetched under its own name", (_name, _error),
          ("ports.deckyemu.json", ""))
    check("and the file is in the transfer folder",
          os.path.isfile(os.path.join(_INBOX, "ports.deckyemu.json")), True)
    # The same list the panel shows, so it arrives exactly as an upload does --
    # with an Import button, not installed.
    check("and it is listed as received",
          any(item["name"] == "ports.deckyemu.json" for item in fileserver._received),
          True)

    # A path that climbs, a name with a separator in it: the inbox is the only
    # place this may write, and the name comes off the address.
    _name, _error = fileserver.fetch_definition(
        "https://example.test/a/../../etc/passwd.deckyemu.json")
    check("a name that tries to climb out is flattened",
          (_name, os.path.dirname(_name)), ("passwd.deckyemu.json", ""))


    section("a shortened link, which says nothing about what it holds")

    _name, _error = fileserver.fetch_definition("https://sho.rt/abc123")
    check("is followed and kept under the name it was reached by",
          (_name, _error), ("abc123.deckyemu.json", ""))
    _name, _error = fileserver.fetch_definition("https://sho.rt/")
    check("and one with nothing to name it after still lands",
          (_name, _error), ("definitions.deckyemu.json", ""))


    section("and what is refused before a byte is read")

    for url, expected in (
        ("ftp://example.test/x.deckyemu.json", "http:// or https://"),
        ("file:///etc/passwd", "http:// or https://"),
        ("", "http:// or https://"),
    ):
        _name, _error = fileserver.fetch_definition(url)
        check("%r is refused" % (url or "(nothing)",),
              (_name, expected in _error), ("", True))

    # A name proves nothing, which is the whole reason the body is read: this
    # one ends in the suffix and holds a web page.
    _ANSWERS["https://example.test/trap.deckyemu.json"] = "<!doctype html><html>"
    _name, _error = fileserver.fetch_definition(
        "https://example.test/trap.deckyemu.json")
    check("a file named like a definition that is not one is refused",
          (_name, "not a definition" in _error), ("", True))
    check("and it is not left in the inbox under that name",
          os.path.isfile(os.path.join(_INBOX, "trap.deckyemu.json")), False)

    _ANSWERS["https://example.test/list.deckyemu.json"] = '{"definitions": []}'
    _name, _error = fileserver.fetch_definition(
        "https://example.test/list.deckyemu.json")
    check("a file holding several is a definition too", _error, "")

    _name, _error = fileserver.fetch_definition(
        "https://example.test/missing.deckyemu.json")
    # Plain words, not `str()` of a urllib exception: a page on a phone showed
    # `<urlopen error [Errno 111] Connection refused>`, which is the plugin
    # thinking aloud. The detail goes to the log.
    check("a download that fails says so in words",
          (_name, _error), ("", "The Deck could not reach that address."))

    # A server handing out a diagnostic report uses the same token, so it must
    # not also fetch files into the ROM folder -- the same rule PUT follows.
    fileserver._uploads = False
    _name, _error = fileserver.fetch_definition(
        "https://example.test/ports.deckyemu.json")
    check("and a link that takes no files refuses this too",
          (_name, "does not accept files" in _error), ("", True))
finally:
    net.download = _real_download
    fileserver._uploads = False
    fileserver._target_dir = ""


if __name__ == "__main__":
    summary()
