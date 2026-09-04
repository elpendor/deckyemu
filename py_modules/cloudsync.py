"""Copying save data to and from the storage somebody signed into.

`cloudsave` owns the credentials and answers whether a remote works. This owns
the only thing that is ever *copied*, and the two are apart because a bug here
writes over somebody's saves and a bug there does not.

**Loose files, not an archive.** The backup that goes to another device is one
zip, and that is right for a file somebody carries around. It is wrong here: a
zip cannot be diffed, so every upload would send every save again, and after a
five-minute game that is a hundred megabytes over wifi to record a two-kilobyte
change. Loose files let rclone send what actually differs, which is the whole
reason this is per emulator rather than one bundle.

**Everything this writes is reachable from the panel.** The layout::

    <remote>:DeckyEmu/saves/<emulator id>/<what the emulator calls it>/...

is legible if somebody opens their storage in a browser, and that is a pleasant
side effect rather than the plan. It is not a route anything here depends on: a
Deck in Game Mode has no browser and no second device, so a folder that can only
be used from a laptop is a folder this plugin should not have made. That applies
to the safety copies under `REPLACED` as much as to the saves -- they are listed
on the restore screen, restored from there, and removed from here when they age
out. Nothing is left for a website to deal with.

**Nothing here deletes, and nothing here merges.** `rclone copy`, never `sync`:
a save removed on the Deck stays on the remote, because the alternative is that
one uninstall silently empties somebody's cloud backup. Both comparable decky
plugins made the same call and say so in their own READMEs. What comes back down
is governed by `replace`, which is the same switch the local restore already
has -- off writes only what is missing here, on overwrites -- so the two ways of
restoring cannot mean different things.

**Where the switching question lands.** Saves go to whichever storage is in use;
restoring can read from any storage signed into. Nothing is ever moved between
two remotes, so choosing a different one cannot strand, duplicate or delete what
is on the old one -- it stays exactly as it was, and is still one press away on
the restore screen. Every comparable project holds one remote and answers this
by making you start again.
"""

import json
import os
import re
import time

import decky

import cloudsave
import savedata

#: The folder every Deck writes into, under whatever the remote's own root is.
#: Named rather than dumped at the top level: this is somebody's Dropbox, and a
#: plugin that scatters directories across it is a plugin they uninstall.
ROOT = "DeckyEmu/saves"

#: Where a file that was about to be overwritten goes instead, in a folder named
#: for the moment it happened.
#:
#: **`copy` overwrites the destination, and that is a way to lose a save.** It
#: skips files that match and never deletes, which is what the module docstring
#: is about -- but a cloud copy that *differs* is replaced by the Deck's, and
#: "differs" includes "is newer than this one". Play on a second Deck, or press
#: this after restoring an older backup, and the better copy is gone with no
#: warning and nothing to go back to.
#:
#: So nothing is overwritten in place. rclone moves the old file here first,
#: keeping its path, and both comparable plugins reach the same rule by a
#: different route: the loser of a conflict is renamed, never destroyed. It has
#: to sit outside `ROOT` or rclone refuses it, which also keeps it out of what
#: `contents` reads back.
#:
#: **And it is read back from the Deck, not from a website.** A safety copy
#: somebody can only reach by opening Dropbox on a laptop is the escape hatch
#: this whole plugin exists to remove. Each folder under here holds the same
#: tree `ROOT` does, so `contents` and `pull_steps` read one exactly as they
#: read the other, and the restore screen offers them as what they are: the
#: state a copy replaced.
REPLACED = "DeckyEmu/replaced"

#: Long enough to send a large emulator's save directory over a phone's wifi,
#: short enough that a remote that has stopped answering does not hold the
#: executor thread until decky is restarted. Measured against the thing this
#: actually copies: memory cards and save states, tens of megabytes, not the
#: gigabytes an emulator's whole directory can reach.
TRANSFER_SECONDS = 900

