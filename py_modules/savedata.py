"""Collecting save data off the device, so it can be sent somewhere it survives.

Nothing else here touches saves, and two of the plugin's own buttons destroy
them: uninstalling an emulator with its data removes `~/.var/app/<id>` entire,
and the reset tab clears the same directories deliberately. Neither is
recoverable, and Game Mode offers no route to those paths at all -- so the only
way to keep a save today is to leave Game Mode, which is the one thing this
plugin exists to avoid.

**Where saves live is read, never assumed.** RetroArch is why. Its own config on
the development Deck points `savefile_directory` at
`~/Emulation/saves/retroarch/saves`, EmuDeck's location -- while the flatpak's
own `config/retroarch/saves` still sits there holding 436KB of older files. A
backup that assumed the default would have copied the stale directory, reported
success, and carried none of the live saves. So RetroArch is asked (`ra_detect`)
and every other emulator declares its own paths in the catalog.

**An emulator that installs games into itself has to declare `saves`; one that
only reads ROMs off the disk does not.** RPCS3, Vita3K, Ryujinx and the rest keep
games and firmware beside the saves, and a backup of the whole directory would be
gigabytes of re-downloadable content -- so those name the save directory and
nothing else. Dolphin, PCSX2, DuckStation and PPSSPP keep nothing there but
configuration, memory cards and states, and for them the whole directory *is* the
right answer: it needs no per-emulator fact that could rot, and it cannot miss a
save by naming the wrong subdirectory. `sources()` measures both, so whichever
applies, the size is on screen before anything is sent.

The flatpak `cache` directory is the one thing dropped from a whole-directory
backup. It is `XDG_CACHE_HOME` by definition rather than by guess -- shader and
recompiler caches that the emulator rebuilds on its own, and on RPCS3 the largest
thing in the tree.

**The archive says where every file came from.** `manifest.json` maps each root
to the absolute directory it was read from, so a restore puts files back rather
than working it out from the shape of the paths -- which would be a guess in the
one direction where a wrong answer overwrites something.
"""

import json
import os
import posixpath
import shutil
import time
import zipfile

import decky

import emulator_catalog
import ra_detect
import sysenv
from emulator_catalog import schema

#: Version of the archive layout, written into the manifest and checked when one
#: is read back. A restore that cannot read the layout must say so rather than
#: extract half of it somewhere plausible.
FORMAT = 1

#: Where a built archive waits to be read off the device. decky's runtime
#: directory rather than the transfer folder: this is the plugin's own working
#: file, and the transfer folder is scanned for arrivals the user is meant to act
#: on. Whoever builds one owns deleting it -- a backup left here is a copy of
#: somebody's saves that nothing is going to clean up.
BACKUP_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "backups")

#: Where a backup *arriving* from another device is kept, under the user's own
#: `~/deckyemu` rather than decky's runtime directory.
#:
#: Not the transfer folder. That is the ROM inbox: everything in it is offered as
#: something to add to Steam, so a 75MB archive of save files sat in the picker
#: pretending to be a game -- and, being a zip with a `.rtc` inside, was offered
#: libretro cores to run it with. `sysenv.user_dir`'s docstring already reserves
#: room for exactly this: "there is room for whatever else needs a home".
#:
#: Kept rather than deleted after restoring, which is where this parts company
#: with `unpack_transferred_file`. That deletes the zip it extracted because the
#: extraction is all-or-nothing, so afterwards the archive holds nothing that is
#: not already on disk. A restore is partial by default -- it skips saves already
#: here -- so the archive is still the only copy of the versions that were
#: skipped, and deleting it would take away the ability to come back and replace
#: them. Discarding it is offered instead.
ARRIVALS_SUBDIR = "backups"


def arrivals_dir(create=True):
    """`<home>/deckyemu/backups`, created on demand."""
    return sysenv.user_dir(ARRIVALS_SUBDIR, create=create)

