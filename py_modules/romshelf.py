"""Filing a ROM under the system it turned out to be for.

Uploads arrive in one folder because the sender has no idea what to call it and
should not have to: a phone browser knows a filename and nothing else. The
system is known later and known properly -- at the moment a game is added, from
the core the user picked -- so that is when the file is moved, out of the inbox
and into `roms/<system>/`.

Filing on the way in was the alternative and is worse in the way that matters.
It has to ask, and an answer from someone who is holding a phone and guessing
from a filename is a guess. `.iso` is GameCube, PS2, PSP and Xbox; `.zip` is a
SNES ROM or a Vita release. Filing on the way out has an authoritative answer
and needs no question.

Two rules keep this from being dangerous:

Only files sitting directly in the inbox are ever moved. Anything the user
keeps elsewhere -- an SD card, a library some other tool laid out -- is theirs,
and a plugin that tidies other people's directories is a plugin nobody trusts
twice.

Nothing is moved unless the whole game moves. A .cue names its .bin files and a
.m3u names its discs; move one without the others and the game stops working in
a way that looks like a bad dump. If any companion cannot be accounted for, the
file stays where it is -- unfiled and working beats filed and broken.
"""

import os
import re
import shutil

import decky

import platforms
import sysenv

# Formats that are one file naming others. Each needs its companions read out
# rather than guessed, because they do not share a stem: a .m3u lists
# "Game (Disc 2).chd", which no amount of stem matching will find from
# "Game.m3u".
_PLAYLISTS = (".cue", ".m3u", ".gdi")

# `FILE "Something (Track 1).bin" BINARY`, and the unquoted form some tools
# still write.
_CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE | re.MULTILINE)

# A playlist naming megabytes of anything is not a playlist.
MAX_PLAYLIST_BYTES = 256 * 1024


def _referenced(path):
    """Filenames a playlist points at, or None if it could not be read.

    None and empty mean different things and the caller depends on it: nothing
    referenced is fine, unreadable is a reason not to touch the file at all.
    """
    extension = os.path.splitext(path)[1].lower()
    if extension not in _PLAYLISTS:
        return []
    try:
        if os.path.getsize(path) > MAX_PLAYLIST_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None

    names = []
    if extension == ".cue":
        for quoted, bare in _CUE_FILE.findall(text):
            names.append(quoted or bare)
    else:
        # .m3u and .gdi are line-oriented. A .gdi's first line is a track count
        # and its track lines end in a filename; taking the last quoted or
        # whitespace-separated token that looks like a file covers both without
        # a parser for either.
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.search(r'"([^"]+)"', line)
            if match:
                names.append(match.group(1))
            elif extension == ".m3u":
                names.append(line)
            else:
                parts = line.split()
                if len(parts) > 1 and "." in parts[-2:][0]:
                    names.append(next(p for p in parts if "." in p))

    # Only plain names. A playlist pointing at ../.. is not something to follow
    # around the filesystem, and one pointing outside the inbox means this game
    # is not self-contained and should not be moved at all.
    return [os.path.basename(name) for name in names if name and not name.startswith("/")]


#: Extensions that hold a game rather than being part of one. A file with the
#: same stem and one of these is the container the ROM arrived in, not a track
#: or a disc that has to travel with it.
_ARCHIVES = frozenset(("zip", "7z", "rar", "tar", "gz"))


def companions(rom_path):
    """Every file that has to travel with this one, or None if unknowable.

    The same stem covers the ordinary cases -- Game.cue beside Game.bin, an
    .img and .sub beside a .ccd -- and the playlist's own contents cover the
    ones that do not share a stem, which is every multi-disc set.
    """
    folder = os.path.dirname(rom_path)
    stem = os.path.splitext(os.path.basename(rom_path))[0].lower()

    try:
        siblings = os.listdir(folder)
    except OSError:
        return None

    # The archive a ROM came out of is not part of the game. Unpacking names a
    # lone extensionless member after its zip, so `Banjo-Kazooie (World) (XBLA)`
    # and `Banjo-Kazooie (World) (XBLA).zip` share a stem exactly -- and without
    # this the 47MB source archive was filed into `roms/xbox-360/` alongside the
    # game and then deleted with it. Never for the ROM itself, which may
    # legitimately *be* a zip: RetroArch reads one directly.
    keep = os.path.basename(rom_path)
    group = {
        name for name in siblings
        if os.path.splitext(name)[0].lower() == stem
        and os.path.isfile(os.path.join(folder, name))
        and (name == keep
             or os.path.splitext(name)[1].lower().lstrip(".") not in _ARCHIVES)
    }

    named = _referenced(rom_path)
    if named is None:
        return None
    for name in named:
        if not os.path.isfile(os.path.join(folder, name)):
            # A disc the playlist expects and the folder has not got. Moving
            # what is here would not make the game work and would make finding
            # the rest harder.
            return None
        group.add(name)
        # A .m3u names .cue files, which name .bin files in turn.
        deeper = _referenced(os.path.join(folder, name))
        if deeper is None:
            return None
        for inner in deeper:
            if not os.path.isfile(os.path.join(folder, inner)):
                return None
            group.add(inner)

    return sorted(group)


def library_dir(create=False):
    """`<home>/deckyemu/roms`, where filed games live.

    A different folder from the inbox rather than a subfolder of it. One folder
    doing both jobs means loose arrivals sitting beside sorted ones forever, and
    no way to say "empty the inbox" without meaning "delete the library".
    """
    return sysenv.user_dir("roms", create=create)


# How much of each end to compare when deciding two files are the same. Enough
# that two different dumps sharing a name and a byte count would have to match
# at both ends to fool it, cheap enough to do on a four-gigabyte ISO.
_SAMPLE_BYTES = 256 * 1024


