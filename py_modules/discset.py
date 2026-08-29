"""Recognising a multi-disc game from the files beside the one you picked.

A two-disc PlayStation game is two files, and today it is two Steam entries --
both called the same thing, because the name cleanup strips `(Disc 1)` before
either reaches the library. What makes it one game is an `.m3u`: a text file
naming the discs in order, which every emulator that can swap discs reads as a
single piece of content.

Nothing in this plugin wrote one. `romshelf` has parsed and followed them from
the beginning -- filing a set and deleting it both already work, including the
`.m3u` -> `.cue` -> `.bin` recursion -- so the whole of what was missing is the
writing.

**This is name-based, and there is no honest way around that.** The disc number
is not in the file: a `.chd` would have to be decoded to read the volume label,
a `.cue` names tracks and not discs, and the serial inside a PlayStation disc is
*different* on each disc of a set, so it identifies the disc rather than the
game. Anything that does this keys off the filename, because the filename is
what the naming conventions were written to carry.

So the rules below are strict on purpose, and the two ways they can be wrong are
not equally bad:

* **Missing a set** costs nothing. The files stay as they are and the game is
  added a disc at a time, exactly as it is today. `Final Fantasy VII - Disc 2`
  is missed, and the user picks the other discs by hand instead.
* **Merging two games that are not a set** would produce a playlist that runs
  the wrong thing. So everything except the disc number must match character
  for character, in the same folder, with the same extension.
"""

import os
import re

import romshelf

#: `(Disc 1)`, `(Disc 1 of 2)`, `[Disk 2]`, `(CD 3)`. All three words are in
#: real use -- Redump writes "Disc", No-Intro's older sets write "Disk", and
#: European PlayStation releases were labelled "CD" often enough to matter.
#:
#: Anchored to a bracket on both sides, so `Game - Disc 2` and `Game Disc 2`
#: match nothing here. **That is a deliberate narrowness and not a safety
#: argument**, which is worth stating plainly because the comment that used to
#: sit here made the opposite claim: it said a looser rule would have to decide
#: whether the number in `Star Wars Episode 1` was a disc, which is not so --
#: the pattern needs the literal word, and that title has none of them.
#:
#: What the brackets actually buy, measured against 1,166 filenames across a
#: twelve-system library: nothing. Every multi-disc game there is bracketed, an
#: unbracketed rule matched no new file, and it produced no false positive
#: either. So the case for loosening is coverage of rips named by hand, and the
#: case against is only that `cd` is two letters and appears in real titles --
#: `Sonic CD 1.bin` is a plausible name meaning nothing about discs, while
#: `disc`/`disk` followed by a number at the end of a name is unambiguous.
#:
#: Left strict for now because a miss costs nothing and is visible -- the panel
#: offers **Pick another disc** for exactly this -- while a wrong match is a
#: playlist that runs something else. If it is loosened, loosen `disc` and
#: `disk` only, and only at the end of a name after a separator.
_DISC_RE = re.compile(
    r"[\(\[]\s*(?:disc|disk|cd)\s*(\d{1,2})\s*(?:of\s*\d{1,2}\s*)?[\)\]]",
    re.IGNORECASE,
)

#: More discs than any game ever shipped on. The largest retail sets are around
#: a dozen; this is only here so that a folder of two hundred similarly named
#: files cannot become one entry.
MAX_DISCS = 24


def _split_marker(stem):
    """(base, number) from a stem carrying exactly one disc marker, or None.

    Searched anywhere in the name rather than anchored to the end, and that is
    not a detail: Redump writes the revision *after* the disc, so
    `Final Fantasy IX (USA) (Disc 1) (Rev 1)` is the real shape of four of the
    biggest multi-disc games there are. A rule anchored to the end finds none of
    them, and finds them silently.
    """
    matches = list(_DISC_RE.finditer(stem))
    # Exactly one marker. A name carrying two is not a shape anybody writes, and
    # guessing which of them is the disc number is not worth doing.
    if len(matches) != 1:
        return None
    match = matches[0]
    number = int(match.group(1))
    if number < 1 or number > MAX_DISCS:
        return None
    base = stem[:match.start()] + stem[match.end():]
    # The marker took its own spacing with it, so `Game (USA) (Disc 1)` and
    # `Game (Disc 1) (USA)` both have to end up as `Game (USA)`.
    base = re.sub(r"\s{2,}", " ", base).strip(" -_")
    return (base, number) if base else None


def split_disc(name):
    """(base, number, extension) for a disc filename, or None.

    `base` is the stem with the disc marker and the space it left taken out, so
    it is directly comparable between two files of the same set and directly
    usable as the playlist's name.
    """
    stem, extension = os.path.splitext(os.path.basename(name or ""))
    parts = _split_marker(stem)
    return (parts[0], parts[1], extension.lower()) if parts else None


def split_disc_folder(name):
    """(base, number) for a *directory* named after a disc, or None.

    Separate from `split_disc` because there is no extension to strip, and
    stripping one is actively wrong here: `os.path.splitext` on a folder called
    `Game v1.5 (Disc 1)` takes `.5 (Disc 1)` for an extension and the marker
    goes with it.
    """
    return _split_marker(os.path.basename((name or "").rstrip("/\\")))