#: Dropped from a whole-directory backup. `cache` is a flatpak's XDG_CACHE_HOME,
#: so this is the definition rather than a guess about any one emulator, and it
#: is the largest thing in several of these trees.
#:
#: `.ld.so` is flatpak's own linker cache, and it holds a symlink -- which is
#: how it announced itself, three times, in the middle of a backup: "NOTICE:
#: .ld.so/active: Can't follow symlink without -L/--copy-links". Nothing behind
#: it is a save, and a line that reads like an error in the log of the feature
#: whose whole job is not losing saves is worth the one word it costs to stop.
#:
#: `log` and `shaders` are the same thing under other names, and they are what
#: makes a whole-directory emulator look like it has new saves constantly:
#: Azahar truncates its log every time it starts and writes a precompiled
#: shader for every game that runs, both inside the directory it keeps its NAND
#: in. Opening an emulator once then showed up as save data to upload. Neither
#: is anybody's save: a log is a record of the last run and a shader cache is
#: rebuilt from the game.
_SKIP_TOP = ("cache", ".ld.so", "log", "shaders")

#: Written beside the archive while it is being built, and renamed over only once
#: every file is in. Same suffix and same reason as `unpack`: something scanning
#: this folder must not find a half-written archive and believe it.
_PARTIAL = ".deckyemu-tmp"


def _walk(root, skip_top=(), except_names=()):
    """Every file under `root`, as (absolute path, path relative to root).

    Symlinks are followed for their target's contents only when they point back
    inside the root: an emulator that symlinks its save directory onto an SD card
    is normal, and one that has a link to somewhere else in the home directory
    must not turn a save backup into a copy of that.

    `except_names` are filenames to leave behind wherever they appear. **It
    exists for a config that shares a folder with the saves**, which is not a
    tidiness problem: BigPEmu keeps `BigPEmuConfig.bigpcfg` beside its EEPROMs,
    and that file binds the controller by device id -- restore it onto another
    Deck and the pad is bound to a controller that is not there, which reads as
    a dead pad with every binding looking correct.
    """
    found = []
    root = os.path.normpath(root)

    # A declared save can be one file rather than a directory -- a memory card,
    # a record of achievements -- and `os.walk` over a file yields nothing at
    # all. Silently backing up none of it is the worst answer available.
    if os.path.isfile(root):
        if os.path.basename(root) in except_names:
            return []
        return [(root, os.path.basename(root))]

    for current, directories, files in os.walk(root, followlinks=False):
        relative = os.path.relpath(current, root)
        if relative == ".":
            directories[:] = [name for name in directories if name not in skip_top]
            relative = ""
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path) and not os.path.realpath(path).startswith(root + os.sep):
                continue
            if not os.path.isfile(path):
                continue
            if name in except_names:
                continue
            found.append((path, posixpath.join(*relative.split(os.sep), name) if relative else name))
    return found


def links_skipped(root, skip_top=()):
    """Symlinks under `root` that a backup walks straight past.

    **Skipping is the old behaviour; being quiet about it is the bug.** A
    directory reached through a symlink is not descended into -- `os.walk` does
    not follow links and rclone does not either without `--copy-links` -- so an
    emulator whose save folder was moved to the SD card and linked back has its
    saves in neither the archive nor the storage, and nothing said so. Both
    halves agree, which is why it never looked broken: the record shows what the
    copy shows, and both show nothing.

    Following them instead is a real decision with a real cost -- a link
    pointing at a ROM library would put the ROM library in somebody's Dropbox --
    so what this does is name them. Deciding is then somebody's to make with
    the facts in front of them.
    """
    found = []
    root = os.path.normpath(root)
    for current, directories, _files in os.walk(root, followlinks=False):
        relative = os.path.relpath(current, root)
        if relative == ".":
            directories[:] = [name for name in directories if name not in skip_top]
            relative = ""
        for name in sorted(directories):
            path = os.path.join(current, name)
            if not os.path.islink(path):
                continue
            found.append({
                "at": posixpath.join(*relative.split(os.sep), name) if relative else name,
                "target": os.path.realpath(path),
            })
    return found