#: Reading the index of what is up there talks to the network but moves nothing.
LIST_SECONDS = 90

#: How many replaced states to keep, and therefore how many exist.
#:
#: The two have to be the same number. Keeping more than the restore screen
#: offers would leave the rest reachable only through the storage provider's own
#: website, which is the second device this plugin exists to do without -- so
#: what is not listed is not kept. Five is enough to reach the mistake somebody
#: is undoing, and the chooser these rows go in does not scroll.
KEEP = 5

#: What a path segment may be once it names a folder on somebody's cloud storage.
#: Emulator ids and root labels both come from the catalog rather than from
#: input, so this is a guard against a bad catalog entry rather than against an
#: attacker -- but it is the last point before a string becomes a path on a
#: remote, and `..` in one of those is worth refusing here rather than trusting
#: four layers of somebody else's software to refuse it.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _slug(label):
    """A folder name for one save root, from what the emulator calls it."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (label or "").strip()).strip("-._")
    return cleaned.lower() or "data"


def _roots_of(source):
    """One (segment, local directory) per save root of one emulator.

    The segment is stable for a given emulator whatever else is being copied,
    which is what lets an upload of one emulator sit beside an upload of another
    and lets a later download find it again. `savedata._key` cannot be used for
    this: it numbers collisions against everything in the same archive, so the
    same directory would land under a different name depending on what happened
    to be ticked.
    """
    taken = set()
    listed = []
    for label, path in source["roots"]:
        segment = _slug(label)
        candidate = segment
        nth = 2
        while candidate in taken:
            candidate = "%s-%d" % (segment, nth)
            nth += 1
        taken.add(candidate)
        listed.append((candidate, path))
    return listed


def _safe(*segments):
    """Join path segments for a remote, refusing anything that is not one."""
    for segment in segments:
        if not _SEGMENT.match(segment or ""):
            return ""
    return "/".join(segments)


def _sources(ids=None):
    """The emulators this Deck could copy, narrowed to `ids` when given."""
    return [
        source for source in savedata._all_sources()
        if ids is None or source["id"] in ids
    ]


def _excludes(source):
    """rclone's half of the rule `savedata` applies when it walks a directory.

    An emulator that declares no save directory contributes everything it keeps,
    minus the flatpak cache -- which on RPCS3 is the largest thing in the tree
    and is rebuilt on its own. Uploading it would be gigabytes of shader cache
    charged to somebody's Dropbox quota.
    """
    if not source.get("whole"):
        return []
    args = []
    for name in savedata._SKIP_TOP:
        args += ["--exclude", "%s/**" % name]
    return args


#: Asked of rclone so a copy can be watched rather than waited on. One line a
#: second on stderr, at a level that is logged, reading::
#:
#:     Transferred: 4.750 MiB / 13.061 MiB, 36%, 1.583 MiB/s, ETA 5s
#:
#: A percentage is the only part of it the panel draws, but the whole line is
#: worth logging: "it stopped at 36%" and "it was doing 40 KiB/s" are different
#: problems and the second is not visible from a bar.
_STATS = ["--stats", "1s", "--stats-one-line", "--stats-log-level", "NOTICE"]

#: The percentage out of one of those lines. Anchored to the comma so it cannot
#: match the ETA or a filename that happens to contain a number and a sign.
_PERCENT = re.compile(r",\s*(\d{1,3})%\s*,")

#: rclone stamps every line it logs with a date, a time and a level. None of the
#: three means anything on a Deck, but the level is worth reading on the way
#: past: it is what separates the sentence that explains a failure from the four
#: retry notices around it.
_STAMPED = re.compile(r"(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d)\s+(\w+)\s*:\s*")

#: How much of a reason to show. Long enough for a sentence from rclone, short
#: enough that it cannot push the dialog off the screen.
_REASON_CHARS = 160


def readable(text):
    """One sentence out of rclone's output, for a dialog rather than a log.

    What this replaced was five raw log lines with their timestamps, their
    levels and their retry counts pasted end to end -- six lines of red that
    said "directory not found" three times and buried what it was about.

    rclone's own convention is what makes this possible: it stamps every line
    with a level, so the run can be split back apart and the ERROR lines kept.
    The last of those is the one that names the thing that went wrong; the
    NOTICE lines around it are the retry counter and the stats ticking.
    """
    text = (text or "").strip()
    stamps = list(_STAMPED.finditer(text))
    if not stamps:
        return (text[:_REASON_CHARS] or "no output")

    lines = []
    for index, stamp in enumerate(stamps):
        end = stamps[index + 1].start() if index + 1 < len(stamps) else len(text)
        lines.append((stamp.group(2).upper(), text[stamp.end():end].strip()))

    # An attempt counter says how many times, never what. The reason it repeats
    # is on its own line and is the line worth keeping.
    complaints = [
        body for level, body in lines
        if level in ("ERROR", "CRITICAL", "FATAL") and not body.startswith("Attempt ")
    ]
    reason = (complaints or [body for _, body in lines] or ["no output"])[-1]
    if len(reason) > _REASON_CHARS:
        reason = reason[:_REASON_CHARS].rstrip() + "..."
    return reason


def percent_in(line):
    """The percentage rclone last reported, or None if that line held none."""
    found = _PERCENT.search(line or "")
    if not found:
        return None
    return max(0, min(100, int(found.group(1))))


def push_steps(remote, ids=None):
    """One rclone call per save root, ready to run. Returns (steps, error).

    Planning and running are apart because running is now streamed -- the panel
    draws a bar, so the copy has to be watched rather than waited on, and that
    has to happen on the event loop. What is worth pinning is which command
    lines get built, and a plan is something a test can read without a
    subprocess.

    Never `sync`: what is on the remote and not here stays. See the module
    docstring -- this is the same call both comparable plugins settled on, and
    for the same reason.

    Nothing is overwritten in place either: whatever this would replace is moved
    aside first, into one dated folder for the whole press. See `REPLACED` --
    without it, pressing this after restoring an old save quietly destroys the
    newer copy in the cloud.
    """
    if not cloudsave.valid_name(remote):
        return [], "That storage cannot be used."

    # One folder for the press, not one per emulator: what somebody wants back
    # is "whatever that copy replaced", and thirteen timestamps a second apart
    # is a worse answer to that than one.
    aside = "%s:%s/%s" % (remote, REPLACED, time.strftime("%Y%m%d-%H%M%S"))

    listed = _sources(ids)
    if not listed:
        return [], "There are no saves to copy yet."

    steps = []
    for source in listed:
        for segment, path in _roots_of(source):
            target = _safe(source["id"], segment)
            if not target:
                decky.logger.warning(
                    "Cloud push skipped %s: not a usable folder name", source["id"])
                continue
            command = cloudsave.argv(
                ["copy", path, "%s:%s/%s" % (remote, ROOT, target),
                 "--backup-dir", "%s/%s" % (aside, target)]
                + _excludes(source) + _STATS
            )
            if not command:
                return [], "The cloud transfer tool is missing."
            steps.append({"id": source["id"], "name": source["name"], "argv": command})
    if not steps:
        return [], "There are no saves to copy yet."
    return steps, ""


def _stamp_label(name):
    """`20260903-145100` as somebody would say it, or the name if it is not one."""
    try:
        when = time.strptime(name, "%Y%m%d-%H%M%S")
    except ValueError:
        return name
    return time.strftime("%d %b, %H:%M", when).lstrip("0")


def snapshots(remote, keep=KEEP):
    """The states a copy replaced, newest first. Returns (list, error).

    Capped at `KEEP`, which is also how many are kept -- see that constant. The
    cap hides nothing: `prune` removes what falls past it.
    """
    if not cloudsave.valid_name(remote):
        return [], "That storage cannot be used."
    ok, output = cloudsave.rclone(
        ["lsjson", "%s:%s" % (remote, REPLACED), "--dirs-only"], LIST_SECONDS,
    )
    if not ok:
        # Nothing has ever been replaced. Not an error: it is the ordinary
        # state of a remote nobody has overwritten anything on.
        if "not found" in output.lower():
            return [], ""
        return [], output
    try:
        entries = json.loads(output or "[]")
    except ValueError:
        return [], "The storage answered with something unreadable."

    listed = []
    for entry in entries:
        name = entry.get("Name") or ""
        if not _SEGMENT.match(name):
            continue
        listed.append({"stamp": name, "label": _stamp_label(name)})
    listed.sort(key=lambda one: one["stamp"], reverse=True)
    return listed[:keep] if keep else listed, ""


def prune(remote, keep=KEEP):
    """Remove replaced states past the newest `keep`. Returns how many went.

    The one thing here that deletes from somebody's storage, and it is bounded
    to what this plugin made: folders under `REPLACED`, named as a timestamp,
    older than the ones the restore screen is offering. Saves are never touched
    -- see the module docstring.

    It runs after a copy rather than on a schedule, because that is the moment a
    new one is made and the moment somebody is watching. A failure is logged and
    swallowed: the copy worked, and tidying up afterwards is not a reason to
    tell somebody their saves did not go.
    """
    listed, error = snapshots(remote, keep=0)
    if error:
        return 0
    gone = 0
    for old in listed[keep:]:
        ok, output = cloudsave.rclone(
            ["purge", "%s:%s/%s" % (remote, REPLACED, old["stamp"])], LIST_SECONDS)
        if ok:
            gone += 1
        else:
            decky.logger.warning(
                "Could not remove replaced copy %s: %s", old["stamp"], output)
    if gone:
        decky.logger.info("Removed %d replaced cop(ies) from %s", gone, remote)
    return gone


def _root_for(stamp=""):
    """Which tree to read: the live saves, or the state one copy replaced."""
    if not stamp:
        return ROOT
    if not _SEGMENT.match(stamp):
        return ""
    return "%s/%s" % (REPLACED, stamp)


def _index(remote, stamp=""):
    """Every file under one of our folders on `remote`, as rclone reports them.

    One listing for the whole tree rather than one per emulator: this is a
    network round trip and the panel asks for it to draw a list.
    """
    root = _root_for(stamp)
    if not root:
        return False, [], "That is not a copy this can read."
    ok, output = cloudsave.rclone(
        ["lsjson", "%s:%s" % (remote, root), "--recursive", "--files-only"],
        LIST_SECONDS,
    )
    if not ok:
        # An empty folder and a remote that has never been written to are the
        # same answer here, and rclone says "directory not found" for both.
        if "not found" in output.lower():
            return True, [], ""
        return False, [], output
    try:
        entries = json.loads(output or "[]")
    except ValueError:
        return False, [], "The storage answered with something unreadable."
    return True, entries if isinstance(entries, list) else [], ""


def contents(remote, stamp=""):
    """What is on `remote`, per emulator, in the shape the restore screen reads.

    `stamp` reads one of the folders under `REPLACED` instead of the live saves.
    Same tree, same shape, so the screen needs no second kind of row.

    Deliberately the same shape `savedata.describe` returns for a zip, down to
    `installed` and `present`, so one list of rows and one pair of buttons serve
    both. A restore that means something different depending on where the saves
    came from is two features wearing one word.
    """
    if not cloudsave.valid_name(remote):
        return {"ok": False, "error": "That storage cannot be used."}

    ok, entries, error = _index(remote, stamp)
    if not ok:
        return {"ok": False, "error": error or "The storage did not answer."}

    here = {source["id"]: source for source in savedata._all_sources()}
    landing = {}
    for source in here.values():
        for segment, path in _roots_of(source):
            landing[(source["id"], segment)] = path

    found = {}
    for entry in entries:
        parts = (entry.get("Path") or "").split("/")
        if len(parts) < 3:
            # <emulator>/<root>/<file> is the shallowest thing that means
            # anything. Anything else was not written by this.
            continue
        emulator, segment = parts[0], parts[1]
        source = here.get(emulator)
        row = found.setdefault(emulator, {
            "id": emulator,
            # An emulator this Deck does not have still gets a row, saying so,
            # rather than being dropped -- the same rule the archive's own
            # listing follows, and it is how somebody learns their Vita saves
            # are safe on a Deck that has no Vita3K on it right now.
            "name": source["name"] if source else emulator,
            "installed": source is not None,
            "files": 0,
            "bytes": 0,
            "present": 0,
        })
        row["files"] += 1
        try:
            row["bytes"] += int(entry.get("Size") or 0)
        except (TypeError, ValueError):
            pass
        local = landing.get((emulator, segment))
        if local and os.path.exists(os.path.join(local, *parts[2:])):
            row["present"] += 1

    return {"ok": True, "sources": sorted(found.values(), key=lambda row: row["name"])}


def pull_steps(remote, ids=None, replace=False, stamp=""):
    """One rclone call per save root, coming the other way. Returns (steps, error).

    `replace` is the same switch as the local restore and means the same thing:
    off writes only what is not already here, which cannot lose a save played
    since the copy went up; on overwrites, which is what somebody wants when the
    saves on this Deck are the ones they are trying to be rid of.

    Off is `--ignore-existing`, which is rclone's own version of that rule and
    is stricter than comparing timestamps -- a file here is left alone whatever
    its age, because "newer" across two devices and a cloud is a claim about
    clocks nobody should be betting a save on.

    No `--backup-dir` on this side, unlike `push_steps`, and the difference is
    the question that was asked. Off overwrites nothing at all. On is reached
    through a confirmation that counts the files it will overwrite and says
    there is no undo -- so what it destroys was named before it happened.
    Pressing copy asks nothing, which is exactly why that side needs a net.

    The remote is listed first, and what comes back is matched **per save
    root**, not per emulator. Matching per emulator was a real failure: RPCS3
    keeps `savedata` and `savestates`, only one of them had ever been copied up,
    and a restore planned a call for both -- so rclone was asked to read a
    folder that was never created and the dialog filled with "error reading
    source root directory: directory not found". Every emulator with anything at
    all up there produced it for the roots that had nothing.
    """
    if not cloudsave.valid_name(remote):
        return [], "That storage cannot be used."

    root = _root_for(stamp)
    if not root:
        return [], "That is not a copy this can read."

    ok, entries, error = _index(remote, stamp)
    if not ok:
        return [], error or "The storage did not answer."
    # The pairs that actually exist up there. `<emulator>/<root>/<file>` is the
    # shallowest path that means anything, so anything shorter is not ours.
    up_there = set()
    for entry in entries:
        parts = (entry.get("Path") or "").split("/")
        if len(parts) >= 3:
            up_there.add((parts[0], parts[1]))

    listed = [source for source in _sources(ids)
              if any(source["id"] == emulator for emulator, _ in up_there)]
    if not listed:
        return [], "That storage has nothing for the emulators installed here."

    steps = []
    for source in listed:
        for segment, path in _roots_of(source):
            if (source["id"], segment) not in up_there:
                continue
            target = _safe(source["id"], segment)
            if not target:
                continue
            args = ["copy", "%s:%s/%s" % (remote, root, target), path]
            if not replace:
                args.append("--ignore-existing")
            command = cloudsave.argv(args + _STATS)
            if not command:
                return [], "The cloud transfer tool is missing."
            steps.append({"id": source["id"], "name": source["name"], "argv": command})
    return steps, ""
