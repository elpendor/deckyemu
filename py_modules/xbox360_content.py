"""Naming an Xbox 360 file by its header, for the files that have no name to go on.

XBLA titles, DLC and title updates ship as STFS containers, and a STFS container
normally arrives with **no extension at all** -- the filename is a hash. Every
other route into this plugin keys off an extension: `cores_for_extension` returns
nothing for an empty string, so the file cannot be paired with an emulator, and
the panel offers no way forward. The user has the game, the emulator is
installed, and there is no button.

Xenia does not care. `Emulator::LaunchPath` switches on the first four bytes and
sends LIVE/CON/PIRS to `LaunchStfsContainer`, so an XBLA container boots straight
from a path with nothing installed anywhere. The gap was never Xenia's; it was
this plugin insisting on a filename convention that this one format does not
follow.

So the header supplies the extension the filename does not have. That keeps the
whole downstream unchanged -- matching, the remembered core, artwork, the strings
in the panel -- rather than growing a second way to pair a file with an emulator
alongside the extension it already has.

`stfs` is what the format is called rather than what the files are called, and
`MANUAL_EXTENSIONS` lists it for that reason. A file genuinely named `.stfs`
matches on its name and never reaches here.

Deliberately narrow. Only the headers that identify themselves in their first
four bytes are read, which is the case this exists for. `.iso` and `.zar` are
left to their extensions: XISO's magic sits at a sector offset that varies by
disc layout, and a zarchive's is at the *end* of the file -- both are real work
to do properly, and neither is a format that shows up without a name.
"""

import os
import zipfile

import decky

#: The first four bytes of an Xbox 360 content package. `CON ` carries the
#: trailing space -- it is a four-character code, not a word.
_STFS_MAGIC = (b"CON ", b"LIVE", b"PIRS")

#: Xenia has six XEX signatures -- XEX0, XEXQ, XEXH, XEX25, XEX1, XEX2 -- and
#: every one of them opens `XEX`. Matched as a prefix rather than transcribed as
#: six constants, because the list is Xenia's to grow and a copy of it here would
#: be a second thing to keep in step for no gain.
_XEX_PREFIX = b"XEX"


def extension_from_header(path):
    """The extension this file would have if it were named for its contents.

    Empty when the header says nothing, which is the overwhelmingly common case
    and must stay cheap: four bytes, and no exception a caller has to handle.
    """
    try:
        with open(path, "rb") as handle:
            magic = handle.read(4)
    except OSError as error:
        # Not an error worth surfacing. This runs on a path the user just chose
        # in a file browser, and if it cannot be read the failure belongs to
        # whatever tries to use it next, with a message about that rather than
        # about a header.
        decky.logger.debug("no header read from %s: %s", path, error)
        return ""

    return _identify(magic)


def _identify(magic):
    """What a four-byte header says this is, or ""."""
    if magic in _STFS_MAGIC:
        return "stfs"
    if magic.startswith(_XEX_PREFIX):
        return "xex"
    return ""


def inside_archive(path):
    """What the first real member of the zip at `path` is, by its header.

    For telling the user why a zip cannot be run rather than for running it.
    `archive_inner_extension` answers "what is in here" from filenames, and an
    XBLA container has no filename to answer with -- so a zipped one looked like
    a plain `.zip`, matched the twenty-two libretro cores that legitimately
    claim that extension, and had an Amstrad CPC core suggested for it. Every
    one of those is a wrong answer offered confidently.

    Not a route to running it. Xenia refuses an archive outright, so a zip that
    turns out to hold Xbox 360 content still cannot be paired with an emulator;
    what this buys is saying *why*, and pointing at the button that fixes it.
    """
    if os.path.splitext(path)[1].lower() != ".zip":
        return ""
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir() or not os.path.basename(entry.filename):
                    continue
                with archive.open(entry) as handle:
                    return _identify(handle.read(4))
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        decky.logger.debug("could not look inside %s: %s", path, error)
    return ""


def named_by_header(path):
    """Whether this file's extension had to come from its header.

    The panel says so, because "Xbox 360 content package" is the only thing that
    explains why a file with no extension was matched at all.
    """
    return not os.path.splitext(path)[1] and bool(extension_from_header(path))