def _measure(root, skip_top=(), except_names=()):
    # The same exclusions the build applies, or the panel counts files it is
    # not going to carry -- and the count is what somebody reads as "this is
    # everything".
    files = _walk(root, skip_top, except_names)
    total = 0
    for path, _ in files:
        try:
            total += os.path.getsize(path)
        except OSError:
            # Vanished between the walk and the measure. Counting it as nothing
            # is right: the build skips it for the same reason.
            pass
    return len(files), total


def _retroarch_source():
    """RetroArch's saves and states, read out of its own configuration.

    Absent rather than guessed when RetroArch is not installed, and absent when
    its config names directories that do not exist -- which is what a fresh
    install looks like before its first save.
    """
    install = ra_detect.detect()
    if not install:
        return None
    roots = []
    for label, path in ra_detect.save_dirs(install["config_dir"]).items():
        if path and os.path.isdir(path):
            roots.append((label, path))
    if not roots:
        return None
    return {"id": "retroarch", "name": "RetroArch", "roots": roots, "whole": False}


def relative_of(path, home):
    """`path` as the home-relative form the catalog declared it in."""
    return os.path.relpath(path, home).replace(os.sep, "/")


def _is_cache_root(relative):
    """Whether a declared directory is the cache half of an XDG layout.

    `.cache/<name>` holds shader caches, thumbnails and game lists: rebuilt on
    demand, large, and not a save. Excluded from a backup for exactly the reason
    `_SKIP_TOP` excludes a flatpak's `cache` -- but *not* from `owned_roots`,
    because a reset that leaves a stale cache behind is a reset that did not
    happen.
    """
    return relative == ".cache" or relative.startswith(".cache/")


def _catalog_sources():
    """The catalog emulators that are installed, and what to take from each."""
    home = sysenv.user_home()
    found = []
    for entry in emulator_catalog.CATALOG:
        owned = [
            os.path.join(home, *relative.split("/"))
            for relative in schema.owned_roots(entry)
        ]
        if not any(os.path.isdir(path) for path in owned):
            continue

        declared = list(entry.get("saves") or ())
        if declared:
            roots = [
                (relative.rsplit("/", 1)[-1], os.path.join(home, *relative.split("/")))
                for relative in declared
            ]
        else:
            # A root that *is* a cache directory, rather than one holding a
            # `cache` folder. An imported entry lists the XDG directories it
            # owns, and `.cache/<name>` is one of them -- so the whole of an
            # emulator's shader cache and game-list thumbnails arrived in the
            # backup, and in the pending upload count, as saves. The same
            # definition as `_SKIP_TOP`, applied one level up.
            roots = [(os.path.basename(path), path) for path in owned
                     if not _is_cache_root(relative_of(path, home))]
        roots = [(label, path) for label, path in roots
                 if os.path.isdir(path) or os.path.isfile(path)]
        if not roots:
            continue
        found.append({
            "id": entry["id"],
            "name": entry["name"],
            "roots": roots,
            "whole": not declared,
            "except": tuple(entry.get("saves_except") or ()),
        })
    return found


def _all_sources():
    """Every emulator and port with something to back up, by name.

    By name because that is how the restore list reads and how a list of a dozen
    things is looked through. RetroArch used to lead, on the reasoning that it
    leads the setup page -- but nothing here is missing for the reader to
    notice, and a list that is alphabetical except for one row reads as a list
    that is not sorted.
    """
    found = []
    libretro = _retroarch_source()
    if libretro:
        found.append(libretro)
    return sorted(found + _catalog_sources(),
                  key=lambda source: source["name"].casefold())


def sources():
    """What a backup would carry, per emulator, measured rather than estimated.

    `whole` says this emulator declared no save directory, so what is offered is
    everything it keeps -- which the UI has to say out loud, because it is the
    difference between two megabytes of memory cards and everything the user has
    configured.
    """
    listed = []
    for source in _all_sources():
        files = 0
        total = 0
        skip = _SKIP_TOP if source["whole"] else ()
        for _, path in source["roots"]:
            count, size = _measure(path, skip, source.get("except", ()))
            files += count
            total += size
        # Named beside the count, because the count is what somebody reads as
        # "this is everything" -- and it is not, when a folder here is a link.
        links = []
        for _, path in source["roots"]:
            links += links_skipped(path, skip)
        listed.append({
            "id": source["id"],
            "name": source["name"],
            "whole": source["whole"],
            "paths": [path for _, path in source["roots"]],
            "files": files,
            "bytes": total,
            "links": links,
        })
    return listed


