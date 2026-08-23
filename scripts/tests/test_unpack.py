#!/usr/bin/env python3
"""Unpacking a zip in the transfer folder, and the four ways it must refuse.

    python scripts/tests/test_unpack.py

The feature exists because Xenia cannot read a zip and every XBLA release is
distributed as one, so the only route from "sent to the Deck" to "playable" ran
through Desktop Mode. What is checked here is mostly the refusals: an extraction
that goes wrong quietly is worse than one that does not happen, because these
are files somebody sent over wifi and the original is the only way back.
"""

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary, TMP  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import unpack  # noqa: E402

ROOT = os.path.join(TMP, "unpack")


def _folder(label):
    path = os.path.join(ROOT, label)
    os.makedirs(path, exist_ok=True)
    return path


def _zip(folder, name, members):
    """A zip at `folder/name` holding {archive path: bytes}."""
    path = os.path.join(folder, name)
    with zipfile.ZipFile(path, "w") as bundle:
        for inner, payload in members.items():
            bundle.writestr(inner, payload)
    return path


section("the case it was built for: an XBLA container buried in folders")

_xbla = _folder("xbla")
# The real layout, taken from a Banjo-Kazooie release: one file, no extension,
# under <TitleID>/<content type>/. `LIVE` is the header Xenia dispatches on.
_archive = _zip(_xbla, "Banjo-Kazooie (XBLA).zip", {
    "58410954/000D0000/DA78E477AA5E31A7D01AE8F84109FD4B": b"LIVE" + bytes(64),
})
_written, _error = unpack.into_folder(_archive, _xbla)
check("it unpacks", _error, "")
# Named after the zip, not after itself. Its own name is a hash: unreadable in
# the received list, and nothing for the artwork search to match, so the game
# would reach Steam titled DA78E477... with no cover.
check("a lone extensionless member takes the zip's name",
      _written, ["Banjo-Kazooie (XBLA)"])
check("and the file is really there",
      os.path.isfile(os.path.join(_xbla, "Banjo-Kazooie (XBLA)")), True)
check("with its contents intact",
      open(os.path.join(_xbla, "Banjo-Kazooie (XBLA)"), "rb").read(4),
      b"LIVE")
# Extracting leaves the archive alone; consuming it is the endpoint's call, and
# tests/test_definition_inbox.py checks that half.
check("extracting on its own does not delete the archive",
      os.path.isfile(_archive), True)
check("and nothing was left half-written",
      [n for n in os.listdir(_xbla) if n.endswith(".deckyemu-tmp")], [])


section("it does not write outside the folder it was given")

_escape = _folder("escape")
# The reason members are flattened rather than extracted as named. These arrive
# over wifi from a phone, and `extractall` would honour both of these.
_archive = _zip(_escape, "nasty.zip", {
    "../../escaped.txt": b"no",
    "/absolute.txt": b"no",
})
_written, _error = unpack.into_folder(_archive, _escape)
check("both members are written by basename alone",
      sorted(_written), ["absolute.txt", "escaped.txt"])
check("so nothing lands above the destination",
      os.path.exists(os.path.join(ROOT, "escaped.txt")), False)
check("and nothing lands at the root of the filesystem",
      os.path.exists(os.path.join(os.path.abspath(os.sep), "absolute.txt")), False)


section("what it refuses, before writing a byte")

_clash = _folder("clash")
_archive = _zip(_clash, "two-discs.zip", {
    "disc1/game.bin": b"a",
    "disc2/game.bin": b"b",
})
_written, _error = unpack.into_folder(_archive, _clash)
check("two members with one basename are refused", _written, [])
check("and the reason names the file", "game.bin" in _error, True)
check("with nothing written", sorted(os.listdir(_clash)), ["two-discs.zip"])

_taken = _folder("taken")
_archive = _zip(_taken, "again.zip", {"game.bin": b"new"})
with open(os.path.join(_taken, "game.bin"), "wb") as _handle:
    _handle.write(b"original")
_written, _error = unpack.into_folder(_archive, _taken)
check("a name already in the folder is refused rather than replaced", _written, [])
check("and the file that was there is untouched",
      open(os.path.join(_taken, "game.bin"), "rb").read(), b"original")

_broken = _folder("broken")
_path = os.path.join(_broken, "truncated.zip")
with open(_path, "wb") as _handle:
    _handle.write(b"PK\x03\x04 and then nothing")
_written, _error = unpack.into_folder(_path, _broken)
check("a file that is not a zip is refused", _written, [])
check("and says so in words rather than a traceback",
      "does not look like a zip" in _error, True)

_empty = _folder("empty")
_archive = _zip(_empty, "nothing.zip", {})
_written, _error = unpack.into_folder(_archive, _empty)
check("an empty zip is refused", _error, "There are no files inside this zip.")

_dirs = _folder("dirs")
_path = os.path.join(_dirs, "folders-only.zip")
with zipfile.ZipFile(_path, "w") as _bundle:
    _bundle.writestr("58410954/", b"")
    _bundle.writestr("58410954/000D0000/", b"")
_written, _error = unpack.into_folder(_path, _dirs)
check("and so is one holding only directory entries",
      _error, "There are no files inside this zip.")


section("plan answers without touching the destination")

_planned = _folder("planned")
_archive = _zip(_planned, "two.zip", {"a/one.bin": b"1", "b/two.bin": b"22"})
_names, _total, _error = unpack.plan(_archive)
check("it names what would be written", sorted(_names), ["one.bin", "two.bin"])
check("and totals the uncompressed size", _total, 3)
check("without writing anything", sorted(os.listdir(_planned)), ["two.zip"])


section("when the zip's name must not be taken")

# A member that has an extension has a name somebody chose, and the zip it came
# in may be called anything at all -- so renaming would make this worse rather
# than better.
_named = _folder("named")
_archive = _zip(_named, "download (1).zip", {"Banjo-Kazooie.iso": b"x"})
_written, _error = unpack.into_folder(_archive, _named)
check("a member with an extension keeps its own name", _written, ["Banjo-Kazooie.iso"])

# More than one file and there is no single thing to name after the zip.
_several = _folder("several")
_archive = _zip(_several, "Some Game.zip", {"a/one": b"1", "b/two": b"2"})
_written, _error = unpack.into_folder(_archive, _several)
check("several members keep theirs too", sorted(_written), ["one", "two"])


if __name__ == "__main__":
    summary()
