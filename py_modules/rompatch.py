"""ROM hacks, kept as a list and handed to RetroArch as files beside the ROM.

RetroArch soft-patches at load, in memory, so nothing here reads or writes a
ROM. It applies `rom.ips`, then `rom.ips1`, `rom.ips2` and so on, in that order,
which is what turns a list somebody can reorder and switch off into something an
emulator understands.

The patches themselves live in `~/deckyemu/patches/<app id>/` rather than beside
the ROM, because a switched-off patch still has to exist somewhere RetroArch
will not read. Only the ones that are on are written out.
"""

import json
import os
import re
import shutil

import sysenv

PATCH_MAGIC = (
    (".ips", b"PATCH"),
    (".bps", b"BPS1"),
    (".ups", b"UPS1"),
)

# XDelta1, which RetroArch also applies, is left out: it is the one format we
# cannot recognise from a short header, so offering it would mean accepting a
# file on trust.

MAX_PATCH_BYTES = 64 * 1024 * 1024

# `.bin` and `.img` are deliberately absent -- a Mega Drive cartridge dump is a
# `.bin`, and warning about those would be wrong more often than right.
_DISC_SUFFIXES = (".cue", ".chd", ".m3u", ".pbp", ".gdi", ".ccd", ".nrg",
                  ".mdf", ".iso", ".cso")

_RECORD = "patches.json"

_SAFE_APP = re.compile(r"^[0-9]{1,20}$")


def store_dir(app_id, create=True):
    """Where this game's patch files are kept, or "" for an unusable id."""
    if not _SAFE_APP.match(str(app_id or "")):
        return ""
    return sysenv.user_dir("patches", str(app_id), create=create)


def kind_of(patch_path):
    """The format this file actually is -- ".ips", ".bps", ".ups" -- or "".

    Read from the bytes rather than the extension: patches arrive through a
    browser, which renames them, and the ROM is what people pick by mistake.
    """
    try:
        with open(patch_path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return ""
    for suffix, magic in PATCH_MAGIC:
        if head.startswith(magic):
            return suffix
    return ""


def warning_for(rom_path):
    """What to say before patching this ROM, or "".

    It turns on how the *core* loads content, which is not in a core's info
    file, so this is a guess from the extension and is worded as one.

    There used to be a second warning, about ROMs inside an archive. It was
    speculative -- the libretro docs say nothing either way -- and the device
    disagreed with it: the same hack applied to `Pokemon Sapphire.zip` and to
    the `.gba` extracted from it, on mGBA, with identical results. A warning
    nobody can act on and that turns out to be wrong is worse than silence.
    """
    suffix = os.path.splitext(rom_path)[1].lower()
    if suffix in _DISC_SUFFIXES:
        return ("Disc games are usually loaded straight from the file rather "
                "than into memory, and RetroArch can only patch what it loads "
                "into memory. Patches may have no effect.")
    return ""


# ---------------------------------------------------------------------- list

def _record_path(app_id):
    directory = store_dir(app_id, create=False)
    return os.path.join(directory, _RECORD) if directory else ""


def listing(app_id):
    """This game's patches, in the order they are applied."""
    path = _record_path(app_id)
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("file")]


def _write_listing(app_id, rows):
    directory = store_dir(app_id)
    if not directory:
        return "That game cannot hold patches."
    try:
        with open(os.path.join(directory, _RECORD), "w", encoding="utf-8") as handle:
            json.dump(rows, handle, indent=2)
    except OSError as error:
        return "Could not record the patch list: %s" % error
    return ""


def _stored_name(directory, name):
    """A filename for `name` in `directory` that is not taken and cannot escape."""
    safe = re.sub(r"[^A-Za-z0-9 ._-]", "_", os.path.basename(name)).strip(". ")
    safe = safe or "patch"
    candidate, count = safe, 1
    while os.path.exists(os.path.join(directory, candidate)):
        stem, suffix = os.path.splitext(safe)
        candidate = "%s (%d)%s" % (stem, count, suffix)
        count += 1
    return candidate


