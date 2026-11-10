#!/usr/bin/env python3
"""A full backup to a drive: what it carries, what it leaves, and that a second
one only copies what changed.

    python scripts/tests/test_fullbackup.py
"""

import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import appenv  # noqa: E402
import fullbackup  # noqa: E402
import savedata  # noqa: E402

_home = os.path.join(TMP, "fullhome")
_media = os.path.join(TMP, "media")
_drive = os.path.join(_media, "deck", "SDCARD")
_previous_home = os.environ.get("DECKYEMU_USER_HOME")
os.environ["DECKYEMU_USER_HOME"] = _home
os.makedirs(_drive, exist_ok=True)


def _drop(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w") as handle:
        handle.write(text)
    return path


_drop(os.path.join(_home, "deckyemu", "roms", "snes", "Made Up Quest.sfc"), "rom")
_drop(os.path.join(_home, "deckyemu", "firmware", "bios.bin"), "bios")
_drop(os.path.join(_home, "deckyemu", "emulators", "plain", "Plain.AppImage"), "app")
_save = _drop(os.path.join(_home, "plain-saves", "slot1.sav"), "save")
os.makedirs(appenv.SETTINGS_DIR, exist_ok=True)
_drop(os.path.join(appenv.SETTINGS_DIR, "library.json"),
      json.dumps({"3000000001": {"title": "Made Up Quest"}}))
_drop(os.path.join(appenv.SETTINGS_DIR, "settings.json"), "{}")
_drop(os.path.join(appenv.SETTINGS_DIR, "rclone.conf"), "token")
_drop(os.path.join(appenv.SETTINGS_DIR, "cloudstate", "plain.json"), "{}")
_grid = os.path.join(_home, ".steam", "steam", "userdata", "42", "config", "grid")
_drop(os.path.join(_grid, "3000000001p.png"), "art")
_drop(os.path.join(_grid, "3000000001_hero.png"), "art")
_drop(os.path.join(_grid, "999p.png"), "not ours")

_real_sources = savedata._all_sources
_real_media, _real_mounted = fullbackup.MEDIA, fullbackup._mounted
savedata._all_sources = lambda empty=False, anywhere=False: [{
    "id": "plain", "name": "Plain", "whole": False,
    "roots": [("saves", os.path.join(_home, "plain-saves"))]}]
fullbackup.MEDIA = _media
fullbackup._mounted = lambda path: path == _drive


def _zip_on_drive():
    """The one backup on the drive, joined from its pieces when it has them."""
    names = fullbackup.backups_on(_drive)
    assert len(names) == 1, names
    first = os.path.join(_drive, names[0])
    if not first.endswith(".001"):
        return zipfile.ZipFile(first)
    stem = first[:-4]
    pieces = sorted(n for n in os.listdir(_drive) if n.startswith(os.path.basename(stem) + "."))
    joined = b"".join(open(os.path.join(_drive, n), "rb").read() for n in pieces)
    return zipfile.ZipFile(io.BytesIO(joined))


try:
    section("the drives a backup can go to")
    check("a mounted drive is offered", [d["path"] for d in fullbackup.drives()], [_drive])

    _sys = os.path.join(TMP, "sysblock")
    _drop(os.path.join(_sys, "sda", "removable"), "1")
    _drop(os.path.join(_sys, "sda", "size"), "262146048")
    _drop(os.path.join(_sys, "nvme0n1", "removable"), "0")
    _drop(os.path.join(_sys, "nvme0n1", "size"), "100")
    _real_sys, fullbackup.SYS_BLOCK = fullbackup.SYS_BLOCK, _sys
    check("an attached drive nothing could mount is named, not hidden",
          fullbackup.unreadable(), [{"name": "sda", "size": 262146048 * 512}])
    fullbackup.SYS_BLOCK = _real_sys

    section("everything, as the checklist starts")
    _result = fullbackup.backup(_drive, fullbackup.PARTS)
    check("the backup succeeds", (_result["ok"], _result["skipped"]), (True, 0))
    check("as one zip", len(fullbackup.backups_on(_drive)), 1)
    with _zip_on_drive() as _bundle:
        _names = set(_bundle.namelist())
        check("uncompressed",
              {i.compress_type for i in _bundle.infolist()}, {zipfile.ZIP_STORED})
        check("ROMs, BIOS and emulators go as they are",
              {"roms/snes/Made Up Quest.sfc", "firmware/bios.bin",
               "emulators/plain/Plain.AppImage"} <= _names, True)
        check("saves use the cloud's layout", "saves/plain/saves/slot1.sav" in _names, True)
        check("settings go, but not this Deck's cloud sync records",
              ("settings/library.json" in _names,
               any(n.startswith("settings/cloudstate") for n in _names)), (True, False))
        check("our games' artwork goes, and nobody else's",
              sorted(n for n in _names if n.startswith("art/")),
              ["art/3000000001_hero.png", "art/3000000001p.png"])
        check("sign-ins go in their own part", "signins/rclone.conf" in _names, True)
        check("and the manifest names what is in it",
              json.loads(_bundle.read(fullbackup.MANIFEST))["parts"], sorted(fullbackup.PARTS))
        check("files keep their contents",
              _bundle.read("roms/snes/Made Up Quest.sfc"), b"rom")

    section("a second backup")
    fullbackup.backup(_drive, ["settings"])
    check("replaces the first once it is complete", len(fullbackup.backups_on(_drive)), 1)

    section("a drive that cannot hold a big file gets pieces")
    _real_table, _real_piece = fullbackup._mount_table, fullbackup.PIECE
    fullbackup._mount_table = lambda: {_drive: ("/dev/sda1", "vfat")}
    fullbackup.PIECE = 700
    try:
        fullbackup.backup(_drive, fullbackup.PARTS)
    finally:
        fullbackup._mount_table, fullbackup.PIECE = _real_table, _real_piece
    _first = fullbackup.backups_on(_drive)
    check("named .zip.001 and on", (len(_first), _first[0].endswith(".zip.001")), (1, True))
    check("more than one piece",
          len([n for n in os.listdir(_drive) if n.startswith(_first[0][:-4])]) > 1, True)
    with _zip_on_drive() as _bundle:
        check("which join into the same zip", _bundle.read("firmware/bios.bin"), b"bios")

    section("no room for two: the old one goes first")
    _pieces_bytes = sum(os.path.getsize(os.path.join(_drive, n)) for n in os.listdir(_drive))
    check("a drive says how much its backups take",
          [d["backup_bytes"] for d in fullbackup.drives()], [_pieces_bytes])
    _seen_old = []
    fullbackup.backup(_drive, ["settings"],
                      lambda _t, _p: _seen_old.append(len(os.listdir(_drive))), True)
    check("the old pieces are gone before the copy starts", max(_seen_old), 1)
    check("leaving just the new one", len(os.listdir(_drive)), 1)

    section("cancelling")
    _cancelled = fullbackup.backup(_drive, fullbackup.PARTS, lambda _t, _p: fullbackup.cancel())
    _real_flush = fullbackup._FLUSH
    check("stops and says so", (_cancelled["ok"], _cancelled.get("cancelled")), (False, True))
    check("leaving the earlier backup and nothing half-written",
          (len(fullbackup.backups_on(_drive)),
           [n for n in os.listdir(_drive) if n.endswith(fullbackup._PARTIAL)]), (1, []))

    section("restoring, from one zip and from pieces")
    _rom = os.path.join(_home, "deckyemu", "roms", "snes", "Made Up Quest.sfc")
    _drop(_rom, "rom")
    os.utime(_rom, (1700000000, 1700000000))
    for _label, _pieces in (("one zip", False), ("pieces", True)):
        for _old in fullbackup.backups_on(_drive):
            for _n in os.listdir(_drive):
                if _n.startswith(_old.split(".zip")[0]):
                    os.remove(os.path.join(_drive, _n))
        _real_table, _real_piece = fullbackup._mount_table, fullbackup.PIECE
        if _pieces:
            fullbackup._mount_table = lambda: {_drive: ("/dev/sda1", "vfat")}
            fullbackup.PIECE = 300
        try:
            fullbackup.backup(_drive, fullbackup.PARTS)
        finally:
            fullbackup._mount_table, fullbackup.PIECE = _real_table, _real_piece
        _path = os.path.join(_drive, fullbackup.backups_on(_drive)[0])
        check("%s: it describes itself" % _label, fullbackup.describe(_path)["parts"],
              sorted(fullbackup.PARTS))
        os.remove(_rom)
        os.remove(_save)
        os.remove(os.path.join(appenv.SETTINGS_DIR, "library.json"))
        _back = fullbackup.restore(_path)
        check("%s: everything comes back" % _label, (_back["ok"], _back["failed"]), (True, 0))
        check("%s: with its contents" % _label,
              (open(_rom).read(), os.path.isfile(_save),
               os.path.isfile(os.path.join(appenv.SETTINGS_DIR, "library.json"))),
              ("rom", True, True))
    check("and its time", int(os.path.getmtime(_rom)), 1700000000)
    check("artwork waits for the games to be re-added",
          sorted(os.listdir(fullbackup.ART_DIR)), ["3000000001_hero.png", "3000000001p.png"])

    _hostile = os.path.join(TMP, "hostile.zip")
    with zipfile.ZipFile(_hostile, "w") as _bundle:
        _bundle.writestr(fullbackup.MANIFEST, json.dumps({"format": fullbackup.FORMAT}))
        _bundle.writestr("roms/../../escaped.txt", "x")
        _bundle.writestr("settings/../outside.json", "x")
    fullbackup.restore(_hostile)
    check("a path that climbs out is refused",
          (os.path.exists(os.path.join(_home, "escaped.txt")),
           os.path.exists(os.path.join(os.path.dirname(appenv.SETTINGS_DIR), "outside.json"))),
          (False, False))
    _plain = os.path.join(TMP, "plain.zip")
    with zipfile.ZipFile(_plain, "w") as _bundle:
        _bundle.writestr("a.txt", "x")
    check("a zip that is not a backup is refused", fullbackup.restore(_plain)["ok"], False)

    section("a game added back to Steam under a new id")
    import store  # noqa: E402
    _drop(os.path.join(appenv.SETTINGS_DIR, "library.json"), json.dumps({"3000000001": {
        "app_id": 3000000001, "title": "Made Up Quest", "core_id": "mgba_libretro",
        "core_path": "/nowhere/mgba_libretro.so", "collection": "Handhelds",
        "launcher_path": "/launchers/made-up-quest.sh"}}))
    _drop(os.path.join(_home, "deckyemu", "icons", "3000000001.png"), "icon")
    _drop(os.path.join(_home, "deckyemu", "patches", "3000000001", "fix.ips"), "patch")
    _drop(os.path.join(fullbackup.ART_DIR, "3000000001p.png"), "art")
    _drop(os.path.join(fullbackup.ART_DIR, "3000000001_hero.png"), "art")
    _plan = {name for files in fullbackup.plan(["roms", "settings"]).values() for _, name in files}
    check("the backup carries game icons and patches",
          {"icons/3000000001.png", "patches/3000000001/fix.ips"} <= _plan, True)
    _games = fullbackup.games_to_readd()
    check("each game comes with what Steam needs",
          [(g["app_id"], g["exe"], g["start_dir"], g["collection"]) for g in _games],
          [(3000000001, "/launchers/made-up-quest.sh", "/launchers", "Handhelds")])
    check("and the missing libretro core is named", fullbackup.cores_to_install(), ["mgba_libretro"])
    check("the restored artwork fills Steam's slots",
          sorted(fullbackup.restored_art(3000000001)), ["capsule", "hero"])
    check("moving to the new id works", fullbackup.rekey_game(3000000001, 4000000002), (True, ""))
    check("the record moves, with its id",
          (list(store.get_library()), store.get_library()["4000000002"]["app_id"]),
          (["4000000002"], 4000000002))
    check("and so do its icon, patches and artwork",
          (os.path.isfile(os.path.join(_home, "deckyemu", "icons", "4000000002.png")),
           os.path.isdir(os.path.join(_home, "deckyemu", "patches", "4000000002")),
           sorted(fullbackup.restored_art(4000000002))),
          (True, True, ["capsule", "hero"]))
    check("an unknown id is refused", fullbackup.rekey_game(1, 2)[0], False)

    section("what is left out, and what is refused")
    _other = os.path.join(_media, "deck", "OTHER")
    os.makedirs(_other, exist_ok=True)
    fullbackup._mounted = lambda path: path in (_drive, _other)
    fullbackup.backup(_other, ["settings"])
    with zipfile.ZipFile(os.path.join(_other, fullbackup.backups_on(_other)[0])) as _bundle:
        check("an unticked part is not included",
              any(n.startswith("signins/") for n in _bundle.namelist()), False)
    check("a drive that is not connected is refused",
          fullbackup.backup(os.path.join(TMP, "nowhere"), ["settings"])["ok"], False)
    _real_usage = fullbackup.shutil.disk_usage
    fullbackup.shutil.disk_usage = lambda _p: fullbackup.shutil._ntuple_diskusage(1, 1, 1)
    try:
        _full = fullbackup.backup(_other, ["roms", "emulators"])
    finally:
        fullbackup.shutil.disk_usage = _real_usage
    check("a drive without room says so before writing",
          (_full["ok"], "Not enough room" in _full["error"]), (False, True))

    section("to a phone or PC: made while it downloads")
    import fileserver
    import urllib.request

    os.makedirs(os.path.join(TMP, "net-inbox"), exist_ok=True)
    _served = fileserver.start(os.path.join(TMP, "net-inbox"), uploads=False)
    if _served.get("error"):
        print("SKIP file server (%s)" % _served["error"])
    else:
        try:
            _outcome = []

            def _producer(send):
                result = fullbackup.stream(send, fullbackup.PARTS)
                _outcome.append(result)
                return result["ok"]

            fileserver.offer_download(
                name="DeckyEmu-backup-x.zip", size=1, producer=_producer,
                emulators=["ROMs"], heading="DeckyEmu backup")
            _url = "http://127.0.0.1:%d/%s/" % (_served["port"], fileserver.current_token())
            with urllib.request.urlopen(_url, timeout=5) as _page:
                check("the page names it", b"<h1>DeckyEmu backup</h1>" in _page.read(), True)
            with urllib.request.urlopen(_url + "download", timeout=30) as _response:
                _got = _response.read()
                _chunked = _response.headers.get("Transfer-Encoding")
            check("sent in chunks, so a cut-off download shows as failed", _chunked, "chunked")
            with zipfile.ZipFile(io.BytesIO(_got)) as _bundle:
                check("a whole, readable zip", _bundle.testzip(), None)
                check("holding the backup", _bundle.read("roms/snes/Made Up Quest.sfc"), b"rom")
            check("and the backup says it finished", _outcome[-1]["ok"], True)

            def _broken(_data):
                raise OSError("connection reset")

            check("a download cut off is reported, not finished",
                  fullbackup.stream(_broken, ["roms"])["ok"], False)
        finally:
            fileserver.offer_download("")
            fileserver.stop()

    section("a backup sent to this Deck")
    _sent = os.path.join(fullbackup.arrivals(), "DeckyEmu-backup-sent.zip")
    with open(_sent, "wb") as _handle:
        fullbackup.stream(_handle.write, ["settings"])
    with open(os.path.join(fullbackup.arrivals(), "deckyemu-saves-1.zip"), "wb") as _handle:
        _handle.write(b"not ours")
    check("is offered to restore, and nothing else there is",
          [one["name"] for one in fullbackup.on_deck()], ["DeckyEmu-backup-sent.zip"])
finally:
    savedata._all_sources = _real_sources
    fullbackup.MEDIA, fullbackup._mounted = _real_media, _real_mounted
    if _previous_home is None:
        os.environ.pop("DECKYEMU_USER_HOME", None)
    else:
        os.environ["DECKYEMU_USER_HOME"] = _previous_home

section("ejecting only says so when the drive is unmounted")
_real_table, _real_run = fullbackup._mount_table, fullbackup.subprocess.run
_ran = []
try:
    fullbackup.subprocess.run = lambda args, **_: (
        _ran.append(args) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    fullbackup._mount_table = lambda: {"/m/card": ("/dev/mmcblk0p1", "ext4"),
                                       "/m/stick": ("/dev/sda1", "vfat")}
    check("an SD card is left mounted, and not called safe to pull",
          (fullbackup.eject("/m/card"), _ran), ((False, ""), []))
    check("a USB drive is unmounted, even one mounted elsewhere",
          (fullbackup.eject("/m/stick"), _ran[-1][3] if _ran else None), ((True, ""), "/dev/sda1"))
finally:
    fullbackup._mount_table, fullbackup.subprocess.run = _real_table, _real_run

section("finding a drive to mount, nested or flat")
_real_run = fullbackup.subprocess.run
_flat = [{"path": "/dev/sda", "fstype": None, "mountpoint": None, "rm": True, "tran": "usb",
          "type": "disk"},
         {"path": "/dev/sda1", "fstype": "vfat", "mountpoint": None, "rm": True, "tran": None,
          "type": "part"},
         {"path": "/dev/nvme0n1p1", "fstype": "vfat", "mountpoint": None, "rm": False,
          "tran": "nvme", "type": "part"}]
_nested = [dict(_flat[0], children=[dict(_flat[1], rm=False)]), _flat[2]]
try:
    for _label, _listing in (("flat", _flat), ("nested", _nested)):
        _ran = []

        def _fake(args, _listing=_listing, **_):
            _ran.append(args)
            out = json.dumps({"blockdevices": _listing}) if args[0] == "lsblk" else "Mounted"
            return type("R", (), {"returncode": 1, "stdout": out, "stderr": ""})()

        fullbackup.subprocess.run = _fake
        fullbackup.mount_removable()
        check("a %s listing mounts the USB partition only" % _label,
              [args[3] for args in _ran if args[0] == "udisksctl"], ["/dev/sda1"])
finally:
    fullbackup.subprocess.run = _real_run

if __name__ == "__main__":
    summary()
