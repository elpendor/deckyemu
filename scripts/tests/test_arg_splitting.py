#!/usr/bin/env python3
"""An emulator whose own launcher word-splits the arguments it is handed.

    python scripts/tests/test_arg_splitting.py

Vita3K's AppImage ends its wrapper with

    "${APPDIR}/usr/bin/Vita3K" $@

and `$@` is unquoted, so the shell inside the AppImage re-splits every argument
the shell outside it took care to keep together. A game at `.../GRAVITY RUSH
(PCSA00011).vpk` arrives as three arguments and the emulator reports the second
word as unsupported content -- which reads as a bad dump, not as a quoting
fault.

Launching was already immune by accident, because an installed title is started
by an id and a title id has no spaces. The installs were not: a package, its
firmware and its font package are all handed a path the user chose the name of.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402

# A file whose name is the problem, and one whose name is not.
_SPACED_DIR = os.path.join(TMP, "transfer")
os.makedirs(_SPACED_DIR, exist_ok=True)
_SPACED = os.path.join(_SPACED_DIR, "GRAVITY RUSH (PCSA00011).pkg")
_PLAIN = os.path.join(_SPACED_DIR, "gravity-rush.pkg")
for _path in (_SPACED, _PLAIN):
    with open(_path, "wb") as _handle:
        _handle.write(b"\x7fPKG")

_SPLITTER = {
    "id": "vita3k", "name": "Vita3K", "kind": "path",
    "target": "/home/deck/deckyemu/emulators/vita3k/Vita3K-x86_64.AppImage",
    "splits_args": True,
}
_ORDINARY = dict(_SPLITTER, id="rpcs3", name="RPCS3", splits_args=False)


# Making a symlink is a privileged operation on Windows unless developer mode is
# on, and `space_free` falls back to the original path when it cannot. That
# fallback is correct -- the call then fails exactly as it does today rather than
# not running at all -- but it means these checks can only be made where linking
# works. The Deck is POSIX, and so is CI, so the behaviour is still exercised.
def _can_link():
    probe = os.path.join(TMP, "link-probe")
    try:
        os.symlink(_PLAIN, probe)
        os.unlink(probe)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


LINKS = _can_link()

section("a path with a space is replaced by a link that has none")

if not LINKS:
    print("SKIP symlinks cannot be created on this host, so linking is not exercised")

_link = emulators.space_free(_SPACED)
if LINKS:
    check("the answer has no space in it", " " in _link, False)
check("it points at the file that was asked for",
      os.path.realpath(_link), os.path.realpath(_SPACED))
# Every one of these emulators decides what it has been handed by looking at the
# extension, so a link that drops it would be refused as an unknown file.
check("and it keeps the extension", os.path.splitext(_link)[1], ".pkg")
check("asking twice gives the same link", emulators.space_free(_SPACED), _link)
# Whatever happened above, the file the emulator is pointed at has to be the one
# the user sent -- a link that resolves elsewhere is worse than no link.
check("the path handed over is always readable", os.path.isfile(_link), True)

# Nothing to fix, so nothing is made: a link for every path would leave a
# directory of them and one more thing that can go stale.
check("a path that is already fine is handed back untouched",
      emulators.space_free(_PLAIN), _PLAIN)


section("which is applied to the emulator that needs it, and only that one")

_argv = emulators.tool_argv(_SPLITTER, ["--pkg", _SPACED, "--zrif", "KO5ifakekey"])
if LINKS:
    check("the package path reaches the emulator without spaces",
          any(" " in token for token in _argv), False)
check("the flags are untouched", [_argv[1], _argv[3]], ["--pkg", "--zrif"])
# The key is base64 and never contains a space, but it is also not a path --
# substituting one would be a link to a file that does not exist.
check("and so is the licence key, which is not a path", _argv[4], "KO5ifakekey")

check("an emulator that does not split its arguments gets the real path",
      emulators.tool_argv(_ORDINARY, ["--pkg", _SPACED])[2], _SPACED)
# An argument that names nothing on disk is a flag or a value, not a path, and
# linking it would invent a file.
check("an argument that is not a file is never linked",
      emulators.tool_argv(_SPLITTER, ["--zrif", "a key with spaces"])[2],
      "a key with spaces")


section("the catalog says which emulator this is")

_vita = emulator_catalog.find("vita3k")
check("Vita3K declares it", bool(_vita.get("splits_args")), True)
check("and nothing else does",
      [entry["id"] for entry in emulator_catalog.CATALOG
       if entry.get("splits_args") and entry["id"] != "vita3k"],
      [])

# The field is carried into a registered emulator by the same list that carries
# `installed_args`; without that the flag exists in the catalog and never
# reaches the code that reads it.
_registered = emulator_catalog.to_emulator(_vita, "/tmp/Vita3K.AppImage", {})
check("registering an emulator from the catalog carries it over",
      _registered.get("splits_args"), True)


if __name__ == "__main__":
    summary()
