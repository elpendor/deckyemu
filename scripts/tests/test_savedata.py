#!/usr/bin/env python3
"""What a save backup contains, and what it must never carry off the device.

    python scripts/tests/test_savedata.py
"""

import io
import json
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import ra_detect  # noqa: E402
import emulator_catalog  # noqa: E402
import savedata  # noqa: E402
from emulator_catalog import schema  # noqa: E402

section("what a save backup carries, and what it leaves behind")

_home = os.path.join(TMP, "savehome")
_previous_home = os.environ.get("DECKY_USER_HOME")
_previous_catalog = emulator_catalog.CATALOG
os.environ["DECKY_USER_HOME"] = _home


def _archive_not_ours():
    """An ordinary zip, for the check that says so rather than trying to read it."""
    path = os.path.join(TMP, "just-a-zip.zip")
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("Some Game.sfc", "not a backup")
    return path


def _drop(relative, text="x"):
    path = os.path.join(_home, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w") as handle:
        handle.write(text)
    return path


# An emulator that installs games into itself: the saves are a corner of a tree
# that is mostly content nobody needs a copy of. This is the case that decides
# whether the feature is useful at all -- on a real Deck RPCS3's saves are 28KB
# inside 367MB.
_drop(".config/pretendo/dev_hdd0/home/00000001/savedata/GAME01/SAVE")
_drop(".config/pretendo/dev_hdd0/game/GAME01/big.bin", "x" * 4096)
_drop(".config/pretendo/dev_flash/firmware.bin", "x" * 4096)

_declares = {
    "id": "pretendo",
    "name": "Pretendo",
    "source": {"kind": "github", "repo": "example/pretendo"},
    "data": [".config/pretendo"],
    "saves": [".config/pretendo/dev_hdd0/home"],
    "platform": "Sony - PlayStation 3",
}

# An emulator that only reads ROMs off the disk keeps nothing in its own
# directory but configuration and memory cards, so the whole directory is the
# right answer and needs no per-emulator fact that could rot.
_drop(".var/app/dev.plainly.Plain/config/plain/memcards/card1.mcd")
_drop(".var/app/dev.plainly.Plain/config/plain/settings.ini")
_drop(".var/app/dev.plainly.Plain/cache/shaders/huge.bin", "x" * 8192)

_whole = {
    "id": "plain",
    "name": "Plain",
    "source": {"kind": "flatpak", "id": "dev.plainly.Plain"},
    "platform": "Sony - PlayStation 2",
}

emulator_catalog.CATALOG = (_declares, _whole)

_listed = {source["id"]: source for source in savedata.sources()}

check("an emulator that declares its saves offers only those",
      _listed["pretendo"]["paths"],
      [os.path.join(_home, ".config", "pretendo", "dev_hdd0", "home")])
check("and is not reported as a whole-directory backup",
      _listed["pretendo"]["whole"], False)
check("so the games and firmware beside them are not counted",
      _listed["pretendo"]["files"], 1)

check("an emulator that declares none offers everything it keeps",
      _listed["plain"]["whole"], True)
# The one exclusion, and it is a definition rather than a guess about any
# emulator: `cache` is a flatpak's XDG_CACHE_HOME. On RPCS3 it is the largest
# thing in the tree and the emulator rebuilds it unasked.
check("except the flatpak cache directory", _listed["plain"]["files"], 2)
check("and the measured size is the files, not the tree",
      _listed["plain"]["bytes"], 2)

section("building the archive")

_destination = os.path.join(TMP, "backups", "saves.zip")
_result = savedata.build(_destination)
check("the build reports success", _result["ok"], True)
check("and names the emulators it took from",
      sorted(_result["emulators"]), ["Plain", "Pretendo"])
check("and the archive is really there", os.path.isfile(_destination), True)
check("with nothing half-written left beside it",
      os.path.isfile(_destination + savedata._PARTIAL), False)

with zipfile.ZipFile(_destination) as _bundle:
    _members = sorted(_bundle.namelist())
    _manifest = json.loads(_bundle.read("manifest.json").decode("utf-8"))

check("every file is stored under the root it came from",
      [name for name in _members if name.startswith("files/")],
      ["files/plain-dev.plainly.plain/config/plain/memcards/card1.mcd",
       "files/plain-dev.plainly.plain/config/plain/settings.ini",
       "files/pretendo-home/00000001/savedata/GAME01/SAVE"])
# Restoring has to put files back where they were, and working that out from the
# shape of the paths would be a guess in the one direction where a wrong answer
# overwrites something. So the archive says.
check("the manifest names the absolute directory behind each root",
      sorted((root["key"], os.path.basename(root["path"]))
             for root in _manifest["roots"]),
      [("plain-dev.plainly.plain", "dev.plainly.Plain"),
       ("pretendo-home", "home")])
check("and records the layout version so a restore can refuse an unknown one",
      _manifest["format"], savedata.FORMAT)

section("a saves path may not reach outside what the entry owns")

# A `saves` path is read on backup and *written* on restore, so "relative to
# home" is not enough of a fence: home also holds Steam's data and the user's
# ssh keys.
check("a path escaping home is refused",
      any("must not escape" in problem
          for problem in schema.validate(dict(_declares, saves=["../../etc"]))),
      True)
check("a path inside home but outside the entry's own directories is refused",
      any("outside every directory" in problem
          for problem in schema.validate(dict(_declares, saves=[".ssh"]))),
      True)
check("and an entry that owns nothing declared cannot name saves at all",
      any("nothing to sit inside" in problem
          for problem in schema.validate(
              {"id": "loose", "name": "Loose", "source": {"kind": "byo"},
               "platform": "Sony - PlayStation 2", "saves": [".ssh"]})),
      True)

section("a symlink out of the tree is not followed")

if os.name == "posix":
    _outside = _drop("secrets/private.key", "not a save")
    _linked = os.path.join(_home, ".var", "app", "dev.plainly.Plain",
                           "config", "plain", "leak.key")
    os.symlink(_outside, _linked)
    _walked = [relative for _, relative in
               savedata._walk(os.path.join(_home, ".var", "app", "dev.plainly.Plain"),
                              savedata._SKIP_TOP)]
    check("a link pointing out of the backed-up tree is skipped",
          "config/plain/leak.key" in _walked, False)
    check("while the real files beside it still go", len(_walked), 2)
    os.remove(_linked)
else:
    print("SKIP symlink escapes are POSIX-only")

section("RetroArch is asked where its saves are, never assumed")

# The measurement this exists for: on the development Deck RetroArch's own
# config points at EmuDeck's directory while `<config>/saves` still holds an
# older set of files. Both exist; only one of them is where the next save lands.
_config_dir = os.path.join(_home, ".var", "app", "org.libretro.RetroArch",
                           "config", "retroarch")
os.makedirs(_config_dir, exist_ok=True)
with io.open(os.path.join(_config_dir, "retroarch.cfg"), "w") as _handle:
    _handle.write('savefile_directory = "%s"\n' % os.path.join(_home, "Emulation", "saves"))
    _handle.write('savestate_directory = ":/states"\n')

_dirs = ra_detect.save_dirs(_config_dir)
check("an absolute directory in the config wins over the default",
      _dirs["saves"], os.path.join(_home, "Emulation", "saves"))
check("and RetroArch's `:` stands for its own config directory",
      _dirs["states"], os.path.normpath(os.path.join(_config_dir, "states")))

with io.open(os.path.join(_config_dir, "retroarch.cfg"), "w") as _handle:
    _handle.write('libretro_directory = ":/cores"\n')
_dirs = ra_detect.save_dirs(_config_dir)
check("an unset key falls back to RetroArch's own default",
      _dirs["saves"], os.path.join(_config_dir, "saves"))

section("a backup arriving is filed away from the ROM inbox")

# The transfer folder is the ROM inbox: everything in it is offered as something
# to add to Steam, so a 75MB archive of saves sat in the picker pretending to be
# a game -- and, being a zip with a `.rtc` inside, was offered libretro cores to
# run it with.
_inbox = os.path.join(_home, "deckyemu", "transfer")
os.makedirs(_inbox, exist_ok=True)
_delivered = os.path.join(_inbox, "deckyemu-saves-20260828-120000.zip")
shutil.copyfile(_destination, _delivered)
_filed = savedata.take_delivery(_delivered)
check("it is moved out of the transfer folder", os.path.isfile(_delivered), False)
check("into the backups folder",
      os.path.dirname(_filed), savedata.arrivals_dir())

# Every ROM, BIOS and definition uses this same server, and none of them may be
# moved by this.
_rom = os.path.join(_inbox, "Some Game.sfc")
with io.open(_rom, "w") as _handle:
    _handle.write("not a backup")
check("anything that is not a backup stays exactly where it landed",
      savedata.take_delivery(_rom), _rom)

# Re-sending the same backup is ordinary. Replacing the copy already here would
# discard whatever it held, which for save data is the whole risk.
shutil.copyfile(_destination, _delivered)
_second = savedata.take_delivery(_delivered)
check("a second copy is kept beside the first rather than replacing it",
      (_second != _filed, os.path.isfile(_filed)), (True, True))
check("and both are offered, newest first",
      len(savedata.backups_in(savedata.arrivals_dir())), 2)
os.remove(_second)

section("restoring puts files back where this device says they go")

# The archive built at the top of this file, restored onto a home where the
# saves have been deleted -- which is the case the whole feature exists for.
os.remove(os.path.join(_home, ".config", "pretendo", "dev_hdd0", "home",
                       "00000001", "savedata", "GAME01", "SAVE"))
_described = savedata.describe(_destination)
check("the archive is recognised as one of ours", _described["ok"], True)
_by_id = {entry["id"]: entry for entry in _described["sources"]}
check("and it says which emulators are in it", sorted(_by_id), ["plain", "pretendo"])
check("and how many of those files are already on this device",
      (_by_id["pretendo"]["files"], _by_id["pretendo"]["present"]), (1, 0))
check("counting the ones that are", _by_id["plain"]["present"], 2)

_result = savedata.restore(_destination)
check("the missing save is written back", _result["written"], 1)
check("and the files already here are left alone", _result["skipped"], 2)
check("so the save is really there again",
      os.path.isfile(os.path.join(_home, ".config", "pretendo", "dev_hdd0", "home",
                                  "00000001", "savedata", "GAME01", "SAVE")),
      True)

# Not overwriting is the default because it cannot lose a save that has been
# played since the backup. Somebody who means the other thing has to say so.
with io.open(os.path.join(_home, ".var", "app", "dev.plainly.Plain", "config",
                          "plain", "memcards", "card1.mcd"), "w") as _handle:
    _handle.write("played since the backup")
savedata.restore(_destination)
check("a file changed since the backup survives a plain restore",
      io.open(os.path.join(_home, ".var", "app", "dev.plainly.Plain", "config",
                           "plain", "memcards", "card1.mcd")).read(),
      "played since the backup")
savedata.restore(_destination, replace=True)
check("and is overwritten only when replacing was asked for",
      io.open(os.path.join(_home, ".var", "app", "dev.plainly.Plain", "config",
                           "plain", "memcards", "card1.mcd")).read(),
      "x")

section("an archive may not say where its files go")

# The rule the restore turns on. This zip arrived over the network from a device
# the plugin knows nothing about, so an absolute path or a `..` inside it would
# be an arbitrary write into the home directory. The destination is recomputed
# from the catalog and the member is only allowed to land under it.
_hostile = os.path.join(TMP, "hostile.zip")
with zipfile.ZipFile(_hostile, "w") as _bundle:
    _bundle.writestr("manifest.json", json.dumps({
        "format": savedata.FORMAT,
        "home": "/home/somebody-else",
        "roots": [{"key": "pretendo-home", "id": "pretendo", "name": "Pretendo",
                   "path": "/home/somebody-else/.config/pretendo/dev_hdd0/home",
                   "whole": False}],
    }))
    _bundle.writestr("files/pretendo-home/../../../../.ssh/authorized_keys", "pwned")
    _bundle.writestr("files/pretendo-home/00000001/savedata/OK", "fine")

_result = savedata.restore(_hostile)
check("a member climbing out of its root is refused", _result["refused"], 1)
check("the one that stayed inside is written", _result["written"], 1)
check("and nothing was written outside the emulator's own directory",
      os.path.exists(os.path.join(_home, ".ssh", "authorized_keys")), False)
# The manifest named another machine's home. It is ignored entirely: where a
# file goes is decided by what this device has installed now.
check("and the archive's own idea of where it came from is not used",
      os.path.isfile(os.path.join(_home, ".config", "pretendo", "dev_hdd0",
                                  "home", "00000001", "savedata", "OK")),
      True)

section("what cannot be restored is reported, not guessed at")

_unknown = os.path.join(TMP, "unknown.zip")
with zipfile.ZipFile(_unknown, "w") as _bundle:
    _bundle.writestr("manifest.json", json.dumps({
        "format": savedata.FORMAT,
        "home": _home,
        "roots": [{"key": "notinstalled-home", "id": "notinstalled",
                   "name": "Some Emulator", "path": "/x", "whole": False}],
    }))
    _bundle.writestr("files/notinstalled-home/SAVE", "x")
_result = savedata.restore(_unknown)
check("saves for an emulator this Deck does not have are named, not written",
      (_result["written"], _result["not_installed"]), (0, ["Some Emulator"]))

check("a zip that is not one of ours says so",
      savedata.describe(_archive_not_ours())["error"].startswith("This zip is not"),
      True)

# A layout this build does not know could put files anywhere, so it is refused
# outright rather than attempted.
_future = os.path.join(TMP, "future.zip")
with zipfile.ZipFile(_future, "w") as _bundle:
    _bundle.writestr("manifest.json", json.dumps({"format": savedata.FORMAT + 1}))
check("and a backup from a newer layout is refused rather than attempted",
      "does not know" in savedata.restore(_future)["error"], True)

# Put back what this file changed, or every check that runs after it reads a
# home and a catalog that are not the suite's.
emulator_catalog.CATALOG = _previous_catalog
if _previous_home is None:
    os.environ.pop("DECKY_USER_HOME", None)
else:
    os.environ["DECKY_USER_HOME"] = _previous_home

if __name__ == "__main__":
    summary()
