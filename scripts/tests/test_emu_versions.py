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



# ------------------------------------------- AppImage builds and the record

section("AppImage builds -- what was installed, and what else there is")

import io as _io  # noqa: E402
import os as _os  # noqa: E402

_ID = "vita3k"
_dir = emu_install.emulators_dir(_ID)

# Nothing recorded yet, which is the state of every install made before the
# record existed. "Unknown" has to be sayable, or the panel invents a build.
check("an install with no record reads as unknown", emu_install.read_build_record(_ID), {})

with _io.open(_os.path.join(_dir, "Vita3K-x86_64.AppImage"), "w") as _handle:
    _handle.write("x")

check("the AppImage is found", _os.path.basename(emu_install.installed_appimage(_ID)),
      "Vita3K-x86_64.AppImage")

emu_install.write_build_record(_ID, "v0.2.0", "Vita3K-x86_64.AppImage")
check("the recorded tag is read back", emu_install.read_build_record(_ID).get("tag"), "v0.2.0")

# The record starts with a dot, so it sorts before every AppImage name. Without
# skipping it, this returns the metadata file as the binary to run -- and a
# launcher pointing at a JSON file is a game that closes instantly.
check("the record is not mistaken for the emulator",
      _os.path.basename(emu_install.installed_appimage(_ID)), "Vita3K-x86_64.AppImage")

# A corrupt record is not an install with no emulator.
with _io.open(emu_install.build_record_path(_ID), "w") as _handle:
    _handle.write("{not json")
check("an unreadable record reads as unknown", emu_install.read_build_record(_ID), {})
check("and the emulator is still found", bool(emu_install.installed_appimage(_ID)), True)

# Replacing a build must not take the record with it: _remove_others sweeps the
# folder, and the record describes the build being kept.
emu_install.write_build_record(_ID, "v0.2.0", "Vita3K-x86_64.AppImage")
emu_install._remove_others(_dir, keep="Vita3K-x86_64.AppImage")
check("a cleanup keeps the record", emu_install.read_build_record(_ID).get("tag"), "v0.2.0")
check("and keeps the build it was told to", bool(emu_install.installed_appimage(_ID)), True)

# A previous build goes, as it must -- otherwise the folder grows by a couple of
# hundred megabytes per update.
with _io.open(_os.path.join(_dir, "Vita3K-old.AppImage"), "w") as _handle:
    _handle.write("x")
emu_install._remove_others(_dir, keep="Vita3K-x86_64.AppImage")
check("but the previous build does not survive",
      _os.path.exists(_os.path.join(_dir, "Vita3K-old.AppImage")), False)

# What a device has seen is remembered where the build cannot take it away.
# The record is the only place that survives a rollback, and it is written when
# a history is *read*, not only after an install -- a Deck that rolled back
# before anything was remembered would otherwise be stranded on the old build's
# own list forever.
emu_install.write_build_record(_ID, "1.17", "bigpemu", ["1.17", "1.16"])
_ROLLED_BACK_NOTES = """Version 1.17
Version 1.15
"""
check("reading a history remembers what came with it",
      emu_install.remember_versions({"id": _ID}, _ROLLED_BACK_NOTES, ["1.221"]),
      ["1.17", "1.16", "1.15", "1.221"])
check("and it is on disk for the next time the dialog opens",
      emu_install.read_build_record(_ID).get("versions"),
      ["1.17", "1.16", "1.15", "1.221"])
check("without disturbing which build is installed",
      emu_install.read_build_record(_ID).get("tag"), "1.17")

check("a bad id records nothing", emu_install.write_build_record("../etc", "v1", "x"), None)
check("and reads back nothing", emu_install.read_build_record("../etc"), {})

# Tags reach a download URL, so the same rule as commits applies.
for _bad in ("", "-leading", "a" * 65, "v1 --system", "v1/../x", "$(id)"):
    check("a bad tag is refused %r" % _bad, emu_install.valid_tag(_bad), False)
for _good in ("v0.2.0", "1.22.2", "v2026.08.10-1", "release_5"):
    check("a real tag is accepted %r" % _good, emu_install.valid_tag(_good), True)


section("a feed-installed emulator -- the history ships inside the build")

# The publisher has no releases API and no changelog page, so the only list of
# past versions anywhere is the release notes in the build's own ReadMe. It
# needs no network, and it grows by itself: every build carries its own notes.
_FEED_ENTRY = {
    "id": "feedemu",
    "name": "FeedEmu",
    "source": {
        "kind": "url",
        "feed": "https://example.test/build_info.txt",
        "select": "Linux64",
        "notes": "ReadMe.txt",
        "build_name": "https://example.test/builds/FeedEmu_Linux64_v{version}.tar.gz",
    },
}
_NOTES = "\n".join([
    "Title: FeedEmu", "Release Notes", "-------------",
    "Version 1.221", " - did a thing",
    "Version 1.22", " - did another",
    "Version 1.21", "Version 1.19",
])

_asked = []


