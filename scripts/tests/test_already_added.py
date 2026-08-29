#!/usr/bin/env python3
"""Recognising a ROM that is already a game, at the moment it is being added.

    python scripts/tests/test_already_added.py

The add flow **files a ROM into the library folder after adding it**, and that
one fact is what makes this more than a path comparison: send the same game
again and the copy that arrives sits in the transfer folder under the same name
and a different path. A check that only compared paths would say nothing about
the single most common way somebody adds a game twice.

So there are two answers, and they are deliberately not merged. `same_file` is a
certainty; a name match is a likelihood, and the panel words them differently
because two systems both have a `Frogger.zip`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import store  # noqa: E402

section("already added -- path, name, and neither")

LIBRARY = {
    "1001": {"name": "Tobu Tobu Girl", "rom_path": "/home/deck/Emulation/gb/Tobu.gb"},
    "1002": {"name": "Super Mario World", "rom_path": "/home/deck/Emulation/snes/SMW.smc"},
}

found = store.already_added(LIBRARY, "/home/deck/Emulation/gb/Tobu.gb")
check("the same path is the game that runs it", found["name"], "Tobu Tobu Girl")
check("and is reported as certain", found["same_file"], True)
check("with the appid, so the panel could name the entry", found["app_id"], "1001")

# The one this exists for: the same file sent again lands in the transfer
# folder, which is not where the added copy was filed.
found = store.already_added(LIBRARY, "/home/deck/deckyemu/transfer/Tobu.gb")
check("the same name elsewhere is found", found["name"], "Tobu Tobu Girl")
check("and is reported as a likelihood, not a fact", found["same_file"], False)

check("a game that is not there is not invented",
      store.already_added(LIBRARY, "/home/deck/deckyemu/transfer/Zelda.gb"), None)
check("an empty library says nothing",
      store.already_added({}, "/home/deck/Emulation/gb/Tobu.gb"), None)
check("and no path is not a match against everything",
      store.already_added(LIBRARY, ""), None)

section("an exact match wins wherever it is in the list")

# The name match is found first walking the dict, and must not be the answer:
# the panel's two sentences say different things, and the weaker one would be
# shown for a file the plugin is certain about.
ORDERED = {
    "1001": {"name": "Sent again", "rom_path": "/home/deck/deckyemu/transfer/Tobu.gb"},
    "1002": {"name": "The filed one", "rom_path": "/home/deck/Emulation/gb/Tobu.gb"},
}
found = store.already_added(ORDERED, "/home/deck/Emulation/gb/Tobu.gb")
check("the exact path is preferred over the earlier name match",
      found["name"], "The filed one")
check("and reported as certain", found["same_file"], True)

section("junk in the library is not a crash in the panel")

# Every one of these has been in a real registry at some point: a half-written
# entry, an entry from a version that did not record the path, and a null where
# a dict belongs. probe_rom runs this on every file the picker touches, so an
# exception here is a panel that cannot add anything.
JUNK = {
    "1": None,
    "2": {},
    "3": {"rom_path": ""},
    "4": {"rom_path": "/home/deck/Emulation/gb/Tobu.gb"},
}
found = store.already_added(JUNK, "/home/deck/Emulation/gb/Tobu.gb")
check("a broken entry is skipped rather than raising", found["app_id"], "4")
check("and an unnamed game still answers", found["name"], "")
check("nothing matches nothing", store.already_added(JUNK, "/other/Thing.gb"), None)
check("a library that is not a dict is not a match",
      store.already_added(None, "/home/deck/Emulation/gb/Tobu.gb"), None)

section("case, because a transfer can change it")

CASED = {"1": {"name": "Tobu", "rom_path": "/home/deck/Emulation/gb/TOBU.GB"}}
check("a name match ignores case",
      store.already_added(CASED, "/home/deck/deckyemu/transfer/tobu.gb")["name"],
      "Tobu")
