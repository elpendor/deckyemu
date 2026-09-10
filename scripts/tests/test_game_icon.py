#!/usr/bin/env python3
"""The icon a game added here is given: a file that ships, not one that is made.

    python scripts/tests/test_game_icon.py

Steam records the *path* to a shortcut's icon and reads it from there
afterwards, so what matters is that the file ships, that it is a real PNG at the
size Steam draws from, and that the backend refuses to name it when it is
missing rather than handing Steam a path to nothing.
"""

import base64
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import decky  # noqa: E402  -- the stub the harness installed
import gameicon  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ASSET = os.path.join(REPO, "assets", gameicon.NAME)

with open(_ASSET, "rb") as _handle:
    _PNG = _handle.read()


def _chunks(data):
    """(tag, payload, crc ok) for each chunk."""
    at, found = 8, []
    while at < len(data):
        length = struct.unpack(">I", data[at:at + 4])[0]
        tag = data[at + 4:at + 8]
        payload = data[at + 8:at + 8 + length]
        stated = struct.unpack(">I", data[at + 8 + length:at + 12 + length])[0]
        found.append((tag, payload, stated == zlib.crc32(tag + payload) & 0xFFFFFFFF))
        at += 12 + length
    return found


section("the file that ships is a PNG, by the specification not the extension")

check("it is in assets/, which is where the packaging looks",
      os.path.isfile(_ASSET), True)
check("the signature is there", _PNG[:8], b"\x89PNG\r\n\x1a\n")

_parts = _chunks(_PNG)
check("the chunks are the three a minimal image needs",
      [tag.decode() for tag, _payload, _ok in _parts], ["IHDR", "IDAT", "IEND"])
check("and every checksum is right", [ok for _tag, _payload, ok in _parts],
      [True, True, True])

_width, _height, _depth, _colour = struct.unpack(">IIBB", _parts[0][1][:10])
check("it is square, at the size Steam draws icons from", (_width, _height),
      (256, 256))
check("eight bits per channel with an alpha channel, so the corners can be "
      "transparent rather than a colour guessed from the theme",
      (_depth, _colour), (8, 6))


section("the shipped one is named only when it is really there")

_plugin_dir = os.path.join(REPO)
decky.DECKY_PLUGIN_DIR = _plugin_dir
check("the path points at the shipped file", gameicon.generic(), _ASSET)

# The failure this guards. Steam records whatever it is handed and goes on
# reading it, so a path to a file that never shipped stays wrong afterwards --
# it is better to leave the shortcut without an icon than to give it a broken
# one that looks set.
decky.DECKY_PLUGIN_DIR = os.path.join(REPO, "nowhere")
check("and nothing at all when it did not ship", gameicon.generic(), "")

decky.DECKY_PLUGIN_DIR = ""
check("nor when the plugin does not know where it is", gameicon.generic(), "")
decky.DECKY_PLUGIN_DIR = _plugin_dir


section("artwork wins, and the shipped one is what is left when there is none")

_URI = "data:image/png;base64," + base64.b64encode(_PNG).decode()
_APP = 4242424242

check("with no artwork and none of its own, a game gets the shipped picture",
      gameicon.for_game(_APP), _ASSET)

_own = gameicon.for_game(_APP, _URI)
check("with an icon from the lookup, the game gets its own file",
      (os.path.isfile(_own), os.path.basename(_own)), (True, "%s.png" % _APP))
with open(_own, "rb") as _handle:
    check("holding what was found", _handle.read(), _PNG)

# Steam shows a JPEG happily, but the name written into shortcuts.vdf would be
# lying about the file and every other reader has only the name to go on.
check("anything that is not a PNG data URI falls back rather than being written",
      [gameicon.for_game(_APP + 1, one) for one in
       ("data:image/jpeg;base64,AAAA", "not a uri", "", "data:image/png,plain")],
      [_ASSET] * 4)
check("and none of those left a file behind",
      os.path.isfile(os.path.join(os.path.dirname(_own), "%s.png" % (_APP + 1))),
      False)


section("an .ico counts too, because plenty of games have nothing else")

# Adventures of Lolo 2 is the case: two icons on SteamGridDB, both .ico, and
# asking for PNG only left it on the plain tile with nothing to say why. Steam
# reads one -- that is what a Windows shortcut icon has always been.
_ICO = bytes((0, 0, 1, 0)) + b"icondata"
_saved = gameicon.save(_APP, _ICO)
check("it is written, under a name that says what it is",
      os.path.basename(_saved), "%s.ico" % _APP)
check("and counts as an icon of the game's own", gameicon.has_own(_APP), True)

# The extension follows the bytes, so a game can change format -- and the old
# file has to go, or `has_own` keeps finding the stale one.
_swapped = gameicon.save(_APP, _PNG)
check("swapping format replaces rather than accumulates",
      (os.path.basename(_swapped), os.path.isfile(_saved)),
      ("%s.png" % _APP, False))

check("bytes that are neither are refused rather than written under a guess",
      gameicon.save(_APP + 2, b"not an image at all"), "")

# The regression this answers. The startup repair asks with nothing, and an
# answer of "generic" for a game holding a real icon is how it came to write
# the plain tile over a library's worth of artwork.
check("asking with nothing answers with the icon the game already has",
      gameicon.for_game(_APP), _swapped)

check("and forgetting takes whichever one is there",
      (gameicon.forget(_APP), gameicon.has_own(_APP)), (True, False))

# Steam reuses shortcut app ids, so an icon left behind would turn up on
# whatever game is added next under that number. Forgotten just above, so this
# is the state that leaves rather than a second removal.
check("with the icon gone, the file is too", os.path.isfile(_own), False)
check("forgetting one that has none is not an error", gameicon.forget(_APP), False)
check("and the game is back on the shipped picture",
      gameicon.for_game(_APP), _ASSET)


section("and the packaging carries it")

for _where, _name in ((os.path.join(REPO, "scripts", "deploy.sh"), "deploy"),
                      (os.path.join(REPO, ".github", "workflows", "ci.yml"), "CI")):
    with open(_where, encoding="utf-8") as _handle:
        _text = _handle.read()
    check("%s copies assets/ into the plugin" % _name, "assets" in _text, True)


if __name__ == "__main__":
    summary()
