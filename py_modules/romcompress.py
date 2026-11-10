"""Compressing library games into formats their emulators read directly.

Discs become CHD (CD systems, PS2, PSP) or RVZ (GameCube, Wii), 3DS games
Azahar's own .zcci, cartridges .zip. A game is offered only when the
emulator or core it is set up with lists the new extension.

Each game is compressed into a work folder beside it, checked, moved into
place, and only then do the originals go -- and only after the caller has
repointed the record and launcher (`finish`). Anything earlier that fails
leaves the originals as they were (`undo`).
"""

import hashlib
import os
import re
import shutil
import subprocess
import threading
import zipfile

import appenv
import romshelf
import sysenv

#: Kept beside the games so the final move is a rename, not a copy.
WORK_DIR = ".deckyemu-compress"

#: Free space kept back on top of what a game needs.
_MARGIN = 256 * 1024 * 1024

DOLPHIN = "org.DolphinEmu.dolphin-emu"

CD_SYSTEMS = frozenset((
    "Sony - PlayStation",
    "Sega - Saturn",
    "Sega - Mega-CD - Sega CD",
    "Sega - Dreamcast",
    "NEC - PC Engine CD - TurboGrafx-CD",
    "NEC - PC-FX",
    "SNK - Neo Geo CD",
    "The 3DO Company - 3DO",
    "Commodore - CD32",
    "Commodore - CDTV",
    "Philips - CD-i",
))

#: Cartridge systems whose libretro cores take a zipped ROM.
CARTRIDGE_SYSTEMS = frozenset((
    "Nintendo - Nintendo Entertainment System",
    "Nintendo - Super Nintendo Entertainment System",
    "Nintendo - Nintendo 64",
    "Nintendo - Game Boy",
    "Nintendo - Game Boy Color",
    "Nintendo - Game Boy Advance",
    "Nintendo - Nintendo DS",
    "Nintendo - Virtual Boy",
    "Nintendo - Pokemon Mini",
    "Sega - Master System - Mark III",
    "Sega - Mega Drive - Genesis",
    "Sega - 32X",
    "Sega - Game Gear",
    "Sega - SG-1000",
    "NEC - PC Engine - TurboGrafx 16",
    "NEC - PC Engine SuperGrafx",
    "Atari - 2600",
    "Atari - 5200",
    "Atari - 7800",
    "Atari - Jaguar",
    "Atari - Lynx",
    "SNK - Neo Geo Pocket",
    "SNK - Neo Geo Pocket Color",
    "Bandai - WonderSwan",
    "Bandai - WonderSwan Color",
    "Coleco - ColecoVision",
    "Mattel - Intellivision",
    "GCE - Vectrex",
    "Magnavox - Odyssey2",
    "Fairchild - Channel F",
    "Watara - Supervision",
))

_3DS = {"3ds": "zcci", "cci": "zcci", "cxi": "zcxi", "3dsx": "z3dsx"}
_ARCHIVES = ("zip", "7z", "rar", "gz", "xz", "zst")

#: method -> what it needs, for the panel's tool check.
TOOLS = {"createcd": "chdman", "createdvd": "chdman", "createdvd_psp": "chdman",
         "rvz": "dolphin", "z3ds": "azahar", "zip": ""}

#: "45.3% complete"; chdman also prints "final ratio = 23.6%", not progress.
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)% complete")
_BREAK = re.compile(r"[\r\n]+")

_cancel = threading.Event()


class Cancelled(Exception):
    """The run was cancelled."""


def cancel():
    _cancel.set()


def reset():
    _cancel.clear()


def method_for(system, extension):
    """(method, new extension) for one file of a system, or None."""
    ext = (extension or "").lower().lstrip(".")
    if system in CD_SYSTEMS and ext in ("cue", "gdi"):
        return "createcd", "chd"
    if system == "Sony - PlayStation 2":
        if ext == "cue":
            return "createcd", "chd"
        if ext == "iso":
            return "createdvd", "chd"
    if system == "Sony - PlayStation Portable" and ext == "iso":
        return "createdvd_psp", "chd"
    if system in ("Nintendo - GameCube", "Nintendo - Wii") and ext in ("iso", "gcm", "wbfs"):
        return "rvz", "rvz"
    if system == "Nintendo - Nintendo 3DS" and ext in _3DS:
        return "z3ds", _3DS[ext]
    if system in CARTRIDGE_SYSTEMS and ext and ext not in _ARCHIVES:
        return "zip", "zip"
    return None


def _inside(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) \
            == os.path.realpath(root)
    except ValueError:
        return False


