"""PS3 titles RPCS3 has installed, and the packages waiting to become them.

A PKG-installed PS3 game has no ROM file to point at. RPCS3 unpacks it into
`dev_hdd0/game/<TITLE_ID>/`, and what boots is `USRDIR/EBOOT.BIN` -- a path
nobody would type and no ROM picker would suggest. Everything here exists so
that a game which arrived as a package can be added to Steam without the user
ever seeing that path.

Three jobs:

  packages          the .pkg files sitting in the transfer folders, unopened
  installed_games   what RPCS3 has unpacked, by name, with its own artwork
  stage_packages    short-named links to the packages still waiting to install

Installing a package needs none of RPCS3's windows: `--headless --installpkg`
unpacks a 240MB package in about five seconds with nothing on screen. The third
job is for the times somebody wants RPCS3's own interface anyway, and it is not
cosmetic. RPCS3's install dialog prints the package's
filename inline in its description, and the dialog is as wide as that text: a
101-character name produced a window 1539px across on a 1280px display, with
the Install button 240px off the right edge. Gamescope scales the picture to
fit but not the pointer, so the button was visible and unreachable, and taps
landed on nothing. A short name is what keeps the dialog on screen.
"""

import json
import os
import re
import shutil

import decky

import jsonstore
import sfo
import sysenv


# PARAM.SFO is the same container on the PS3 and the PS4, so it lives in `sfo`.
# Kept as a name here because everything in this module speaks of PARAM.SFO.
read_sfo = sfo.read


# ------------------------------------------------------------- installed games

GAME_ROOT = ".config/rpcs3/dev_hdd0/game"

# HG is a package installed to the hard disk, DG a disc game. The other
# categories in a PARAM.SFO are themes, save data, patches and demos of the
# kind that are not separately bootable, and offering those as games would put
# rows in the picker that cannot start.
PLAYABLE_CATEGORIES = ("HG", "DG")


def game_root():
    return os.path.join(sysenv.user_home(), *GAME_ROOT.split("/"))


def installed_games(root=None):
    """[{title, title_id, eboot, icon, background}] for every bootable title.

    Sorted by title so the panel's order does not depend on the filesystem.
    """
    root = root or game_root()
    try:
        names = os.listdir(root)
    except OSError:
        return []

    found = []
    for name in sorted(names):
        directory = os.path.join(root, name)
        sfo = read_sfo(os.path.join(directory, "PARAM.SFO"))
        if not sfo:
            # RPCS3 ships an empty TEST12345 folder, and there is no PARAM.SFO
            # in it. Requiring one is what keeps that placeholder out.
            continue
        if not sfo.get("BOOTABLE"):
            continue
        if sfo.get("CATEGORY") not in PLAYABLE_CATEGORIES:
            continue

        eboot = os.path.join(directory, "USRDIR", "EBOOT.BIN")
        if not os.path.isfile(eboot):
            continue

        found.append(
            {
                # TITLE_ID from the SFO rather than the directory name: they
                # agree today, and the SFO is the one the game asserts.
                "title_id": sfo.get("TITLE_ID") or name,
                "title": sfo.get("TITLE") or name,
                "eboot": eboot,
                # Reported because they say what is in the folder, not as an
                # artwork source. Using them was tried and dropped: a package
                # ships ICON0 and PIC1 but nothing shaped like Steam's portrait
                # capsule, so games arrived with slots missing. SteamGridDB
                # answers for every slot, and the PARAM.SFO title is what makes
                # its search find the right game.
                "icon": _present(os.path.join(directory, "ICON0.PNG")),
                "background": _present(os.path.join(directory, "PIC1.PNG")),
                # Where the game's licence stands, for the games this plugin
                # installed and therefore knows the content id of. Empty for
                # anything installed another way, which is honest: without the
                # content id there is no way to look.
                "licence_state": licence_state(
                    content_id_for(sfo.get("TITLE_ID") or name)
                ),
            }
        )

    found.sort(key=lambda item: item["title"].lower())
    return found


def _present(path):
    return path if os.path.isfile(path) else ""


# RPCS3's compiled shaders and PPU modules for a title, keyed by the same id.
# Derived entirely from the game, so it goes when the game goes -- otherwise it
# is a few hundred megabytes belonging to something no longer installed.
CACHE_ROOT = ".cache/rpcs3/cache"


def game_dir(title_id, root=None):
    """The folder RPCS3 unpacked `title_id` into, or ''.

    The id arrives from the frontend and is about to be handed to `rmtree`, so
    it is matched against the shape of a real title id and the result is checked
    to be a direct child of the game folder. Two gates rather than one, because
    only one of them has to be wrong.
    """
    if not _TITLE_ID_RE.fullmatch(title_id or ""):
        return ""
    root = os.path.normpath(root or game_root())
    path = os.path.normpath(os.path.join(root, title_id))
    if os.path.dirname(path) != root:
        return ""
    return path


