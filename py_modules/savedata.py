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

import fnmatch
import json
import os
import posixpath
import re
import shutil
import struct
import time
import zipfile

import appenv

import emulator_catalog
import ra_detect
import sysenv
from emulator_catalog import schema

#: Version of the archive layout, written into the manifest and checked when one
#: is read back. 2 holds `saves/<emulator>/<root>/...`, the cloud's own layout;
#: 1 named roots by `_key` and is still read.
FORMAT = 2
_READABLE = (1, 2)

#: Where a built archive waits to be read off the device. The runtime
#: directory rather than the transfer folder: this is the plugin's own working
#: file, and the transfer folder is scanned for arrivals the user is meant to act
#: on. Whoever builds one owns deleting it -- a backup left here is a copy of
#: somebody's saves that nothing is going to clean up.
BACKUP_DIR = os.path.join(appenv.DATA_DIR, "backups")

#: Where a backup *arriving* from another device is kept, under the user's own
#: `~/deckyemu` rather than the runtime directory.
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


def _walk(root, skip_top=(), except_names=(), only=()):
    """Every file under `root`, as (absolute path, path relative to root).

    `only` are filename patterns, and with them nothing else is taken. It is
    how a declared save that is a pattern is carried: the root becomes the
    directory holding it and the pattern becomes this, so the save has a real
    directory behind it. Expanding the pattern into one root per matching file
    instead meant a Deck with none of them had no root at all -- nothing to
    back up, which is true, and nowhere to restore to, which is the bug.

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
    except_names, except_dirs = split_except(except_names)

    # A declared save can be one file rather than a directory -- a memory card,
    # a record of achievements -- and `os.walk` over a file yields nothing at
    # all. Silently backing up none of it is the worst answer available.
    if os.path.isfile(root):
        if _named_by(os.path.basename(root), except_names):
            return []
        if only and not _named_by(os.path.basename(root), only):
            return []
        return [(root, os.path.basename(root))]

    for current, directories, files in os.walk(root, followlinks=False):
        relative = os.path.relpath(current, root)
        if relative == ".":
            directories[:] = [name for name in directories if name not in skip_top]
            relative = ""
        # Pruned rather than filtered afterwards: there is no reason to walk
        # into a directory nothing will be taken from, and some of them hold
        # tens of thousands of shader files.
        if except_dirs:
            directories[:] = [name for name in directories
                              if not _named_by(name, except_dirs)]
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path) and not os.path.realpath(path).startswith(root + os.sep):
                continue
            if not os.path.isfile(path):
                continue
            if _named_by(name, except_names):
                continue
            if only and not _named_by(name, only):
                continue
            found.append((path, posixpath.join(*relative.split(os.sep), name) if relative else name))
    return found


def _named_by(name, patterns):
    """Whether a filename matches any of `patterns`."""
    return any(fnmatch.fnmatch(name, one) for one in patterns)


def split_except(names):
    """`saves_except` as (file rules, directory rules).

    A rule ending in `/` names a directory and everything under it; anything
    else names a file, exactly or as a pattern. Both match wherever they appear
    in the tree, which is what the field always promised for plain names.

    Directories are here because nothing could say "not this". A definition
    that declared its whole folder carried whatever the program left in it --
    one put 60 MB of shader and pipeline caches, a year of logs and a pile of
    crash dumps into somebody's Dropbox, and neither a filename list nor the
    flatpak `cache` rule could stop it.
    """
    files, folders = [], []
    for one in names or ():
        if not isinstance(one, str) or not one:
            continue
        if one.endswith("/"):
            folders.append(one[:-1])
        else:
            files.append(one)
    return tuple(files), tuple(folders)


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


def _measure(root, skip_top=(), except_names=(), only=()):
    # The same exclusions the build applies, or the panel counts files it is
    # not going to carry -- and the count is what somebody reads as "this is
    # everything".
    files = _walk(root, skip_top, except_names, only)
    total = 0
    for path, _ in files:
        try:
            total += os.path.getsize(path)
        except OSError:
            # Vanished between the walk and the measure. Counting it as nothing
            # is right: the build skips it for the same reason.
            pass
    return len(files), total


def _retroarch_source(anywhere=False):
    """RetroArch's saves and states, read out of its own configuration.

    Absent rather than guessed when RetroArch is not installed, and absent when
    its config names directories that do not exist -- which is what a fresh
    install looks like before its first save. `anywhere` is for a full
    restore: the flatpak's default folders, which a reinstall then uses.
    """
    install = ra_detect.detect()
    if install:
        config_dir = install["config_dir"]
    elif anywhere:
        config_dir = os.path.join(sysenv.user_home(), ".var", "app", "org.libretro.RetroArch",
                                  "config", "retroarch")
    else:
        return None
    roots = []
    for label, path in ra_detect.save_dirs(config_dir).items():
        if path and (anywhere or os.path.isdir(path)):
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


def _matching(path):
    """`path` itself, or what its pattern matches, in a stable order.

    For a program that numbers its save files. One N64 port writes sixteen
    `controllerPak_file_N.sav` beside its config, and a definition listing them
    by hand is sixteen lines a reader has to check are consecutive -- and that
    silently misses the seventeenth if a later build writes one.

    Only the filename may hold a pattern. The directory part is taken
    literally, so a pattern cannot reach out of the directory it was written in
    -- and that directory is the prefix the schema already checked sits inside a
    root this entry owns. One in a directory name simply matches nothing.

    `fnmatch` rather than `glob`, and the difference is what a frozen
    runtime carries. A PyInstaller bundle packs what its analysis saw imported:
    `shutil` is proven present and imports `fnmatch` at module scope, so
    `fnmatch` comes with it, while nothing proven imports `glob`. That
    distinction is not pedantry -- `http` was proven, `http.server` was not
    bundled, and the plugin failed to load at all.

    Sorted, because a directory's own order is the filesystem's and a backup
    listing its contents differently each run reads as having changed.
    """
    if "*" not in path and "?" not in path:
        return [path]
    folder, pattern = os.path.split(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(os.path.join(folder, name) for name in names
                  if fnmatch.fnmatch(name, pattern))


def _catalog_sources(empty=False, anywhere=False):
    """The catalog emulators that are installed, and what to take from each.

    `empty` keeps an emulator that is installed but has no saves yet. Backing
    up wants it left out -- it is a row saying nothing -- and restoring needs
    it: a port reinstalled a minute ago has an empty folder, and deciding from
    that folder that the port is "not installed here" is how a restore offered
    to put saves everywhere except the emulator they belong to.
    """
    home = sysenv.user_home()
    found = []
    for entry in emulator_catalog.CATALOG:
        owned = [
            os.path.join(home, *relative.split("/"))
            for relative in schema.owned_roots(entry)
        ]
        # `anywhere`: every entry, installed or not, for a full restore onto a
        # Deck that has not reinstalled its emulators yet.
        if not anywhere and not any(os.path.isdir(path) for path in owned):
            continue

        declared = schema.saves_of(entry)
        one_file = set()
        only = {}
        if declared:
            roots = []
            for relative, kind in declared:
                absolute = os.path.join(home, *relative.split("/"))
                name = os.path.basename(relative)
                if "*" in name or "?" in name:
                    # The directory holding it, filtered to the pattern. One
                    # root per matching file read better and restored to
                    # nowhere: a Deck missing all of them had no root, so the
                    # saves had nothing to come back into.
                    folder = os.path.dirname(absolute)
                    roots.append((name, folder))
                    only[name] = (name,)
                    continue
                roots.append((os.path.basename(absolute), absolute))
                # What the definition says it is, for the code that would
                # otherwise have to look -- and a restore looks on the Deck
                # that is missing the file. See `schema.saves_of`.
                if kind == "file":
                    one_file.add(absolute)
        else:
            # A root that *is* a cache directory, rather than one holding a
            # `cache` folder. An imported entry lists the XDG directories it
            # owns, and `.cache/<name>` is one of them -- so the whole of an
            # emulator's shader cache and game-list thumbnails arrived in the
            # backup, and in the pending upload count, as saves. The same
            # definition as `_SKIP_TOP`, applied one level up.
            roots = [(os.path.basename(path), path) for path in owned
                     if not _is_cache_root(relative_of(path, home))]
        # A declared path that is not there yet is still where its saves go.
        # Kept only for restoring, because a backup listing it would offer an
        # emulator with nothing in it.
        if not empty:
            # A filtered root is the directory holding a pattern, and that
            # directory is the port's install folder -- there whether or not a
            # single save matches. "Something to back up" has to mean a match,
            # or every port with none appears in the list offering nothing.
            roots = [
                (label, path) for label, path in roots
                if (os.path.isdir(path) or os.path.isfile(path))
                and (label not in only
                     or _walk(path, (), (), only[label]))
            ]
        if not roots:
            continue
        found.append({
            "id": entry["id"],
            "name": entry["name"],
            "roots": roots,
            "one_file": one_file,
            "only": only,
            "whole": not declared,
            "except": tuple(entry.get("saves_except") or ()),
        })
    return found


def _all_sources(empty=False, anywhere=False):
    """Every emulator and port with something to back up, by name.

    `empty` is passed straight through to `_catalog_sources`: with it, an
    installed emulator that has no saves yet is listed too, which is what a
    restore needs and a backup does not.

    By name because that is how the restore list reads and how a list of a dozen
    things is looked through. RetroArch used to lead, on the reasoning that it
    leads the setup page -- but nothing here is missing for the reader to
    notice, and a list that is alphabetical except for one row reads as a list
    that is not sorted.
    """
    found = []
    libretro = _retroarch_source(anywhere)
    if libretro:
        found.append(libretro)
    return sorted(found + _catalog_sources(empty, anywhere),
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
        for label, path in source["roots"]:
            count, size = _measure(path, skip, source.get("except", ()),
                                   (source.get("only") or {}).get(label, ()))
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


def slug(label):
    """A folder name for one save root, from what the emulator calls it."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (label or "").strip()).strip("-._")
    return cleaned.lower() or "data"


