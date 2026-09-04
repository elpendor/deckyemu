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


#: How rclone decides whether two files are the same, and what it does not
#: bother to keep in step.
#:
#: **Measured on the device, and it was costing every push its whole payload.**
#: rclone's default is size-and-modification-time, and Dropbox cannot set a
#: modification time at all -- so it re-uploaded every file to stamp one, and
#: said so in the log: "Forced to upload files to set modification times on this
#: backend". Forty kilobytes of unchanged saves, on somebody's data plan, every
#: time a game closed.
#:
#: `--checksum` compares content instead, which every provider here can answer
#: without being sent anything, and `--no-update-modtime` says not to reach for
#: the timestamp when the content already matches. Nothing needs those
#: timestamps: what tells this Deck's uploads from another device's is the
#: record beside the saves -- see `compare`.
_BY_CONTENT = ["--checksum", "--no-update-modtime"]

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
                + _excludes(source) + _BY_CONTENT + _STATS
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


def _index(remote, stamp="", under=""):
    """Every file under one of our folders on `remote`, as rclone reports them.

    `under` narrows it to one emulator, and doing so is worth real time:
    measured on the device against Dropbox, listing the whole saves tree is
    14.5 seconds and one emulator's subtree is 5. `--fast-list` changes neither
    -- the cost is per-directory API latency, not the listing strategy -- so the
    only way to spend less is to ask for less.
    """
    root = _root_for(stamp)
    if not root:
        return False, [], "That is not a copy this can read."
    if under:
        if not _SEGMENT.match(under):
            return False, [], "That is not a copy this can read."
        root = "%s/%s" % (root, under)
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


#: What every copy up leaves beside the saves, and what every launch reads.
#:
#: **Because provider metadata is not something to build on.** Dropbox cannot
#: set a modification time at all -- rclone re-uploads a file to stamp it, and
#: says so in the log -- pCloud has the same limitation, S3 keeps it as metadata
#: that a copy rewrites, and SFTP just works. A comparison resting on those
#: behaves differently on every service somebody might choose, which is not what
#: "cloud saves" can mean.
#:
#: So the only numbers compared are ones written here: what was uploaded, how
#: big each file was, when this Deck's clock said it happened, and which Deck
#: did it. Every provider stores a JSON file identically.
STATE_FILE = ".deckyemu-state.json"

#: Where the same record is kept on this side, so "did somebody else write to
#: the storage since we last did?" is one comparison rather than a guess.
STATE_DIR = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "cloudstate")

#: How long the check before a launch may take.
#:
#: **This is the number that decides whether launching a game got slower.** It
#: is not a timeout for a slow network so much as a promise: whatever the
#: storage is doing, the game starts within about this long. Six seconds is the
#: outside of what a Dropbox listing takes on hotel wifi; the ordinary answer
#: arrives in well under one.
BEFORE_PLAY_SECONDS = 6


def _device():
    """Which Deck this is, as far as a storage needs to know.

    Not a fingerprint and not stable across a reinstall -- it only has to tell
    "this Deck" from "some other device", and it is written into a file in
    somebody's own storage, so it says nothing about the machine.
    """
    path = os.path.join(STATE_DIR, "device")
    try:
        with open(path, encoding="utf-8") as handle:
            found = handle.read().strip()
        if found:
            return found
    except OSError:
        pass
    made = "deck-%s" % os.urandom(4).hex()
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(made)
    except OSError as error:
        decky.logger.warning("Could not keep a device name: %s", error)
    return made


def _local_files(source):
    """Every save file of one emulator, as `<root>/<relative>`: (size, mtime)."""
    listed = {}
    skip = savedata._SKIP_TOP if source.get("whole") else ()
    for segment, path in _roots_of(source):
        for absolute, relative in savedata._walk(path, skip):
            try:
                found = os.stat(absolute)
            except OSError:
                continue
            listed["%s/%s" % (segment, relative.replace(os.sep, "/"))] = (
                found.st_size, int(found.st_mtime))
    return listed


def _state_of(source):
    """What this Deck would upload, in the shape the record keeps it."""
    return {
        "device": _device(),
        "at": int(time.time()),
        "files": {name: {"size": size, "mtime": mtime}
                  for name, (size, mtime) in _local_files(source).items()},
    }