def _same_file(left, right):
    """Whether two paths hold the same bytes, without reading gigabytes.

    Size first, since two different dumps almost never agree on it, then both
    ends of the file. Hashing four gigabytes to decide whether to delete a
    duplicate would cost more than the duplicate does.
    """
    try:
        if os.path.getsize(left) != os.path.getsize(right):
            return False
        size = os.path.getsize(left)
        with open(left, "rb") as one, open(right, "rb") as two:
            if one.read(_SAMPLE_BYTES) != two.read(_SAMPLE_BYTES):
                return False
            if size > _SAMPLE_BYTES * 2:
                one.seek(-_SAMPLE_BYTES, os.SEEK_END)
                two.seek(-_SAMPLE_BYTES, os.SEEK_END)
                if one.read() != two.read():
                    return False
    except OSError:
        return False
    return True


def owned(rom_path, library=""):
    """Whether this ROM is one we filed, and so one we may offer to delete.

    Only the system folders directly under the library count. A ROM on an SD
    card or in a library some other tool laid out was never ours to move and is
    not ours to delete either -- the same rule `file_rom` moves by, for the same
    reason.
    """
    if not rom_path:
        return False
    library = os.path.realpath(library or library_dir())
    folder = os.path.dirname(os.path.realpath(rom_path))
    parent = os.path.dirname(folder)
    return parent == library and folder != library


def footprint(rom_path):
    """(bytes, [names]) for a ROM and everything that has to go with it.

    The same group `file_rom` moves, so what is deleted is what was filed --
    a .cue without its .bin leaves a game that cannot start and a file nothing
    will ever point at again.
    """
    group = companions(rom_path) or []
    folder = os.path.dirname(rom_path)
    total = 0
    for name in group:
        try:
            total += os.path.getsize(os.path.join(folder, name))
        except OSError:
            continue
    return total, group


def delete_rom(rom_path, library=""):
    """Delete a filed ROM and its companions. Returns (bytes freed, error)."""
    if not owned(rom_path, library):
        return 0, "That ROM is not in the library folder, so it is not ours to delete."

    freed, group = footprint(rom_path)
    folder = os.path.dirname(rom_path)
    for name in group:
        try:
            os.remove(os.path.join(folder, name))
        except FileNotFoundError:
            continue
        except OSError as error:
            return 0, "Could not delete %s: %s" % (name, error)

    # The system folder goes too once the last game leaves it, for the same
    # reason an empty collection does: a shelf with nothing on it is clutter
    # that nothing will ever clear later.
    try:
        if not os.listdir(folder):
            os.rmdir(folder)
    except OSError:
        pass

    decky.logger.info("Deleted %s, freeing %d bytes", ", ".join(group), freed)
    return freed, ""


def file_rom(rom_path, system, inbox, library=""):
    """Move a freshly added ROM into `roms/<system>/`. Returns its new path.

    Returns the path unchanged whenever anything is unclear, which is the
    default this should have: the cost of not filing is an untidy folder, and
    the cost of filing wrongly is a game that does not start.
    """
    if not rom_path or not inbox or not os.path.isfile(rom_path):
        return rom_path
    library = library or library_dir()

    # Only the inbox itself, and only its top level. A file already in
    # roms/snes is filed; a file on an SD card is not ours to move.
    folder = os.path.dirname(os.path.realpath(rom_path))
    if folder != os.path.realpath(inbox):
        return rom_path

    slug = platforms.folder_name(system)
    if not slug:
        return rom_path

    group = companions(rom_path)
    if not group:
        return rom_path

    target = os.path.join(library, slug)

    # A name already taken over there is almost always this same file sent
    # twice, and refusing to file it was wrong in a way that looked like the
    # feature was broken: the ROM stayed in the inbox, the launcher pointed at
    # the inbox copy, and the folder never emptied. Reported as "it was copied,
    # not moved", which is exactly what two identical files in two places is.
    #
    # So a byte-identical file at the destination means the game is already
    # filed: the arriving copy is redundant and goes, and the caller is pointed
    # at the one already there. A file of the same name that is *not* the same
    # file is a different dump, and nothing is overwritten for that.
    clash = [name for name in group if os.path.exists(os.path.join(target, name))]
    if clash:
        if all(
            _same_file(os.path.join(inbox, name), os.path.join(target, name))
            for name in clash
        ) and len(clash) == len(group):
            for name in group:
                try:
                    os.remove(os.path.join(inbox, name))
                except OSError as error:
                    decky.logger.warning("Could not remove the duplicate %s: %s", name, error)
                    return rom_path
            decky.logger.info(
                "%s was already filed in %s; removed the duplicate",
                os.path.basename(rom_path), slug,
            )
            return os.path.join(target, os.path.basename(rom_path))

        decky.logger.info(
            "Not filing %s: a different %s is already in %s",
            os.path.basename(rom_path), clash[0], slug,
        )
        return rom_path

    try:
        os.makedirs(target, exist_ok=True)
    except OSError as error:
        decky.logger.warning("Could not create %s: %s", target, error)
        return rom_path

    moved = []
    for name in group:
        try:
            shutil.move(os.path.join(inbox, name), os.path.join(target, name))
        except OSError as error:
            decky.logger.warning("Could not file %s: %s", name, error)
            # Put back whatever already went, so a half-moved set never exists.
            for done in moved:
                try:
                    shutil.move(os.path.join(target, done), os.path.join(inbox, done))
                except OSError:
                    decky.logger.exception("Could not undo the move of %s", done)
            return rom_path
        moved.append(name)

    decky.logger.info("Filed %s into %s", ", ".join(moved), slug)
    return os.path.join(target, os.path.basename(rom_path))
