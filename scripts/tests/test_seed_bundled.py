#!/usr/bin/env python3
"""A flatpak can ship a file its own application cannot find.

Supermodel is the case, and it is not a degraded feature: `CCrosshair::Init`
loads two crosshair bitmaps unconditionally -- whatever the crosshair settings
say -- and `Main.cpp` treats a failure as fatal. The Flathub build installs them
to `/app/bin/Assets` while `FileSystemPath::GetPath(Assets)` resolves under the
application's own data directory, so every game loaded its ROM set, opened a
window, printed "Unable to load bitmap crosshair texture" and exited. From Game
Mode that is a shortcut that flashes and returns to the library.

Unlike `Games.xml`, which has the same fault, there is no flag to point at the
packaged copy. The files have to be put where the emulator looks.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import sysenv  # noqa: E402

APP = "com.example.Seeded"
SEED = {"bin/Assets": ".var/app/%s/data/example/Assets" % APP}

_home = sysenv.user_home()
_root = os.path.join(_home, ".local", "share", "flatpak")
_deploy = os.path.join(_root, "app", APP, "x86_64", "stable", "abc123")
_assets = os.path.join(_deploy, "files", "bin", "Assets")
_target = os.path.join(_home, *SEED["bin/Assets"].split("/"))


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


section("nothing to copy out of")

check("an application that is not installed is an error, not a silent no-op",
      emu_install.seed_bundled_files(APP, SEED)[1] != "", True)
check("and an entry with nothing to seed is neither",
      emu_install.seed_bundled_files(APP, None), ([], ""))

section("the files a flatpak ships, put where the application looks")

# The layout flatpak itself leaves behind: the commit tree, with `current` and
# `active` symlinked at it. `flatpak_files_dir` follows the same symlinks
# `sysenv.flatpak_deployed` does, so what it finds is whatever build is
# installed rather than a path recorded when it was.
_write(os.path.join(_assets, "p1crosshair.bmp"), "one")
_write(os.path.join(_assets, "p2crosshair.bmp"), "two")
_write(os.path.join(_assets, "DIR.txt"), "notes")
os.makedirs(os.path.join(_assets, "nested"), exist_ok=True)
_write(os.path.join(_assets, "nested", "deep.bmp"), "deep")

if os.name == "posix":
    os.symlink(os.path.join(_root, "app", APP, "x86_64", "stable"),
               os.path.join(_root, "app", APP, "current"))
    os.symlink(_deploy, os.path.join(_root, "app", APP, "x86_64", "stable", "active"))
else:
    # Windows will not make these without elevation, and what is being checked
    # is the copying rather than flatpak's symlink layout. Directories stand in
    # for the links; every path below resolves the same way.
    import shutil

    shutil.copytree(_deploy, os.path.join(_root, "app", APP, "x86_64", "stable", "active"))
    shutil.copytree(os.path.join(_root, "app", APP, "x86_64", "stable"),
                    os.path.join(_root, "app", APP, "current"))

_copied, _error = emu_install.seed_bundled_files(APP, SEED)
check("the copy reports no error", _error, "")
check("every file in the directory arrives",
      sorted(os.path.basename(path) for path in _copied),
      ["DIR.txt", "p1crosshair.bmp", "p2crosshair.bmp"])
check("and they are really there",
      os.path.isfile(os.path.join(_target, "p1crosshair.bmp")), True)

# Not recursive on purpose. This is for the small data an application ships
# beside itself; copying an arbitrary tree out of a package is a bigger promise
# than anything here needs, and a bigger one to get wrong.
check("a subdirectory is not walked",
      os.path.exists(os.path.join(_target, "nested")), False)

section("what is already there belongs to whoever put it there")

_write(os.path.join(_target, "p1crosshair.bmp"), "the user's own")
_copied, _error = emu_install.seed_bundled_files(APP, SEED)
check("a second pass copies nothing", _copied, [])
check("and leaves the replaced file alone",
      open(os.path.join(_target, "p1crosshair.bmp"), encoding="utf-8").read(),
      "the user's own")

# Which is also what makes this safe to run on every startup: the pass exists so
# a fault found after somebody already has the emulator still reaches them, and
# it can only ever put back a file that has gone.
os.remove(os.path.join(_target, "p2crosshair.bmp"))
_copied, _error = emu_install.seed_bundled_files(APP, SEED)
check("a file that has gone is put back",
      [os.path.basename(path) for path in _copied], ["p2crosshair.bmp"])

section("a package that moved its data is reported, not fatal")

_missing, _error = emu_install.seed_bundled_files(APP, {"bin/Gone": SEED["bin/Assets"]})
check("nothing is copied", _missing, [])
check("and the install is not failed over it", _error, "")

section("the entry that needs this declares it")

# The check that keeps the two halves together: this whole file is worth nothing
# if the catalog stops asking for the copy, and Supermodel does not reach its
# first frame without it.
_supermodel = emulator_catalog.find("supermodel")
check("Supermodel seeds its assets", bool(_supermodel.get("seed")), True)
check("out of the directory the flatpak actually ships them in",
      "bin/Assets" in _supermodel["seed"], True)
check("into the one FileSystemPath::GetPath(Assets) resolves to",
      _supermodel["seed"]["bin/Assets"].endswith("/data/supermodel/Assets"), True)

section("what an imported definition may ask for")

# `seed` names a destination under the home directory, which is exactly the
# power `_written_paths` exists to bound. An imported entry may only write
# inside the one root it declares.
_problems = emulator_catalog.validate(
    {"id": "outsider", "name": "Outsider", "summary": "x", "args": "{rom}",
     "platform": "Sega - Model 3", "root": ".var/app/com.example.Outsider",
     "source": {"kind": "flatpak", "id": "com.example.Outsider"},
     "seed": {"bin/Assets": ".ssh"}},
    imported=True,
)
check("an imported entry cannot seed outside its own root",
      any("seed destination" in problem for problem in _problems), True)

_problems = emulator_catalog.validate(
    {"id": "escaper", "name": "Escaper", "summary": "x", "args": "{rom}",
     "platform": "Sega - Model 3",
     "source": {"kind": "flatpak", "id": "com.example.Escaper"},
     "seed": {"../../etc": ".var/app/com.example.Escaper"}},
)
check("nor can any entry read out of a path that escapes the package",
      any("seed source" in problem for problem in _problems), True)

_problems = emulator_catalog.validate(
    {"id": "notflat", "name": "Not Flatpak", "summary": "x", "args": "{rom}",
     "platform": "Sega - Model 3",
     "source": {"kind": "github", "repo": "a/b", "asset": "^x$"},
     "seed": {"bin/Assets": ".local/share/x"}},
)
check("and a release download has no deployed tree to seed out of",
      any("means nothing for" in problem for problem in _problems), True)


if __name__ == "__main__":
    summary()