def plan_game(entry, library):
    """What compressing one record would do: ("ready", game), ("skip", reason)
    or None when there is nothing to offer.

    `entry` carries the record's app_id, title, system, rom_path, plus the
    emulator's `extensions`, whether it is `libretro`, and `patched`.
    """
    rom = entry.get("rom_path") or ""
    if not rom or not library or not _inside(rom, library):
        return None
    if not os.path.isfile(rom):
        return None
    folder = os.path.dirname(rom)
    system = entry.get("system") or ""

    playlist = rom if rom.lower().endswith(".m3u") else ""
    if playlist:
        discs = romshelf.named_by(playlist)
        if not discs:
            return None
    else:
        discs = [os.path.basename(rom)]

    methods = {method_for(system, os.path.splitext(name)[1]) for name in discs}
    if len(methods) != 1 or None in methods:
        return None
    method, new_ext = methods.pop()

    reads = [ext.lower() for ext in entry.get("extensions") or []]
    if method == "zip":
        if not entry.get("libretro"):
            return None
    elif new_ext not in reads:
        return ("skip", "%s can't read .%s files." % (entry.get("emulator") or "Its emulator",
                                                       new_ext))
    if entry.get("patched") and method != "zip":
        return ("skip", "It has ROM patches, which can't be applied to a .%s." % new_ext)

    # Each disc and what its sheet names. Not same-stem neighbours: a patch
    # or a .sbi has to stay beside the compressed game.
    files = set()
    for name in discs:
        named = romshelf.named_by(os.path.join(folder, name))
        if named is None:
            return ("skip", "Some of its files are missing.")
        files.add(name)
        files.update(named)

    outputs = []
    for name in discs:
        out = os.path.splitext(name)[0] + "." + new_ext
        if os.path.exists(os.path.join(folder, out)):
            return ("skip", "%s is already there." % out)
        outputs.append(out)

    size = 0
    for name in files:
        try:
            size += os.path.getsize(os.path.join(folder, name))
        except OSError:
            return ("skip", "Some of its files are missing.")

    return ("ready", {
        "app_id": entry.get("app_id"),
        "title": entry.get("title") or os.path.basename(rom),
        "system": system,
        "folder": folder,
        "playlist": os.path.basename(playlist),
        "discs": list(discs),
        "outputs": outputs,
        "files": sorted(files),
        "bytes": size,
        "method": method,
        "format": new_ext,
    })


def plan(entries, library=None):
    """{"games": [...], "skipped": [{"title", "reason"}]} for the records given."""
    library = library or romshelf.library_dir()
    games, skipped = [], []
    for entry in entries:
        try:
            result = plan_game(entry, library)
        except OSError as error:
            result = ("skip", str(error))
        if not result:
            continue
        kind, value = result
        if kind == "ready":
            games.append(value)
        else:
            skipped.append({"title": entry.get("title") or "", "reason": value})
    games.sort(key=lambda game: (game["system"], game["title"].lower()))
    return {"games": games, "skipped": skipped}


# --- running the tools ------------------------------------------------------


def _run(argv, on_percent=None):
    """Run a tool to the end. Returns (ok, last lines). Raises Cancelled."""
    try:
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=sysenv.clean_env())
    except OSError as error:
        return False, str(error)

    tail = []
    stop = threading.Event()

    def watch():
        while not stop.wait(0.5):
            if _cancel.is_set() and process.poll() is None:
                process.terminate()
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    buffer = ""
    try:
        while True:
            chunk = process.stdout.read1(512) if hasattr(process.stdout, "read1") \
                else process.stdout.read(512)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            pieces = _BREAK.split(buffer)
            buffer = pieces.pop()
            for line in pieces:
                line = line.strip()
                if not line:
                    continue
                tail = (tail + [line])[-5:]
                found = _PERCENT.search(line)
                if found and on_percent:
                    on_percent(min(float(found.group(1)), 100.0) / 100.0)
        if buffer.strip():
            tail = (tail + [buffer.strip()])[-5:]
        process.wait()
    finally:
        stop.set()
    if _cancel.is_set():
        raise Cancelled()
    return process.returncode == 0, " ".join(tail) or "no output"


def _chdman_argv(chdman, method, source, out):
    if method == "createcd":
        return chdman + ["createcd", "-i", source, "-o", out]
    if method == "createdvd":
        return chdman + ["createdvd", "-c", "zstd", "-i", source, "-o", out]
    return chdman + ["createdvd", "--hunksize", "2048", "-i", source, "-o", out]


def _dolphin_tool(folder, *args):
    return ["flatpak", "run", "--filesystem=%s" % folder, "--command=dolphin-tool",
            DOLPHIN] + list(args)


def _digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            if _cancel.is_set():
                raise Cancelled()
            hasher.update(block)
    return hasher.hexdigest()


def _zip(source, out):
    name = os.path.basename(source)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(source, name)
    with zipfile.ZipFile(out) as archive:
        if archive.testzip() is not None or archive.getinfo(name).file_size \
                != os.path.getsize(source):
            return False, "The zip did not read back."
    return True, ""


