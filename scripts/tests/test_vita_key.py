#!/usr/bin/env python3
"""A Vita package's licence key, matched by what it licenses.

    python scripts/tests/test_vita_key.py

A zRIF names the content it decrypts and so does the package header, so the
key for a package is found by that and not by its filename: the right key under
any name is used, and a wrong one is never used, even named for the package.
The keys here are made up -- built the way a zRIF is, for invented content ids.
"""

import base64
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import vita_games  # noqa: E402

_DIR = os.path.join(TMP, "vita-key")
os.makedirs(_DIR, exist_ok=True)

_GAME = "UP0000-PCSA99999_00-HARBORDASH000000"
_OTHER = "UP0000-PCSB88888_00-OTHERGAME0000000"


def _zrif(content_id):
    """A licence for `content_id`, deflated against the zRIF dictionary."""
    rif = bytearray(512)
    rif[0x10:0x10 + len(content_id)] = content_id.encode("ascii")
    packer = zlib.compressobj(9, zlib.DEFLATED, 10, zdict=vita_games._ZRIF_DICT)
    return base64.b64encode(packer.compress(bytes(rif)) + packer.flush()).decode("ascii")


def _write(name, data):
    path = os.path.join(_DIR, name)
    with open(path, "wb" if isinstance(data, bytes) else "w") as handle:
        handle.write(data)
    return path


section("a key decodes to what it licenses")

check("a made-up key has the shape of a real one", _zrif(_GAME).startswith(vita_games.ZRIF_PREFIX), True)
check("and names its content", vita_games.zrif_content_ids(_zrif(_GAME)), {_GAME})
check("something that is not a key names nothing", vita_games.zrif_content_ids("KO5ifnotakey"), set())

section("the key for a package, whatever it is called")

_header = bytearray(0x60)
_header[0x30:0x30 + len(_GAME)] = _GAME.encode("ascii")
_pkg = _write("harbor dash.pkg", bytes(_header))
check("the package names its content", vita_games.package_content_id(_pkg), _GAME)

# A wrong key named for the package, and the right one named for nothing.
_write("harbor dash.zrif", _zrif(_OTHER))
_right = _write("hd.zrif", _zrif(_GAME))
_key, _path = vita_games.locate_zrif(_pkg)
check("the right key is found under another name", _path, _right)
check("and the wrong one named for the package is not used", _key, _zrif(_GAME))

os.remove(_right)
check("with only the wrong key there, there is no key",
      vita_games.locate_zrif(_pkg), ("", ""))
check("and the report says a key is here, for another game",
      vita_games.zrif_report(_pkg)["candidates"], ["harbor dash.zrif"])

if __name__ == "__main__":
    summary()
