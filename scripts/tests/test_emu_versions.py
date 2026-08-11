#!/usr/bin/env python3
"""Updating a flatpak emulator, going back to a past build, and pinning one.

    python scripts/tests/test_emu_versions.py

Two halves, and only one of them can be checked without a device.

The **argv builders** are pure and every one of them puts a value from the
frontend on a command line, so what is checked here is that a bad value produces
no command at all rather than a quoted surprise.

The **parsers** read real `flatpak` output. The samples below are copied from a
Deck running flatpak 1.16.6 rather than written from the documentation, because
the shapes are what they are: `remote-info --log` indents its keys, repeats
`Commit:` per record, and prints an empty `History:` line before the past builds
begin. A parser written against an imagined format is a parser that works until
it meets the tool.

One thing these encode that is easy to get wrong: **the newest build appears in
the log too**, as the first record, so "past builds" is the whole list and not
the tail of it -- and the currently deployed commit may be several records down,
because a remote can have moved on more than once.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import emu_install  # noqa: E402

section("flatpak versions -- update, go back, hold")

# ---------------------------------------------------------------- argv shapes

# A real hash, so the shape is exercised; 64 hex characters is what flatpak
# prints and what `valid_commit` demands.
COMMIT = "d8644a97df3db3cdd46eff2f7aea7d429c40f7e1e7ed5788a191714cc29a74a8"
APP = "org.libretro.RetroArch"

# flatpak may be absent on the machine running the suite, in which case every
# builder correctly returns []. The checks below are written to hold either way,
# so this file passes on Windows and still means something on Linux.
_HAVE_FLATPAK = bool(emu_install.flatpak_binary())


def tail(argv):
    """The arguments after the binary, so a path that varies is not asserted."""
    return argv[1:] if argv else []


if _HAVE_FLATPAK:
    check("an update names the app and nothing else",
          tail(emu_install.flatpak_update_argv(APP)),
          ["update", "--user", "-y", "--noninteractive", APP])
    # --user everywhere, for the reason every other flatpak call here uses it:
    # a system install is root-owned and the plugin cannot answer a password.
    check("going back is an update to a commit",
          tail(emu_install.flatpak_downgrade_argv(APP, COMMIT)),
          ["update", "--user", "-y", "--noninteractive", "--commit=%s" % COMMIT, APP])
    check("holding masks the app", tail(emu_install.flatpak_hold_argv(APP, True)),
          ["mask", "--user", APP])
    check("releasing removes the mask", tail(emu_install.flatpak_hold_argv(APP, False)),
          ["mask", "--user", "--remove", APP])
else:
    print("SKIP flatpak is not installed, so argv shapes are not exercised")

# What must never reach a command line. Both values arrive from the frontend.
for bad in ("", "not an app id", "org.foo; rm -rf ~", "../../etc", "org.foo/bar"):
    check("a bad app id builds no update command %r" % bad,
          emu_install.flatpak_update_argv(bad), [])
    check("a bad app id builds no hold command %r" % bad,
          emu_install.flatpak_hold_argv(bad, True), [])

for bad in ("", "abc", COMMIT[:-1], COMMIT + "0", COMMIT.upper(),
            COMMIT[:-1] + "z", "$(id)", COMMIT + " --system"):
    check("a bad commit builds no command %r" % bad,
          emu_install.flatpak_downgrade_argv(APP, bad), [])

check("a real commit is accepted", emu_install.valid_commit(COMMIT), True)


# ------------------------------------------------------------------- parsing

# `flatpak remote-info --user --log flathub org.libretro.RetroArch`, verbatim
# apart from being cut to four records. Note the indentation, the blank
# `History:` line, and that the first record is the *newest* build.
LOG = """\
        Ref: app/org.libretro.RetroArch/x86_64/stable
        ID: org.libretro.RetroArch
   Version: 1.22.2
    Commit: 1f766799d9ffffd822b8d9d2ceda6368c622aa1dfba495ce9b99b7b636a37f10
   Subject: Fix filter module name typos (#358) (6e708dc2f3b3)
      Date: 2026-08-10 01:18:12 +0000
   History:\x20
    Commit: c0620ff86a22e5bae44e49005292f9877c41ea59c6da1c2b4e08cd43fa406ad8
   Subject: Update AppStream metadata (#359) (cff45f4ee77f)
      Date: 2026-08-09 18:24:23 +0000
    Commit: d8644a97df3db3cdd46eff2f7aea7d429c40f7e1e7ed5788a191714cc29a74a8
   Subject: Install metainfo to share/metainfo (#351) (752e8acdc14a)
      Date: 2026-07-26 20:53:49 +0000
    Commit: e6aae903d4422a3f46603693cfe777e622ab18071c239ebe619b9480f59af46d
   Subject: Restrict nvidia-cg-toolkit to x86_64 (#352) (665b442ec6fa)
      Date: 2026-07-26 18:42:52 +0000
"""

# The parsers take lines, so they are exercised directly rather than through a
# subprocess: what is being checked is the reading, not flatpak.
_builds = emu_install._parse_history(LOG.splitlines(), limit=12)

check("every build in the log is found", len(_builds), 4)
check("newest first, which is the order flatpak prints",
      _builds[0]["commit"][:12], "1f766799d9ff")
# The date and subject are what make this choosable with a controller. A list of
# hashes is not.
check("each build carries its date", _builds[0]["date"], "2026-08-10 01:18:12 +0000")
check("each build carries its subject",
      _builds[2]["subject"], "Install metainfo to share/metainfo (#351) (752e8acdc14a)")
check("the installed build is in the list, several records down",
      [b["commit"] for b in _builds].index(COMMIT), 2)
check("commits are full hashes, not truncated for display",
      all(emu_install.valid_commit(b["commit"]) for b in _builds), True)
check("the limit is honoured", len(emu_install._parse_history(LOG.splitlines(), limit=2)), 2)
check("nothing at all parses to nothing", emu_install._parse_history([], limit=5), [])
# The `History:` line has a value on some builds and not others, and it is not a
# commit either way.
check("the History label is not mistaken for a build",
      all("Fix filter" not in b["subject"] or b["commit"] for b in _builds), True)


# `flatpak remote-ls --user --updates flathub --columns=application`, verbatim.
# Runtimes and extensions come back in the same listing, which is why callers
# intersect with ids they already know rather than treating this as a to-do list.
UPDATES = """\
com.github.Matoking.protontricks
com.microsoft.Edge
io.github.sameboy.SameBoy
org.libretro.RetroArch
org.freedesktop.Platform.Compat.i386
org.freedesktop.Platform.GL32.default
"""

_pending = emu_install._parse_ids(UPDATES.splitlines())
check("an app with an update is listed", APP in _pending, True)
check("an app without one is not", "info.cemu.Cemu" in _pending, False)
# Not filtered here on purpose: "is this a runtime" is not a question this
# module can answer, and the caller only ever asks about its own ids.
check("runtimes come through too, and are the caller's problem",
      "org.freedesktop.Platform.GL32.default" in _pending, True)
check("a blank listing means nothing pending", emu_install._parse_ids([]), set())

# `flatpak mask --user` prints its patterns indented.
MASKED = """\
info.cemu.Cemu
org.libretro.RetroArch
"""
check("held apps are read back", emu_install._parse_ids(MASKED.splitlines()),
      {"info.cemu.Cemu", APP})

# `flatpak info --user <id>`, cut to the lines that matter.
INFO = """\
RetroArch - Frontend for emulators, game engines and media players

          ID: org.libretro.RetroArch
         Ref: app/org.libretro.RetroArch/x86_64/stable
        Arch: x86_64
      Commit: d8644a97df3db3cdd46eff2f7aea7d429c40f7e1e7ed5788a191714cc29a74a8
     Runtime: org.kde.Platform/x86_64/6.9
"""
check("the deployed commit is read out of info",
      emu_install._parse_commit(INFO.splitlines()), COMMIT)
check("a listing without a commit reads as unknown",
      emu_install._parse_commit(["ID: org.foo.Bar"]), "")
# A truncated hash is what `--columns` prints and is not usable with
# `--commit=`; taking it would build a command that fails on the device.
check("a shortened commit is refused rather than passed on",
      emu_install._parse_commit(["Commit: d8644a97df3d"]), "")


# ------------------------------------------------- one build's own details

# `flatpak remote-info --user flathub <id> --commit=<hash>`, verbatim from a
# Deck. The two sizes are the reason this call exists: switching build re-fetches
# the whole app, and 409MB is a different proposition on a handheld from what the
# one-line subject suggests.
#
# The `?` between the number and the unit is real. flatpak writes a narrow
# no-break space there and substitutes `?` when it runs without a UTF-8 locale --
# which is how it runs from the plugin, since there is no login shell. Written
# here as the byte flatpak actually produced rather than the one it meant to.
DETAIL = """\

RetroArch - Frontend for emulators, game engines and media players

        ID: org.libretro.RetroArch
       Ref: app/org.libretro.RetroArch/x86_64/stable
      Arch: x86_64
    Branch: stable
   Version: 1.22.2
   License: GPL-3.0
Collection: org.flathub.Stable
  Download: 409.0?MB
 Installed: 768.4?MB
   Runtime: org.kde.Platform/x86_64/6.11
       Sdk: org.kde.Sdk/x86_64/6.11

    Commit: d8644a97df3db3cdd46eff2f7aea7d429c40f7e1e7ed5788a191714cc29a74a8
    Parent: e6aae903d4422a3f46603693cfe777e622ab18071c239ebe619b9480f59af46d
   Subject: Install metainfo to share/metainfo (#351) (752e8acdc14a)
      Date: 2026-07-26 20:53:49 +0000
"""

_detail = emu_install._parse_fields(DETAIL.splitlines())

check("the download size is read", _detail.get("download"), "409.0 MB")
check("and the installed size", _detail.get("installed"), "768.4 MB")
check("the version is read", _detail.get("version"), "1.22.2")
check("the subject comes through whole, not truncated",
      _detail.get("subject"), "Install metainfo to share/metainfo (#351) (752e8acdc14a)")
check("the commit is the full hash", _detail.get("commit"), COMMIT)
check("the parent is kept separate from the commit",
      _detail.get("parent", "").startswith("e6aae903"), True)
check("the date is read", _detail.get("date"), "2026-07-26 20:53:49 +0000")

# The same field with the character flatpak means to print, for a device whose
# locale it is happy with. Both have to read the same on screen.
check("a real no-break space is cleaned up the same way",
      emu_install._clean_value("409.0 MB"), "409.0 MB")
check("and a plain space is left alone", emu_install._clean_value(" 409.0 MB "), "409.0 MB")
# Nothing non-printable may reach the panel: it renders whatever it is given.
# Built with chr() rather than written as a literal: a control character typed
# into source is a file that will not parse, which is how this line first went in.
check("anything unprintable is dropped",
      emu_install._clean_value("1.22.2" + chr(0) + chr(7)), "1.22.2")

# The header repeats the app's name above the fields, and `Ref:`/`Arch:` are not
# worth showing -- only the keys asked for come back.
check("only the fields worth showing are returned",
      sorted(_detail), ["commit", "date", "download", "installed", "license",
                        "parent", "subject", "version"])
check("nothing is read out of a listing with no fields",
      emu_install._parse_fields(["", "RetroArch - a frontend", "   "]), {})


if __name__ == "__main__":
    from harness import summary

    summary()