def add(app_id, patch_path):
    """Take a patch into this game's list, switched on. Returns `(row, error)`."""
    if not os.path.isfile(patch_path):
        return None, "That patch file is missing."

    try:
        size = os.path.getsize(patch_path)
    except OSError as error:
        return None, "Could not read that patch: %s" % error
    if size == 0:
        return None, "That patch file is empty."
    if size > MAX_PATCH_BYTES:
        return None, "That file is too large to be a patch."

    kind = kind_of(patch_path)
    if not kind:
        return None, ("That is not an IPS, BPS or UPS patch. Check you picked "
                      "the patch and not the ROM.")

    directory = store_dir(app_id)
    if not directory:
        return None, "That game cannot hold patches."

    name = os.path.basename(patch_path)
    stored = _stored_name(directory, name)
    try:
        shutil.copyfile(patch_path, os.path.join(directory, stored))
    except OSError as error:
        return None, "Could not keep a copy of that patch: %s" % error

    row = {"file": stored, "name": name, "kind": kind.lstrip("."), "on": True}
    problem = _write_listing(app_id, listing(app_id) + [row])
    if problem:
        return None, problem
    return row, ""


def remove(app_id, stored):
    """Drop one patch from the list and delete the copy we kept."""
    rows = [row for row in listing(app_id) if row.get("file") != stored]
    directory = store_dir(app_id, create=False)
    if directory and stored:
        try:
            os.remove(os.path.join(directory, os.path.basename(stored)))
        except OSError:
            pass
    return _write_listing(app_id, rows)


def switch(app_id, stored, on):
    """Turn one patch on or off without losing it."""
    rows = listing(app_id)
    for row in rows:
        if row.get("file") == stored:
            row["on"] = bool(on)
    return _write_listing(app_id, rows)


def reorder(app_id, order):
    """Put the list in `order` (stored filenames). Unknown names are ignored."""
    rows = {row.get("file"): row for row in listing(app_id)}
    moved = [rows.pop(name) for name in order if name in rows]
    return _write_listing(app_id, moved + list(rows.values()))


# ------------------------------------------------------------------ the ROM

def beside(rom_path):
    """Every patch file RetroArch would read for this ROM."""
    directory = os.path.dirname(rom_path)
    stem = os.path.splitext(os.path.basename(rom_path))[0]
    found = []
    try:
        names = os.listdir(directory or ".")
    except OSError:
        return found
    for name in sorted(names):
        root, suffix = os.path.splitext(name)
        if root != stem:
            continue
        # `.ips`, and `.ips1` through `.ips9` and beyond.
        base = re.sub(r"\d+$", "", suffix.lower())
        if base in {one for one, _ in PATCH_MAGIC}:
            found.append(os.path.join(directory, name))
    return found


def _target_names(rows):
    """The filename suffix each enabled patch gets, in order."""
    seen: dict = {}
    names = []
    for row in rows:
        if not row.get("on"):
            continue
        kind = "." + str(row.get("kind") or "ips")
        count = seen.get(kind, 0)
        names.append((row, kind if count == 0 else "%s%d" % (kind, count)))
        seen[kind] = count + 1
    return names


def sync(app_id, rom_path):
    """Write the switched-on patches beside the ROM. Returns `(count, error)`.

    Everything RetroArch would read is removed first, so a patch switched off
    stops being applied and the numbering never has a gap in it.
    """
    if not os.path.isfile(rom_path):
        return 0, "The ROM file is missing."

    for path in beside(rom_path):
        try:
            os.remove(path)
        except OSError as error:
            return 0, "Could not clear the old patches: %s" % error

    directory = store_dir(app_id, create=False)
    stem = os.path.splitext(rom_path)[0]
    written = 0
    for row, suffix in _target_names(listing(app_id)):
        source = os.path.join(directory, row["file"]) if directory else ""
        if not source or not os.path.isfile(source):
            return written, "%s is no longer on this Deck." % row.get("name", "A patch")
        try:
            shutil.copyfile(source, stem + suffix)
        except OSError as error:
            return written, "Could not put %s beside the ROM: %s" % (
                row.get("name", "the patch"), error)
        written += 1
    return written, ""


def adopt(app_id, rom_path):
    """Take a patch somebody put beside the ROM by hand into the list.

    Only when the list is empty, and only what is actually a patch. Without it
    a hand-placed hack would be applied by RetroArch and absent from the screen
    that claims to say which hacks are applied.
    """
    if listing(app_id):
        return 0
    taken = 0
    for path in beside(rom_path):
        if not kind_of(path):
            continue
        row, error = add(app_id, path)
        if row and not error:
            taken += 1
    return taken
