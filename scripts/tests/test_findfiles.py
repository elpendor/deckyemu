#!/usr/bin/env python3
"""Listing files without `glob`, which decky's bundle does not carry.

    python scripts/tests/test_findfiles.py

`import glob` worked on a Deck only because SteamOS's own Python sits on
`sys.path` behind decky's executable -- the same shape of luck that ran out for
`http.server` and stopped the plugin loading at all. The core scan, the launcher
sweep and the Steam shortcut list all went through it, so the replacement has to
behave the same where it matters: hidden files, directories, a folder that is
not there, and the case of a name somebody else chose.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import findfiles  # noqa: E402

section("finding files without glob")

_root = os.path.join(TMP, "findfiles")
os.makedirs(os.path.join(_root, "cores"), exist_ok=True)


def _touch(*parts):
    path = os.path.join(_root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write("x")
    return path


_touch("cores", "snes9x_libretro.so")
_touch("cores", "mesen_libretro.so")
_touch("cores", "readme.txt")
os.makedirs(os.path.join(_root, "cores", "subdir.so"), exist_ok=True)

check("every file with the suffix, sorted",
      [os.path.basename(p) for p in findfiles.in_directory(os.path.join(_root, "cores"), ".so")],
      ["mesen_libretro.so", "snes9x_libretro.so"])
check("other files are left out",
      any(p.endswith(".txt") for p in findfiles.in_directory(os.path.join(_root, "cores"), ".so")),
      False)
# A directory named like a core would have been listed by glob and then failed
# to load; it is not a file, so it is not a match.
check("a directory with the suffix is not a file",
      any(p.endswith("subdir.so") for p in findfiles.in_directory(
          os.path.join(_root, "cores"), ".so")),
      False)
check("a folder that does not exist is empty, not an error",
      findfiles.in_directory(os.path.join(_root, "nothing-here"), ".so"), [])

# The AppImage search: two globs before, because the name's capitals are
# whoever downloaded it, not us.
_touch("Applications", "RetroArch-1.22.AppImage")
_touch("Applications", "retroarch-nightly.appimage")
_touch("Applications", "Xenia.AppImage")
check("a prefix and suffix match whatever the capitals are",
      [os.path.basename(p) for p in findfiles.in_directory(
          os.path.join(_root, "Applications"), ".appimage", "retroarch")],
      ["RetroArch-1.22.AppImage", "retroarch-nightly.appimage"])
check("and nothing else in the folder comes with it",
      any("Xenia" in p for p in findfiles.in_directory(
          os.path.join(_root, "Applications"), ".appimage", "retroarch")),
      False)

# `settings/*/library.json`, and every Steam account's shortcuts.vdf.
_touch("settings", "deckyemu", "library.json")
_touch("settings", "someone-else", "library.json")
_touch("settings", "no-library", "other.json")
check("one fixed path under each subdirectory, where it exists",
      [os.path.relpath(p, _root).replace(os.sep, "/")
       for p in findfiles.under_each(os.path.join(_root, "settings"), "library.json")],
      ["settings/deckyemu/library.json", "settings/someone-else/library.json"])
check("a root that does not exist is empty",
      findfiles.under_each(os.path.join(_root, "nope"), "library.json"), [])

_touch("userdata", "1234", "config", "shortcuts.vdf")
check("and it works for a path several levels down",
      [os.path.relpath(p, _root).replace(os.sep, "/")
       for p in findfiles.under_each(os.path.join(_root, "userdata"), "config", "shortcuts.vdf")],
      ["userdata/1234/config/shortcuts.vdf"])


if __name__ == "__main__":
    summary()