def _one(game, tools, name, out_name, work, on_percent):
    """Compress one disc into `work`. Returns an error, or "".

    `tools` maps "chdman" and "azahar" to the argv that starts each.
    """
    folder = game["folder"]
    source = os.path.join(folder, name)
    out = os.path.join(work, out_name)
    method = game["method"]

    if method in ("createcd", "createdvd", "createdvd_psp"):
        ok, said = _run(_chdman_argv(tools["chdman"], method, source, out), on_percent)
        if not ok:
            return "chdman failed: %s" % said
        ok, said = _run(tools["chdman"] + ["verify", "-i", out])
        return "" if ok else "The CHD did not verify: %s" % said

    if method == "rvz":
        ok, said = _run(_dolphin_tool(folder, "convert", "-i", source, "-o", out,
                                      "-f", "rvz", "-b", "131072", "-c", "zstd", "-l", "5"),
                        on_percent)
        if not ok:
            return "dolphin-tool failed: %s" % said
        ok, said = _run(_dolphin_tool(folder, "header", "-i", out))
        return "" if ok else "The RVZ did not read back: %s" % said

    if method == "z3ds":
        ok, said = _run(tools["azahar"] + ["-c", source, "-o", work], on_percent)
        if not ok or not os.path.isfile(out):
            return "Azahar could not compress it: %s" % said
        back = os.path.join(work, "check")
        os.makedirs(back, exist_ok=True)
        ok, said = _run(tools["azahar"] + ["-x", out, "-o", back])
        # Unpacked under Azahar's own name for it (.3ds comes back .cci).
        found = os.listdir(back)
        restored = os.path.join(back, found[0]) if len(found) == 1 else ""
        try:
            if not ok or not restored or _digest(restored) != _digest(source):
                return "The compressed copy did not match the original."
        finally:
            shutil.rmtree(back, ignore_errors=True)
        return ""

    if method == "zip":
        ok, said = _zip(source, out)
        return "" if ok else said

    return "Unknown method %s." % method


def compress(game, tools, progress=None):
    """Compress one game and move the results beside it.

    Returns {"ok", "error", "rom_path", "created", "saved"}. On success the
    originals are still there; call `finish` once the record points at
    `rom_path`, or `undo` if it could not be repointed.
    """
    folder = game["folder"]
    work = os.path.join(folder, WORK_DIR)
    failed = {"ok": False, "error": "", "rom_path": "", "created": [], "saved": 0}

    largest = 0
    for name in game["files"]:
        largest = max(largest, os.path.getsize(os.path.join(folder, name)))
    # Azahar's check unpacks a second copy.
    need = largest * (2 if game["method"] == "z3ds" else 1) + _MARGIN
    if shutil.disk_usage(folder).free < need:
        failed["error"] = "Not enough free space to compress %s." % game["title"]
        return failed

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    count = len(game["discs"])
    try:
        for index, (name, out_name) in enumerate(zip(game["discs"], game["outputs"])):
            seen = [0.0]

            def on_percent(fraction, index=index, seen=seen):
                # Never backwards, whatever a tool prints.
                seen[0] = max(seen[0], fraction)
                if progress:
                    progress((index + seen[0]) / count)
            error = _one(game, tools, name, out_name, work, on_percent)
            if error:
                failed["error"] = error
                return failed

        created = []
        for out_name in game["outputs"]:
            target = os.path.join(folder, out_name)
            if os.path.exists(target):
                undo(game, created)
                failed["error"] = "%s appeared while compressing." % out_name
                return failed
            os.replace(os.path.join(work, out_name), target)
            created.append(target)

        rom_path = os.path.join(folder, game["outputs"][0])
        if game["playlist"]:
            rom_path = os.path.join(folder, game["playlist"])
            error = _rewrite_playlist(rom_path, game["discs"], game["outputs"])
            if not error and romshelf.named_by(rom_path) != game["outputs"]:
                error = "The playlist names its discs in a way this can't rewrite."
            if error:
                undo(game, created)
                failed["error"] = error
                return failed

        after = sum(os.path.getsize(path) for path in created)
        return {"ok": True, "error": "", "rom_path": rom_path, "created": created,
                "saved": max(game["bytes"] - after, 0)}
    except Cancelled:
        raise
    except OSError as error:
        failed["error"] = str(error)
        return failed
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _rewrite_playlist(path, old, new):
    """Swap each disc's name for its compressed one, keeping everything else."""
    names = dict(zip(old, new))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
        lines = [names.get(line.strip(), line) for line in lines]
        partial = path + ".deckyemu-tmp"
        with open(partial, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(partial, path)
    except OSError as error:
        return "Could not rewrite the playlist: %s" % error
    return ""


def undo(game, created):
    """Put a game back as it was before `compress`."""
    if game.get("playlist"):
        _rewrite_playlist(os.path.join(game["folder"], game["playlist"]),
                          game["outputs"], game["discs"])
    for path in created:
        try:
            os.remove(path)
        except OSError:
            pass


def finish(game):
    """Delete the originals once the record points at the compressed game."""
    for name in game["files"]:
        try:
            os.remove(os.path.join(game["folder"], name))
        except OSError as error:
            appenv.logger.warning("Could not remove %s: %s", name, error)
