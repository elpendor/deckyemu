"""Recognising a BIOS by what it is, not by what it is called.

Matching on the filename is what keeps the firmware panel free of pickers, and
it fails the moment a dump is named the way its owner named it: `PS1 US.bin`
matches nothing, and a SwanStation row asking for `scph5501.bin` never sees it.
libretro publishes the checksum of every BIOS its cores read, with the name each
core opens it under and the system it belongs to -- `dat/System.dat` in
libretro-database. With that, a file is identified by its MD5 and can land under
the name the core wants.

**The list is fetched, never shipped.** It is a table of checksums, but it is a
table derived from firmware, and this repository carries nothing derived from
firmware. It is fetched at start and cached for thirty days, and **matching never
touches the network**: `identify` reads only what is already here, so a Deck
with no connection falls back to names, exactly as before this existed.

Hashing is cheap to avoid: only a file whose size appears in the list is read,
which leaves out almost every ROM sitting beside a BIOS in the transfer folder.
"""

import hashlib
import json
import os
import re
import time

import decky

import net

URL = "https://raw.githubusercontent.com/libretro/libretro-database/master/dat/System.dat"
CACHE_PATH = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "bios_dat.json")
TTL_SECONDS = 30 * 24 * 60 * 60

#: The largest BIOS in the list is 16MB; nothing bigger is worth hashing.
MAX_HASHED_BYTES = 32 * 1024 * 1024

_SYSTEM = re.compile(r'^\s*comment\s+"([^"]+)"\s*$')
_ROM = re.compile(
    r'^\s*rom\s*\(\s*name\s+("[^"]+"|\S+)\s+size\s+(\d+).*?\bmd5\s+([0-9a-fA-F]{32})'
)

#: {md5: {"names": [basename, lowercase], "system": str}}, and the sizes seen.
_table: dict = {}
_sizes: set = set()
#: (path, size, mtime) -> md5, so a panel redrawn twice hashes nothing twice.
_hashed: dict = {}


def parse(text):
    """The checksum table out of a clrmamepro `System.dat`."""
    table = {}
    system = ""
    for line in text.splitlines():
        found = _SYSTEM.match(line)
        if found:
            system = found.group(1)
            continue
        found = _ROM.match(line)
        if not found:
            continue
        name = found.group(1).strip('"').replace("\\", "/").rsplit("/", 1)[-1].lower()
        row = table.setdefault(found.group(3).lower(), {"names": [], "system": system})
        if name not in row["names"]:
            row["names"].append(name)
        row["size"] = int(found.group(2))
    return table


def use(table):
    """Make `table` the one `identify` reads. Also how tests supply one."""
    global _table, _sizes
    _table = dict(table or {})
    _sizes = {row.get("size") for row in _table.values() if row.get("size")}
    _hashed.clear()


def _load_cache(allow_stale=False):
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not allow_stale and time.time() - payload.get("fetched_at", 0) > TTL_SECONDS:
        return None
    table = payload.get("table")
    return table if isinstance(table, dict) else None


def refresh():
    """Load the list, fetching it if the cache is missing or old. For startup.

    A failed fetch keeps whatever was cached, however old: a stale list still
    names every BIOS it named last month, and an empty one names none.
    """
    table = _load_cache()
    if table is None:
        payload, _ = net.get_bytes(URL, max_bytes=4 * 1024 * 1024)
        fetched = parse(payload.decode("utf-8", errors="replace")) if payload else {}
        if fetched:
            table = fetched
            try:
                os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
                with open(CACHE_PATH, "w", encoding="utf-8") as handle:
                    json.dump({"fetched_at": time.time(), "table": table}, handle)
            except OSError as error:
                decky.logger.warning("Could not cache the BIOS checksum list: %s", error)
        else:
            table = _load_cache(allow_stale=True)
    use(table or {})
    decky.logger.info("BIOS checksum list: %d known files", len(_table))


def loaded():
    """Whether there is a list to judge a file against at all."""
    return bool(_table)


def identify(path):
    """What the file at `path` is, as `{"names", "system"}`, or None.

    Never fetches. None for anything the list does not know, including every
    file when the list has not been loaded.
    """
    if not _table:
        return None
    try:
        info = os.stat(path)
    except OSError:
        return None
    if info.st_size not in _sizes or info.st_size > MAX_HASHED_BYTES:
        return None
    key = (path, info.st_size, info.st_mtime)
    digest = _hashed.get(key)
    if digest is None:
        hasher = hashlib.md5()
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
        except OSError:
            return None
        digest = _hashed[key] = hasher.hexdigest()
    return _table.get(digest)
