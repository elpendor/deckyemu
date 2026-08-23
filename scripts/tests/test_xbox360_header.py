#!/usr/bin/env python3
"""A file with no extension still has to reach the emulator that can run it.

XBLA titles are the case. They ship as STFS containers whose filename is a hash
with no suffix, and every route into this plugin matched on an extension -- so
the file could be selected, and then nothing claimed it and the panel had no
button. Xenia boots one straight from a path; only the matching was missing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary, TMP  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emulator_catalog  # noqa: E402
import xbox360_content  # noqa: E402

home = os.path.join(TMP, "xbox360")
os.makedirs(home, exist_ok=True)


def _write(directory, name, payload):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


section("the three headers an Xbox 360 content package can carry")

# Padded past four bytes so the file is not a special case for its size.
for magic in (b"CON ", b"LIVE", b"PIRS"):
    path = _write(home, magic.decode().strip().lower() + "_container", magic + b"\0" * 64)
    check("%s is recognised with no extension at all" % magic.decode().strip(),
          xbox360_content.extension_from_header(path), "stfs")

check("and the panel is told the name came from the header",
      xbox360_content.named_by_header(
          _write(home, "9fa1c0de", b"LIVE" + b"\0" * 64)),
      True)

section("what it must not claim")

# The trailing space in `CON ` is load-bearing: it is a four-character code,
# and matching "CON" alone would swallow anything beginning with those three
# letters -- including, on the machine these tests run on, a file the OS
# will not let you create for exactly that reason.
check("CON without its trailing space is not a container",
      xbox360_content.extension_from_header(
          _write(home, "conquest", b"CONQ" + b"\0" * 64)),
      "")
check("an ordinary file says nothing",
      xbox360_content.extension_from_header(
          _write(home, "notes", b"hello there")),
      "")
check("nor does a file too short to have a header",
      xbox360_content.extension_from_header(_write(home, "stub", b"CO")),
      "")
check("a path that does not exist is not an error",
      xbox360_content.extension_from_header(os.path.join(home, "absent")), "")
check("and a directory is not either",
      xbox360_content.extension_from_header(home), "")

section("an executable, which does have a name but need not")

for magic in (b"XEX2", b"XEX1", b"XEX0"):
    check("%s is an xex" % magic.decode(),
          xbox360_content.extension_from_header(
              _write(home, magic.decode().lower() + "_module", magic + b"\0" * 64)),
          "xex")

section("the name it supplies is one an emulator actually claims")

# The point of the whole module: a header is only worth reading if what it
# returns pairs the file with something. If `stfs` ever leaves Xenia's
# extension list, this module goes back to producing a string nothing
# matches -- silently, because an unmatched ROM is a panel with no button
# rather than an error.
_xenia = emulator_catalog.find("xenia")
check("Xenia is still in the catalog", bool(_xenia), True)
_extensions = emulator_catalog.MANUAL_EXTENSIONS["Microsoft - Xbox 360"]
for _produced in ("stfs", "xex"):
    check("%r is claimed by the Xbox 360 entry" % _produced,
          _produced in _extensions, True)


if __name__ == "__main__":
    summary()