def _mine_path(source_id):
    return os.path.join(STATE_DIR, "%s.json" % source_id)


def read_mine(source_id):
    """The record of what this Deck last put up for one emulator, or {}."""
    try:
        with open(_mine_path(source_id), encoding="utf-8") as handle:
            found = json.load(handle)
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def _keep_mine(source_id, state):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(_mine_path(source_id), "w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except OSError as error:
        decky.logger.warning("Could not keep the cloud record: %s", error)


def changed_since_push(source_id):
    """Whether this emulator's saves differ from what was last put up.

    **A game closing is not evidence that anything was written.** Steam counts
    an app as running while its launcher script is still deciding what to do, so
    a launch the two-games gate refused, a launch somebody declined at the save
    conflict, and a game that failed to start all look exactly like a session
    that ended. Every one of them was uploading, and the upload rewrote the
    record beside the saves -- which, in the conflict case, quietly did the
    thing the dialog had just been used to decline.

    So the question asked after a game is not "did something close" but "is any
    of this different". Answered from `os.stat` against the record kept here:
    no network, no provider, and no upload at all when a session wrote nothing.
    """
    source = next(
        (one for one in savedata._all_sources() if one["id"] == source_id), None)
    if source is None:
        return False
    mine = read_mine(source_id)
    # Never uploaded. Everything is new by definition.
    if not mine:
        return True
    was = mine.get("files") or {}
    now = _local_files(source)
    if set(was) != set(now):
        return True
    for name, (size, mtime) in now.items():
        said = was.get(name) or {}
        if said.get("size") != size or said.get("mtime") != mtime:
            return True
    return False


def record_push(remote, source_id):
    """Write the record of what was just uploaded, both sides. (ok, error).

    Both, and the same bytes: the storage's copy says what is up there, and this
    Deck's copy says what *it* put there. A launch compares the two, and a
    difference means another device wrote since -- which is the only question
    worth asking, and it is answered without consulting a provider for anything
    but a file it was handed.
    """
    source = next(
        (one for one in savedata._all_sources() if one["id"] == source_id), None)
    if source is None or not _SEGMENT.match(source_id):
        return False, ""

    state = _state_of(source)
    body = json.dumps(state, sort_keys=True)
    staged = os.path.join(STATE_DIR, "%s.uploading" % source_id)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(staged, "w", encoding="utf-8") as handle:
            handle.write(body)
    except OSError as error:
        return False, str(error)

    ok, output = cloudsave.rclone(
        ["copyto", staged, "%s:%s/%s/%s" % (remote, ROOT, source_id, STATE_FILE)],
        LIST_SECONDS,
    )
    try:
        os.remove(staged)
    except OSError:
        pass
    if ok:
        _keep_mine(source_id, state)
    return ok, "" if ok else output


def _identity(state):
    """Which upload a record is, as the pair that names it."""
    return {"device": (state or {}).get("device") or "",
            "at": int((state or {}).get("at") or 0)}


def remember_answer(source_id, theirs):
    """Record that a save conflict against `theirs` has been settled.

    **"Keep this Deck's" has to be remembered or it is not an answer.** Nothing
    about the files changes when somebody chooses their own copy -- so the next
    launch compares the same two records, finds the same disagreement, and asks
    the same question. A decision that has to be made again every time is not a
    decision, it is a nag.

    What is remembered is which upload was declined, not "stop asking": another
    device writing again is a new state and a new question. The record is
    dropped the moment this Deck uploads, because that upload settles it for
    real.
    """
    mine = read_mine(source_id)
    if not mine:
        return
    mine["answered"] = _identity(theirs)
    _keep_mine(source_id, mine)


def preserve_local(remote, source_id, names):
    """Put this Deck's copies of `names` beside the other replaced ones. (ok, error).

    **The other half of a promise that was only half kept.** A copy *up* moves
    whatever it would overwrite into `REPLACED` first, so nothing this plugin
    does automatically can destroy a save in the cloud. Taking the cloud's copy
    at a conflict overwrites files here instead -- and those are, by definition,
    the versions the cloud does *not* have. Without this they were the one thing
    the feature could destroy, under a dialog saying neither answer loses
    anything.

    They go to the same folder everything else preserved goes to, so the restore
    screen lists them with no new idea and no new screen: they are simply
    another "Replaced <date>" row.

    One call per save root rather than one per file, with the names handed to
    rclone in a file -- a conflict over twenty memory cards should not be twenty
    round trips in front of a game that is waiting.
    """
    source = next(
        (one for one in savedata._all_sources() if one["id"] == source_id), None)
    if source is None or not _SEGMENT.match(source_id) or not names:
        return True, ""

    aside = "%s:%s/%s/%s" % (
        remote, REPLACED, time.strftime("%Y%m%d-%H%M%S"), source_id)
    roots = {segment: path for segment, path in _roots_of(source)}

    wanted = {}
    for name in names:
        segment, _, relative = name.partition("/")
        if relative and segment in roots:
            wanted.setdefault(segment, []).append(relative)

    for segment, relatives in wanted.items():
        listing = os.path.join(STATE_DIR, "%s.keeping" % source_id)
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(listing, "w", encoding="utf-8") as handle:
                handle.write("\n".join(relatives))
        except OSError as error:
            return False, str(error)
        ok, output = cloudsave.rclone(
            ["copy", roots[segment], "%s/%s" % (aside, segment),
             "--files-from", listing] + _BY_CONTENT,
            TRANSFER_SECONDS,
        )
        try:
            os.remove(listing)
        except OSError:
            pass
        if not ok:
            return False, output
    decky.logger.info(
        "Kept this Deck's copy of %d file(s) for %s before replacing them",
        len(names), source_id)
    return True, ""


def adopt_state(remote, source_id):
    """Take the storage's record as this Deck's own. (ok, error).

    For the answer "play with the cloud's": the files here are now the files up
    there, so the record of what this Deck last put there is that one. Copying
    it rather than writing a fresh one keeps the two byte-identical, which is
    what `compare` checks -- a new record would look like a third device.
    """
    theirs, error = _remote_state(remote, source_id, LIST_SECONDS)
    if error or not theirs:
        return False, error
    _keep_mine(source_id, theirs)
    return True, ""


def _remote_state(remote, source_id, seconds):
    """The record sitting beside one emulator's saves. (state, error).

    One request, and a small one: the record lists every file, so this answers
    what is up there as well as who put it there. Listing the folder as well
    would be a second round trip on the front of a launch.
    """
    ok, output = cloudsave.rclone(
        ["cat", "%s:%s/%s/%s" % (remote, ROOT, source_id, STATE_FILE)], seconds)
    if not ok:
        # Never copied up, or copied up by a version that did not keep records.
        # Both mean there is nothing here to compare against.
        if "not found" in output.lower() or "no such" in output.lower():
            return {}, ""
        return {}, output
    try:
        found = json.loads(output or "{}")
    except ValueError:
        return {}, ""
    return (found if isinstance(found, dict) else {}), ""


def name_of(source_id):
    """What to call one save source on screen, or its id if it is not here.

    Needed because a conflict is about an *emulator*, not a game: the question
    names what the answer covers, and "RetroArch" is that. See the module
    docstring for why the scope is what it is.
    """
    source = next(
        (one for one in savedata._all_sources() if one["id"] == source_id), None)
    return (source or {}).get("name") or source_id


def _nothing(error):
    """The shape `compare` answers with when there is nothing to say."""
    return {"missing": 0, "differing": [], "roots": [], "here": 0, "there": 0,
            "theirs": {"device": "", "at": 0}, "error": error}


def compare(remote, source_id, seconds=BEFORE_PLAY_SECONDS):
    """What one emulator has up there that this Deck does not. One request.

    Returns a dict: `missing` (files up there and not here), `differing` (names
    that this Deck and another device have both changed), `roots` (which save
    roots exist up there, so the fetch that follows does not ask again), `here`
    and `there` (when each side was last written, as unix seconds) and `error`.

    **Nothing here reads a provider's metadata, and that is the point.** Dropbox
    cannot set a modification time -- rclone re-uploads a file to stamp one, and
    says so -- pCloud has the same limitation, S3 keeps it as metadata a copy
    rewrites, and SFTP just works. Comparing those would mean a feature that
    behaves differently on every service somebody might pick. The only numbers
    compared are ones this plugin wrote: the record beside the saves says what
    was uploaded and which Deck uploaded it, and the copy kept here says what
    *this* Deck last put there. Every provider stores a JSON file the same way.

    **The question is only ever "did something else write since we did?"** If
    the record up there is the one this Deck wrote, nothing has, whatever the
    files look like -- so a save played here and not yet uploaded is not a
    conflict, it is the ordinary state of a save after playing. If the record is
    somebody else's, then the files this Deck has also changed since its own
    last upload are the ones worth asking about, and only those.
    """
    if not cloudsave.valid_name(remote):
        return _nothing("That storage cannot be used.")
    source = next(
        (one for one in savedata._all_sources() if one["id"] == source_id), None)
    if source is None or not _SEGMENT.match(source_id):
        return _nothing("")

    theirs, error = _remote_state(remote, source_id, seconds)
    if error:
        return _nothing(error)
    if not theirs:
        # Nothing up there, or up there from before records were kept. Either
        # way there is nothing to compare and nothing to ask.
        return _nothing("")

    up_there = theirs.get("files") or {}
    here_now = _local_files(source)
    mine = read_mine(source_id)

    # Whether the record up there is this Deck's own last upload. Compared on
    # the whole record rather than a timestamp: two Decks writing in the same
    # second is unlikely and a clock going backwards is not.
    ours = bool(mine) and _identity(mine) == _identity(theirs)
    # Or somebody has already looked at this exact upload and kept their own.
    # Not "stop asking": another device writing again is a new state, and a new
    # question. See `remember_answer`.
    settled = ours or (bool(mine)
                       and mine.get("answered") == _identity(theirs))

    missing = 0
    differing = []
    roots = set()
    for name, said in up_there.items():
        root = name.split("/", 1)[0]
        if not isinstance(said, dict):
            continue
        roots.add(root)
        if name not in here_now:
            missing += 1
            continue
        if settled:
            # Our own upload, or one somebody has already decided about.
            # Whatever differs is what this Deck has done since, which is not a
            # question for anybody.
            continue
        was = (mine.get("files") or {}).get(name)
        size, mtime = here_now[name]
        changed_here = was is None or (
            was.get("size") != size or was.get("mtime") != mtime)
        changed_there = said.get("size") != size or said.get("mtime") != mtime
        if changed_here and changed_there:
            # The whole name, not the basename: this list is what decides
            # which files get preserved before they are overwritten, and a
            # basename does not say which save root it came from.
            differing.append(name)

    return {
        "missing": missing,
        "differing": differing,
        "roots": sorted(roots),
        # What each side last wrote, by its own clock. Shown in the dialog and
        # never compared with each other -- see the module docstring.
        "here": int(mine.get("at") or 0),
        "there": int(theirs.get("at") or 0),
        # Which upload is up there, so an answer about it can be remembered.
        "theirs": _identity(theirs),
        "error": "",
    }


def pull_steps(remote, ids=None, replace=False, stamp="", known=None):
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

    `known` is the set of `(emulator, root)` pairs a caller has already looked
    up -- `compare` returns them, and passing them through is what keeps a
    launch to one network round trip instead of two.

    Otherwise the remote is listed first, and what comes back is matched **per
    save root**, not per emulator. Matching per emulator was a real failure: RPCS3
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

    if known is not None:
        up_there = set(known)
    else:
        # One emulator asked for is one emulator listed. The whole tree costs
        # three times as long against Dropbox, and a restore of one emulator
        # has no use for the rest of it.
        only = ids[0] if (ids and len(ids) == 1) else ""
        ok, entries, error = _index(remote, stamp, only)
        if not ok:
            return [], error or "The storage did not answer."
        # The pairs that actually exist up there. `<emulator>/<root>/<file>` is
        # the shallowest path that means anything; anything shorter is not ours.
        # A scoped listing drops the emulator from the path, so it is put back.
        up_there = set()
        for entry in entries:
            parts = (entry.get("Path") or "").split("/")
            if only:
                parts = [only] + parts
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
            command = cloudsave.argv(args + _BY_CONTENT + _STATS)
            if not command:
                return [], "The cloud transfer tool is missing."
            steps.append({"id": source["id"], "name": source["name"], "argv": command})
    return steps, ""