def discs_in_sibling_folders(rom_path):
    """The disc folders beside this file's own, newest question first: [] usually.

    **A Redump download arrives as one folder per disc** -- `Fear Effect (USA)
    (Disc 1)/` holding that disc's `.cue` and `.bin`, and three more beside it.
    Every multi-disc game in a 156-game collection was laid out that way.

    `find_set` cannot do anything with it and should not try: a playlist names
    files beside itself, and `romshelf` deliberately refuses to follow one out of
    its own directory, which is what stops filing scattering a game across the
    disk. So this exists only to let the panel *say* what it is looking at,
    rather than showing nothing and reading as a failure to notice.

    Lenient where `find_set` is strict -- two folders is enough, gaps and all.
    It decides a sentence, not a file that gets written.
    """
    own = os.path.dirname(os.path.abspath(rom_path or ""))
    parts = split_disc_folder(own)
    if not parts:
        return []
    base = parts[0]
    parent = os.path.dirname(own)
    try:
        entries = os.listdir(parent)
    except OSError:
        return []

    by_number = {}
    for name in entries:
        if not os.path.isdir(os.path.join(parent, name)):
            continue
        other = split_disc_folder(name)
        if not other or other[0] != base:
            continue
        if other[1] in by_number:
            return []
        by_number[other[1]] = name
    if len(by_number) < 2:
        return []
    return [by_number[number] for number in sorted(by_number)]


def find_set(rom_path):
    """The discs of the set `rom_path` belongs to, in order, or [].

    Filenames rather than paths: they all live in the one folder, and the
    playlist names them the same way.

    Every member must share the base name, the extension and the folder, and the
    numbering must run 1..n with nothing missing. **A gap means no set**, not a
    shorter one -- a folder holding discs 1 and 3 is either a broken copy or two
    different things, and neither is something to write a playlist for.
    """
    parts = split_disc(rom_path)
    if not parts:
        return []
    # A track is not a disc, whatever its name says. A CD game with audio is one
    # `.cue` and a dozen `.bin` files, and those files carry the disc marker too
    # -- `Game (Disc 2) (Track 01).bin`. On names alone that is disc 2 of
    # something, and the set built from it was track 1 of each disc: two files
    # that are neither discs nor a game. The `.cue` naming them is what settles
    # it, and `romshelf` already reads those.
    if romshelf.part_of_a_disc(rom_path):
        return []
    base, _number, extension = parts
    folder = os.path.dirname(rom_path)
    try:
        siblings = os.listdir(folder)
    except OSError:
        return []

    by_number = {}
    for name in siblings:
        if not os.path.isfile(os.path.join(folder, name)):
            continue
        other = split_disc(name)
        if not other:
            continue
        if other[0] != base or other[2] != extension:
            continue
        # Same rule for every member, not only the one that was picked: a set
        # is only a set if all of it is discs.
        if romshelf.part_of_a_disc(os.path.join(folder, name)):
            return []
        # Two files claiming the same disc number. A `.chd` beside a `.cue`
        # would already have been separated by the extension, so this is a real
        # duplicate -- neither can be preferred, so nothing is offered.
        if other[1] in by_number:
            return []
        by_number[other[1]] = name

    if len(by_number) < 2:
        return []
    if sorted(by_number) != list(range(1, len(by_number) + 1)):
        return []
    return [by_number[number] for number in sorted(by_number)]


def playlist_name(disc_names):
    """What the playlist is called on disk: the shared base name, plus `.m3u`.

    Falls back to the first filename's stem when the discs carry no marker,
    which is the hand-picked case: somebody choosing `FF7 d1.cue` and
    `FF7 d2.cue` gets `FF7 d1.m3u`. Not pretty, and it is never what the game is
    called in Steam -- the title comes from the file the user picked, and this
    is only the name on disk.
    """
    if not disc_names:
        return ""
    parts = split_disc(disc_names[0])
    if parts:
        return parts[0] + ".m3u"
    return os.path.splitext(os.path.basename(disc_names[0]))[0] + ".m3u"


def playlist_body(disc_names):
    """The file's contents: one filename per line, in the order given.

    No paths and no comments. RetroArch, DuckStation and every libretro core
    that reads one resolve each line against the playlist's own directory, so
    bare names are what keeps the set movable -- which matters here, because
    `romshelf` files the whole group into the library folder straight after.
    """
    return "".join("%s\n" % name for name in disc_names)


def write_playlist(folder, disc_names):
    """Write the playlist beside its discs. Returns (path, error).

    Refuses rather than overwrites when something is already there saying
    something different: the file may be the user's own, hand-made and correct,
    and replacing it is not this function's decision to make. One that already
    says exactly this is a success -- adding the same set twice is allowed, and
    the second time has nothing to do.
    """
    if len(disc_names) < 2:
        return "", "A playlist needs at least two discs."
    if len(disc_names) > MAX_DISCS:
        return "", "That is more discs than any game has."
    if len(set(disc_names)) != len(disc_names):
        return "", "The same disc is in the list twice."

    for name in disc_names:
        if name != os.path.basename(name) or name in (".", ".."):
            # Never a path. The playlist names files beside itself, and a name
            # with a separator in it either escapes the folder or is not a name.
            return "", "%s is not a file in this folder." % name
        if not os.path.isfile(os.path.join(folder, name)):
            return "", "%s is not in this folder." % name

    path = os.path.join(folder, playlist_name(disc_names))
    body = playlist_body(disc_names)

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                existing = handle.read()
        except OSError as error:
            return "", "Could not read the playlist already there: %s" % error
        if existing.strip() == body.strip():
            return path, ""
        return "", (
            "%s is already there and lists different discs. Rename or remove it "
            "first." % os.path.basename(path)
        )

    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    except OSError as error:
        return "", "Could not write %s: %s" % (os.path.basename(path), error)
    return path, ""
