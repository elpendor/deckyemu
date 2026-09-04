#!/usr/bin/env python3
"""Copying saves to a remote: what rclone is told, and what it is never told.

    python scripts/tests/test_cloudsync.py

No real rclone runs and nothing is copied. What is checked is the command lines
this module *plans*, which is the whole of what it decides -- running them is the
plugin's job, because a copy is watched rather than waited on so the panel can
draw a bar. A mistake here is not a failed copy but a save somebody has lost.

Three things are pinned, and each of them is a decision that would be invisible
in a screenshot of a working feature:

**`copy`, never `sync`.** `sync` makes the remote match the Deck, which means an
emulator uninstalled here silently empties its saves there. Both comparable decky
plugins refuse to delete from the remote for the same reason and say so in their
own READMEs.

**And nothing is overwritten in place.** `copy` does not delete, but it does
replace a file that differs -- including one that is newer than the Deck's,
which is what a second device or a restored old save produces. `--backup-dir`
moves it aside instead, so pressing copy cannot destroy anything up there.

**What it moved aside is read back from the Deck, and removed from the Deck.** A
safety copy reachable only by opening Dropbox on a laptop would be the second
device this plugin exists to do without -- so a replaced state is another thing
the restore screen reads, and the number kept is the number offered. Anything
past that is deleted rather than left somewhere only a website can reach.

**"Restore only what is missing" is `--ignore-existing`.** Not a timestamp
comparison: "newer" across two devices and a cloud is a claim about clocks, and
the thing being bet on it is a save.

**The remote path is built from the catalog, one segment at a time.** An
emulator id is not user input, but it is the last thing a string passes through
before it becomes a folder in somebody's Dropbox.
"""

import json as _json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import cloudsave  # noqa: E402
import cloudsync  # noqa: E402
import savedata  # noqa: E402