def roots_of(source):
    """One (segment, local directory) per save root of one emulator.

    The segment depends on that emulator alone, so its folder has the same name
    in every zip and on every storage, whatever else was copied with it.
    """
    taken = set()
    listed = []
    for label, path in source["roots"]:
        segment = slug(label)
        candidate = segment
        nth = 2
        while candidate in taken:
            candidate = "%s-%d" % (segment, nth)
            nth += 1
        taken.add(candidate)
        listed.append((candidate, path))
    return listed


def file_root(path, source=None):
    """Whether a declared save root is one file rather than a directory.

    A file root travels inside a folder of its own name (`card.mcd/card.mcd`)
    and comes back beside itself. The definition says so first (`one_file`):
    on a Deck that lost the file, the disk cannot tell.
    """
    if path in ((source or {}).get("one_file") or ()):
        return True
    return os.path.isfile(path)


def rows_from(files_by_emulator, names=None):
    """The restore screen's rows from `{emulator: {"<root>/<path>": size}}`.

    `names` names an emulator this Deck does not have, which still gets a row
    saying so.
    """
    here = {source["id"]: source for source in _all_sources(True)}
    landing = {}
    for source in here.values():
        for segment, path in roots_of(source):
            landing[(source["id"], segment)] = path

    found = []
    for emulator, files in files_by_emulator.items():
        source = here.get(emulator)
        row = {
            "id": emulator,
            "name": source["name"] if source else (names or {}).get(emulator, emulator),
            "installed": source is not None,
            "files": 0,
            "bytes": 0,
            "present": 0,
        }
        for name, size in files.items():
            parts = name.split("/")
            if len(parts) < 2:
                continue
            row["files"] += 1
            row["bytes"] += int(size or 0)
            local = landing.get((emulator, parts[0]))
            if local and file_root(local, source):
                here_already = os.path.exists(local)
            else:
                here_already = bool(local) and os.path.exists(
                    os.path.join(local, *parts[1:]))
            if here_already:
                row["present"] += 1
        if row["files"]:
            found.append(row)
    return sorted(found, key=lambda row: row["name"])