def _probe(url):
    """Stands in for the HEAD: the size, or 0 when the build has gone.

    One request answers both questions, which is why the listing asks for a
    size rather than a yes -- the dialog shows what a rollback would download,
    and a second request per build would double the wait.
    """
    _asked.append(url)
    # 1.19's file has been taken down, which is the case the probe exists for.
    return 0 if "v119" in url else 8_900_000


_builds, _error = emu_install.feed_history(_FEED_ENTRY, _NOTES, _probe)
check("the notes are the list of versions", _error, "")
check("newest first, as the dialog renders them",
      [build["tag"] for build in _builds], ["1.221", "1.22", "1.21"])
# The convention is the publisher's, undocumented, and relied on by the AUR and
# EmuDeck as well: the version with its dots removed.
check("a version becomes an address by losing its dots",
      _builds[1]["url"].rsplit("/", 1)[-1], "FeedEmu_Linux64_v122.tar.gz")
# **Guessed addresses have to be confirmed.** A build taken down must not be
# offered and then 404 halfway through an install.
check("one that is no longer published is dropped",
      any(build["tag"] == "1.19" for build in _builds), False)
check("and every one offered was asked about first", len(_asked), 4)
# The size comes from that same request. Without it the dialog falls through to
# asking for build details, which only a flatpak can answer -- and every row
# then read "Could not read this build. It needs the network."
check("each build carries what it would download",
      [build["size"] for build in _builds], [8_900_000] * 3)
# And what changed, from the same notes that named the version. Without it the
# row reads as the version number twice: once as the date column's fallback and
# once as its own description.
check("and what changed in it, in the author's words",
      _builds[0]["notes"], "did a thing")
check("with each release taking only its own lines",
      _builds[1]["notes"], "did another")
# No checksum, unlike an install: the feed states one for the current build
# only. Empty rather than wrong.
check("a past build carries no checksum to verify against",
      [build["digest"] for build in _builds], ["", "", ""])

# The newest release is listed from the feed rather than guessed, and carries
# the checksum the feed states: choosing it here downloads what an update
# would, verified the same way. The older rows still carry none.
_with_newest, _ = emu_install.feed_history(
    _FEED_ENTRY, _NOTES, lambda url: 8_900_000, ["1.23"],
    {"tag": "1.23", "url": "https://example.invalid/feed/odd-name.tar.gz",
     "name": "odd-name.tar.gz", "digest": "fnv1a64:c1b241bbfa5135cb"},
)
# A release the installed build has never heard of carries no notes: they come
# inside each download. Empty, not the version number again -- the row is
# headed by that already.
check("a release newer than the installed build carries no notes",
      _with_newest[0]["notes"], "")

check("the current release is offered at the address the feed states",
      _with_newest[0]["url"], "https://example.invalid/feed/odd-name.tar.gz")
check("with the checksum that came with it",
      _with_newest[0]["digest"], "fnv1a64:c1b241bbfa5135cb")
check("while the builds before it still carry none",
      [build["digest"] for build in _with_newest[1:]], ["", "", "", ""])

# **Going back must not take away the way forward.** The list comes from the
# notes inside the installed build, so an older build's notes end at itself:
# roll back to 1.19 and the newest thing on offer was 1.19, with no route back
# to the build that was just replaced. Every version seen before is remembered
# and merged in.
_rolled_back = """Version 1.19
 - an older build
Version 1.18
"""
_after, _why = emu_install.feed_history(
    _FEED_ENTRY, _rolled_back, lambda url: 8_900_000,
    remembered=["1.221", "1.22", "1.21"],
)
check("an older build still offers the ones that came after it",
      [build["tag"] for build in _after], ["1.221", "1.22", "1.21", "1.19", "1.18"])
# Ordering is the version's own: the part after the dot reads as a fraction, or
# 1.1 sorts below 1.09 and 1.221 below 1.22.
_ordered, _ = emu_install.feed_history(
    _FEED_ENTRY, """Version 1.1
Version 1.09
Version 1.221
Version 1.22
""",
    lambda url: 1,
)
check("and newest first however the numbers are spelled",
      [build["tag"] for build in _ordered], ["1.221", "1.22", "1.1", "1.09"])

# Some releases run to thirty lines and the row shows the first few. Cut at a
# word and marked as cut, because a line ending mid-word reads as a rendering
# fault rather than as a paragraph that carries on.
check("a long release note is cut at a word", emu_install._clip("a " * 400, 60)[-4:],
      "a...")
check("and a short one is left exactly as written",
      emu_install._clip("did a thing", 60), "did a thing")

check("a build with no notes lists nothing rather than guessing",
      emu_install.feed_history(_FEED_ENTRY, "", _probe)[1],
      "No release notes came with this build, so its past builds are not listed.")
check("and an entry that names no notes is simply not offered a history",
      emu_install.feed_history({"source": {"kind": "url"}}, _NOTES, _probe), ([], ""))


if __name__ == "__main__":
    from harness import summary

    summary()