class FakeRun:
    """Records every argv it is handed and answers with a chosen exit code."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv, self.returncode, self.stdout, self.stderr)


#: Two emulators shaped as `savedata._all_sources` returns them: one that
#: declares where its saves are, and one that declares nothing and therefore
#: contributes its whole directory.
SOURCES = [
    {"id": "retroarch", "name": "RetroArch", "whole": False,
     "roots": [("saves", "/home/deck/ra/saves"), ("states", "/home/deck/ra/states")]},
    {"id": "duckstation", "name": "DuckStation", "whole": True,
     "roots": [("duckstation", "/home/deck/.var/app/duckstation")]},
]


class FakeByCall:
    """Answers each rclone call from a rule, because one answer is not enough.

    Reading what a storage holds is a directory listing and then one record per
    emulator, and a stub returning the same bytes to both makes a test that
    passes whatever the code does.
    """

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.returncode = 0

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = self.answer(argv)
        return subprocess.CompletedProcess(
            argv, 0 if out is not None else 1, out or "", "" if out else "not found")


def with_run(fake, action, sources=SOURCES):
    """Run `action` with rclone, the binary lookup and the catalog all replaced."""
    real_run = subprocess.run
    real_binary = cloudsave.binary
    real_sources = savedata._all_sources
    subprocess.run = fake
    cloudsave.binary = lambda: "/tools/rclone"
    savedata._all_sources = lambda: list(sources)
    try:
        return action()
    finally:
        subprocess.run = real_run
        cloudsave.binary = real_binary
        savedata._all_sources = real_sources


def copies(steps):
    """The command line of each planned step."""
    return [step["argv"] for step in steps]


def moved(argv):
    """The (from, to) of one copy. Flags follow them, so read from the verb."""
    at = argv.index("copy")
    return argv[at + 1], argv[at + 2]


section("sending saves up")

# What a storage can be compared by is asked once, before anything is planned --
# `cloudsync.learn_compare`, called by the plugin. Answered here so the plan
# below runs no subprocess, which is the thing the next check is about.
cloudsync._COMPARES["dropbox"] = list(cloudsync._BY_CONTENT)

fake = FakeRun()
steps, error = with_run(fake, lambda: cloudsync.push_steps("dropbox"))
check("it plans without running anything", (error, fake.calls), ("", []))
check("and names the emulator each step is for, for the bar to say",
      [step["name"] for step in steps],
      ["RetroArch", "RetroArch", "DuckStation"])

sent = copies(steps)
check("one call per save root, not one per emulator", len(sent), 3)

check("**it copies, and never syncs** -- sync would delete from the remote "
      "whatever this Deck no longer has",
      [argv[argv.index("--config") + 2] for argv in sent], ["copy"] * 3)

check("the source is the directory on the Deck and the target is the remote",
      moved(sent[0]),
      ("/home/deck/ra/saves", "dropbox:DeckyEmu/saves/retroarch/saves"))
check("a second root of the same emulator lands beside the first",
      moved(sent[1])[1], "dropbox:DeckyEmu/saves/retroarch/states")
check("and each emulator has a folder of its own, named as the catalog names it",
      moved(sent[2])[1], "dropbox:DeckyEmu/saves/duckstation/duckstation")

# **Content, not timestamps.** rclone's default is size-and-modtime, and Dropbox
# cannot set a modtime -- so it re-uploaded every file to stamp one, saying so
# in the log, and every push cost its whole payload however little had changed.
check("a copy compares content and leaves timestamps alone",
      all("--checksum" in argv and "--no-update-modtime" in argv for argv in sent),
      True)

# Every call carries it, for the reason `test_cloudsave` exists: a Deck that
# already runs rclone has a configuration this plugin must not edit.
check("every call still names our own config file",
      all("--config" in argv and argv[argv.index("--config") + 1] == cloudsave.CONFIG_PATH
          for argv in sent),
      True)

# Without these the copy is a black box for as long as it takes, which over a
# phone's wifi is exactly when somebody needs to see it moving.
check("and asks for a line a second, so the panel has something to draw",
      all(argv[-5:] == ["--stats", "1s", "--stats-one-line",
                        "--stats-log-level", "NOTICE"]
          for argv in sent),
      True)

section("pressing copy cannot destroy what is already up there")

# The failure this prevents: restore an old save, press copy, and the newer
# copy in the cloud is replaced by the older one with nothing to go back to.
aside = [argv[argv.index("--backup-dir") + 1] for argv in sent
         if "--backup-dir" in argv]
check("every copy names somewhere to put what it would have overwritten",
      len(aside), len(sent))
check("one folder per emulator, which is one folder for a copy after a game "
      "closes -- that only ever covers the emulator that was played",
      len({one.rsplit("/", 1)[0] for one in aside}), 2)
# Named for the emulator and the moment, which is what lets the restore screen
# say "RetroArch - 3 Sep, 22:10" from one directory listing rather than one
# network round trip per snapshot to look inside.
check("it is named after the emulator and when it happened",
      bool(re.match(r".*/retroarch-\d{8}-\d{6}/saves$", aside[0])), True)

# rclone refuses a backup directory that sits inside the destination, and it
# would otherwise be read straight back as saves by `contents`.
check("and it is outside the folder saves are read from",
      (cloudsync.REPLACED.startswith(cloudsync.ROOT),
       cloudsync.ROOT.startswith(cloudsync.REPLACED)),
      (False, False))

section("a storage that cannot hash is compared another way")

# **`--checksum` on a storage with no checksums is worse than not asking.**
# rclone says so and then does it -- "falling back to --size-only" -- and a save
# is very often the same size after a session, so the change is read as no
# change. Measured against an FTP server on the device: ten bytes, contents
# replaced, "Unchanged skipping", old copy left up there. Without the flag the
# same case reads "Modification times differ" and is copied.
cloudsync._COMPARES["myftp"] = []
flat = FakeRun()
plain, _ = with_run(flat, lambda: cloudsync.push_steps("myftp"))
check("nothing asks for a comparison it cannot make",
      any("--checksum" in step["argv"] for step in plain), False)
check("and size and time are left to rclone, which is what catches it",
      any("--size-only" in step["argv"] for step in plain), False)
check("while a storage that hashes still compares content",
      all("--checksum" in argv for argv in copies(steps)), True)

# A WebDAV dialect reports the hashes it *can* carry, not the ones the server
# behind it sends. Taken at face value that turns on --checksum, which with no
# hash on either side compares size -- the exact failure above. Measured on the
# device against a real server: same file, contents replaced, "Unchanged
# skipping".
_real_kinds = cloudsave.remote_kinds
cloudsave.remote_kinds = lambda: {"mywd": "webdav", "mydrop": "dropbox"}
_real_rclone = cloudsave.rclone
cloudsave.rclone = lambda args, seconds: (True, '{"Hashes": ["md5", "sha1"]}')
try:
    cloudsync._COMPARES.pop("mywd", None)
    check("a hash a dialect claims is not a hash the server has",
          cloudsync.learn_compare("mywd"), [])
    cloudsync._COMPARES.pop("mydrop", None)
    check("and one a storage really reports is still used",
          cloudsync.learn_compare("mydrop"), list(cloudsync._BY_CONTENT))
finally:
    cloudsave.rclone = _real_rclone
    cloudsave.remote_kinds = _real_kinds
    cloudsync._COMPARES.pop("mywd", None)
    cloudsync._COMPARES.pop("mydrop", None)

section("what a whole-directory emulator does not send")


def carries(argv, first, second):
    """Whether `first second` sit next to each other on one command line.

    By shape rather than by position: this used to count backwards from the end
    of the list, which made adding a flag anywhere after it a failing test about
    an exclusion that was still perfectly correct.
    """
    return any(argv[at:at + 2] == [first, second] for at in range(len(argv) - 1))


check("the flatpak cache is excluded, because the emulator rebuilds it and it "
      "is the largest thing in the tree",
      carries(sent[2], "--exclude", "cache/**"), True)
check("and an emulator that declared its save directory needs no exclusion",
      any("--exclude" in argv for argv in sent[:2]), False)

# Saves are hundreds of small files and a small file is almost all waiting, so
# the round trips are overlapped. Measured on the device at 50s against Dropbox
# and 168s against pCloud with rclone's default of four, and 11s on both at 32.
check("every copy overlaps its files rather than sending them one at a time",
      all(carries(argv, "--transfers", "32") and carries(argv, "--checkers", "32")
          for argv in sent),
      True)

section("bringing saves back down")

listing = (
    '[{"Path":"retroarch/saves/game.srm","Size":128},'
    ' {"Path":"duckstation/duckstation/memcard.mcd","Size":8192}]'
)

# RetroArch keeps `saves` and `states`; only `saves` is up there. Both were
# planned once, and rclone was asked to read a folder nobody had created --
# which filled the restore dialog with "error reading source root directory".
partial = '[{"Path":"retroarch/saves/game.srm","Size":128}]' 

fake = FakeRun(stdout=listing)
steps, error = with_run(fake, lambda: cloudsync.pull_steps("dropbox"))
came = copies(steps)
check("it plans a step per save root that exists on the remote",
      (error, [step["name"] for step in steps]),
      ("", ["RetroArch", "DuckStation"]))
check("the remote is the source now, and the Deck the target",
      moved(came[0]),
      ("dropbox:DeckyEmu/saves/retroarch/saves", "/home/deck/ra/saves"))

check("**by default nothing already here is touched** -- a save played since "
      "the copy went up cannot be lost to a restore",
      all("--ignore-existing" in argv for argv in came), True)

# The other direction needs no net: off overwrites nothing, and on is reached
# through a confirmation that counts what it will overwrite.
check("and coming down needs no folder for replaced files, unlike going up",
      any("--backup-dir" in argv for argv in came), False)

fake = FakeRun(stdout=listing)
replacing, _ = with_run(fake, lambda: cloudsync.pull_steps("dropbox", None, True))
check("replacing is the one that overwrites, and only when asked",
      any("--ignore-existing" in argv for argv in copies(replacing)), False)

# **One emulator asked for is one emulator listed**, and a scoped listing comes
# back relative to it. Measured against Dropbox: the whole saves tree is 14.5
# seconds and one emulator's subtree is 5, with `--fast-list` changing neither.
scoped = '[{"Path":"saves/game.srm","Size":128}]'
fake = FakeRun(stdout=scoped)
narrowed, _ = with_run(fake, lambda: cloudsync.pull_steps("dropbox", ["retroarch"]))
check("one emulator can be asked for on its own",
      [moved(argv)[1] for argv in copies(narrowed)],
      ["/home/deck/ra/saves"])
check("and only that emulator is listed, not the whole storage",
      [a for a in fake.calls[0] if a.startswith("dropbox:")],
      ["dropbox:DeckyEmu/saves/retroarch"])

section("a save root with nothing up there is not asked for")

fake = FakeRun(stdout=partial)
some, error = with_run(fake, lambda: cloudsync.pull_steps("dropbox"))
check("only the roots that exist on the remote are read",
      (error, [moved(step["argv"])[0] for step in some]),
      ("", ["dropbox:DeckyEmu/saves/retroarch/saves"]))
check("and the emulator is still restored, not skipped for the root it lacks",
      [step["name"] for step in some], ["RetroArch"])

section("a storage holding nothing for this Deck")

fake = FakeRun(stdout='[{"Path":"vita3k/savedata/x.bin","Size":4}]')
steps, error = with_run(fake, lambda: cloudsync.pull_steps("dropbox"))
check("nothing is planned when none of it belongs to an installed emulator",
      steps, [])
check("and it says so rather than reporting a success that moved nothing",
      "nothing for the emulators installed here" in error, True)

section("reading what a storage holds")

# **Names first, then figures, one emulator at a time.** Describing one is a
# tree walk -- 4.7 seconds against Dropbox, the same whether it is asked as
# `lsjson`, `size` or with `--fast-list` -- so asking for all fourteen before
# anything appeared was 11.5 seconds of empty screen. The names alone are one
# cheap directory listing, 1.1 seconds, and each row then says what it holds
# when its own answer lands. Every copy up leaves a record of what it wrote,
# which is exactly what a row needs, so the usual case is one read, not a walk.
_records = {
    "retroarch": _json.dumps({"device": "d", "at": 1, "files": {
        "saves/a.srm": {"size": 10, "mtime": 1},
        "saves/b.srm": {"size": 20, "mtime": 1}}}),
    "vita3k": _json.dumps({"device": "d", "at": 1, "files": {
        "savedata/c.bin": {"size": 40, "mtime": 1}}}),
}


def _answer(argv):
    if "--dirs-only" in argv:
        return _json.dumps([{"Name": name} for name in _records])
    if "cat" in argv:
        for name, body in _records.items():
            if any(("/%s/" % name) in a for a in argv):
                return body
    return None


fake = FakeByCall(_answer)
listed, error = with_run(fake, lambda: cloudsync.listed_on("dropbox"))
check("one listing says which emulators are up there, before any is described",
      (sorted(listed), error), (["retroarch", "vita3k"], ""))
check("and it does not walk the storage to find that out",
      any("--recursive" in argv for argv in fake.calls), False)

rows = {name: with_run(fake, lambda name=name: cloudsync.describe_one("dropbox", name))
        for name in listed}
check("it counts files and bytes per emulator",
      (rows["retroarch"]["files"], rows["retroarch"]["bytes"]), (2, 30))
check("an emulator this Deck does not have is listed and marked, not dropped -- "
      "that is how somebody learns their saves are safe on a Deck without it",
      (rows["vita3k"]["installed"], rows["vita3k"]["files"]), (False, 1))
check("and one it does have is offered", rows["retroarch"]["installed"], True)
check("a row is answered from the record beside the saves, not by walking",
      any("--recursive" in argv for argv in fake.calls), False)

# The shape the restore screen reads, whichever source it is reading from.
check("every row carries what a backup's own listing carries",
      all(set(row) == {"id", "name", "installed", "files", "bytes", "present"}
          for row in rows.values()),
      True)

# An emulator whose record predates them is still answered for, by listing its
# own subtree -- one emulator, not the whole storage.
_no_record = {"retroarch": None}


def _older(argv):
    if "--dirs-only" in argv:
        return _json.dumps([{"Name": "retroarch"}])
    if "cat" in argv:
        return None
    return '[{"Path":"saves/a.srm","Size":10}]'


fake = FakeByCall(_older)
row = with_run(fake, lambda: cloudsync.describe_one("dropbox", "retroarch"))
check("one copied up before records were kept is not missing from the answer",
      (row["id"], row["files"]), ("retroarch", 1))

# **A read does not write.** Nothing about looking at a storage should change
# what is in it.
fake = FakeByCall(_older)
with_run(fake, lambda: cloudsync.listed_on("dropbox"))
with_run(fake, lambda: cloudsync.describe_one("dropbox", "retroarch"))
check("reading a storage writes nothing to it",
      any("copyto" in argv for argv in fake.calls), False)

fake = FakeByCall(lambda argv: None)
check("a storage with nothing on it is empty, not an error",
      with_run(fake, lambda: cloudsync.listed_on("dropbox")),
      ([], ""))
check("and an emulator with nothing under it is no row at all",
      with_run(fake, lambda: cloudsync.describe_one("dropbox", "retroarch")), {})

section("what never reaches a remote path")

check("a segment that is not one is refused rather than escaped",
      [cloudsync._safe("..", "saves"), cloudsync._safe("ok", "../.."),
       cloudsync._safe("a/b", "c"), cloudsync._safe("", "x"),
       cloudsync._safe("-lead", "x")],
      ["", "", "", "", ""])
check("and an ordinary pair joins", cloudsync._safe("retroarch", "saves"),
      "retroarch/saves")

check("a remote name that is not one never becomes a command line",
      (cloudsync.push_steps("../../etc")[0], cloudsync.pull_steps("--dump")[0],
       cloudsync.listed_on("a b:c")[0],
       cloudsync.describe_one("a b:c", "retroarch")),
      ([], [], [], {}))

section("a folder name is stable whatever else is being copied")

# `savedata._key` numbers collisions against everything in one archive, so the
# same directory would land under a different name depending on what was
# ticked -- and a later download would look in the wrong place.
one = with_run(FakeRun(), lambda: cloudsync._roots_of(SOURCES[0]))
alone = with_run(FakeRun(), lambda: cloudsync._roots_of(SOURCES[0]),
                 sources=[SOURCES[0]])
check("the same emulator gets the same segments either way", one, alone)

check("two roots that would slug the same way are still told apart",
      [segment for segment, _ in cloudsync._roots_of({
          "id": "x", "name": "X", "whole": False,
          "roots": [("Save Data", "/a"), ("save-data", "/b")]})],
      ["save-data", "save-data-2"])

section("reading how far along a copy is")

# The one line the panel draws a bar from. Anchored between commas so it cannot
# take the ETA, the speed, or a number out of a filename.
check("a stats line yields its percentage",
      cloudsync.percent_in(
          "2026/09/03 14:30:00 NOTICE: Transferred: 4.750 MiB / 13.061 MiB, "
          "36%, 1.583 MiB/s, ETA 5s"),
      36)
check("the first line, before rclone knows the total, yields nothing rather "
      "than a zero that would read as no progress",
      cloudsync.percent_in(
          "Transferred: 0 / 0 Bytes, -, 0 Bytes/s, ETA -"),
      None)
check("a line about a file is not a percentage",
      cloudsync.percent_in("INFO  : 100% Complete Save.srm: Copied (new)"), None)
check("and it cannot leave the range a bar can draw",
      (cloudsync.percent_in("x, 100%, y"), cloudsync.percent_in("x, 999%, y")),
      (100, 100))

section("reading back what a copy replaced")

fake = FakeRun(stdout=(
    '[{"Path":"retroarch-20260903-145100","Name":"retroarch-20260903-145100","IsDir":true},'
    ' {"Path":"retroarch-20260901-090000","Name":"retroarch-20260901-090000","IsDir":true}]'
))
kept, error = with_run(fake, lambda: cloudsync.snapshots("dropbox"))
check("newest first, because the one being undone is the last one",
      (error, [one["stamp"] for one in kept]),
      ("", ["retroarch-20260903-145100", "retroarch-20260901-090000"]))
# The row reads as what it holds, and both halves come from the folder name --
# opening each one to find out would be a network round trip per snapshot.
check("and it says which saves and when, not a folder name",
      kept[0]["label"], "RetroArch - 3 Sep, 14:51")

check("an emulator id with a dash in it survives the split",
      cloudsync._split_stamp("xenia-canary-20260903-145100"),
      ("xenia-canary", "3 Sep, 14:51"))
check("and a folder that is not one of ours is left alone rather than guessed at",
      cloudsync._split_stamp("something else"), ("", "something else"))
check("one kept before the folders were named still reads as a date",
      cloudsync._split_stamp("20260903-212443"), ("", "3 Sep, 21:24"))

fake = FakeRun(returncode=1, stderr="ERROR : directory not found")
check("a storage nothing has ever been overwritten on has none, which is not "
      "an error",
      with_run(fake, lambda: cloudsync.snapshots("dropbox")), ([], ""))

# The point of keeping them: reading one is reading the same tree one level
# along, so the restore screen needs no second kind of row.
# A snapshot's own folder holds `<root>/<file>`: the emulator is its name.
fake = FakeRun(stdout='[{"Path":"saves/game.srm","Size":128}]')
steps, error = with_run(
    fake,
    lambda: cloudsync.pull_steps("dropbox", None, False, "retroarch-20260903-145100"))
check("restoring from one reads the folder it was kept in",
      moved(steps[0]["argv"])[0],
      "dropbox:DeckyEmu/replaced/retroarch-20260903-145100/saves")
check("and lands in the same place on the Deck as the live saves would",
      moved(steps[0]["argv"])[1], "/home/deck/ra/saves")

fake = FakeRun(stdout='[{"Path":"saves/game.srm","Size":128}]')
named, _ = with_run(
    fake, lambda: cloudsync.listed_on("dropbox", "retroarch-20260903-145100"))
check("naming which emulator a kept copy holds costs no request at all",
      (named, fake.calls), (["retroarch"], []))
row = with_run(
    fake,
    lambda: cloudsync.describe_one(
        "dropbox", "retroarch", "retroarch-20260903-145100"))
check("and it can be looked at first, in the same shape as everything else",
      (named, row["id"], row["files"]), (["retroarch"], "retroarch", 1))

# Snapshots made before the folders carried an emulator name are the other
# shape -- `<stamp>/<emulator>/<root>/` -- and still readable. The name is what
# says which, so nothing has to be migrated and nothing already kept is lost.
fake = FakeRun(stdout='[{"Path":"retroarch/saves/game.srm","Size":128}]')
older, _ = with_run(
    fake, lambda: cloudsync.pull_steps("dropbox", None, False, "20260903-145100"))
check("one kept before the folders were named still restores from the right place",
      moved(older[0]["argv"])[0],
      "dropbox:DeckyEmu/replaced/20260903-145100/retroarch/saves")

# And it can be looked at first, like any other. The name says nothing about
# which emulator, so the only way to know is to read it -- which is one request
# against a folder holding one press worth of saves. Naming these from the
# folder alone left every one of them showing no rows at all, under a line
# saying none of those emulators were installed.
fake = FakeRun(stdout='[{"Path":"retroarch/saves/game.srm","Size":128}]')
named, error = with_run(fake, lambda: cloudsync.listed_on("dropbox", "20260903-145100"))
check("an unnamed copy says which emulators it holds by being read",
      (named, error), (["retroarch"], ""))
row = with_run(
    fake, lambda: cloudsync.describe_one("dropbox", "retroarch", "20260903-145100"))
check("and its row counts what is in it", (row["id"], row["files"]), ("retroarch", 1))

check("a stamp that is not one never becomes a path",
      (cloudsync._root_for("dropbox", "../.."), cloudsync._root_for("dropbox", "a/b"),
       cloudsync._root_for("dropbox", ""),
       cloudsync._root_for("dropbox", "retroarch-20260903-145100")),
      ("", "", cloudsync.ROOT, "DeckyEmu/replaced/retroarch-20260903-145100"))

section("a bucket is not a folder, and cannot be spelled like one")

# Measured against a MinIO on the device: `s3:DeckyEmu/saves/...` fails with
# "is a file not a directory", because the first segment of an S3 path is a
# bucket and bucket names are lowercase. The same copy to `deckyemu/...` works.
_real_kinds = cloudsave.remote_kinds
cloudsave.remote_kinds = lambda: {"mys3": "s3", "mydrop": "dropbox"}
try:
    check("a bucketed storage gets a name a bucket may have",
          (cloudsync.root_of("mys3"), cloudsync.replaced_of("mys3")),
          ("deckyemu/saves", "deckyemu/replaced"))
    check("and every other storage keeps the folder it has been using",
          (cloudsync.root_of("mydrop"), cloudsync.replaced_of("mydrop")),
          (cloudsync.ROOT, cloudsync.REPLACED))
    check("what a copy sets aside stays outside what a restore reads",
          (cloudsync.replaced_of("mys3").startswith(cloudsync.root_of("mys3")),
           cloudsync.root_of("mys3").startswith(cloudsync.replaced_of("mys3"))),
          (False, False))
    plan, _ = with_run(FakeRun(), lambda: cloudsync.push_steps("mys3"))
    check("and the plan a copy runs is built with it",
          all("mys3:deckyemu/saves/" in " ".join(step["argv"]) for step in plan),
          True)
finally:
    cloudsave.remote_kinds = _real_kinds

section("what is kept is what is offered")

# The cap and the retention have to be one number. Keeping more than the restore
# screen lists would leave the rest reachable only through the provider's own
# website, which is the thing this plugin exists to do without.
made = "".join(
    '{"Path":"retroarch-2026090%d-120000","Name":"retroarch-2026090%d-120000",'
    '"IsDir":true},' % (n, n)
    for n in range(1, 8)
).rstrip(",")
fake = FakeRun(stdout="[" + made + "]")
kept, _ = with_run(fake, lambda: cloudsync.snapshots("dropbox"))
check("only the newest few are offered", len(kept), cloudsync.KEEP)
check("and they are the newest", kept[0]["stamp"], "retroarch-20260907-120000")

# **Kept per emulator.** Playing one game five times must not evict the safety
# copy for another: how far back somebody can go is a question per emulator.
_mixed = ("[" + "".join(
    '{"Path":"%s-2026090%d-120000","Name":"%s-2026090%d-120000","IsDir":true},'
    % (who, n, who, n)
    for who in ("retroarch", "xenia") for n in range(1, 8)
).rstrip(",") + "]")
fake = FakeRun(stdout=_mixed)
kept, _ = with_run(fake, lambda: cloudsync.snapshots("dropbox"))
check("a busy emulator does not push another one out",
      sorted({one["emulator"] for one in kept}), ["retroarch", "xenia"])
check("and each keeps its own few", len(kept), cloudsync.KEEP * 2)

fake = FakeRun(stdout="[" + made + "]")
gone = with_run(fake, lambda: cloudsync.prune("dropbox"))
purged = [argv[argv.index("purge") + 1] for argv in fake.calls if "purge" in argv]
check("everything past the cap is removed, so nothing is kept out of reach",
      (gone, sorted(purged)),
      (2, ["dropbox:DeckyEmu/replaced/retroarch-20260901-120000",
           "dropbox:DeckyEmu/replaced/retroarch-20260902-120000"]))

fake = FakeRun(stdout='[{"Path":"retroarch-20260903-120000",'
                       '"Name":"retroarch-20260903-120000","IsDir":true}]')
with_run(fake, lambda: cloudsync.prune("dropbox"))
check("and nothing is removed while there is room",
      [argv for argv in fake.calls if "purge" in argv], [])

# The one thing here that deletes from somebody's storage, so what it can reach
# is worth pinning: folders this plugin made, under the folder it made them in.
fake = FakeRun(stdout=(
    '[{"Path":"retroarch-20260903-120000","Name":"retroarch-20260903-120000",'
    '"IsDir":true},'
    ' {"Path":"../..","Name":"../..","IsDir":true},'
    ' {"Path":"holiday photos","Name":"holiday photos","IsDir":true}]'
))
listed, _ = with_run(fake, lambda: cloudsync.snapshots("dropbox", keep=0))
check("a folder that is not one of ours is not a replaced copy, so it is never "
      "listed and never deleted",
      [one["stamp"] for one in listed], ["retroarch-20260903-120000"])

section("what a failure says in a dialog")

# What this replaced: five stamped log lines pasted end to end, saying
# "directory not found" three times across six lines of red.
noisy = (
    "2026/09/03 15:08:10 ERROR : Attempt 2/3 failed with 1 errors and: "
    "directory not found "
    "2026/09/03 15:08:11 ERROR : Dropbox root 'DeckyEmu/saves/rpcs3/savestates': "
    "error reading source root directory: directory not found "
    "2026/09/03 15:08:11 NOTICE: 0 B / 0 B, -, 0 B/s, ETA - "
    "2026/09/03 15:08:11 NOTICE: Failed to copy: directory not found"
)
check("the line that names what went wrong is the one kept",
      cloudsync.readable(noisy),
      "Dropbox root 'DeckyEmu/saves/rpcs3/savestates': error reading source "
      "root directory: directory not found")
check("a retry counter says how many times and never what, so it is not it",
      "Attempt" in cloudsync.readable(noisy), False)
check("output with no stamps in it is still shown rather than swallowed",
      cloudsync.readable("rclone: command not found"), "rclone: command not found")
check("and nothing at all says so",
      (cloudsync.readable(""), cloudsync.readable(None)), ("no output", "no output"))
check("a reason too long for a dialog is cut rather than allowed to push the "
      "buttons off the screen",
      len(cloudsync.readable("2026/09/03 15:08:11 ERROR : " + "x" * 400)) <= 163,
      True)

section("the check on the front of a launch")

# **Nothing here reads a provider's metadata, and that is the point.** Dropbox
# cannot set a modification time -- rclone re-uploads a file to stamp one and
# says so in the log -- pCloud has the same limitation, S3 keeps it as metadata
# a copy rewrites, and SFTP just works. A comparison resting on those is a
# feature that behaves differently on every service somebody might pick.
import tempfile as _tempfile  # noqa: E402

_home = _tempfile.mkdtemp()
_saves = os.path.join(_home, "saves")
os.makedirs(_saves, exist_ok=True)
with open(os.path.join(_saves, "here.srm"), "wb") as _handle:
    _handle.write(b"x" * 128)
_here = os.stat(os.path.join(_saves, "here.srm"))

ONE = [{"id": "retroarch", "name": "RetroArch", "whole": False,
        "roots": [("saves", _saves)]}]

# Where the records live, pointed at scratch so a real install is not read.
cloudsync.STATE_DIR = os.path.join(_home, "state")


def _record(device, at, files):
    return {"device": device, "at": at, "files": files}


_as_uploaded = {"saves/here.srm": {"size": 128, "mtime": int(_here.st_mtime)}}

# 1. The storage holds this Deck's own last upload.
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _as_uploaded))
fake = FakeRun(stdout=_json.dumps(_record("deck-aaa", 1000, _as_uploaded)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("one request for the whole emulator, and it is the record, not a listing",
      (len(fake.calls), "cat" in fake.calls[0]), (1, True))
check("our own upload is never a question, whatever the files look like",
      (found["missing"], found["differing"], found["error"]), (0, [], ""))
check("and it says which save roots are up there, so the fetch does not ask again",
      found["roots"], ["saves"])

# 2. Our own upload, and this Deck has played since. **Still not a question**:
# that is a save waiting to be uploaded, not a conflict. After a session with no
# wifi it is every save somebody owns.
_played = {"saves/here.srm": {"size": 200, "mtime": int(_here.st_mtime) - 900}}
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _played))
fake = FakeRun(stdout=_json.dumps(_record("deck-aaa", 1000, _played)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("a save this Deck has changed since its own upload is not a conflict",
      found["differing"], [])

# 3. Somebody else wrote, and this Deck has not touched the file since its own
# upload. Nothing to ask: their copy is simply newer.
_theirs = {"saves/here.srm": {"size": 999, "mtime": 5}}
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _as_uploaded))
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 2000, _theirs)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("another device writing is not itself a conflict when this Deck has not "
      "touched the file",
      found["differing"], [])

# 4. Both wrote. **This is the only question worth interrupting a launch for.**
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _played))
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 2000, _theirs)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("two devices having changed the same save is the one thing that asks",
      found["differing"], ["saves/here.srm"])
check("and each side's own time comes back, for the dialog to show",
      (found["here"], found["there"]), (1000, 2000))

# 4b. **An answer has to be remembered or it is not an answer.** Keeping this
# Deck's copy changes none of the files, so without this the next launch
# compares the same two records, finds the same disagreement, and asks again --
# a decision that has to be made every session is a nag, not a decision.
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _played))
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 2000, _theirs)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
cloudsync.remember_answer("retroarch", found["theirs"])
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 2000, _theirs)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("the same disagreement is not asked about twice", found["differing"], [])

# But it is an answer about *that* upload, not "stop asking". Another device
# writing again is a new state and a new question.
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 3000, _theirs)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("and a later upload from that device asks again",
      found["differing"], ["saves/here.srm"])

# 4c. **A Deck with no record of its own has nothing to disagree about.** Saying
# "both sides changed it since we uploaded" needs an upload to have happened;
# without one, every shared file read as changed and an emulator put up before
# records existed raised a conflict over every file it has. Missing files still
# come down -- there is simply nothing to argue about.
cloudsync._keep_mine("retroarch", {})
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 2000, _theirs)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("with nothing ever uploaded from here, nothing is a conflict",
      found["differing"], [])

# 5. A file up there that is not here at all. Exact, and it needs no permission.
_extra = dict(_as_uploaded)
_extra["saves/other.srm"] = {"size": 64, "mtime": 7}
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _as_uploaded))
fake = FakeRun(stdout=_json.dumps(_record("deck-aaa", 1000, _extra)))
found = with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE)
check("a save only up there is missing here, and is fetched without asking",
      (found["missing"], found["differing"]), (1, []))

# 6. Nothing up there at all, or up there from before records were kept.
fake = FakeRun(returncode=1, stderr="ERROR : directory not found")
check("an emulator never copied up has nothing to compare and nothing to say",
      with_run(fake, lambda: cloudsync.compare("dropbox", "retroarch"), sources=ONE),
      {"missing": 0, "differing": [], "roots": [], "here": 0, "there": 0,
       "theirs": {"device": "", "at": 0}, "error": ""})

check("the record is asked for with a deadline, so a launch cannot hang on it",
      cloudsync.BEFORE_PLAY_SECONDS <= 10, True)

section("a game closing is not evidence that anything was written")

# **Steam counts an app as running while its launcher is still deciding.** A
# launch the two-games gate refused, one somebody declined at the save conflict,
# and a game that failed to start all look exactly like a session that ended --
# and every one of them was uploading. In the conflict case the upload rewrote
# the record beside the saves, which quietly did the thing the dialog had just
# been used to decline.
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _as_uploaded))
check("a session that wrote nothing sends nothing",
      with_run(FakeRun(), lambda: cloudsync.changed_since_push("retroarch"),
               sources=ONE),
      False)

_edited = {"saves/here.srm": {"size": 5, "mtime": 1}}
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _edited))
check("a save that changed does send",
      with_run(FakeRun(), lambda: cloudsync.changed_since_push("retroarch"),
               sources=ONE),
      True)

_gone = dict(_as_uploaded)
_gone["saves/vanished.srm"] = {"size": 1, "mtime": 1}
cloudsync._keep_mine("retroarch", _record("deck-aaa", 1000, _gone))
check("and so does a save that is no longer here, since the record must follow",
      with_run(FakeRun(), lambda: cloudsync.changed_since_push("retroarch"),
               sources=ONE),
      True)

_real = cloudsync.read_mine
cloudsync.read_mine = lambda _id: {}
try:
    check("with nothing ever uploaded, everything is new",
          with_run(FakeRun(), lambda: cloudsync.changed_since_push("retroarch"),
                   sources=ONE),
          True)
finally:
    cloudsync.read_mine = _real

section("this Deck's copy is kept before the cloud's replaces it")

# **The other half of a promise that was only half kept.** A copy up moves what
# it would overwrite into `replaced/`; taking the cloud's copy overwrites files
# *here*, and those are by definition the versions the storage does not have.
# Without this they were the one thing the feature could destroy, under a dialog
# saying neither answer loses anything.
fake = FakeRun()
ok, error = with_run(
    fake, lambda: cloudsync.preserve_local("dropbox", "retroarch", ["saves/here.srm"]),
    sources=ONE)
check("it copies them somewhere before anything is overwritten", (ok, error), (True, ""))
sent = fake.calls[-1]
check("and that somewhere is where every other replaced copy goes, so the "
      "restore screen already lists it",
      cloudsync.REPLACED in sent[sent.index("copy") + 2], True)
check("named by the file rather than by copying the whole root",
      "--files-from" in sent, True)
check("one call per save root, not one per file",
      len([a for a in fake.calls if "copy" in a]), 1)
check("and nothing to keep is not an error",
      with_run(fake, lambda: cloudsync.preserve_local("dropbox", "retroarch", []),
               sources=ONE),
      (True, ""))

section("what a copy up leaves behind")

fake = FakeRun()
ok, error = with_run(
    fake, lambda: cloudsync.record_push("dropbox", "retroarch"), sources=ONE)
check("it writes the record beside the saves", (ok, error), (True, ""))
check("and puts it where the next launch looks for it",
      fake.calls[-1][-1], "dropbox:DeckyEmu/saves/retroarch/.deckyemu-state.json")

_mine = cloudsync.read_mine("retroarch")
check("the same record is kept here, which is what makes the comparison work",
      (_mine["files"], bool(_mine["device"])), (_as_uploaded, True))

# Byte-identical on both sides, because `compare` decides "is this our own
# upload?" by comparing them. A freshly written one would look like a third
# device.
fake = FakeRun(stdout=_json.dumps(_record("deck-bbb", 2000, _theirs)))
with_run(fake, lambda: cloudsync.adopt_state("dropbox", "retroarch"), sources=ONE)
check("taking the storage's copy adopts its record rather than writing a new one",
      cloudsync.read_mine("retroarch"), _record("deck-bbb", 2000, _theirs))

section("the records for a whole copy, in one run rather than fourteen")

# Measured on the device: a process, a sign-in and a round trip each is 70
# seconds against Box for fourteen emulators, and every one of them is spent
# after the last save has gone up, with the bar already at 100%.
fake = FakeRun()
ok, error = with_run(
    fake, lambda: cloudsync.record_pushes("dropbox", ["retroarch", "duckstation"]))
check("it succeeds", (ok, error), (True, ""))
check("one rclone call, whatever the number of emulators", len(fake.calls), 1)
check("and it is one copy into the saves root",
      (fake.calls[0][3], fake.calls[0][5]), ("copy", "dropbox:DeckyEmu/saves"))
check("sent with the rest of the transfer flags",
      ["--transfers", "32"] == fake.calls[0][6:8], True)

check("both records are kept on this Deck as well",
      (bool(cloudsync.read_mine("retroarch").get("device")),
       bool(cloudsync.read_mine("duckstation").get("device"))),
      (True, True))

# A record claiming an upload that did not happen is worse than no record: the
# next launch believes it and compares against saves that were never sent.
before = cloudsync.read_mine("retroarch")
failed = FakeRun(returncode=1, stderr="ERROR : quota exceeded")
ok, error = with_run(
    failed, lambda: cloudsync.record_pushes("dropbox", ["retroarch", "duckstation"]))
check("a failed write keeps nothing",
      (ok, cloudsync.read_mine("retroarch")), (False, before))

# The ordinary case: a copy after a game covers the emulator that was played.
solo = FakeRun()
with_run(solo, lambda: cloudsync.record_pushes("dropbox", ["retroarch"]), sources=ONE)
check("one emulator still goes the way it always has",
      (len(solo.calls), solo.calls[0][3]), (1, "copyto"))

check("nothing to record is not an error",
      with_run(FakeRun(), lambda: cloudsync.record_pushes("dropbox", [])), (True, ""))
check("and a name that could not be a folder is refused rather than staged",
      with_run(FakeRun(), lambda: cloudsync.record_pushes("dropbox", ["../evil", "a/b"])),
      (True, ""))

summary()
