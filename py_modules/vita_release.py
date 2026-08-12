"""Telling a PS Vita release apart from every other .zip.

Vita games are most commonly distributed as NoNpDrm releases: a zip holding the
game's own folder -- `eboot.bin`, `sce_sys/param.sfo` -- and usually the
`work.bin` licence beside it. Vita3K installs and runs one directly, so a Vita
zip needs no unpacking step of this plugin's own. What it needs is to be
recognised.

**That is harder than it sounds, because `.zip` belongs to everyone.** Every
zipped SNES, NES and Mega Drive ROM has the same extension, and the ROM picker
already looks inside an archive to match cores on the content. A Vita release
has no file in it that looks like a ROM, so without this it matches nothing and
Vita3K is never offered.

So the rule is the same one `xbox_disc` uses: look inside, and only speak when
certain. A zip is a Vita release when it carries a `sce_sys/param.sfo`, which
is the file Vita3K itself reads to learn what the game is. Anything else draws
no comment at all -- the archive goes back to being matched on its contents,
exactly as before.
"""

import posixpath
import zipfile

import decky
import sfo

# What every Vita release carries and no ROM archive does.
PARAM = "sce_sys/param.sfo"
BOOT = "eboot.bin"

# The NoNpDrm licence, which Vita3K accepts directly -- see `Install License
# (.rif / work.bin)` in its own binary. Reported so the panel can say whether
# the release brought one, because a game installed without it will not start
# and the reason is invisible.
LICENCE = "work.bin"

# A zip's central directory is read to answer this, never its contents. Still
# bounded: an archive with an implausible number of entries is not a game.
MAX_ENTRIES = 100000


def inspect(path):
    """{vita, title, title_id, licence} for a zip, or vita False.

    False is the answer for every zipped ROM as well as for anything that is
    not a readable zip, and it is not a complaint: callers should say nothing.
    """
    found = {"vita": False, "title": "", "title_id": "", "licence": False}
    try:
        with zipfile.ZipFile(path) as bundle:
            names = bundle.namelist()
            if len(names) > MAX_ENTRIES:
                return found

            param = _member(names, PARAM)
            if not param:
                return found
            found["vita"] = True
            found["licence"] = bool(_member(names, LICENCE))

            # Read the SFO out of the archive rather than unpacking it, so
            # picking a 4GB release costs a couple of kilobytes.
            with bundle.open(param) as handle:
                data = handle.read(sfo.MAX_BYTES)
    except (OSError, zipfile.BadZipFile, ValueError, RuntimeError) as error:
        decky.logger.info("Could not read %s as a Vita release: %s", path, error)
        return found

    parsed = sfo.read_bytes(data)
    found["title"] = parsed.get("TITLE", "")
    found["title_id"] = parsed.get("TITLE_ID", "")
    return found


def _member(names, suffix):
    """The archive member ending in `suffix`, at any depth, or ''.

    Depth varies: some releases put the game at the root, others inside a
    folder named after the title id, and both are things people have.
    """
    for name in names:
        if name.endswith("/"):
            continue
        if name == suffix or name.endswith("/" + suffix):
            return name
        # A licence sits beside the app rather than under sce_sys, so it is
        # matched on its basename alone.
        if "/" not in suffix and posixpath.basename(name) == suffix:
            return name
    return ""
