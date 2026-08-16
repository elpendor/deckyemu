"""PS Vita titles Vita3K has installed.

The third console here whose games arrive as something other than a ROM, and
the only one this plugin cannot install itself. Vita3K decrypts content as it
installs -- copying an extracted release into `ux0/app` produces a game it
lists and cannot start, `Invalid SELF: still encrypted` -- so installing stays
in its own interface. What happens either side of that is ours.

Afterwards a game is a folder under `ux0/app/<TITLE_ID>` with an `eboot.bin`
and a `sce_sys/param.sfo`, which is the same shape as the PS3 and PS4 ones and
reads with the same parser.

**Launching is by title id, not by path.** `-Fr PCSA00011` boots the game;
handing Vita3K a path does not, and a title id has no spaces, which matters
because the AppImage's launcher word-splits its arguments. Other launchers
arrived at the same answer independently -- they read a title id out of a
`.psvita` file and run `-Fr` with it.
"""

import os
import re
import shutil
import struct

import decky
import sfo
import sysenv

# A PS Vita package. The magic is the PS3's -- both are `\x7fPKG` -- and the
# type field at offset 6 is what separates them: 2 for Vita, 1 for the PS3.
# Read off a real Vita package rather than assumed; a PS4 one is `\x7fCNT` and
# never reaches here.
PKG_MAGIC = b"\x7fPKG"
PKG_TYPE_AT = 6
PKG_TYPE_VITA = 2
_CONTENT_ID_AT = 0x30
_CONTENT_ID_LEN = 36
_TITLE_ID_RE = re.compile(r"([A-Z]{4}\d{5})")

# What a zRIF looks like. Every one begins with the same few characters --
# they are a fixed zlib header with a shared dictionary, base64'd -- which is
# enough to tell a licence key from a readme sitting in the same folder.
ZRIF_PREFIX = "KO5if"
_ZRIF_RE = re.compile(r"^[A-Za-z0-9+/=]{40,}$")

# Where a key may be kept beside its package. A `.zrif` is unambiguous; a
# `.txt` is what these are usually distributed as.
ZRIF_SUFFIXES = (".zrif", ".txt")

# Vita3K's own filesystem, under XDG data rather than beside its config.
GAMES_DIR = ".local/share/Vita3K/Vita3K/ux0/app"


def games_dir():
    return os.path.join(sysenv.user_home(), *GAMES_DIR.split("/"))


def installed_games(root=None):
    """[{title, title_id, eboot, icon, background}] for every installed title.

    `eboot` is reported because the library needs a real file to point at --
    every health check in this plugin asks whether a game's ROM still exists --
    even though launching uses the title id instead.
    """
    root = root or games_dir()
    try:
        names = os.listdir(root)
    except OSError:
        return []

    found = []
    for name in sorted(names):
        directory = os.path.join(root, name)
        eboot = os.path.join(directory, "eboot.bin")
        if not os.path.isfile(eboot):
            continue

        system = os.path.join(directory, "sce_sys")
        param = sfo.read(os.path.join(system, "param.sfo"))
        found.append(
            {
                "title_id": param.get("TITLE_ID") or name,
                "title": param.get("TITLE") or name,
                "eboot": eboot,
                "icon": _present(os.path.join(system, "icon0.png")),
                "background": _present(os.path.join(system, "pic1.png")),
            }
        )

    found.sort(key=lambda item: item["title"].lower())
    return found


def _present(path):
    return path if os.path.isfile(path) else ""


def is_package(path):
    """Whether `path` is a PS Vita package rather than a PS3 one."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(PKG_TYPE_AT + 2)
    except OSError:
        return False
    if not header.startswith(PKG_MAGIC) or len(header) < PKG_TYPE_AT + 2:
        return False
    return struct.unpack_from(">H", header, PKG_TYPE_AT)[0] == PKG_TYPE_VITA


def package_title_id(path):
    """The title id inside a Vita .pkg, or ''."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(_CONTENT_ID_AT + _CONTENT_ID_LEN)
    except OSError:
        return ""
    content = header[_CONTENT_ID_AT:_CONTENT_ID_AT + _CONTENT_ID_LEN]
    match = _TITLE_ID_RE.search(content.split(b"\x00", 1)[0].decode("utf-8", "replace"))
    return match.group(1) if match else ""


