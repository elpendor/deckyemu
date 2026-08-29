#!/usr/bin/env python3
"""Whether an AppImage emulator has an update, and the three answers to that.

    python scripts/tests/test_appimage_updates.py

The point of this file is one distinction: **"nobody has asked" is not "you are
up to date."** The panel reported the second for years because the field was a
boolean, and a boolean has nowhere to put the first -- so an emulator installed
from a release always claimed to be current, whatever the project had published.

What is checked here is the comparison and the cache around it. The network call
that fills the cache is not: it goes to other people's repositories, and a test
that asks them fails on a train.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import emu_install  # noqa: E402

section("three states, and unknown is one of them")

check("a newer tag is an update",
      emu_install.update_state("4070", "4074"), "available")
check("the same tag is not",
      emu_install.update_state("4074", "4074"), "current")

# The two that used to answer "no update available", which reads as up to date.
check("an install with no recorded build is unknown",
      emu_install.update_state("", "4074"), "unknown")
check("a check that never ran is unknown",
      emu_install.update_state("4074", ""), "unknown")
check("neither known is still unknown",
      emu_install.update_state("", ""), "unknown")

section("tag shapes -- equality, never ordering")

# Every one of these is a real tag shape from an emulator this plugin installs:
# Vita3K numbers its builds, Azahar uses a version, Xenia publishes a rolling
# name. No ordering is right for all three, and equality does not need one --
# it only ever claims the two are the same build.
check("a version tag compares",
      emu_install.update_state("2122.3", "2123"), "available")
check("a rolling tag that has not moved is current",
      emu_install.update_state("canary_experimental", "canary_experimental"),
      "current")
# The one an ordering would get wrong: 9 sorts after 10 as a string, and a
# "newer" test built on that would report an update in the wrong direction.
check("a lower number than the installed one is still 'not the same build'",
      emu_install.update_state("4074", "4070"), "available")

section("the cache -- unreadable is empty, never a claim")

with tempfile.TemporaryDirectory() as tmp:
    emu_install.LATEST_TAGS = os.path.join(tmp, "latest-tags.json")

    check("nothing written yet reads as nothing known",
          emu_install.read_latest_tags(), {})

    emu_install.write_latest_tags({"vita3k": "4074"})
    check("what was written comes back",
          emu_install.read_latest_tags(), {"vita3k": "4074"})

    # Half a file is what a power cut during a write leaves. It must not raise
    # and must not be treated as "checked, nothing published" -- which would
    # turn every row unknown into a silent claim again.
    with open(emu_install.LATEST_TAGS, "w", encoding="utf-8") as handle:
        handle.write('{"vita3k": "40')
    check("a truncated cache reads as nothing known",
          emu_install.read_latest_tags(), {})

    # A list where a mapping belongs: the file is ours, but it is on disk, and
    # anything on disk can be edited by hand.
    with open(emu_install.LATEST_TAGS, "w", encoding="utf-8") as handle:
        json.dump(["vita3k"], handle)
    check("a cache of the wrong shape reads as nothing known",
          emu_install.read_latest_tags(), {})

    # Writing into a directory that does not exist yet is the first-run case:
    # the runtime directory is created by decky, but this file is written
    # before anything else has needed it.
    emu_install.LATEST_TAGS = os.path.join(tmp, "made", "up", "latest-tags.json")
    emu_install.write_latest_tags({"xenia": "canary_experimental"})
    check("the cache creates its own directory",
          emu_install.read_latest_tags(), {"xenia": "canary_experimental"})

section("a source that is not a release is not asked")

# `latest_tag` returns early for anything but a github source, so a flatpak
# entry never reaches the network call. Checked because the loop that calls it
# runs over the whole catalog, and a mistake here would be one HTTP request per
# flatpak emulator every time somebody pressed the button.
tag, error = emu_install.latest_tag({"source": {"kind": "flatpak", "id": "org.x.Y"}})
check("a flatpak entry answers without asking", (tag, error), ("", ""))
tag, error = emu_install.latest_tag({})
check("an entry with no source answers without asking", (tag, error), ("", ""))
