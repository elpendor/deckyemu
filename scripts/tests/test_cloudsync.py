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

import os
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
check("one dated folder for the whole press, so 'what did that copy replace' "
      "has one answer rather than thirteen",
      len({one.rsplit("/", 2)[0] for one in aside}), 1)
check("it keeps the path the file had, so the old copy can be found by name",
      aside[0].endswith("/retroarch/saves"), True)

# rclone refuses a backup directory that sits inside the destination, and it
# would otherwise be read straight back as saves by `contents`.
check("and it is outside the folder saves are read from",
      (cloudsync.REPLACED.startswith(cloudsync.ROOT),
       cloudsync.ROOT.startswith(cloudsync.REPLACED)),
      (False, False))

section("what a whole-directory emulator does not send")

check("the flatpak cache is excluded, because the emulator rebuilds it and it "
      "is the largest thing in the tree",
      sent[2][-7:-5], ["--exclude", "cache/**"])
check("and an emulator that declared its save directory needs no exclusion",
      any("--exclude" in argv for argv in sent[:2]), False)

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

fake = FakeRun(stdout=listing)
narrowed, _ = with_run(fake, lambda: cloudsync.pull_steps("dropbox", ["retroarch"]))
check("one emulator can be asked for on its own",
      [moved(argv)[1] for argv in copies(narrowed)],
      ["/home/deck/ra/saves"])

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

fake = FakeRun(stdout=(
    '[{"Path":"retroarch/saves/a.srm","Size":10},'
    ' {"Path":"retroarch/saves/b.srm","Size":20},'
    ' {"Path":"vita3k/savedata/c.bin","Size":40}]'
))
held = with_run(fake, lambda: cloudsync.contents("dropbox"))
rows = {row["id"]: row for row in held["sources"]}
check("it counts files and bytes per emulator",
      (rows["retroarch"]["files"], rows["retroarch"]["bytes"]), (2, 30))
check("an emulator this Deck does not have is listed and marked, not dropped -- "
      "that is how somebody learns their saves are safe on a Deck without it",
      (rows["vita3k"]["installed"], rows["vita3k"]["files"]), (False, 1))
check("and one it does have is offered", rows["retroarch"]["installed"], True)

# The shape the restore screen reads, whichever source it is reading from.
check("every row carries what a backup's own listing carries",
      all(set(row) == {"id", "name", "installed", "files", "bytes", "present"}
          for row in held["sources"]),
      True)

fake = FakeRun(returncode=1, stderr="2026/09/03 12:00:00 ERROR : directory not found")
check("a folder that was never written to is empty, not an error",
      with_run(fake, lambda: cloudsync.contents("dropbox")),
      {"ok": True, "sources": []})

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
       cloudsync.contents("a b:c")["ok"]),
      ([], [], False))

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
    '[{"Path":"20260903-145100","Name":"20260903-145100","IsDir":true},'
    ' {"Path":"20260901-090000","Name":"20260901-090000","IsDir":true}]'
))
kept, error = with_run(fake, lambda: cloudsync.snapshots("dropbox"))
check("newest first, because the one being undone is the last one",
      (error, [one["stamp"] for one in kept]),
      ("", ["20260903-145100", "20260901-090000"]))
check("and said as somebody would say it, not as a folder name",
      kept[0]["label"], "3 Sep, 14:51")

check("a folder that is not a stamp is left alone rather than guessed at",
      cloudsync._stamp_label("something-else"), "something-else")

fake = FakeRun(returncode=1, stderr="ERROR : directory not found")
check("a storage nothing has ever been overwritten on has none, which is not "
      "an error",
      with_run(fake, lambda: cloudsync.snapshots("dropbox")), ([], ""))

# The point of keeping them: reading one is reading the same tree one level
# along, so the restore screen needs no second kind of row.
fake = FakeRun(stdout='[{"Path":"retroarch/saves/game.srm","Size":128}]')
steps, error = with_run(
    fake, lambda: cloudsync.pull_steps("dropbox", None, False, "20260903-145100"))
check("restoring from one reads the folder it was kept in",
      moved(steps[0]["argv"])[0],
      "dropbox:DeckyEmu/replaced/20260903-145100/retroarch/saves")
check("and lands in the same place on the Deck as the live saves would",
      moved(steps[0]["argv"])[1], "/home/deck/ra/saves")

fake = FakeRun(stdout='[{"Path":"retroarch/saves/game.srm","Size":128}]')
held = with_run(
    fake, lambda: cloudsync.contents("dropbox", "20260903-145100"))
check("and it can be looked at first, in the same shape as everything else",
      [row["id"] for row in held["sources"]], ["retroarch"])

check("a stamp that is not one never becomes a path",
      (cloudsync._root_for("../.."), cloudsync._root_for("a/b"),
       cloudsync._root_for(""), cloudsync._root_for("20260903-145100")),
      ("", "", cloudsync.ROOT, "DeckyEmu/replaced/20260903-145100"))

section("what is kept is what is offered")

# The cap and the retention have to be one number. Keeping more than the restore
# screen lists would leave the rest reachable only through the provider's own
# website, which is the thing this plugin exists to do without.
made = "".join(
    '{"Path":"2026090%d-120000","Name":"2026090%d-120000","IsDir":true},' % (n, n)
    for n in range(1, 8)
).rstrip(",")
fake = FakeRun(stdout="[" + made + "]")
kept, _ = with_run(fake, lambda: cloudsync.snapshots("dropbox"))
check("only the newest few are offered", len(kept), cloudsync.KEEP)
check("and they are the newest", kept[0]["stamp"], "20260907-120000")

fake = FakeRun(stdout="[" + made + "]")
gone = with_run(fake, lambda: cloudsync.prune("dropbox"))
purged = [argv[argv.index("purge") + 1] for argv in fake.calls if "purge" in argv]
check("everything past the cap is removed, so nothing is kept out of reach",
      (gone, purged),
      (2, ["dropbox:DeckyEmu/replaced/20260902-120000",
           "dropbox:DeckyEmu/replaced/20260901-120000"]))

fake = FakeRun(stdout='[{"Path":"20260903-120000","Name":"20260903-120000","IsDir":true}]')
with_run(fake, lambda: cloudsync.prune("dropbox"))
check("and nothing is removed while there is room",
      [argv for argv in fake.calls if "purge" in argv], [])

# The one thing here that deletes from somebody's storage, so what it can reach
# is worth pinning: folders this plugin made, under the folder it made them in.
fake = FakeRun(stdout=(
    '[{"Path":"20260903-120000","Name":"20260903-120000","IsDir":true},'
    ' {"Path":"../..","Name":"../..","IsDir":true},'
    ' {"Path":"holiday photos","Name":"holiday photos","IsDir":true}]'
))
listed, _ = with_run(fake, lambda: cloudsync.snapshots("dropbox", keep=0))
check("a folder that is not one of ours is not a replaced copy, so it is never "
      "listed and never deleted",
      [one["stamp"] for one in listed], ["20260903-120000"])

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
import json as _json  # noqa: E402
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
      found["differing"], ["here.srm"])
check("and each side's own time comes back, for the dialog to show",
      (found["here"], found["there"]), (1000, 2000))

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
       "error": ""})

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

summary()