def find_zrif(pkg_path, title_id=""):
    """The licence key kept beside a package, or ''."""
    return locate_zrif(pkg_path, title_id)[0]


def locate_zrif(pkg_path, title_id=""):
    """(key, the file it came out of) for a package's licence, or ('', '').

    Vita3K cannot install a package without one and cannot derive it: the key
    is what decrypts the content. It is not bundled here and never will be --
    a third-party table of licence keys is not something to ship, and it goes
    stale. So it travels with the game, which is how these are distributed.

    **A key belongs to this package only when its name says so** -- the
    package's own stem, or the title id. Anything else in the folder is a file
    that happens to hold a zRIF, and this does not guess between them.

    It used to: a lone candidate was taken as the answer, on the reasoning that
    "I sent both files" ought to be enough without naming them alike. That is
    wrong whenever the folder is an inbox, which is exactly what it is. A
    transfer folder holding `gravity rush.pkg` and one unrelated `tennis.zrif`
    installed a gigabyte and a half under the wrong licence; Vita3K decompressed
    the key, failed the content with `header signature is invalid`, and the
    plugin reported that no new game had appeared -- three steps at which it
    read as a bad dump of the game rather than as the wrong key for a good one.

    An unnamed key is now offered to the user by name instead, which costs one
    tap and cannot pick the wrong one silently. See `zrif_report`.

    The file is reported as well as the key so the caller can clear it away with
    the package it belonged to.
    """
    folder = os.path.dirname(pkg_path)
    stem = os.path.splitext(os.path.basename(pkg_path))[0]

    names = []
    for base in (stem, title_id):
        if base:
            names.extend(base + suffix for suffix in ZRIF_SUFFIXES)

    for name in names:
        path = os.path.join(folder, name)
        key = _read_zrif(path)
        if key:
            return key, path
    return "", ""


def zrif_candidates(folder):
    """Filenames in `folder` that hold something shaped like a zRIF."""
    found = []
    try:
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(ZRIF_SUFFIXES) and _read_zrif(os.path.join(folder, name)):
                found.append(name)
    except OSError:
        pass
    return found


def is_zrif(text):
    """Whether `text` looks like a licence key rather than something pasted by
    accident.

    The same two things `_read_zrif` looks for in a file: the fixed prefix every
    zRIF starts with, and base64 after it. This is the whole of the validation
    and it is deliberately shallow -- Vita3K is the only thing that can say
    whether a key actually decrypts a package, and it says so by failing.
    """
    text = (text or "").strip()
    return bool(text.startswith(ZRIF_PREFIX) and _ZRIF_RE.match(text))


def write_zrif(pkg_path, key, title_id=""):
    """Save a pasted key beside its package. Returns (path, error).

    Named after the title id, which is what `locate_zrif` looks for first and
    what the panel tells the user to name a file they send. A key that arrives
    by clipboard should land exactly where one that arrived by transfer would,
    or the two routes would need two different searches.
    """
    key = (key or "").strip()
    if not is_zrif(key):
        return "", "That does not look like a zRIF. They begin %s." % ZRIF_PREFIX

    folder = os.path.dirname(pkg_path or "")
    if not folder or not os.path.isdir(folder):
        return "", "That package is no longer where it was."

    name = "%s.zrif" % (title_id or os.path.splitext(os.path.basename(pkg_path))[0])
    target = os.path.join(folder, name)
    try:
        # Written whole, not appended: a second paste replaces the first, which
        # is what somebody correcting a wrong key expects to happen.
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(key + "\n")
    except OSError as error:
        return "", "Could not save the key: %s" % error

    decky.logger.info("Saved a pasted licence key as %s", name)
    return target, ""