def _key(source_id, label, taken):
    """A short readable name for one root inside the archive, unique across it."""
    base = "%s-%s" % (source_id, label.strip("._").lower().replace(" ", "-") or "data")
    key = base
    suffix = 2
    while key in taken:
        key = "%s-%d" % (base, suffix)
        suffix += 1
    taken.add(key)
    return key


def build(destination, ids=None):
    """Write an archive of every listed emulator's saves to `destination`.

    `ids` narrows it to those source ids, which is what a user unticking one
    emulator asks for. None means all of them.

    Written to a temporary name and renamed into place, so a disk that fills up
    halfway leaves no archive rather than a truncated one somebody might send.
    Returns what went in, so the caller can say so without opening it again.
    """
    listed = [
        source for source in _all_sources() if ids is None or source["id"] in ids
    ]
    if not listed:
        return {"ok": False, "error": "There are no saves to back up yet."}

    manifest = {"format": FORMAT, "home": sysenv.user_home(), "roots": []}
    partial = destination + _PARTIAL
    taken = set()
    written = 0
    try:
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:
            for source in listed:
                skip = _SKIP_TOP if source["whole"] else ()
                for label, path in source["roots"]:
                    key = _key(source["id"], label, taken)
                    manifest["roots"].append({
                        "key": key,
                        "id": source["id"],
                        "name": source["name"],
                        "path": path,
                        "whole": source["whole"],
                    })
                    for absolute, relative in _walk(path, skip, source.get("except", ())):
                        try:
                            bundle.write(absolute, posixpath.join("files", key, relative))
                        except OSError as error:
                            # One unreadable file must not cost the whole backup.
                            # It is named in the log; every other save still goes.
                            decky.logger.warning(
                                "Save backup skipped %s: %s", absolute, error
                            )
                            continue
                        written += 1
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        os.replace(partial, destination)
    except OSError as error:
        decky.logger.error("Could not build the save backup: %s", error)
        try:
            os.remove(partial)
        except OSError:
            pass
        return {"ok": False, "error": "The backup could not be written: %s" % error}

    size = os.path.getsize(destination)
    decky.logger.info(
        "Save backup: %d file(s) from %d emulator(s), %d bytes",
        written, len(listed), size,
    )
    return {
        "ok": True,
        "path": destination,
        "files": written,
        "bytes": size,
        "emulators": [source["name"] for source in listed],
    }


def default_name():
    """What the archive is called. Dated, because a second backup is a second file."""
    return time.strftime("deckyemu-saves-%Y%m%d-%H%M%S.zip")


# ---------------------------------------------------------------- restoring
#
# **The archive never says where a file goes.** It arrived over the network from
# a device this plugin knows nothing about, and honouring an absolute path out of
# it would be an arbitrary write into the home directory -- the same hazard
# `unpack` refuses by flattening to basenames, in a direction where flattening is
# not available because the tree is the point.
#
# So the manifest is read for *which emulator* each root belongs to, and the
# destination is recomputed from the catalog as it stands on this device. A key
# naming an emulator that is not installed is reported and skipped rather than
# guessed at; a member whose relative path would climb out of its root is
# refused. Between the two, nothing outside an installed emulator's own save
# directory can be written no matter what the archive contains.


def _current_roots():
    """{key: (source, absolute path)} for the roots this device has right now.

    The keys are the ones `build` wrote, and they are stable across devices
    because `_key` is built from the emulator's id and the last segment of the
    path -- both properties of that emulator alone. Which *other* emulators are
    installed cannot shift them, which is what lets an archive taken on one Deck
    be read on another.

    What does move them is the catalog changing an entry's `saves`. That is why
    an unrecognised key is reported rather than matched to something nearby: a
    near-miss here writes somebody's saves into the wrong directory.
    """
    taken: set = set()
    mapping = {}
    for source in _all_sources():
        for label, path in source["roots"]:
            mapping[_key(source["id"], label, taken)] = (source, path)
    return mapping


