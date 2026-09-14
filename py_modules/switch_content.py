"""Telling a Switch update or DLC apart from a game, and which game it is for.

An NSP is a PFS0 container: a plain header naming the files inside, then the
files. The NCAs are encrypted and the header is not, so the questions asked here
need no keys at all -- which matters, because the backend runs on a Python with
no AES and prod.keys is the user's file to use, not ours to read.

Three sources of evidence, in the order they are trusted:

* **`<id>.cnmt.xml`**, when the package carries one. It says outright what the
  package is (`Application`, `Patch`, `AddOnContent`) and, for an update, which
  game it patches. Many dumps include it; plenty do not.
* **The ticket's filename**, `<title id><key generation>.tik`. Every package
  under title-key crypto has one, and the title id in its name is enough: an
  update is the game's id with `800` at the end, and a DLC is the game's id plus
  `0x1000` and a counter -- so all three reduce to the game with `& ~0x1FFF`.
* **`[0100...]` in the filename**, which is what naming tools write and the only
  thing left for a package converted to standard crypto, which has no ticket.

Checked against real packages on a Deck, and Ryujinx agreed with each answer at
boot: a base game (ticket only), an update (ticket and XML) and a DLC (ticket
only).
"""

import html
import os
import re
import struct

BASE, UPDATE, DLC = "base", "update", "dlc"

_MAGIC = b"PFS0"

#: Bounds on what a header may claim before it is believed. A real package
#: lists a dozen files; these only stop a file that merely starts with the magic
#: from asking for gigabytes.
_MAX_ENTRIES = 1024
_MAX_NAMES = 1 << 20
_MAX_XML = 256 * 1024

_TICKET = re.compile(r"^([0-9a-f]{16})[0-9a-f]{16}\.tik$", re.IGNORECASE)
_ID_IN_NAME = re.compile(r"\[(0100[0-9a-f]{12})\]", re.IGNORECASE)
#: `v2.0.2`, `[v1.1.1]`, `Upd v1.1.1`. Only a dotted version: `[v262144]` is the
#: package's release counter, which means nothing to anybody reading it.
_VERSION_IN_NAME = re.compile(
    r"(?:^|[\s\[(_-])v(\d+(?:\.\d+){1,3})(?=$|[\s\])_.-])", re.IGNORECASE)

_CNMT_TYPES = {"application": BASE, "patch": UPDATE, "addoncontent": DLC}

#: What a DLC is to Ryujinx is every NCA whose decrypted header says PublicData.
#: Without keys the nearest reading is every NCA that is not the meta one, which
#: is what a DLC package holds: the meta NCA and its data.
_NCA_SUFFIXES = (".nca", ".ncz")
_META_SUFFIXES = (".cnmt.nca", ".cnmt.ncz")


