#!/usr/bin/env python3
"""flatpak's install output, read into a progress bar a person can follow.

    python scripts/tests/test_flatpak_progress.py

The plan rows and the progress lines are flatpak's own output on a Deck,
captured with `cat -A`: tabs between columns, a narrow no-break space inside
sizes, an ellipsis after the verb.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section, summary  # noqa: E402  -- installs the stub

sys.path.insert(0, REPO_ROOT)

import flatpak_progress  # noqa: E402

APP = "org.example.Emulator"

section("names")
check("graphics drivers", flatpak_progress.describe("org.freedesktop.Platform.GL.default"), "graphics drivers")
check("the base runtime is not mistaken for an extension",
      flatpak_progress.describe("org.freedesktop.Platform"), "base runtime")
check("translations", flatpak_progress.describe("org.kde.Platform.Locale"), "translations")
check("the app goes by its own name", flatpak_progress.describe(APP, APP, "Emulator"), "Emulator")

section("one part, as captured")
p = flatpak_progress.Progress(APP, "Emulator")
check("permissions are not shown", p.feed("    x11\tdevices\tfile access [1]"), None)
check("a plan row is read, not shown",
      p.feed(" 1.\t   \t%s\tstable\ti\tflathub\t< 2.8 MB" % APP), None)
check("the plan is recorded", p.plan, [(APP, 2.8e6)])
check("the start has a name", p.feed("Installing…"), ("Downloading Emulator", 0))
check("and a percentage",
      p.feed("Installing… ███ 46%  22.8 kB/s  00:52"), ("Downloading Emulator", 46))
check("the closing note is not shown",
      p.feed("Note that '/home/deck/.local/share/flatpak/exports/share' is not in the search path"), None)

section("several parts, weighted by size")
p = flatpak_progress.Progress(APP, "Emulator")
p.feed(" 1.\t   \torg.freedesktop.Platform.GL.default\t26.08\ti\tflathub\t< 150 MB")
p.feed(" 2.\t   \torg.freedesktop.Platform\t26.08\ti\tflathub\t< 250 MB")
p.feed(" 3.\t   \t%s\tstable\ti\tflathub\t< 100 MB" % APP)
check("each part is named and counted",
      p.feed("Installing 1/3… 50%"), ("Downloading graphics drivers (1 of 3)", 15))
check("the bar covers the whole install",
      p.feed("Installing 2/3… 0%"), ("Downloading base runtime (2 of 3)", 30))
check("the app comes last", p.feed("Installing 3/3… 100%"), ("Downloading Emulator (3 of 3)", 100))

section("unnumbered steps")
p = flatpak_progress.Progress(APP, "Emulator")
p.feed(" 1.\t   \torg.freedesktop.Platform.GL.default\t26.08\ti\tflathub\t< 100 MB")
p.feed(" 2.\t   \t%s\tstable\ti\tflathub\t< 100 MB" % APP)
p.feed("Installing… 100%")
check("a percentage falling back starts the next part",
      p.feed("Installing… 10%"), ("Downloading Emulator (2 of 2)", 55))

section("the --noninteractive shape")
p = flatpak_progress.Progress(APP, "Emulator")
check("a bare ref still gets a name",
      p.feed("Installing runtime/org.freedesktop.Platform.GL.default/x86_64/26.08"),
      ("Downloading graphics drivers (part 1)", -1))
check("and the app its own",
      p.feed("Installing app/%s/x86_64/stable" % APP), ("Downloading Emulator (part 2)", -1))

summary()
