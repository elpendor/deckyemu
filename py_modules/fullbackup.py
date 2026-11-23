"""Backing up everything DeckyEmu keeps, and putting it back.

For resetting a Deck, or moving to another. Every destination gets the same
thing: one uncompressed zip, `DeckyEmu-backup-<date>.zip`, in numbered pieces
(`.zip.001`, ...) on a drive whose format cannot hold a file over 4 GB.

What goes is chosen per part (`PARTS`). Settings carry the game list and the
artwork of those games; the cloud sync records stay, since they describe this
Deck. Cloud sign-ins are their own part, because they are login tokens.
"""

import io
import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import zipfile
import zlib

import appenv

import savedata
import sysenv

PREFIX = "DeckyEmu-backup-"
MANIFEST = "backup.json"
FORMAT = 1
PARTS = ("roms", "saves", "emulators", "firmware", "settings", "signins")

#: Where SteamOS mounts a card or USB drive: `/run/media/<user>/<label>`, or
#: directly under it on older builds.
MEDIA = "/run/media"
#: What is mounted where; a constant so tests can give their own.
PROC_MOUNTS = "/proc/mounts"

#: Left free on the drive, on top of what the backup writes.
_MARGIN = 64 * 1024 * 1024
_PARTIAL = ".deckyemu-tmp"

#: The piece size on a FAT drive, under its 4 GB file limit.
PIECE = 4000 * 1024 ** 2

#: Formats a drive may be mounted as. SteamOS mounts only ext4 in Game Mode, so
#: the rest -- what most USB sticks come as -- are mounted here, through udisks.
MOUNTABLE = ("vfat", "exfat", "ntfs", "ntfs3", "ext4", "btrfs")

#: How much is written before forcing it onto the drive. Without it the system
#: takes a gigabyte into memory at once and the bar runs far ahead of the drive.
_FLUSH = 32 * 1024 * 1024

#: Set by `cancel`; the copy stops at its next block.
_cancel = threading.Event()


