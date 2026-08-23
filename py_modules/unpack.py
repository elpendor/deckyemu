"""Extracting a zip that arrived in the transfer folder, without leaving Game Mode.

Xbox 360 content is the case that forced this. Every XBLA release found so far
is distributed zipped, Xenia refuses a zip outright, and nothing here could
extract one -- so the route from "sent to the Deck" to "playable" went through
Desktop Mode and a file manager, which is the one thing a feature here may not
require -- this plugin exists so that it never has to. It is not an Xbox 360
problem, though: a zip holding a `.cue` and its `.bin` files had the same dead
end.

**Members land flat, by basename.** That is a safety rule first -- `extractall`
honours a path inside the archive, and these arrive over wifi from a phone -- and
it happens to be exactly right for the case that prompted it, since an XBLA zip
holds one file buried under `<TitleID>/000D0000/`. `romshelf` only files things
sitting directly in the transfer folder, so flat is also the only shape the rest
of the plugin can act on.

**Nothing is overwritten and nothing is half-written.** Two members with the same
basename, or one whose name is already taken in the folder, stop the whole
extraction before a byte is written rather than silently resolving it -- these
are somebody's games, arrived over a slow link, and quietly replacing one is
worse than refusing. Members are written to temporary names and renamed into
place only once every one of them has been read, so a disk that fills up halfway
leaves the folder as it was.

**Extracting does not delete the archive; the caller does.** Whether the source
has served its purpose is a question about the transfer folder rather than about
zip files, and `unpack_transferred_file` answers it -- the same way importing a
definition consumes it. Keeping this function free of that makes it testable as
what it is: an extraction that either put every member on disk or changed
nothing.
"""

import os
import shutil
import zipfile

import decky

#: Written beside the real name while extracting. Same suffix `emu_config` uses
#: for its own staged writes, and for the same reason: something scanning this
#: folder for a ROM must not pick up a half-written file, and a name nothing
#: else produces is what keeps the two apart.
_PARTIAL = ".deckyemu-tmp"

#: Left over the free space on the drive, so a large extraction cannot be the
#: thing that fills a Deck up. Not a limit on the archive: a PS3 image is
#: legitimately tens of gigabytes, so the only honest bound is what will fit.
_SPACE_MARGIN = 256 * 1024 * 1024


def _named_for(archive, members):
    """The name each member should land under, in the order `members` gives.

    Almost always its own basename. The exception is the one that prompted this:
    a zip holding exactly one file whose name carries **no extension**, which in
    this domain means a hash rather than a title -- an XBLA container arrives as
    `DA78E477AA5E31A7D01AE8F84109FD4BF89E49E858` inside
    `Banjo-Kazooie (World) (XBLA).zip`. Unpacked under its own name it is
    useless: nothing to read in the received list, and nothing for the artwork
    search to match, so the game reaches Steam with a hash for a title and no
    cover.

    The zip's own name is the only human-readable thing in the transaction, so a
    lone extensionless member takes it. Deliberately not the general rule:
    `download (1).zip` holding `Banjo-Kazooie.iso` would be made *worse* by it,
    and a file that has an extension has a name somebody chose.
    """
    if len(members) != 1:
        return [name for _info, name in members]
    name = members[0][1]
    if os.path.splitext(name)[1]:
        return [name]
    stem = os.path.splitext(os.path.basename(archive))[0]
    return [stem or name]


def _members(bundle):
    """The files in `bundle` worth writing, as (info, basename)."""
    found = []
    for info in bundle.infolist():
        if info.is_dir():
            continue
        name = os.path.basename(info.filename)
        # A member named only by its directory, or one whose name is entirely a
        # path this refuses to honour. Skipped rather than refused: an archive
        # can legitimately carry a directory entry that did not set the flag.
        if not name or name in (".", ".."):
            continue
        found.append((info, name))
    return found


def plan(path):
    """(names that would be written, total bytes, error) for the zip at `path`.

    Separate from doing it so the caller can refuse with a reason before
    anything is written, and so the rules can be tested without a filesystem
    full of games.
    """
    try:
        with zipfile.ZipFile(path) as bundle:
            members = _members(bundle)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return [], 0, "This does not look like a zip file: %s" % error

    if not members:
        return [], 0, "There are no files inside this zip."

    names = _named_for(path, members)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        # Flattening is what makes this possible, and resolving it by renaming
        # would produce files whose names no longer match what the archive said
        # they were -- which for a `.cue` naming its `.bin` breaks the game in a
        # way that looks like a bad dump.
        return [], 0, (
            "Two or more files inside this zip have the same name (%s), so they "
            "cannot both be unpacked here." % ", ".join(duplicates[:3])
        )

    return names, sum(info.file_size for info, _name in members), ""


def into_folder(path, destination):
    """Extract the zip at `path` flat into `destination`. Returns (names, error).

    All or nothing. Every member is written under a temporary name first, and
    they are renamed into place together at the end, so a failure part way
    through leaves nothing behind for somebody to wonder about.
    """
    names, total, error = plan(path)
    if error:
        return [], error

    taken = [name for name in names if os.path.exists(os.path.join(destination, name))]
    if taken:
        return [], (
            "%s is already in the transfer folder. Delete it first, or the "
            "unpacked copy would replace it." % taken[0]
            if len(taken) == 1 else
            "%d of the files inside this zip are already in the transfer folder, "
            "starting with %s." % (len(taken), taken[0])
        )

    try:
        free = shutil.disk_usage(destination).free
    except OSError:
        # Not knowing is not a reason to refuse. The write below reports a full
        # disk perfectly well; this check exists to say so *before* spending ten
        # minutes on it, not to be the only thing that can.
        free = None
    if free is not None and total + _SPACE_MARGIN > free:
        return [], (
            "There is not enough room: unpacking this needs %.1f GB and %.1f GB "
            "is free." % (total / 1e9, free / 1e9)
        )

    staged = []
    try:
        with zipfile.ZipFile(path) as bundle:
            members = _members(bundle)
            for (info, _inner), name in zip(members, _named_for(path, members)):
                temporary = os.path.join(destination, name + _PARTIAL)
                with bundle.open(info) as source, open(temporary, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                staged.append((temporary, os.path.join(destination, name)))
        for temporary, target in staged:
            os.replace(temporary, target)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        for temporary, _target in staged:
            try:
                os.remove(temporary)
            except OSError:
                pass
        decky.logger.warning("Could not unpack %s: %s", path, error)
        return [], "Could not unpack this zip: %s" % error

    decky.logger.info("Unpacked %s into %d file(s)", os.path.basename(path), len(names))
    return names, ""
