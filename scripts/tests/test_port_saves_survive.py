#!/usr/bin/env python3
"""A port's saves live beside its binary, and both paths out used to lose them.

    python scripts/tests/test_port_saves_survive.py

Two failures with one cause: the plugin assumed an AppImage keeps nothing in its
own install folder. True of every emulator it ships -- RPCS3, Azahar, Vita3K and
Xenia all write to `~/.config` or `~/.local/share` -- and false of a port of the
portable kind, which writes `saves/`, `Save/` and its own config right next to
the binary.

* **Removing one deleted them.** `remove_appimage` was `rmtree` on the whole
  folder, and `delete_data` -- off by default, and the thing that is supposed to
  decide this -- was honoured only for a flatpak.
* **Restoring them from the cloud could not put them back.** A `saves` entry
  naming one file is held up there inside a folder of its own name, because
  rclone's `copy` puts a source file *into* the destination. Coming back, the
  fetch passed the local file as the destination, so rclone had to make a
  directory where the file already was and refused: *is a file not a
  directory*. It stopped the whole restore on the first emulator declaring one.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import cloudsync  # noqa: E402
import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import sysenv  # noqa: E402


PORT = {
    "id": "zed",
    "name": "Zed",
    "summary": "Native port of a game. Needs your own ROM.",
    "port": True,
    "game_beside": True,
    "source": {"kind": "github", "repo": "someone/zed", "asset": "^zed\\.AppImage$"},
    "root": "deckyemu/emulators/zed",
    "saves": [
        "deckyemu/emulators/zed/saves",
        "deckyemu/emulators/zed/zed.cfg.json",
        "deckyemu/emulators/zed/controllerPak_file_*.sav",
    ],
}


def lay_out(folder):
    """What a portable port's install folder actually looks like."""
    os.makedirs(os.path.join(folder, "saves"), exist_ok=True)
    os.makedirs(os.path.join(folder, "logs"), exist_ok=True)
    os.makedirs(os.path.join(folder, "assets", "deep"), exist_ok=True)
    for relative in ("zed.appimage", "zed.cfg.json", "gamecontrollerdb.txt",
                     ".build.json", "saves/file1.sav", "saves/file2.sav",
                     "logs/last.log", "assets/deep/thing.bin",
                     "controllerPak_file_0.sav", "controllerPak_file_1.sav"):
        path = os.path.join(folder, *relative.split("/"))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(relative)


section("removing a port keeps what it declared as saves")

_real_catalog = emulator_catalog.CATALOG
_real_find = emulator_catalog.find
with tempfile.TemporaryDirectory() as home:
    emulator_catalog.CATALOG = (PORT,)
    emulator_catalog.find = lambda one: PORT if one == "zed" else None
    _real_home = sysenv.user_home
    sysenv.user_home = lambda: home
    try:
        folder = os.path.join(home, "deckyemu", "emulators", "zed")
        os.makedirs(folder)
        lay_out(folder)

        check("the declared saves resolve, patterns included",
              sorted(os.path.relpath(one, folder)
                     for one in emu_install.declared_saves("zed")),
              ["controllerPak_file_0.sav", "controllerPak_file_1.sav", "saves",
               "zed.cfg.json"])

        removed, error = emu_install.remove_appimage(
            "zed", emu_install.declared_saves("zed"))
        check("the removal reports success", (removed, error), (True, ""))

        left = sorted(os.path.relpath(os.path.join(where, name), folder)
                      for where, _, names in os.walk(folder) for name in names)
        check("the saves are still there",
              left,
              ["controllerPak_file_0.sav", "controllerPak_file_1.sav",
               "saves\\file1.sav".replace("\\", os.sep),
               "saves\\file2.sav".replace("\\", os.sep),
               "zed.cfg.json"])
        # The binary, the logs, the bundled assets and the build record are the
        # install, not the save data, and removing is what was asked for.
        check("and nothing else is", any(
            one.endswith((".appimage", ".log", ".bin", ".txt", ".build.json"))
            for one in left), False)

        # The port must read as gone, or the row still offers to launch it --
        # and the first file left behind is now a save, not a program.
        check("the port reads as not installed", emu_install.installed_appimage("zed"), "")

        section("and deleting the data on purpose still does")

        lay_out(folder)
        removed, error = emu_install.remove_appimage("zed")
        check("the folder goes entirely", (removed, os.path.exists(folder)), (True, False))
    finally:
        sysenv.user_home = _real_home
        emulator_catalog.CATALOG = _real_catalog
        emulator_catalog.find = _real_find


section("a save that is one file comes back beside itself, not inside itself")