def _read_manifest(bundle):
    """The manifest inside an archive, or (None, reason)."""
    try:
        raw = bundle.read("manifest.json")
    except KeyError:
        return None, "This zip is not a DeckyEmu save backup -- it has no manifest."
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "The backup's manifest could not be read."
    if not isinstance(manifest, dict):
        return None, "The backup's manifest is not in the expected shape."
    if manifest.get("format") != FORMAT:
        # Refused rather than attempted. A layout this build does not know could
        # put files anywhere, and "somewhere plausible" is the one outcome worth
        # avoiding when the alternative is a clear message.
        return None, (
            "This backup was made in a layout this build does not know (version %s). "
            "Update DeckyEmu and try again." % manifest.get("format")
        )
    return manifest, ""


def _safe_member(root, relative):
    """Where `relative` lands under `root`, or "" if it would not stay there."""
    if not relative or relative.startswith("/") or ".." in relative.split("/"):
        return ""
    destination = os.path.normpath(os.path.join(root, *relative.split("/")))
    if destination != root and not destination.startswith(root + os.sep):
        return ""
    return destination


def is_backup(path):
    """Whether this file is one of ours, cheaply enough to ask of a whole folder.

    Only the manifest is read. `describe` goes on to stat every destination,
    which is the right cost for one file somebody is about to restore and the
    wrong one for a directory scan that runs to draw a row.
    """
    if not path.lower().endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(path) as bundle:
            return _read_manifest(bundle)[0] is not None
    except (OSError, zipfile.BadZipFile, ValueError):
        return False


def take_delivery(path):
    """Move a just-arrived save backup out of the ROM inbox. Returns where it is now.

    Called the moment an upload completes, so a backup never appears in the
    picker at all -- rather than being filtered out of it in three places and
    still sitting in the folder somebody browses in Desktop Mode.

    Anything that is not one of ours is left exactly where it landed, which is
    every ROM, BIOS and definition that uses this same server. A move that fails
    leaves the file usable where it is; the restore screen looks in both folders
    for that reason.
    """
    if not is_backup(path):
        return path
    destination = os.path.join(arrivals_dir(), os.path.basename(path))
    if os.path.abspath(destination) == os.path.abspath(path):
        return path
    try:
        # Not `shutil.move` onto an existing name: re-sending the same backup is
        # ordinary, and silently replacing the copy already here would discard
        # whatever it held. The newer one is kept under a suffixed name and the
        # restore screen shows both with their dates.
        final = destination
        stem, extension = os.path.splitext(destination)
        attempt = 2
        while os.path.exists(final):
            final = "%s (%d)%s" % (stem, attempt, extension)
            attempt += 1
        shutil.move(path, final)
    except OSError as error:
        decky.logger.warning("Could not file the save backup %s: %s", path, error)
        return path
    decky.logger.info("Filed save backup %s under %s", os.path.basename(path), arrivals_dir())
    return final


def backups_in(*directories):
    """The save backups across `directories`, newest first, without repeats.

    More than one folder because a backup that could not be moved out of the
    transfer folder is still restorable, and because an install that predates
    `take_delivery` has its backups where they landed.

    Newest first: restoring is nearly always about the last one taken, and
    nobody should have to read a list to find it.
    """
    found = []
    seen = set()
    for directory in directories:
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in sorted(names):
            path = os.path.join(directory, name)
            if path in seen or not os.path.isfile(path) or not is_backup(path):
                continue
            seen.add(path)
            try:
                found.append({
                    "name": name,
                    "path": path,
                    "bytes": os.path.getsize(path),
                    "modified": os.path.getmtime(path),
                })
            except OSError:
                continue
    return sorted(found, key=lambda entry: entry["modified"], reverse=True)


