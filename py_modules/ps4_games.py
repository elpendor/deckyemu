"""PS4 titles shadPS4 has installed, and the packages waiting to become them.

The same shape as `ps3_games`, for the same reason: a game bought from the store
is a `.pkg`, and until it is unpacked there is no game. What differs is who does
the unpacking. RPCS3 does its own, unattended, with `--headless --installpkg`.
shadPS4 has no such option at all -- its whole CLI is `-g`, `-p`, `-b`, `-f` and
some debug switches, and the only `InstallPkg` strings in the binary are
emulated PS4 system calls. The extraction code was taken *out* of shadPS4 and
lives on as a standalone command-line tool, which is what this plugin fetches.

**`.pkg` does not say which console it is for.** A PS3 package begins `\x7fPKG`
and a PS4 one `\x7fCNT`, and nothing else about the file distinguishes them --
same extension, same rough size, same naming. Getting that wrong sends a PS4
game to RPCS3, which reports a corrupt package. The magic is the whole answer
and it is four bytes in.

An installed PS4 game is a folder holding `eboot.bin` and `sce_sys/param.sfo`,
which is where its real name lives. shadPS4 finds them through `install_dirs` in
its own config; this module reads the same folders, so the two always agree.
"""

import os
import re
import shutil

import decky
import sfo
import sysenv

# What a PS4 package starts with. The PS3's is "\x7fPKG" -- see ps3_games.
PKG_MAGIC = b"\x7fCNT"

# Where extracted games go. Not inside shadPS4's flatpak data directory: these
# are tens of gigabytes each, and a folder under the user's own directory is one
# they can find, move to an SD card, and delete without knowing what a flatpak
# is.
GAMES_DIR = "games/ps4"

# A PS4 content id looks like "UP9000-CUSA00001_00-EXAMPLE000000001". It is read
# by scanning the header rather than from a fixed offset, unlike the PS3's:
# that offset was confirmed against a real package on a Deck and this one has
# not been, so the honest version is the one that does not depend on a guess.
_CONTENT_ID_RE = re.compile(rb"[A-Z]{2}\d{4}-([A-Z]{4}\d{5})_00-[A-Z0-9_]{16}")
_HEADER_BYTES = 4096

_TITLE_ID_RE = re.compile(r"^[A-Z]{4}\d{5}$")


def is_package(path):
    """Whether `path` is a PS4 package."""
    try:
        with open(path, "rb") as handle:
            return handle.read(len(PKG_MAGIC)) == PKG_MAGIC
    except OSError:
        return False