def game_of(rom_path, root=None):
    """The title id whose folder `rom_path` sits inside, or ''.

    Turns a launcher's recorded ROM path -- which is always
    `<game>/<TITLE_ID>/USRDIR/EBOOT.BIN` -- back into the title it belongs to,
    so a game in the library can be told apart from every other kind without
    the frontend knowing anything about RPCS3's layout.
    """
    root = os.path.normpath(root or game_root())
    path = os.path.normpath(rom_path or "")
    if not path.startswith(root + os.sep):
        return ""
    title_id = path[len(root) + 1:].split(os.sep)[0]
    return title_id if _TITLE_ID_RE.fullmatch(title_id) else ""


# Both consoles size a folder for the same sentence in the delete dialog.
directory_bytes = sysenv.directory_bytes


def game_info(rom_path, root=None):
    """{ok, title_id, title, bytes} for the unpacked game a ROM path is in.

    `ok` false means the path is not an installed PS3 game, which is the answer
    for every other system and needs no explaining.
    """
    title_id = game_of(rom_path, root)
    if not title_id:
        return {"ok": False}

    directory = game_dir(title_id, root)
    if not directory or not os.path.isdir(directory):
        return {"ok": False}

    sfo = read_sfo(os.path.join(directory, "PARAM.SFO"))
    return {
        "ok": True,
        "title_id": title_id,
        "title": sfo.get("TITLE") or title_id,
        "bytes": directory_bytes(directory),
    }


def delete_game(title_id, root=None):
    """Delete an unpacked game and the cache derived from it.

    Returns (freed bytes, error). This is the only thing in the plugin that
    deletes something playable, and it is offered for one reason: the .pkg it
    came from was consumed installing it, so "leave the user's own file alone"
    -- the rule everywhere else -- protects nothing here. What is left is a
    couple of hundred megabytes this plugin created, which nothing else can see
    or remove.

    Save data is not touched, and neither is the .rap licence. Both live
    elsewhere in dev_hdd0, both are the user's rather than ours, and a game can
    be installed again while progress in it cannot.
    """
    directory = game_dir(title_id, root)
    if not directory:
        return 0, "%r is not a title id." % title_id
    if not os.path.isdir(directory):
        return 0, "RPCS3 has no game installed under %s." % title_id

    freed = directory_bytes(directory)
    try:
        shutil.rmtree(directory)
    except OSError as error:
        return 0, "Could not delete %s: %s" % (directory, error)

    # Best effort: an orphaned cache is wasted space, not a failure, and the
    # game itself is already gone by here.
    cache = os.path.join(sysenv.user_home(), *CACHE_ROOT.split("/"), title_id)
    if os.path.isdir(cache):
        try:
            freed += directory_bytes(cache)
            shutil.rmtree(cache)
        except OSError as error:
            decky.logger.warning("Left the cache for %s behind: %s", title_id, error)

    decky.logger.info("Deleted PS3 game %s, freeing %d bytes", title_id, freed)
    return freed, ""


# ------------------------------------------------------------ waiting packages

# Where the short-named links live. Its own folder, not the transfer folder:
# these are links standing in for files the user sent, and mixing them in
# beside the originals would show every package twice.
STAGE_DIR = "packages"

_PKG_MAGIC = b"\x7fPKG"
# The content id -- "UP4049-NPUB30133_00-BRAID00000000001" -- sits at a fixed
# offset in every PS3 package header, which is where the title id comes from
# without unpacking anything.
_PKG_CONTENT_ID_AT = 0x30
_PKG_CONTENT_ID_LEN = 0x24
_TITLE_ID_RE = re.compile(r"([A-Z]{4}\d{5})")


def package_title_id(path):
    """The title id inside a .pkg, or '' if the file is not one."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(_PKG_CONTENT_ID_AT + _PKG_CONTENT_ID_LEN)
    except OSError:
        return ""
    if not header.startswith(_PKG_MAGIC):
        return ""
    content = header[_PKG_CONTENT_ID_AT:_PKG_CONTENT_ID_AT + _PKG_CONTENT_ID_LEN]
    match = _TITLE_ID_RE.search(content.split(b"\x00", 1)[0].decode("utf-8", "replace"))
    return match.group(1) if match else ""


# Where RPCS3 reads game licences from, and what they are called: the
# package's own content id with `.rap` on the end. Confirmed on a Deck --
# `UP4049-NPUB30133_00-BRAID00000000001.pkg` wanted
# `UP4049-NPUB30133_00-BRAID00000000001.rap`.
EXDATA_DIR = ".config/rpcs3/dev_hdd0/home/00000001/exdata"


def package_content_id(path):
    """The full content id inside a .pkg, or ''.

    Longer than the title id and worth having separately: the title id says
    which game, the content id says which *licence*, and only the second can
    find the .rap that decrypts it.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(_PKG_CONTENT_ID_AT + _PKG_CONTENT_ID_LEN)
    except OSError:
        return ""
    if not header.startswith(_PKG_MAGIC):
        return ""
    content = header[_PKG_CONTENT_ID_AT:_PKG_CONTENT_ID_AT + _PKG_CONTENT_ID_LEN]
    text = content.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
    return text if _TITLE_ID_RE.search(text) else ""


