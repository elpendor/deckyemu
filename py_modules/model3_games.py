"""Naming an arcade ROM set, for the files whose name is a code.

Every other system this plugin handles arrives with a filename somebody meant to
be read: `Sonic The Hedgehog (USA).md` cleans up to a title. A ROM set does not.
It is named after the MAME set -- `daytona2`, `scud`, `bassdx`, `fvipers2` -- and
`display_title` can do nothing with that, so the game went into Steam as
"daytona2". Wrong on the shelf, and wrong twice over, because the title is also
what the artwork search is given: SteamGridDB has plenty of Daytona USA 2 and
nothing at all under `daytona2`.

The name exists, and the emulator that runs the set is holding it. Supermodel
ships `Games.xml`, which is how it knows what each chip dump in a set is for,
and every entry in it carries the full title:

    <game name="daytona2" ...>
      <identity>
        <title>Daytona USA 2 - Battle on the Edge</title>
        <region>Japan</region>
        <version>Revision A</version>

Read from the installed flatpak rather than copied in here, for the same reason
`args` points `-game-xml-file` at `/app/bin`: whatever build is installed is the
one that knows which sets it supports, and a list bundled with the plugin would
start going stale the moment Supermodel added a game.

`display_title` still does the rest. It turns "Daytona USA 2 - Battle on the
Edge" into "Daytona USA 2: Battle on the Edge" and drops a parenthesised region
tag exactly as it does for a console ROM, so a ROM set ends up named by the same
rules as everything else rather than by a second convention.
"""

import html
import os
import re

import decky

import emu_install

#: The flatpak the game list comes out of, and where inside it.
SUPERMODEL_APP = "com.supermodel3.Supermodel"
GAMES_XML = ("bin", "Config", "Games.xml")

#: A MAME set name: what a ROM set's filename is, and all it ever is.
_SET_NAME_RE = re.compile(r"^[a-z0-9]+$")

# Read with a regex rather than a parser, and not for speed: **the decky plugin
# sandbox has no `xml.etree`**. Importing it is not a slow path or a degraded
# feature, it is `ModuleNotFoundError` at import time and the whole backend fails
# to start -- which is exactly what happened. Nothing else in py_modules imports
# `xml`, and that was the warning.
#
# Safe here because the file is generated and its shape is fixed: one `<game
# name="...">` per set, one `<title>` inside the `<identity>` block that opens
# it. Anything this does not recognise simply does not appear in the map, and a
# set with no title keeps the name its file has.
_GAME_RE = re.compile(
    r'<game\b[^>]*\bname="([^"]+)"(.*?)(?=<game\b|\Z)', re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)

#: {set name: title}, with the file it was read from and that file's stamp.
#:
#: Cached because `probe_rom` asks once per file picked and the list is 150KB of
#: XML. Keyed on size and mtime rather than held forever, so a flatpak update
#: that adds games is picked up without a reload -- the same shape
#: `libretro_meta` uses for its indexes.
_cache = (None, None)


def games_xml_path():
    """Supermodel's game list inside the installed flatpak, or ""."""
    files = emu_install.flatpak_files_dir(SUPERMODEL_APP)
    if not files:
        return ""
    path = os.path.join(files, *GAMES_XML)
    return path if os.path.isfile(path) else ""


def _titles():
    """{set name: title} from the installed Supermodel, or {}."""
    global _cache
    path = games_xml_path()
    if not path:
        return {}
    try:
        info = os.stat(path)
    except OSError:
        return {}

    stamp = (path, info.st_size, info.st_mtime_ns)
    if _cache[0] == stamp:
        return _cache[1]

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError as error:
        # Not worth failing an add over. Without this the game keeps the name
        # its file has, which is what happened before this module existed.
        decky.logger.warning("Could not read %s: %s", path, error)
        return {}

    titles = {}
    for name, body in _GAME_RE.findall(text):
        found = _TITLE_RE.search(body)
        if not found:
            continue
        title = html.unescape(found.group(1)).strip()
        name = name.strip().lower()
        if name and title:
            titles[name] = title

    decky.logger.info("Read %d arcade ROM set names from %s", len(titles), path)
    _cache = (stamp, titles)
    return titles


def title_for(stem):
    """The full title of the ROM set called `stem`, or "".

    Empty for anything that is not one of Supermodel's sets, which includes
    every MAME and FinalBurn Neo set: those are ROM sets too and this list does
    not cover them, so they keep the name their file has. Better a name that is
    merely terse than a confident wrong one taken from a different system.
    """
    name = (stem or "").strip().lower()
    if not name or not _SET_NAME_RE.match(name):
        return ""
    return _titles().get(name, "")


def forget_cached_games():
    """Drop the parsed list. For tests, and after installing the emulator."""
    global _cache
    _cache = (None, None)