def entries(path):
    """(name, offset, size) for every file in a PFS0 package, or None.

    None whenever the file is not one or cannot be read: this runs on whatever
    the picker landed on, and most of that is not a Switch package at all.
    Offsets are from the start of the file.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
            if len(head) < 16 or head[:4] != _MAGIC:
                return None
            count, names_size = struct.unpack("<II", head[4:12])
            if count > _MAX_ENTRIES or names_size > _MAX_NAMES:
                return None
            table = handle.read(24 * count)
            names = handle.read(names_size)
    except OSError:
        return None
    if len(table) < 24 * count or len(names) < names_size:
        return None

    data_start = 16 + 24 * count + names_size
    found = []
    for index in range(count):
        offset, size, name_at, _reserved = struct.unpack_from("<QQII", table, 24 * index)
        end = names.find(b"\0", name_at)
        if name_at >= len(names) or end < 0:
            return None
        try:
            name = names[name_at:end].decode("utf-8")
        except UnicodeDecodeError:
            return None
        found.append((name, data_start + offset, size))
    return found


def kind_of_id(title_id):
    """BASE, UPDATE or DLC, from a title id alone."""
    low = title_id & 0x1FFF
    if low == 0:
        return BASE
    if low == 0x800:
        return UPDATE
    return DLC


def base_of(title_id):
    """The game a title id belongs to -- itself, for a game."""
    return title_id & ~0x1FFF


def _hex(title_id):
    """The spelling Ryujinx uses for a title id on disk: sixteen lowercase digits."""
    return "%016x" % title_id


def _parse_id(text):
    try:
        return int(text.strip(), 16)
    except (AttributeError, ValueError):
        return None


def _read_cnmt(path, offset, size):
    """(kind, title id, base id, release) from a `.cnmt.xml`, or None.

    Regex rather than a parser: the plugin runs on a trimmed standard library
    where `xml.etree` is missing, and importing it takes the whole backend down.

    `Type`, `Id` and `Version` are read before the first `<Content>`, because
    every content entry carries a `<Type>` and an `<Id>` of its own.
    `OriginalId` is read from anywhere: a real update's comes *after* its
    content list, and reading only the top of the file missed it.
    """
    if size <= 0 or size > _MAX_XML:
        return None
    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            text = handle.read(size).decode("utf-8", "replace")
    except OSError:
        return None
    head = text.split("<Content>", 1)[0]

    def field(name, within):
        match = re.search(r"<%s>([^<]*)</%s>" % (name, name), within)
        return html.unescape(match.group(1)).strip() if match else ""

    kind = _CNMT_TYPES.get(field("Type", head).lower())
    title_id = _parse_id(field("Id", head))
    if not kind or title_id is None:
        return None
    version = field("Version", head)
    release = int(version) if version.isdigit() else None
    original = _parse_id(field("OriginalId", text)) if kind == UPDATE else None
    base = original if original is not None else base_of(title_id)
    return kind, title_id, base, release


def version_label(path):
    """The human version in a filename, like "2.0.2", or ""."""
    match = _VERSION_IN_NAME.search(os.path.basename(path or ""))
    return match.group(1) if match else ""


def inspect(path):
    """What a Switch file is, as far as can be said without keys.

    Returns `{kind, title_id, base_id, version, release, data_ncas, evidence}`
    with ids as Ryujinx spells them, or `kind: ""` when nothing identifies it.
    `release` is the package's own version counter when its XML says, which is
    what orders two updates; `version` is the human one from the filename.
    `data_ncas` is only filled for a DLC, as the paths Ryujinx names them by
    inside the package (`/<hash>.nca`).

    **A package holding more than one title is a game.** A merged dump carries
    the base game with its update and DLC in one file; Ryujinx reads those out of
    it by itself, and treating it as an update would hide the game inside it.
    """
    nothing = {"kind": "", "title_id": "", "base_id": "", "version": "",
               "release": None, "data_ncas": [], "evidence": ""}
    listing = entries(path)

    found = []
    evidence = ""
    if listing:
        for name, offset, size in listing:
            if name.lower().endswith(".cnmt.xml"):
                parsed = _read_cnmt(path, offset, size)
                if parsed:
                    found.append(parsed)
        if found:
            evidence = "cnmt"
        else:
            for name, _offset, _size in listing:
                match = _TICKET.match(name)
                if match:
                    title_id = int(match.group(1), 16)
                    found.append((kind_of_id(title_id), title_id, base_of(title_id), None))
            evidence = "ticket" if found else ""

    if not found:
        match = _ID_IN_NAME.search(os.path.basename(path or ""))
        if not match:
            return nothing
        title_id = int(match.group(1), 16)
        found = [(kind_of_id(title_id), title_id, base_of(title_id), None)]
        evidence = "filename"

    titles = {one[1] for one in found}
    bases = {one[2] for one in found}
    if len(bases) != 1:
        # Two different games in one file is nothing anybody ships.
        return nothing
    base_id = bases.pop()
    if len(titles) > 1:
        kind, title_id, release = BASE, base_id, None
    else:
        kind, title_id, _base, release = found[0]

    data_ncas = []
    if kind == DLC and listing:
        data_ncas = [
            "/" + name for name, _offset, _size in listing
            if name.lower().endswith(_NCA_SUFFIXES)
            and not name.lower().endswith(_META_SUFFIXES)
        ]

    return {
        "kind": kind,
        "title_id": _hex(title_id),
        "base_id": _hex(base_id),
        "version": version_label(path) if kind == UPDATE else "",
        "release": release,
        "data_ncas": data_ncas,
        "evidence": evidence,
    }