def package_title_id(path):
    """The title id inside a PS4 .pkg, or '' if it cannot be read.

    Empty is not a refusal: a package whose header will not parse is still
    installable, and the title comes from its param.sfo once it is unpacked.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(_HEADER_BYTES)
    except OSError:
        return ""
    if not header.startswith(PKG_MAGIC):
        return ""
    match = _CONTENT_ID_RE.search(header)
    return match.group(1).decode("ascii") if match else ""


def games_dir(create=True):
    return sysenv.user_dir(*GAMES_DIR.split("/"), create=create)


def installed_games(root=None):
    """[{title, title_id, eboot, icon, background}] for every unpacked game.

    A game is a folder with an `eboot.bin` and a `sce_sys/param.sfo`, which is
    exactly what shadPS4 looks for. Sorted by title so the order does not depend
    on the filesystem.
    """
    root = root or games_dir(create=False)
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
        title_id = param.get("TITLE_ID") or name
        found.append(
            {
                "title_id": title_id,
                # Falling back to the folder rather than skipping: the game is
                # installed and playable either way, and a row named after its
                # product code beats no row at all.
                "title": param.get("TITLE") or name,
                "eboot": eboot,
                # Reported because they say what is in the folder. Artwork comes
                # from SteamGridDB -- a package ships nothing shaped like
                # Steam's portrait capsule, so using these left slots empty.
                "icon": _present(os.path.join(system, "icon0.png")),
                "background": _present(os.path.join(system, "pic1.png")),
            }
        )

    found.sort(key=lambda item: item["title"].lower())
    return found


def _present(path):
    return path if os.path.isfile(path) else ""


def target_dir(title_id, root=None):
    """Where a package with this title id should be unpacked to, or ''.

    The id reaches a filesystem path and an extractor's command line, so it is
    matched against the shape of a real one and checked to land directly inside
    the games folder.
    """
    root = os.path.normpath(root or games_dir())
    name = title_id if _TITLE_ID_RE.match(title_id or "") else ""
    if not name:
        return ""
    path = os.path.normpath(os.path.join(root, name))
    if os.path.dirname(path) != root:
        return ""
    return path


def game_info(rom_path, root=None):
    """{ok, title_id, title, bytes} for the unpacked game a ROM path is in.

    Same contract as the PS3 one, so the remove dialog can ask both without
    knowing which console it is holding.
    """
    title_id = game_of(rom_path, root)
    if not title_id:
        return {"ok": False}
    directory = target_dir(title_id, root)
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
    """Delete an unpacked PS4 game. Returns (freed bytes, error).

    Same bargain as the PS3 one: the package was deleted once the game came out
    of it, so this is the only copy and getting it back means sending the
    package again. Save data lives elsewhere and is not touched.
    """
    directory = target_dir(title_id, root)
    if not directory:
        return 0, "%r is not a title id." % title_id
    if not os.path.isdir(directory):
        return 0, "There is no game unpacked under %s." % title_id

    freed = sysenv.directory_bytes(directory)
    try:
        shutil.rmtree(directory)
    except OSError as error:
        return 0, "Could not delete %s: %s" % (directory, error)

    decky.logger.info("Deleted PS4 game %s, freeing %d bytes", title_id, freed)
    return freed, ""


def game_of(rom_path, root=None):
    """The title id whose folder `rom_path` sits inside, or ''."""
    root = os.path.normpath(root or games_dir(create=False))
    path = os.path.normpath(rom_path or "")
    if not path.startswith(root + os.sep):
        return ""
    name = path[len(root) + 1:].split(os.sep)[0]
    return name if _TITLE_ID_RE.match(name) else ""


def unpacked_game(directory):
    """The game folder at or one level inside `directory`, or ''.

    The extractor names a folder after the title itself, so a game unpacked into
    `<games>/CUSA07010` arrives at `<games>/CUSA07010/CUSA07010`. Looking for the
    eboot rather than assuming a layout is what finds it either way.
    """
    if os.path.isfile(os.path.join(directory, "eboot.bin")):
        return directory
    try:
        for name in sorted(os.listdir(directory)):
            nested = os.path.join(directory, name)
            if os.path.isdir(nested) and os.path.isfile(os.path.join(nested, "eboot.bin")):
                return nested
    except OSError as error:
        decky.logger.warning("Could not look inside %s: %s", directory, error)
    return ""


def settle(target):
    """Leave exactly one game folder at `target`. Returns (path, error).

    The extractor creates a folder named after the title inside whatever it is
    pointed at, so unpacking into `<games>/CUSA07010` produces
    `<games>/CUSA07010/CUSA07010`. That nesting is not cosmetic: `installed_games`
    looks one level down and would miss it, and so would shadPS4, which expects
    game folders directly inside the folders in `install_dirs`. Rather than
    teach three readers about a layout the tool happens to produce, the layout
    is made canonical here, once.
    """
    found = unpacked_game(target)
    if not found:
        return "", ""
    if os.path.normpath(found) == os.path.normpath(target):
        return found, ""

    # Move the real folder aside, drop the wrapper, put it back under the name
    # the wrapper had. Same filesystem throughout, so these are renames.
    holding = target + ".unpacked"
    try:
        if os.path.exists(holding):
            shutil.rmtree(holding)
        os.rename(found, holding)
        shutil.rmtree(target)
        os.rename(holding, target)
    except OSError as error:
        # The game is unpacked and playable where it is; only the layout is
        # wrong. Report it rather than lose it.
        return found, "Unpacked, but could not be moved into place: %s" % error

    decky.logger.info("Flattened %s out of its own folder", target)
    return target, ""