# Content ids remembered from the packages this plugin installed.
#
# An installed game does not record one: its PARAM.SFO carries TITLE_ID and no
# CONTENT_ID -- checked on a Deck against a real install -- and the .pkg that
# did carry it was deleted once the game came out of it. So the one moment the
# id is knowable is the moment of installing, and it is written down here
# rather than recovered later, because later it cannot be.
CONTENT_IDS_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "ps3_content_ids.json")


def _read_content_ids():
    try:
        with open(CONTENT_IDS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_content_id(title_id, content_id):
    """Record which content id a title was installed from."""
    if not title_id or not content_id:
        return
    known = _read_content_ids()
    if known.get(title_id) == content_id:
        return
    known[title_id] = content_id
    try:
        jsonstore.write_json(CONTENT_IDS_PATH, known, sort_keys=True)
    except OSError as error:
        # Only costs the licence warning for this game; the install is done.
        decky.logger.warning("Could not record the content id: %s", error)


def content_id_for(title_id):
    """The content id a title was installed from, or ''."""
    return _read_content_ids().get(title_id, "")


def licence_dirs(pkg_path="", firmware_dir=""):
    """Where a licence for a package might be waiting, nearest first.

    Beside the package before the transfer folder, because beside it is where
    people put it: a licence belongs to one game, and sending both together is
    the obvious thing to do -- it is what the Vita flow already expects. Only
    looking in the firmware folder made a correctly named .rap sitting next to
    its own game invisible.
    """
    found = []
    if pkg_path:
        beside = os.path.dirname(pkg_path)
        if beside:
            found.append(beside)
    if firmware_dir and firmware_dir not in found:
        found.append(firmware_dir)
    return found


def exdata_dir(create=False):
    path = os.path.join(sysenv.user_home(), *EXDATA_DIR.split("/"))
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as error:
            decky.logger.warning("Could not create %s: %s", path, error)
    return path


def find_licence(content_id, directories, pkg_path=""):
    """The .rap waiting for this content, wherever it is sitting, or ''.

    RPCS3 reads a licence only as `<CONTENT_ID>.rap` in exdata, and for a long
    time this demanded that name on the way in too. It does not have to: the
    file is moved into exdata by this plugin, so it can be renamed on the way,
    and the only real requirement is knowing *which* file is meant.

    So the rule is the one the Vita side already uses, for the same reason --
    "I sent both files" should be enough without also having to name them
    alike. Named after the content id, the package or the title id, in that
    order; failing all three, a single .rap sitting beside the package, which
    is unambiguous. Never a guess between two: picking the wrong one installs
    a licence that does not work and fails like a bad dump.
    """
    if not content_id:
        return ""

    names = [content_id]
    if pkg_path:
        names.append(os.path.splitext(os.path.basename(pkg_path))[0])
    title_id = _TITLE_ID_RE.search(content_id)
    if title_id:
        names.append(title_id.group(0))

    for directory in directories:
        if not directory:
            continue
        for base in names:
            for candidate in (base + ".rap", base + ".RAP"):
                path = os.path.join(directory, candidate)
                if os.path.isfile(path):
                    return path

    # Nothing named to match. Only the package's own folder is swept, and only
    # for a lone candidate: the firmware folder collects licences for every
    # game, so "the only .rap here" means nothing there.
    beside = os.path.dirname(pkg_path) if pkg_path else ""
    if not beside:
        return ""
    try:
        found = [
            os.path.join(beside, name)
            for name in sorted(os.listdir(beside))
            if name.lower().endswith(".rap")
        ]
    except OSError:
        return ""
    return found[0] if len(found) == 1 else ""


def install_licence(content_id, directories=(), pkg_path=""):
    """Move a licence into place for `content_id`. Returns its name, or ''.

    Renamed as it goes, because the name is the only binding RPCS3 has -- a
    .rap is sixteen bytes with nothing inside saying which game it unlocks --
    and the file the user sent may be called anything. See `find_licence`.
    """
    if not content_id:
        return ""
    name = content_id + ".rap"
    target = os.path.join(exdata_dir(create=True), name)
    if os.path.isfile(target):
        return name

    source = find_licence(content_id, directories, pkg_path)
    if not source:
        return ""

    try:
        shutil.move(source, target)
    except OSError as error:
        decky.logger.warning("Could not install %s: %s", source, error)
        return ""
    if os.path.basename(source) != name:
        decky.logger.info("Installed licence %s as %s", os.path.basename(source), name)
    else:
        decky.logger.info("Installed licence %s", name)
    return name


def licence_state(content_id, directories=(), pkg_path=""):
    """Where this content's .rap is: 'installed', 'waiting', '' or 'unknown'.

    'unknown' is not the same as missing and must not be shown as one: without
    a content id there is nowhere to look, which is the case for any game
    installed outside this plugin. Saying "no licence" there would be a
    guess, and a wrong one for every licence-free game.

    Reported rather than enforced. Not every package needs one -- anything
    sold licence-free boots without a .rap -- so a missing licence is worth
    saying and not worth refusing over. What it buys is that "Failed to
    decrypt content" stops being the first time anybody hears about it.

    Answers from the same search the install runs, so the panel cannot promise
    a licence the install then fails to find, or warn about one it goes on to
    put in place.
    """
    if not content_id:
        return "unknown"

    if os.path.isfile(os.path.join(exdata_dir(), content_id + ".rap")):
        return "installed"

    # A string here rather than a list is a caller passing one folder, which is
    # the common case and not worth a bracket at every call site.
    if isinstance(directories, str):
        directories = [directories]
    return "waiting" if find_licence(content_id, directories, pkg_path) else ""


def stage_dir(create=True):
    return sysenv.user_dir(STAGE_DIR, create=create)


def packages(source_dirs, installed=None):
    """[{name, path, size, title_id, installed}] for every .pkg waiting.

    More than one folder is searched because a package is a game that arrives
    looking like firmware: the picker for it sits in the ROM folder, but anybody
    who sent it from the PS3 firmware row put it beside PS3UPDAT.PUP instead, and
    a file that vanishes because it was sent to the wrong row is the exact
    friction this plugin exists to remove.

    `installed` is the set of title ids RPCS3 already has, so a package whose
    game is unpacked can say so rather than offering to install it again.
    """
    installed = installed_title_ids() if installed is None else installed

    found = []
    seen = set()
    for source_dir in source_dirs:
        try:
            names = sorted(os.listdir(source_dir))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".pkg"):
                continue
            path = os.path.join(source_dir, name)
            key = os.path.normcase(os.path.realpath(path))
            # The staging folder holds symlinks to these same files, so without
            # this the panel offers every package twice.
            if key in seen:
                continue
            seen.add(key)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            title_id = package_title_id(path)
            found.append(
                {
                    "name": name,
                    "path": path,
                    "size": size,
                    "title_id": title_id,
                    # False for a package whose header would not parse: with no
                    # title id there is nothing to compare, and offering to
                    # install it is the recoverable half of that guess.
                    "installed": bool(title_id) and title_id in installed,
                }
            )

    found.sort(key=lambda item: item["name"].lower())
    return found