def _key(source_id, label, taken):
    """Format 1's name for one root inside an archive."""
    base = "%s-%s" % (source_id, label.strip("._").lower().replace(" ", "-") or "data")
    key = base
    suffix = 2
    while key in taken:
        key = "%s-%d" % (base, suffix)
        suffix += 1
    taken.add(key)
    return key


def _add(bundle, absolute, name):
    """Write one file into an archive, with its time in UTC.

    A zip's own time field is local time with no zone, and rclone reads it as
    UTC; the extended-timestamp field (0x5455) carries the real moment.
    """
    info = zipfile.ZipInfo.from_file(absolute, name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.extra = struct.pack("<HHBl", 0x5455, 5, 1, int(os.stat(absolute).st_mtime))
    with open(absolute, "rb") as reading, \
            bundle.open(info, "w", force_zip64=info.file_size > 2 ** 31) as writing:
        shutil.copyfileobj(reading, writing, 1024 * 1024)


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

    manifest = {"format": FORMAT, "emulators": {}}
    partial = destination + _PARTIAL
    written = 0
    try:
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:
            for source in listed:
                manifest["emulators"][source["id"]] = source["name"]
                skip = _SKIP_TOP if source["whole"] else ()
                only = source.get("only") or {}
                for (label, path), (segment, _) in zip(source["roots"], roots_of(source)):
                    for absolute, relative in _walk(
                            path, skip, source.get("except", ()), only.get(label, ())):
                        try:
                            _add(bundle, absolute,
                                 posixpath.join("saves", source["id"], segment, relative))
                        except OSError as error:
                            # One unreadable file must not cost the whole backup.
                            # It is named in the log; every other save still goes.
                            appenv.logger.warning(
                                "Save backup skipped %s: %s", absolute, error
                            )
                            continue
                        written += 1
            bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        os.replace(partial, destination)
    except OSError as error:
        appenv.logger.error("Could not build the save backup: %s", error)
        try:
            os.remove(partial)
        except OSError:
            pass
        return {"ok": False, "error": "The backup could not be written: %s" % error}

    size = os.path.getsize(destination)
    appenv.logger.info(
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
# **The archive never says where a file goes.** It arrived from a device this
# plugin knows nothing about, so each file names only its emulator and root, and
# the destination is recomputed from what this Deck has installed. A member that
# would climb out of its root is refused.


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
    if manifest.get("format") not in _READABLE:
        return None, (
            "This backup was made in a layout this build does not know (version %s). "
            "Update DeckyEmu and try again." % manifest.get("format")
        )
    return manifest, ""


def _entries(bundle, manifest):
    """Every file in an archive as (emulator, "<root>/<path>", info), and names.

    Format 1 named a root by `_key`, recomputed here against this Deck's
    emulators; a key nothing here produces keeps its emulator but no root, so
    it is reported rather than placed.
    """
    files = [info for info in bundle.infolist() if not info.is_dir()]
    if manifest.get("format") == 2:
        names = {str(k): str(v) for k, v in (manifest.get("emulators") or {}).items()}
        found = []
        for info in files:
            parts = info.filename.split("/")
            if len(parts) >= 4 and parts[0] == "saves":
                found.append((parts[1], "/".join(parts[2:]), info))
        return found, names

    taken: set = set()
    segments = {}
    for source in _all_sources():
        for (label, _), (segment, _) in zip(source["roots"], roots_of(source)):
            segments[_key(source["id"], label, taken)] = (source["id"], segment)
    found = []
    names = {}
    for root in manifest.get("roots") or []:
        key = root.get("key") or ""
        emulator, segment = segments.get(key, (root.get("id") or key, ""))
        names.setdefault(emulator, root.get("name") or emulator)
        prefix = "files/%s/" % key
        for info in files:
            if info.filename.startswith(prefix):
                rest = info.filename[len(prefix):]
                found.append((emulator, "%s/%s" % (segment, rest) if segment else "/" + rest, info))
    return found, names


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
        appenv.logger.warning("Could not file the save backup %s: %s", path, error)
        return path
    appenv.logger.info("Filed save backup %s under %s", os.path.basename(path), arrivals_dir())
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
    """What an archive holds, per emulator, and how much of it is already here."""
    try:
        with zipfile.ZipFile(path) as bundle:
            manifest, problem = _read_manifest(bundle)
            if problem:
                return {"ok": False, "error": problem}
            entries, names = _entries(bundle, manifest)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return {"ok": False, "error": "This does not look like a zip file: %s" % error}
    files: dict = {}
    for emulator, name, info in entries:
        files.setdefault(emulator, {})[name] = info.file_size
    return {"ok": True, "sources": rows_from(files, names)}


#: Kept free on top of what a restore writes, as the cloud restore keeps.
_SPACE_MARGIN = 256 * 1024 * 1024


def _fits(writes):
    """Whether `writes`, (destination, bytes) pairs, fit on their disks."""
    needed: dict = {}
    for path, size in writes:
        at = path
        while at and not os.path.isdir(at):
            parent = os.path.dirname(at)
            if parent == at:
                break
            at = parent
        try:
            device = os.stat(at).st_dev
        except OSError:
            continue
        held = needed.setdefault(device, [at, 0])
        held[1] += size
    for at, size in needed.values():
        try:
            free = shutil.disk_usage(at).free
        except OSError:
            continue
        if size + _SPACE_MARGIN > free:
            return False, ("There is not enough room on this Deck: these saves need "
                           "%d MB and %d MB is free." % (size // 10 ** 6, free // 10 ** 6))
    return True, ""


def _keep_aside(overwritten):
    """Zip what a replace is about to overwrite, beside the other backups.

    `overwritten` is (local path, name in the archive) pairs. The zip is an
    ordinary backup, so Restore offers it like any other. Returns (name, error).
    """
    name = time.strftime("deckyemu-saves-replaced-%Y%m%d-%H%M%S.zip")
    destination = os.path.join(arrivals_dir(), name)
    partial = destination + _PARTIAL
    emulators = sorted({member.split("/")[1] for _, member in overwritten})
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:
            for local, member in overwritten:
                _add(bundle, local, member)
            bundle.writestr("manifest.json", json.dumps(
                {"format": FORMAT, "emulators": {e: e for e in emulators}}, indent=2))
        os.replace(partial, destination)
    except OSError as error:
        try:
            os.remove(partial)
        except OSError:
            pass
        return "", str(error)
    return name, ""


def restore(path, ids=None, replace=False):
    """Put saves back from an archive. Returns what happened, per emulator.

    Off, `replace` writes only what is not here, which cannot lose a save
    played since. On, it overwrites -- after zipping what it overwrites
    beside the other backups, so a replace can be undone from Restore.

    Each file is written beside its destination and renamed over it, so a full
    disk leaves whole files rather than truncated ones.
    """
    try:
        bundle = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return {"ok": False, "error": "This does not look like a zip file: %s" % error}

    with bundle:
        manifest, problem = _read_manifest(bundle)
        if problem:
            return {"ok": False, "error": problem}
        entries, names = _entries(bundle, manifest)

        landing = {}
        for source in _all_sources(True):
            for segment, root in roots_of(source):
                landing[(source["id"], segment)] = (source, root)
        # A root holding only a file of its own name is a file root, even on a
        # Deck that has lost that file. See `file_root`.
        under: dict = {}
        for emulator, name, _ in entries:
            segment, _, rest = name.partition("/")
            under.setdefault((emulator, segment), []).append(rest)

        plan = []
        missing = []
        touched = []
        refused = 0
        skipped = 0
        for emulator, name, info in entries:
            if ids is not None and emulator not in ids:
                continue
            segment, _, rest = name.partition("/")
            hit = landing.get((emulator, segment))
            if hit is None:
                label = names.get(emulator, emulator)
                if label not in missing:
                    missing.append(label)
                continue
            source, root = hit
            one_file = file_root(root, source) or under[(emulator, segment)] == [segment]
            target = _safe_member(os.path.dirname(root) if one_file else root, rest)
            if not target:
                # Logged: an archive holding one is not one we wrote.
                appenv.logger.warning(
                    "Save restore refused a member outside its root: %s", info.filename)
                refused += 1
                continue
            if os.path.exists(target) and not replace:
                skipped += 1
                continue
            if source["name"] not in touched:
                touched.append(source["name"])
            plan.append((info, target, "saves/%s/%s" % (emulator, name)))

        def size_of(target):
            try:
                return os.path.getsize(target)
            except OSError:
                return 0

        overwritten = [(target, member) for _, target, member in plan
                       if os.path.isfile(target)]
        fits, tight = _fits(
            [(target, max(0, info.file_size - size_of(target))) for info, target, _ in plan]
            + [(arrivals_dir(), sum(size_of(target) for target, _ in overwritten))])
        if not fits:
            return {"ok": False, "error": tight}
        kept = ""
        if overwritten:
            kept, failed = _keep_aside(overwritten)
            if failed:
                return {"ok": False, "error": "Your saves could not be kept first, so "
                                              "nothing was replaced. %s" % failed}

        written = 0
        for info, target, _ in plan:
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                partial = target + _PARTIAL
                with bundle.open(info) as reading, open(partial, "wb") as writing:
                    shutil.copyfileobj(reading, writing)
                os.replace(partial, target)
            except OSError as error:
                appenv.logger.warning("Could not restore %s: %s", target, error)
                refused += 1
                continue
            written += 1

    appenv.logger.info(
        "Save restore: %d written, %d already there, %d refused%s", written, skipped,
        refused, ", replaced files kept in %s" % kept if kept else "")
    return {
        "ok": True,
        "written": written,
        "skipped": skipped,
        "refused": refused,
        "emulators": touched,
        "not_installed": missing,
        "kept": kept,
    }