def zrif_report(pkg_path, title_id=""):
    """{key, file, candidates} -- this package's licence, and what else is here.

    `key` is filled only when a file is named for this package. `candidates` is
    every other key file in the folder, offered so the panel can ask *which*
    rather than either guessing or claiming there is none.

    Those are three different situations with three different answers -- send a
    key, choose between these, or go ahead -- and they were one boolean before.
    """
    key, path = locate_zrif(pkg_path, title_id)
    if key:
        return {"key": key, "file": path, "candidates": []}
    return {"key": "", "file": "", "candidates": zrif_candidates(os.path.dirname(pkg_path))}


def zrif_from(path):
    """The key in one named file, for a candidate the user picked themselves."""
    return _read_zrif(path)


# A licence key file is a line of text. Anything larger is not one.
MAX_ZRIF_BYTES = 64 * 1024


def _read_zrif(path):
    """The zRIF inside a text file, or ''."""
    try:
        if os.path.getsize(path) > MAX_ZRIF_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""

    for line in text.splitlines():
        line = line.strip()
        if line.startswith(ZRIF_PREFIX) and _ZRIF_RE.match(line):
            return line
    return ""


# Where Vita3K keeps the licence it wrote from the zRIF at install time, as
# `<TITLE_ID>/<CONTENT_ID>.rif`. A sibling of the app folder, not inside it.
LICENSE_DIR = ".local/share/Vita3K/Vita3K/ux0/license"

_ID_RE = re.compile(r"^[A-Z]{4}\d{5}$")


def game_dir(title_id, root=None):
    """The folder a title is installed in, or '' if the id is not one.

    Two gates, as everywhere else this hands an id to `rmtree`: it must look
    like a title id, and it must land directly inside the games folder.
    """
    if not _ID_RE.match(title_id or ""):
        return ""
    root = os.path.normpath(root or games_dir())
    path = os.path.normpath(os.path.join(root, title_id))
    return path if os.path.dirname(path) == root else ""


def game_info(rom_path, root=None):
    """{ok, title_id, title, bytes} for the installed game a ROM path is in."""
    title_id = title_of(rom_path, root)
    if not title_id:
        return {"ok": False}
    directory = game_dir(title_id, root)
    if not directory or not os.path.isdir(directory):
        return {"ok": False}

    param = sfo.read(os.path.join(directory, "sce_sys", "param.sfo"))
    return {
        "ok": True,
        "title_id": title_id,
        "title": param.get("TITLE") or title_id,
        "bytes": sysenv.directory_bytes(directory),
    }


def delete_game(title_id, root=None):
    """Delete an installed title, keeping its licence and its saves.

    The .rif was written by Vita3K rather than sent by the user, which once
    looked like reason enough to remove it with the game -- reinstalling from
    the same package and key writes a new one, so nothing seemed lost.

    It is lost if the key has gone. The .pkg is deleted on install and only the
    .zrif beside it survives, so a folder tidied out at any point later leaves
    the .rif as the one remaining copy of the licence -- and deleting it then
    is unrecoverable. RPCS3's .rap is kept for exactly this reason; there is no
    argument for treating this one differently, and it is a few hundred bytes.

    Save data is not touched either. A game can be installed again; progress in
    it cannot.
    """
    directory = game_dir(title_id, root)
    if not directory:
        return 0, "%r is not a title id." % title_id
    if not os.path.isdir(directory):
        return 0, "Vita3K has no game installed under %s." % title_id

    freed = sysenv.directory_bytes(directory)
    try:
        shutil.rmtree(directory)
    except OSError as error:
        return 0, "Could not delete %s: %s" % (directory, error)

    decky.logger.info("Deleted Vita game %s, freeing %d bytes", title_id, freed)
    return freed, ""


def title_of(rom_path, root=None):
    """The title id whose folder `rom_path` sits in, or ''.

    Lets a launcher be rebuilt from what the library recorded: the entry stores
    the eboot, and the id `-Fr` needs is the folder above it.
    """
    root = os.path.normpath(root or games_dir())
    path = os.path.normpath(rom_path or "")
    if not path.startswith(root + os.sep):
        return ""
    return path[len(root) + 1:].split(os.sep)[0]