def installed_title_ids(root=None):
    return {game["title_id"] for game in installed_games(root)}


def stage_packages(source_dir, target_dir=None):
    """Link every .pkg in `source_dir` under a short name. Returns the links.

    Symlinks rather than copies: a package is a couple of hundred megabytes and
    the point is only what RPCS3 prints in its dialog, not where the bytes are.

    Named after the title id in the package's own header, so the link says what
    the game is even though the file the user sent may not.
    """
    target_dir = target_dir or stage_dir()
    try:
        names = sorted(os.listdir(source_dir))
    except OSError:
        return []

    # Links from a previous run whose package has since gone. Cleared first, so
    # the folder never offers a package that is no longer there.
    try:
        for stale in os.listdir(target_dir):
            path = os.path.join(target_dir, stale)
            if os.path.islink(path) and not os.path.exists(os.readlink(path)):
                os.unlink(path)
    except OSError:
        pass

    staged = []
    for name in names:
        if not name.lower().endswith(".pkg"):
            continue
        source = os.path.join(source_dir, name)
        title_id = package_title_id(source)
        # A package whose header will not parse still gets a link, because the
        # long name is exactly the case this exists to fix.
        short = "%s.pkg" % (title_id or os.path.splitext(name)[0][:12])
        link = os.path.join(target_dir, short)

        try:
            if os.path.islink(link) or os.path.exists(link):
                if os.path.islink(link) and os.readlink(link) == source:
                    staged.append(link)
                    continue
                os.unlink(link)
            os.symlink(source, link)
        except OSError as error:
            decky.logger.warning("Could not stage package %s: %s", name, error)
            continue
        staged.append(link)

    return staged