def describe(path):
    """What an archive holds, per emulator, and whether this device can take it.

    Answered without writing anything, so the panel can say what restoring would
    do before anybody agrees to it. `installed` is the half that decides whether
    a row is offered at all: saves for an emulator this Deck does not have are
    reported and left alone rather than written into a directory nothing reads.
    """
    try:
        with zipfile.ZipFile(path) as bundle:
            manifest, problem = _read_manifest(bundle)
            if problem:
                return {"ok": False, "error": problem}
            members = [info for info in bundle.infolist() if not info.is_dir()]
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return {"ok": False, "error": "This does not look like a zip file: %s" % error}

    here = _current_roots()
    listed = {}
    for root in manifest.get("roots") or []:
        key = root.get("key") or ""
        prefix = "files/%s/" % key
        held = [info for info in members if info.filename.startswith(prefix)]
        source, destination = here.get(key, (None, ""))
        entry = listed.setdefault(root.get("id") or key, {
            "id": root.get("id") or key,
            # The name the backup was taken under, so a row reads the same on
            # the Deck that made it even if the catalog has been renamed since.
            "name": root.get("name") or key,
            "installed": False,
            "files": 0,
            "bytes": 0,
            "present": 0,
        })
        entry["files"] += len(held)
        entry["bytes"] += sum(info.file_size for info in held)
        if source is not None:
            entry["installed"] = True
            # How many of these already exist here. It is the whole of the
            # decision between "put back what is missing" and "replace what is
            # there", so it is counted rather than described.
            for info in held:
                landing = _safe_member(destination, info.filename[len(prefix):])
                if landing and os.path.exists(landing):
                    entry["present"] += 1

    return {"ok": True, "sources": [entry for entry in listed.values() if entry["files"]]}


def restore(path, ids=None, replace=False):
    """Put saves back from an archive. Returns what happened, per emulator.

    `replace` is the difference between the two things somebody means by
    restoring. Off -- the default -- writes only what is not already here, which
    is right after wiping a Deck and cannot lose a save that has been played
    since. On overwrites, which is what somebody wants when the saves on this
    device are the ones they are trying to get rid of, and is destructive in a
    way nothing else here undoes.

    Each file is written beside its destination and renamed over it, so a disk
    that fills up mid-restore leaves whole files rather than truncated ones.
    """
    try:
        bundle = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return {"ok": False, "error": "This does not look like a zip file: %s" % error}

    with bundle:
        manifest, problem = _read_manifest(bundle)
        if problem:
            return {"ok": False, "error": problem}

        here = _current_roots()
        written = 0
        skipped = 0
        refused = 0
        missing = []
        touched = []
        for root in manifest.get("roots") or []:
            key = root.get("key") or ""
            source, destination = here.get(key, (None, ""))
            name = root.get("name") or key
            if source is None:
                if name not in missing:
                    missing.append(name)
                continue
            if ids is not None and source["id"] not in ids:
                continue
            if source["name"] not in touched:
                touched.append(source["name"])

            prefix = "files/%s/" % key
            for info in bundle.infolist():
                if info.is_dir() or not info.filename.startswith(prefix):
                    continue
                landing = _safe_member(destination, info.filename[len(prefix):])
                if not landing:
                    # A member naming its way out of the root it belongs to.
                    # Counted and logged rather than silently dropped: an archive
                    # that contains one is not an archive this plugin wrote.
                    decky.logger.warning(
                        "Save restore refused a member outside its root: %s",
                        info.filename,
                    )
                    refused += 1
                    continue
                if os.path.exists(landing) and not replace:
                    skipped += 1
                    continue
                try:
                    os.makedirs(os.path.dirname(landing), exist_ok=True)
                    partial = landing + _PARTIAL
                    with bundle.open(info) as reading, open(partial, "wb") as writing:
                        shutil.copyfileobj(reading, writing)
                    os.replace(partial, landing)
                except OSError as error:
                    decky.logger.warning("Could not restore %s: %s", landing, error)
                    refused += 1
                    continue
                written += 1

    decky.logger.info(
        "Save restore: %d written, %d already there, %d refused", written, skipped, refused
    )
    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "refused": refused,
        "emulators": touched,
        # Named so the panel can say which saves are still in the archive rather
        # than reporting a smaller number with no explanation.
        "not_installed": missing,
    }