with tempfile.TemporaryDirectory() as home:
    folder = os.path.join(home, "deckyemu", "emulators", "zed")
    os.makedirs(os.path.join(folder, "saves"))
    config = os.path.join(folder, "zed.cfg.json")
    with open(config, "w", encoding="utf-8") as handle:
        handle.write("{}")

    check("a directory root is its own destination",
          cloudsync._file_root(os.path.join(folder, "saves")), False)
    check("a file root is not", cloudsync._file_root(config), True)
    # A Deck restoring saves it has never had has neither yet, and reading
    # "not a directory" as "a file" sent every one of those into its parent.
    check("and one this Deck does not have yet is left as a directory",
          cloudsync._file_root(os.path.join(folder, "never-here")), False)

    # The failure exactly: rclone was handed the file as the place to put a
    # folder, and said so.
    check("so the fetch aims at the folder holding it",
          os.path.dirname(config), folder)


section("a port reinstalled but not yet played is still installed here")

_real_catalog = emulator_catalog.CATALOG
with tempfile.TemporaryDirectory() as home:
    emulator_catalog.CATALOG = (PORT,)
    _real_home = sysenv.user_home
    sysenv.user_home = lambda: home
    try:
        import savedata

        folder = os.path.join(home, "deckyemu", "emulators", "zed")
        os.makedirs(folder)
        # What a freshly reinstalled port looks like: the binary is there and
        # not one save has been written yet.
        with open(os.path.join(folder, "zed.appimage"), "w", encoding="utf-8") as h:
            h.write("x")

        check("a backup has nothing to offer for it",
              [one["id"] for one in savedata._all_sources()], [])
        # The restore screen read that same emptiness as "not installed here,
        # so these stay in the backup" -- on a port that had just been
        # installed, for saves that belong to precisely it.
        listed = savedata._all_sources(True)
        check("but a restore knows where its saves go",
              [one["id"] for one in listed], ["zed"])
        # The pattern's place is the directory holding it, carried with the
        # filter -- so a Deck with none of those files still knows where they
        # go. One root per matching file had nowhere at all.
        check("and the places are the ones the definition declared",
              sorted(os.path.relpath(path, folder) for _, path in listed[0]["roots"]),
              [".", "saves", "zed.cfg.json"])
        check("the pattern's root carries its filter",
              listed[0]["only"], {"controllerPak_file_*.sav":
                                  ("controllerPak_file_*.sav",)})
    finally:
        sysenv.user_home = _real_home
        emulator_catalog.CATALOG = _real_catalog


section("the storage's record names what the storage holds")

# A copy up never deletes up there, so a file that stopped existing here is
# still in the storage -- and the record beside the saves is the restore
# screen's whole index, because walking a remote costs seconds per emulator.
# Rewriting that index from the local side alone is what made a 46 KB save
# invisible: in Dropbox, absent from the list of what could come back.
_sent = {"files": {"save/file1.sav": {"size": 46715, "mtime": 111},
                   "save/global.sav": {"size": 76, "mtime": 111}}}


class _Src(dict):
    pass


_source = _Src(id="zed", name="Zed", roots=[], whole=False)
_real_local = cloudsync._local_files
cloudsync._local_files = lambda source: {"save/global.sav": (76, 222)}
try:
    here = cloudsync._state_of(_source)
    check("this Deck's own record is what it sent, and nothing else",
          sorted(here["files"]), ["save/global.sav"])
    # Which is what `changed_since_push` compares: a save that is no longer
    # here has to read as a change, so this half must not carry anything.
    theirs = cloudsync._state_of(_source, _sent)
    check("the storage's record still names the file only it has",
          sorted(theirs["files"]), ["save/file1.sav", "save/global.sav"])
    check("and the size carried is the one that went up",
          theirs["files"]["save/file1.sav"]["size"], 46715)
    check("while a file that is here is described as it is now",
          theirs["files"]["save/global.sav"]["mtime"], 222)
finally:
    cloudsync._local_files = _real_local


section("a pattern carries only what it matches, and only where it belongs")

with tempfile.TemporaryDirectory() as home:
    emulator_catalog.CATALOG = (PORT,)
    _real_home = sysenv.user_home
    sysenv.user_home = lambda: home
    try:
        import savedata

        folder = os.path.join(home, "deckyemu", "emulators", "zed")
        os.makedirs(os.path.join(folder, "saves"))
        lay_out(folder)

        source = [one for one in savedata._all_sources() if one["id"] == "zed"][0]
        filtered = [(label, path) for label, path in source["roots"]
                    if label in source["only"]]
        check("the pattern is one root, at the directory holding it",
              [os.path.relpath(path, folder) for _, path in filtered], ["."])

        label, path = filtered[0]
        carried = sorted(rel for _abs, rel in savedata._walk(
            path, (), (), source["only"][label]))
        check("and it carries the files it names", carried,
              ["controllerPak_file_0.sav", "controllerPak_file_1.sav"])
        # The root is the port's whole install folder, so without the filter a
        # backup of it would be the binary, the built archive and the logs.
        check("and nothing else in that folder",
              any(one.endswith((".appimage", ".log", ".txt")) for one in carried),
              False)
    finally:
        sysenv.user_home = _real_home
        emulator_catalog.CATALOG = _real_catalog


if __name__ == "__main__":
    from harness import summary

    summary()