def stay_awake(why):
    """Keep the Deck from sleeping until `release` is given what this returns.

    A logind sleep inhibitor, held by a `systemd-inhibit` that waits forever.
    None where there is none to take; the work goes ahead regardless.
    """
    try:
        return subprocess.Popen(
            ["systemd-inhibit", "--what=sleep:idle", "--mode=block", "--who=DeckyEmu",
             "--why=%s" % why, "sleep", "infinity"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        appenv.logger.warning("Could not keep the Deck awake: %s", error)
        return None


def release(held):
    if held is not None:
        held.terminate()
        try:
            held.wait(timeout=5)
        except subprocess.TimeoutExpired:
            held.kill()


class _WriteFailed(OSError):
    """Writing the backup failed, as opposed to reading one file for it."""


class Cancelled(Exception):
    """The backup was cancelled."""


def cancel():
    _cancel.set()


#: Drives this module mounted, so it unmounts those and only those.
_mounted_here: dict = {}

#: Settings files that describe this Deck rather than the install.
_SETTINGS_SKIP = ("cloudstate", "rclone.conf", "destructive.log")


def _mount_table():
    """{mount point: (device, format)} from /proc/mounts."""
    table = {}
    try:
        with open(PROC_MOUNTS, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 3:
                    table[parts[1].replace("\\040", " ")] = (parts[0], parts[2])
    except OSError:
        pass
    return table


def mount_removable():
    """Mount removable drives SteamOS left alone. Returns the paths mounted."""
    try:
        listed = json.loads(subprocess.run(
            ["lsblk", "-J", "-o", "PATH,FSTYPE,MOUNTPOINT,RM,TRAN,TYPE"],
            capture_output=True, text=True, timeout=10).stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    done = []
    # lsblk nests partitions under their disk on some systems and lists them
    # flat on others (SteamOS): walk both, judging a partition by its disk.
    found = []

    def walk(entries, removable):
        for entry in entries or []:
            here = removable or bool(entry.get("rm")) or entry.get("tran") == "usb"
            found.append((entry, here))
            walk(entry.get("children"), here)

    walk(listed.get("blockdevices"), False)
    usb_disks = {entry["path"] for entry, here in found
                 if here and entry.get("type") == "disk" and entry.get("path")}
    for part, here in found:
        disk_path = (part.get("path") or "").rstrip("0123456789")
        if not (here or disk_path in usb_disks):
            continue
        if part.get("fstype") not in MOUNTABLE or part.get("mountpoint"):
            continue
        try:
            ran = subprocess.run(
                ["udisksctl", "mount", "-b", part["path"], "--no-user-interaction"],
                capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:
            appenv.logger.warning("Could not mount %s: %s", part.get("path"), error)
            continue
        where = ran.stdout.strip().rsplit(" at ", 1)[-1].rstrip(".")
        if ran.returncode == 0 and where:
            _mounted_here[where] = part["path"]
            done.append(where)
            appenv.logger.info("Mounted %s at %s for a backup", part["path"], where)
        else:
            appenv.logger.warning("Could not mount %s: %s", part.get("path"),
                                  (ran.stderr or ran.stdout).strip())
    return done


def _sync_folder(folder):
    """Flush a folder's entries to disk, where the system allows it."""
    try:
        handle = os.open(folder or ".", os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def eject(drive):
    """Unmount a USB drive, or one this module mounted, so it is safe to pull.
    (ejected, error): never claims a drive is safe that is still mounted."""
    if hasattr(os, "sync"):
        os.sync()
    device = _mounted_here.get(drive)
    if not device:
        # A USB drive mounted by someone else; an SD card stays, it may
        # hold Steam games.
        found = _mount_table().get(drive, ("", ""))[0]
        if not found.startswith("/dev/sd"):
            return False, ""
        device = found
    try:
        ran = subprocess.run(["udisksctl", "unmount", "-b", device, "--no-user-interaction"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if ran.returncode != 0:
        return False, (ran.stderr or ran.stdout).strip()
    _mounted_here.pop(drive, None)
    return True, ""


def drives():
    """Removable drives mounted under /run/media, with their free space."""
    table = _mount_table()
    found = []
    roots = [MEDIA]
    try:
        roots += [os.path.join(MEDIA, name) for name in os.listdir(MEDIA)]
    except OSError:
        return []
    seen = set()
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in sorted(names):
            path = os.path.join(root, name)
            if path in seen or not _mounted(path):
                continue
            seen.add(path)
            try:
                usage = shutil.disk_usage(path)
            except OSError:
                continue
            found.append({"path": path, "label": name, "free": usage.free,
                          "total": usage.total,
                          "fstype": table.get(path, ("", ""))[1],
                          "backups": backups_on(path),
                          "backup_bytes": _backup_bytes(path)})
    return found


def _backup_files(drive, name):
    """The files of one backup on a drive: the zip, or its pieces."""
    stem = name[:-4] if name.endswith(".zip.001") else name
    try:
        names = os.listdir(drive)
    except OSError:
        return []
    return [os.path.join(drive, other) for other in names
            if other == stem or other.startswith(stem + ".")]


def _backup_bytes(drive):
    """Space the backups already on a drive take."""
    total = 0
    for name in backups_on(drive):
        for path in _backup_files(drive, name):
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
    return total


def _remove_backups(drive, names):
    for name in names:
        for path in _backup_files(drive, name):
            try:
                os.remove(path)
            except OSError:
                pass


#: Where the kernel lists block devices, for the drives nothing has mounted.
SYS_BLOCK = "/sys/block"


def unreadable():
    """Removable drives that are attached but not mounted, by name and size.

    Usually unformatted or encrypted (a card a phone adopted), so SteamOS has
    nothing to mount. Named so the panel can say that instead of "no drive".
    """
    try:
        with open(PROC_MOUNTS, encoding="utf-8") as handle:
            mounted = handle.read()
    except OSError:
        mounted = ""
    found = []
    try:
        names = sorted(os.listdir(SYS_BLOCK))
    except OSError:
        return []
    for name in names:
        base = os.path.join(SYS_BLOCK, name)
        try:
            with open(os.path.join(base, "removable"), encoding="utf-8") as handle:
                removable = handle.read().strip() == "1"
            with open(os.path.join(base, "size"), encoding="utf-8") as handle:
                size = int(handle.read().strip() or 0) * 512
        except (OSError, ValueError):
            continue
        if not (removable or "/usb" in os.path.realpath(base)) or not size:
            continue
        if "/dev/%s" % name in mounted:
            continue
        found.append({"name": name, "size": size})
    return found


def _mounted(path):
    return os.path.ismount(path)


def _tree(root, prefix):
    """(absolute, name in the backup) for every file under `root`."""
    listed = []
    for current, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            listed.append((path, "%s/%s" % (prefix, relative)))
    return listed


def _art():
    """Our games' Steam artwork: every grid image named for one of their ids."""
    library = _read_json(os.path.join(appenv.SETTINGS_DIR, "library.json"))
    ids = {str(key) for key in library}
    listed = []
    userdata = os.path.join(sysenv.user_home(), ".steam", "steam", "userdata")
    try:
        users = os.listdir(userdata)
    except OSError:
        return []
    for user in users:
        grid = os.path.join(userdata, user, "config", "grid")
        try:
            names = os.listdir(grid)
        except OSError:
            continue
        for name in sorted(names):
            stem = name.split(".")[0]
            for suffix in ("p", "_hero", "_logo"):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            if stem in ids:
                listed.append((os.path.join(grid, name), "art/%s" % name))
    return listed


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def plan(include):
    """{part: [(absolute, name in the backup)]} for the parts asked for."""
    planned = {}
    if "roms" in include:
        # A game's patches and its updates and DLC travel with its ROM.
        planned["roms"] = [entry for top in ("roms", "patches", "updates-dlc")
                           for entry in _tree(sysenv.user_dir(top, create=False), top)]
    if "firmware" in include:
        planned["firmware"] = _tree(sysenv.user_dir("firmware", create=False), "firmware")
    if "emulators" in include:
        planned["emulators"] = _tree(sysenv.user_dir("emulators", create=False), "emulators")
    if "saves" in include:
        files = []
        for source in savedata._all_sources():
            skip = savedata._SKIP_TOP if source["whole"] else ()
            only = source.get("only") or {}
            for (label, path), (segment, _) in zip(source["roots"],
                                                   savedata.roots_of(source)):
                for absolute, relative in savedata._walk(
                        path, skip, source.get("except", ()), only.get(label, ())):
                    files.append((absolute, "saves/%s/%s/%s" % (
                        source["id"], segment, relative)))
        planned["saves"] = files
    if "settings" in include:
        files = []
        try:
            names = sorted(os.listdir(appenv.SETTINGS_DIR))
        except OSError:
            names = []
        for name in names:
            path = os.path.join(appenv.SETTINGS_DIR, name)
            if name in _SETTINGS_SKIP or not os.path.isfile(path):
                continue
            files.append((path, "settings/%s" % name))
        # Imported definitions, so the saves of those emulators have a place.
        imported = os.path.join(appenv.SETTINGS_DIR, "emulators.d")
        planned["settings"] = (files + _tree(imported, "settings/emulators.d") + _art()
                               + _tree(sysenv.user_dir("icons", create=False), "icons"))
    if "signins" in include:
        conf = os.path.join(appenv.SETTINGS_DIR, "rclone.conf")
        planned["signins"] = [(conf, "signins/rclone.conf")] if os.path.isfile(conf) else []
    return planned


def sizes():
    """{part: {files, bytes}} for the checklist, measured now."""
    measured = {}
    for part, files in plan(PARTS).items():
        total = 0
        for path, _ in files:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        measured[part] = {"files": len(files), "bytes": total}
    return measured


def backups_on(drive):
    """The backups on a drive, newest first, by the name of their first file."""
    try:
        names = os.listdir(drive)
    except OSError:
        return []
    return sorted((name for name in names if name.startswith(PREFIX)
                   and (name.endswith(".zip") or name.endswith(".zip.001"))), reverse=True)


class _Pieces(io.RawIOBase):
    """Where a zip is written: one file, or numbered pieces of `size` bytes.

    Each file is written under a temporary name and renamed once the zip is
    complete, so a backup cut short leaves nothing that looks finished.
    """

    def __init__(self, base, size, moved):
        super().__init__()
        self.base, self.size, self.moved = base, size, moved
        self.names, self.pos, self.unsynced = [], 0, 0
        self.handle = None
        self._next()

    def _next(self):
        if self.handle:
            self._sync()
            self.handle.close()
        name = "%s.%03d" % (self.base, len(self.names) + 1) if self.size else self.base
        self.names.append(name)
        self.handle = open(name + _PARTIAL, "wb")
        self.used = 0

    def _sync(self):
        self.handle.flush()
        getattr(os, "fdatasync", os.fsync)(self.handle.fileno())
        self.unsynced = 0

    def writable(self):
        return True

    def tell(self):
        return self.pos

    def write(self, data):
        if _cancel.is_set():
            raise Cancelled()
        try:
            self._write(memoryview(data))
        except OSError as error:
            raise _WriteFailed(error.errno, str(error)) from error
        self.pos += len(data)
        if self.moved:
            self.moved(len(data))
        return len(data)

    def _write(self, view):
        while view:
            room = (self.size - self.used) if self.size else len(view)
            if room <= 0:
                self._next()
                continue
            chunk = view[:room]
            self.handle.write(chunk)
            self.used += len(chunk)
            self.unsynced += len(chunk)
            view = view[len(chunk):]
            if self.unsynced >= _FLUSH:
                self._sync()

    def finish(self):
        self._sync()
        self.handle.close()
        for name in self.names:
            os.replace(name + _PARTIAL, name)
        # The renames and sizes live in the folder: flush it too, or a drive
        # pulled now keeps the data under empty, zero-length names.
        _sync_folder(os.path.dirname(self.names[0]) if self.names else "")
        if hasattr(os, "sync"):
            os.sync()

    def abandon(self):
        if self.handle and not self.handle.closed:
            self.handle.close()
        for name in self.names:
            try:
                os.remove(name + _PARTIAL)
            except OSError:
                pass


def _stored(bundle, absolute, name):
    """Add one file uncompressed, its time also stored in UTC (see savedata)."""
    info = zipfile.ZipInfo.from_file(absolute, name)
    info.compress_type = zipfile.ZIP_STORED
    info.extra = struct.pack("<HHBl", 0x5455, 5, 1, int(os.stat(absolute).st_mtime))
    with open(absolute, "rb") as reading, \
            bundle.open(info, "w", force_zip64=info.file_size > 2 ** 31) as writing:
        shutil.copyfileobj(reading, writing, _FLUSH)


def _drive_ok(drive):
    return any(one["path"] == drive for one in drives())


def write(destination, include, progress=None, split=False):
    """Write a backup zip of the parts asked for, at `destination`.

    `split` writes it as pieces of `PIECE` bytes. Returns what happened;
    `progress` is called with (text, percent).
    """
    include = [part for part in include if part in PARTS]
    if not include:
        return {"ok": False, "error": "Nothing was chosen."}
    entries, total = _entries(include)
    folder = os.path.dirname(destination)
    free = shutil.disk_usage(folder).free
    if total + _MARGIN > free:
        return {"ok": False, "error": "Not enough room: needs %.1f GB, %.1f GB free."
                % (total / 1e9, free / 1e9)}

    out = _Pieces(destination, PIECE if split else 0, _mover(total, progress))
    result = _fill(out, include, entries, total, progress)
    if result.get("ok"):
        appenv.logger.info("Backup written to %s: %d file(s), %d bytes, %d skipped",
                           destination, result["files"], total, result["skipped"])
        result["names"] = [os.path.basename(n) for n in out.names]
    return result


def _entries(include):
    """(files to carry, their total size) for the parts asked for."""
    entries = [entry for files in plan(include).values() for entry in files]
    total = 0
    for path, _ in entries:
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return entries, total


def _mover(total, progress):
    """A callback counting bytes written, reporting speed and time left."""
    done = [0]
    started = time.monotonic()
    said = [0.0]

    def moved(count):
        done[0] += count
        now = time.monotonic()
        if not progress or now - said[0] < 1:
            return
        said[0] = now
        rate = done[0] / max(now - started, 0.001)
        left = (total - done[0]) / max(rate, 1)
        progress("%.1f MB/s · %s left" % (
            rate / 1e6, "about %d min" % (left // 60 + 1) if left >= 60 else "under a minute"),
            min(99, done[0] * 100 // max(total, 1)))

    return moved


def _fill(out, include, entries, total, progress):
    """Write the zip into `out` (_Pieces or _Sink). Returns what happened."""
    _cancel.clear()
    skipped = 0
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED, allowZip64=True) as bundle:
            bundle.writestr(MANIFEST, json.dumps({
                "format": FORMAT, "created": int(time.time()), "deck": socket.gethostname(),
                "version": appenv.VERSION, "parts": sorted(include),
                "files": len(entries), "bytes": total}, indent=2))
            for path, name in entries:
                try:
                    _stored(bundle, path, name)
                except _WriteFailed:
                    raise
                except OSError as error:
                    appenv.logger.warning("Backup skipped %s: %s", path, error)
                    skipped += 1
        out.finish()
    except Cancelled:
        out.abandon()
        return {"ok": False, "cancelled": True, "error": "Cancelled."}
    except OSError as error:
        out.abandon()
        return {"ok": False, "error": "The backup could not be written: %s" % error}
    if progress:
        progress("Done", 100)
    return {"ok": True, "files": len(entries) - skipped, "bytes": total, "skipped": skipped}


def backup(drive, include, progress=None, replace_first=False):
    """Back up to a drive, replacing the backup already there once this one
    is complete, or before it starts with `replace_first` (no room for two)."""
    if not _drive_ok(drive):
        return {"ok": False, "error": "That drive is not connected."}
    older = backups_on(drive)
    stamp = time.strftime(PREFIX + "%Y%m%d-%H%M%S")
    name, nth = stamp + ".zip", 2
    while any(old.startswith(name) for old in older):
        name, nth = "%s-%d.zip" % (stamp, nth), nth + 1
    if replace_first:
        _remove_backups(drive, older)
        older = []
    split = _mount_table().get(drive, ("", ""))[1] == "vfat"
    result = write(os.path.join(drive, name), include, progress, split)
    if result.get("ok"):
        _remove_backups(drive, older)
    return result


# ---------------------------------------------------------------- restoring


class _Joined(io.RawIOBase):
    """A backup's pieces read as one file, so zipfile can open them."""

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.sizes = [os.path.getsize(path) for path in paths]
        self.total = sum(self.sizes)
        self.pos = 0
        self.handles: dict = {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.total + offset}[whence]
        return self.pos

    def readinto(self, buffer):
        start, filled = 0, 0
        for index, size in enumerate(self.sizes):
            if self.pos < start + size and filled < len(buffer):
                handle = self.handles.get(index) or open(self.paths[index], "rb")
                self.handles[index] = handle
                handle.seek(self.pos - start)
                chunk = handle.read(min(len(buffer) - filled, start + size - self.pos))
                buffer[filled:filled + len(chunk)] = chunk
                filled += len(chunk)
                self.pos += len(chunk)
            start += size
        return filled

    def close(self):
        for handle in self.handles.values():
            handle.close()
        super().close()


def open_backup(path):
    """A backup as a ZipFile, from a single zip or the first of its pieces."""
    if path.endswith(".001"):
        stem = os.path.basename(path)[:-4]
        folder = os.path.dirname(path)
        pieces = sorted(name for name in os.listdir(folder)
                        if name.startswith(stem + ".") and name[len(stem) + 1:].isdigit())
        return zipfile.ZipFile(_Joined([os.path.join(folder, name) for name in pieces]))
    return zipfile.ZipFile(path)


def _manifest(bundle):
    try:
        manifest = json.loads(bundle.read(MANIFEST))
    except (KeyError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) and manifest.get("format") == FORMAT else None


def describe(path):
    """What a backup holds: its manifest, or an error."""
    try:
        with open_backup(path) as bundle:
            manifest = _manifest(bundle)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return {"ok": False, "error": "This backup can't be read: %s" % error}
    if not manifest:
        return {"ok": False, "error": "This isn't a DeckyEmu backup this version can read."}
    return {"ok": True, **manifest}


def _mtime(info):
    """A member's time: the UTC field when present, else the zip's own."""
    extra = info.extra
    while len(extra) >= 4:
        kind, size = struct.unpack("<HH", extra[:4])
        if kind == 0x5455 and size >= 5 and extra[4] & 1:
            return struct.unpack("<l", extra[5:9])[0]
        extra = extra[4 + size:]
    return time.mktime(info.date_time + (0, 0, -1))


#: Folders under `~/deckyemu` a backup carries, as they are.
_USER_FOLDERS = ("roms", "patches", "updates-dlc", "firmware", "emulators", "icons")

#: Where restored artwork waits for the games to be added back to Steam.
ART_DIR = os.path.join(appenv.DATA_DIR, "restored-art")


def _destinations(bundle, saves):
    """([(member, local path)], [members with no place here]).

    Everything but saves, or only saves: those are placed once the restored
    settings have brought back the emulators they belong to.
    """
    landing = {}
    under: dict = {}
    members = [info for info in bundle.infolist()
               if not info.is_dir() and info.filename != MANIFEST
               and info.filename.startswith("saves/") == saves]
    if saves:
        for source in savedata._all_sources(True, anywhere=True):
            for segment, root in savedata.roots_of(source):
                landing[(source["id"], segment)] = (source, root)
        for info in members:
            parts = info.filename.split("/")
            if len(parts) >= 4:
                under.setdefault((parts[1], parts[2]), []).append("/".join(parts[3:]))

    placed = []
    nowhere = []
    for info in members:
        top, _, rest = info.filename.partition("/")
        target = ""
        if top in _USER_FOLDERS:
            target = savedata._safe_member(sysenv.user_dir(top, create=False), rest)
        elif top == "settings" and rest.startswith("emulators.d/"):
            target = savedata._safe_member(appenv.SETTINGS_DIR, rest)
        elif top == "settings" and "/" not in rest and rest not in _SETTINGS_SKIP:
            target = os.path.join(appenv.SETTINGS_DIR, rest)
        elif top == "signins" and rest == "rclone.conf":
            target = os.path.join(appenv.SETTINGS_DIR, "rclone.conf")
        elif top == "art" and rest and "/" not in rest:
            target = os.path.join(ART_DIR, rest)
        elif top == "saves":
            emulator, _, more = rest.partition("/")
            segment, _, inside = more.partition("/")
            hit = landing.get((emulator, segment))
            if hit and inside:
                source, root = hit
                one = savedata.file_root(root, source) or under[(emulator, segment)] == [segment]
                target = savedata._safe_member(os.path.dirname(root) if one else root, inside)
        if target:
            placed.append((info, target))
        else:
            appenv.logger.warning("Restore has no place for %s", info.filename)
            nowhere.append(info.filename)
    return placed, nowhere


def _differs(info, target):
    """Whether the file here holds something other than this member."""
    try:
        if os.path.getsize(target) != info.file_size:
            return True
        crc = 0
        with open(target, "rb") as reading:
            for block in iter(lambda: reading.read(_FLUSH), b""):
                crc = zlib.crc32(block, crc)
        return crc != info.CRC
    except OSError:
        return False


def restore(path, progress=None, keep=True):
    """Put everything in a backup back where it belongs. Returns what happened.

    With `keep`, saves here that it would overwrite with something different
    go to the earlier copies first, as a save replace's do.
    """
    try:
        bundle = open_backup(path)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return {"ok": False, "error": "This backup can't be read: %s" % error}
    with bundle:
        if not _manifest(bundle):
            return {"ok": False, "error": "This isn't a DeckyEmu backup this version can read."}
        total = sum(info.file_size for info in bundle.infolist() if not info.is_dir())
        free = shutil.disk_usage(sysenv.user_home()).free
        if total + _MARGIN > free:
            return {"ok": False, "error": "Not enough room: needs %.1f GB, %.1f GB free."
                    % (total / 1e9, free / 1e9)}
        shutil.rmtree(ART_DIR, ignore_errors=True)

        done = [0]
        said = [0.0]
        _cancel.clear()
        counts = {"written": 0, "failed": 0}

        def put(placed):
            for info, target in placed:
                if _cancel.is_set():
                    raise Cancelled()
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    partial = target + _PARTIAL
                    with bundle.open(info) as reading, open(partial, "wb") as writing:
                        while True:
                            block = reading.read(_FLUSH)
                            if not block:
                                break
                            writing.write(block)
                            done[0] += len(block)
                            if progress and time.monotonic() - said[0] >= 1:
                                said[0] = time.monotonic()
                                progress("Restoring", min(99, done[0] * 100 // max(total, 1)))
                    mode = (info.external_attr >> 16) & 0o777
                    if mode:
                        os.chmod(partial, mode)
                    when = _mtime(info)
                    os.utime(partial, (when, when))
                    os.replace(partial, target)
                    counts["written"] += 1
                except OSError as error:
                    appenv.logger.warning("Could not restore %s: %s", target, error)
                    counts["failed"] += 1

        kept = ""
        try:
            placed, nowhere = _destinations(bundle, saves=False)
            put(placed)
            if any(info.filename.startswith("settings/emulators.d/") for info, _ in placed):
                import emulator_catalog

                emulator_catalog.reload_imported()
            placed, more = _destinations(bundle, saves=True)
            nowhere += more
            overwritten = [(target, info.filename) for info, target in placed
                           if os.path.isfile(target) and _differs(info, target)]
            if overwritten and keep:
                kept, failed = savedata._keep_aside(overwritten)
                if failed:
                    return {"ok": False, "written": counts["written"],
                            "error": "The saves here could not be kept first, so none "
                                     "were replaced. %s" % failed}
            put(placed)
        except Cancelled:
            return {"ok": False, "cancelled": True, "written": counts["written"],
                    "error": "Cancelled. What was restored so far stays."}
    if progress:
        progress("Done", 100)
    written, failed = counts["written"], counts["failed"]
    appenv.logger.info("Restored %d file(s) from %s, %d failed, %d with no place%s",
                       written, path, failed, len(nowhere),
                       ", replaced saves kept in %s" % kept if kept else "")
    notes = []
    if nowhere:
        notes.append("%d file(s) had no place on this Deck, so the backup was kept."
                     % len(nowhere))
    if kept:
        notes.append("The saves it replaced are under Restore saves, in This Deck "
                     "- earlier copies.")
    return {"ok": failed == 0, "written": written, "failed": failed,
            "nowhere": len(nowhere), "kept": kept,
            "error": ("%d file(s) could not be restored." % failed if failed
                      else " ".join(notes))}


def still_to_do():
    """What a restore leaves: emulators to reinstall, and whether RetroArch is
    needed. Read from the restored settings."""
    import emu_flatpak
    import emu_install
    import emulator_catalog
    import emulators
    import ra_detect
    import store

    missing = []
    for emulator in emulators.list_emulators():
        entry = emulator_catalog.find(emulator.get("id") or "")
        if not entry or entry["source"]["kind"] == "byo":
            continue
        if entry["source"]["kind"] == "flatpak":
            here = emu_flatpak.flatpak_installed(entry["source"]["id"])
        else:
            here = bool(emu_install.installed_appimage(entry["id"]))
        if not here:
            missing.append({"id": entry["id"], "name": entry["name"]})
    library = store.get_library()
    libretro = any(not emulators.is_emulator_id(entry.get("core_id") or "")
                   for entry in library.values() if entry.get("core_id"))
    return {"emulators": missing,
            "retroarch": libretro and not ra_detect.detect(),
            "games": sorted(int(key) for key in library if str(key).isdigit())}


#: Steam's grid file suffixes, by the artwork slot each fills.
_ART_SLOTS = {"p": "capsule", "": "header", "_hero": "hero", "_logo": "logo"}


def restored_art(app_id):
    """{slot: {data, kind}} for one game's artwork kept by a restore."""
    import base64

    found = {}
    try:
        names = os.listdir(ART_DIR)
    except OSError:
        return found
    for name in names:
        stem, _, ext = name.partition(".")
        for suffix, slot in _ART_SLOTS.items():
            if stem == "%s%s" % (app_id, suffix) and ext in ("png", "jpg", "jpeg"):
                kind = "jpg" if ext != "png" else "png"
                with open(os.path.join(ART_DIR, name), "rb") as handle:
                    data = base64.b64encode(handle.read()).decode()
                found[slot] = {"data": "data:image/%s;base64,%s" % (
                    "jpeg" if kind == "jpg" else "png", data), "kind": kind}
    return found


def games_to_readd():
    """Each restored game as Steam needs it to be added back."""
    import emulators
    import store

    games = []
    for key, entry in store.get_library().items():
        launcher = entry.get("launcher_path") or ""
        if not str(key).isdigit() or not launcher:
            continue
        found = emulators.find(emulators.emulator_id(entry.get("core_id") or "")) \
            if emulators.is_emulator_id(entry.get("core_id") or "") else None
        games.append({
            "app_id": int(key), "title": entry.get("title") or "Game",
            "exe": launcher, "start_dir": os.path.dirname(launcher),
            "layout": (found or {}).get("layout", ""),
            "collection": entry.get("collection") or "",
        })
    return games


def cores_to_install():
    """libretro cores the restored games use that are not on this Deck."""
    import emulators
    import store

    wanted = []
    for entry in store.get_library().values():
        core_id = entry.get("core_id") or ""
        if (core_id and not emulators.is_emulator_id(core_id) and core_id not in wanted
                and not os.path.isfile(entry.get("core_path") or "")):
            wanted.append(core_id)
    return wanted


def rekey_game(old, new):
    """Move a game's record and per-game files from one app id to another,
    after it was added back to Steam under a new one. (ok, error)."""
    import store

    old, new = str(int(old)), str(int(new))
    if not store.rekey_game(old, new):
        return False, "No game with that id."
    for top in ("patches", "updates-dlc"):
        here = os.path.join(sysenv.user_dir(top, create=False), old)
        if os.path.isdir(here):
            os.replace(here, os.path.join(os.path.dirname(here), new))
    icons = sysenv.user_dir("icons", create=False)
    try:
        for name in os.listdir(icons):
            if name.split(".")[0] == old:
                os.replace(os.path.join(icons, name),
                           os.path.join(icons, new + name[len(old):]))
    except OSError:
        pass
    for name in list(os.listdir(ART_DIR)) if os.path.isdir(ART_DIR) else []:
        for suffix in _ART_SLOTS:
            if name.startswith(old + suffix + "."):
                os.replace(os.path.join(ART_DIR, name),
                           os.path.join(ART_DIR, new + name[len(old):]))
    return True, ""


def forget_restored_art():
    """Drop the artwork a restore kept, once the games are back in Steam."""
    shutil.rmtree(ART_DIR, ignore_errors=True)


# ------------------------------------------------------- over the network


class _Sink(io.RawIOBase):
    """A zip written straight into `send` (a download), counting as it goes."""

    def __init__(self, send, moved):
        super().__init__()
        self.send, self.moved, self.pos = send, moved, 0

    def writable(self):
        return True

    def tell(self):
        return self.pos

    def write(self, data):
        if _cancel.is_set():
            raise Cancelled()
        try:
            self.send(bytes(data))
        except OSError as error:
            raise _WriteFailed(error.errno, str(error)) from error
        self.pos += len(data)
        self.moved(len(data))
        return len(data)

    def finish(self):
        pass

    def abandon(self):
        pass


def default_name():
    return time.strftime(PREFIX + "%Y%m%d-%H%M%S.zip")


def measure(include):
    """(files, bytes) a backup of these parts would carry."""
    entries, total = _entries([part for part in include if part in PARTS])
    return len(entries), total


def stream(send, include, progress=None):
    """Write a backup as one zip into `send`, nothing staged on the Deck.
    A download cut off raises OSError from `send`; reported as an error."""
    include = [part for part in include if part in PARTS]
    if not include:
        return {"ok": False, "error": "Nothing was chosen."}
    entries, total = _entries(include)
    result = _fill(_Sink(send, _mover(total, progress)), include, entries, total, progress)
    if result.get("ok"):
        appenv.logger.info("Backup sent over the network: %d file(s), %d bytes, %d skipped",
                           result["files"], total, result["skipped"])
    elif not result.get("cancelled"):
        result["error"] = "The download stopped before the end. Try again."
    return result


def arrivals():
    """Where a backup sent to this Deck lands: `~/deckyemu/backups`."""
    import savedata

    return savedata.arrivals_dir()


def on_deck():
    """Full backups sent to this Deck, newest first: [{path, name, bytes}]."""
    folder = arrivals()
    found = []
    try:
        names = sorted(os.listdir(folder), reverse=True)
    except OSError:
        return found
    for name in names:
        path = os.path.join(folder, name)
        if not name.lower().endswith(".zip") or not os.path.isfile(path):
            continue
        try:
            with zipfile.ZipFile(path) as bundle:
                if not _manifest(bundle):
                    continue
            found.append({"path": path, "name": name, "bytes": os.path.getsize(path)})
        except (OSError, zipfile.BadZipFile, ValueError):
            continue
    return found
