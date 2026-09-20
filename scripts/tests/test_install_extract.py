#!/usr/bin/env python3
"""A release that ships the program inside an archive.

    python scripts/tests/test_install_extract.py

Most projects publish the AppImage itself. Some publish a zip holding it beside
a readme, and downloading that as though it were the program leaves Steam
launching a zip: the execute bit goes on, `exec` fails, and the game closes
instantly with nothing naming why.

So a source may say what to take out of the archive, and the rest of the
install -- the folder per emulator, the execute bit, the build record, the
sweep of the previous build -- is unchanged.

Every project and file here is made up.
"""

import io
import os
import sys
import tarfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import net  # noqa: E402
from emulator_catalog import schema  # noqa: E402

_ENTRY = {
    "id": "packaged-port",
    "name": "Packaged Port",
    "source": {
        "kind": "github",
        "repo": "someone/packaged",
        "asset": "^Packaged-Linux\\.zip$",
        "extract": "^packaged\\.appimage$",
    },
    "args": "{rom}",
}

NEWBUILD = "#!/bin/sh\nexit 0\n"

_ARCHIVE = os.path.join(TMP, "release", "Packaged-Linux.zip")
os.makedirs(os.path.dirname(_ARCHIVE), exist_ok=True)
with zipfile.ZipFile(_ARCHIVE, "w") as _bundle:
    _bundle.writestr("packaged.appimage", "#!/bin/sh\nexit 0\n")
    _bundle.writestr("readme.txt", "put your own copy of the game beside this")


def _fake_download(url, path, max_bytes=0, on_progress=None):
    """Stand in for the network: copy the archive where the installer wants it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(_ARCHIVE, "rb") as source, io.open(path, "wb") as handle:
        handle.write(source.read())
    return True, ""


section("the program is taken out of the archive")

_real_download = net.download
net.download = _fake_download
try:
    _path, _error = emu_install.install_appimage(
        _ENTRY, {"name": "Packaged-Linux.zip", "url": "https://example.test/a.zip",
                 "tag": "1.2.3"})
    check("the install succeeds", _error, "")
    check("and what is installed is the program, not the archive",
          os.path.basename(_path), "packaged.appimage")
    # Not the execute bit: this suite runs on Windows too, where chmod cannot
    # set one. What it can check is that the file the launcher will exec is the
    # one that exists.
    check("and it is really there", os.path.isfile(_path), True)

    _folder = sorted(os.listdir(os.path.dirname(_path)))
    # The archive goes: it is 28MB of what was already unpacked beside it, and
    # the sweep that clears a previous build would otherwise keep it forever as
    # the file the record names.
    check("the archive is not left behind", "Packaged-Linux.zip" in _folder, False)
    check("nor is anything else it held", "readme.txt" in _folder, False)
    check("and the build record names the release it came from",
          emu_install.installed_build(_ENTRY), "1.2.3")
finally:
    net.download = _real_download
    emulator_catalog.reload_imported()


section("a release that is a tree, not a file")

# A binary with its own data folders beside it: everything comes out, and
# `extract` names the one to run.
_TREE = os.path.join(TMP, "release", "Tree-Linux.zip")
with zipfile.ZipFile(_TREE, "w") as _bundle:
    _bundle.writestr("treeport", NEWBUILD)
    _bundle.writestr("lang/en.txt", "hello")
    _bundle.writestr("mods/readme.txt", "mods go here")

_TREE_ENTRY = {
    "id": "tree-port",
    "name": "Tree Port",
    "source": {"kind": "github", "repo": "someone/tree",
               "asset": "^Tree-Linux\.zip$", "unpack": True,
               "extract": "^treeport$"},
    "args": "{rom}",
}

net.download = _fake_download
_real_archive = _ARCHIVE
try:
    _ARCHIVE = _TREE
    _path, _error = emu_install.install_appimage(
        _TREE_ENTRY, {"name": "Tree-Linux.zip", "url": "https://example.test/t.zip",
                      "tag": "2.0.0"})
    check("the install succeeds", _error, "")
    check("and what runs is the file the entry named",
          os.path.basename(_path), "treeport")
    _folder = os.path.dirname(_path)
    check("its data comes out beside it, in its own folders",
          (os.path.isfile(os.path.join(_folder, "lang", "en.txt")),
           os.path.isfile(os.path.join(_folder, "mods", "readme.txt"))),
          (True, True))
    check("and the archive does not stay", os.path.isfile(
        os.path.join(_folder, "Tree-Linux.zip")), False)
finally:
    _ARCHIVE = _real_archive
    net.download = _real_download

# This comes off the network, so a member that climbs out of its own folder is
# refused rather than written.
_ESCAPE = os.path.join(TMP, "release", "Escape.zip")
with zipfile.ZipFile(_ESCAPE, "w") as _bundle:
    _bundle.writestr("../escaped.txt", "nope")
_escaped, _why = emu_install._unpack_release(
    _ESCAPE, emu_install.emulators_dir("escape-port"), "^anything$")
check("a path that leaves its folder is refused", "leaves its own folder" in _why, True)


section("a tarball, and the folder it carries")

# A build published as a .tar.gz rather than a zip, which is what a project
# with no release page hands out. Two things differ from the zip above: tar
# records the execute bit, and a release tarball conventionally holds one
# folder -- so unpacking it into a directory already named for the emulator
# gave `emulators/bigpemu/bigpemu/bigpemu` on a Deck until the leading folder
# was stripped.
_TAR = os.path.join(TMP, "release", "Tarred-Linux.tar.gz")
with tarfile.open(_TAR, "w:gz") as _bundle:
    _staged = os.path.join(TMP, "release", "tarport")
    os.makedirs(os.path.join(_staged, "Data"), exist_ok=True)
    with io.open(os.path.join(_staged, "tarport"), "w", encoding="utf-8") as _handle:
        _handle.write(NEWBUILD)
    os.chmod(os.path.join(_staged, "tarport"), 0o755)
    with io.open(os.path.join(_staged, "Data", "en.txt"), "w", encoding="utf-8") as _handle:
        _handle.write("hello")
    _bundle.add(_staged, arcname="tarport")

_TAR_DIR = emu_install.emulators_dir("tar-port")
_tarred, _why = emu_install._unpack_release(_TAR, _TAR_DIR, "^tarport$")
check("the tarball unpacks", _why, "")
check("the program lands directly in the emulator's folder, not a folder inside it",
      os.path.relpath(_tarred, _TAR_DIR).replace("\\", "/"), "tarport")
check("its data comes with it",
      os.path.isfile(os.path.join(_TAR_DIR, "Data", "en.txt")), True)
if os.name == "posix":
    check("and the execute bit the archive recorded survives",
          bool(os.stat(_tarred).st_mode & 0o111), True)

# **A second build unpacks over the first.** The archive records its own modes,
# and BigPEmu ships its data read-only -- so the file the first install created
# cannot be reopened for writing, and every *change of build* failed with
# "Permission denied" while every fresh install worked. Measured on a Deck
# rolling back from 1.221 to 1.19.
_again, _why = emu_install._unpack_release(_TAR, _TAR_DIR, "^tarport$")
check("unpacking over a previous build succeeds", _why, "")
check("and the read-only file it left is replaced, not refused",
      os.path.isfile(os.path.join(_TAR_DIR, "Data", "en.txt")), True)
if os.name == "posix":
    _locked = os.path.join(_TAR_DIR, "Data", "en.txt")
    os.chmod(_locked, 0o444)
    _third, _why = emu_install._unpack_release(_TAR, _TAR_DIR, "^tarport$")
    check("even one made read-only since", _why, "")

# Only when everything is under the same folder. An archive of loose files has
# no prefix to strip, and taking the first name for one would flatten it wrong.
_LOOSE = os.path.join(TMP, "release", "Loose.tar.gz")
with tarfile.open(_LOOSE, "w:gz") as _bundle:
    for _name in ("looseport", "notes.txt"):
        _path = os.path.join(TMP, "release", _name)
        with io.open(_path, "w", encoding="utf-8") as _handle:
            _handle.write("x")
        _bundle.add(_path, arcname=_name)
_LOOSE_DIR = emu_install.emulators_dir("loose-port")
_loose, _why = emu_install._unpack_release(_LOOSE, _LOOSE_DIR, "^looseport$")
check("an archive of loose files keeps its names", (_why, os.path.basename(_loose)),
      ("", "looseport"))

# Tar carries things zip cannot, and `extractall` would honour every one of
# them. Nothing but regular files and directories is written.
_LINKED = os.path.join(TMP, "release", "Linked.tar.gz")
with tarfile.open(_LINKED, "w:gz") as _bundle:
    _info = tarfile.TarInfo("escape")
    _info.type = tarfile.SYMTYPE
    _info.linkname = "/etc/passwd"
    _bundle.addfile(_info)
    _payload = os.path.join(TMP, "release", "linkedport")
    with io.open(_payload, "w", encoding="utf-8") as _handle:
        _handle.write("x")
    _bundle.add(_payload, arcname="linkedport")
_LINK_DIR = emu_install.emulators_dir("linked-port")
_linked, _why = emu_install._unpack_release(_LINKED, _LINK_DIR, "^linkedport$")
check("a symlink in the archive is not written",
      (_why, os.path.lexists(os.path.join(_LINK_DIR, "escape"))), ("", False))


section("a folder the program lives in is not swept")

# A port that reads the directory it runs in keeps its settings, the archive it
# built from the user's game and its save files beside the build. The sweep that
# clears a previous build would take all three, and an update would look like a
# port that had forgotten everything.
_BESIDE = dict(_ENTRY, id="beside-port", port=True, game_beside=True)
_FOLDER = emu_install.emulators_dir(_BESIDE["id"])

net.download = _fake_download
try:
    emu_install.install_appimage(
        _BESIDE, {"name": "Packaged-Linux.zip", "url": "https://example.test/a.zip",
                  "tag": "1.0.0"})
    for _name in ("shipdata.json", "game.archive"):
        with io.open(os.path.join(_FOLDER, _name), "w", encoding="utf-8") as _handle:
            _handle.write("kept")
    os.makedirs(os.path.join(_FOLDER, "Save"), exist_ok=True)
    with io.open(os.path.join(_FOLDER, "Save", "slot1.sav"), "w", encoding="utf-8") as _handle:
        _handle.write("a save")

    # The next release, installed over it.
    with zipfile.ZipFile(_ARCHIVE, "w") as _bundle:
        _bundle.writestr("packaged.appimage", NEWBUILD)
    _path, _error = emu_install.install_appimage(
        _BESIDE, {"name": "Packaged-Linux.zip", "url": "https://example.test/b.zip",
                  "tag": "1.1.0"})
    check("updating it succeeds", _error, "")
    _after = sorted(os.listdir(_FOLDER))
    check("its settings survive the update", "shipdata.json" in _after, True)
    check("so does what it built from the game", "game.archive" in _after, True)
    check("and so do the saves",
          os.path.isfile(os.path.join(_FOLDER, "Save", "slot1.sav")), True)
    check("while the build itself is the new one",
          emu_install.installed_build(_BESIDE), "1.1.0")
finally:
    net.download = _real_download


section("a pattern that names nothing says what was in there")

# The pattern belongs to whoever wrote the definition, the archive to whoever
# cut the release, and the two drift: PaperBoat's readme says
# `paperboat.appimage` while its zip ships `Paperboat.AppImage`. The install
# stopped with "the download did not contain what was expected", which is true
# of every possible mistake and points at none of them.
_MISNAMED = os.path.join(TMP, "release", "Misnamed.zip")
with zipfile.ZipFile(_MISNAMED, "w") as _bundle:
    _bundle.writestr("Program.AppImage", NEWBUILD)
    _bundle.writestr("readme.txt", "hello")

_nothing, _why = emu_install._unpack_release(
    _MISNAMED, emu_install.emulators_dir("misnamed-port"), r"^program\.appimage$")
check("the pattern that missed is quoted back", r"^program\.appimage$" in _why, True)
check("and so is what the archive actually held",
      "Program.AppImage" in _why and "readme.txt" in _why, True)

# The same answer on the one-file path, which has its own reader.
_single, _single_why = emu_install._extract_member(
    _MISNAMED, emu_install.emulators_dir("misnamed-port"), r"^program\.appimage$")
check("taking a single file out says the same", "Program.AppImage" in _single_why, True)

# A long archive is summarised rather than printed whole: this goes in a toast.
_MANY = os.path.join(TMP, "release", "Many.zip")
with zipfile.ZipFile(_MANY, "w") as _bundle:
    for _n in range(20):
        _bundle.writestr("file%02d.bin" % _n, "x")
_, _many_why = emu_install._unpack_release(
    _MANY, emu_install.emulators_dir("many-port"), r"^nothing$")
check("a long listing is cut short", _many_why.endswith("..."), True)


section("an extract pattern has to be one")

_bad = dict(_ENTRY, source=dict(_ENTRY["source"], extract="^(unclosed"))
check("a pattern that is not a regex is refused",
      any("not a valid regex" in problem
          for problem in schema.validate(_bad, known_platforms=(), imported=True)),
      True)

_empty = dict(_ENTRY, source=dict(_ENTRY["source"], extract=""))
check("an empty one is refused, since it would match nothing",
      any("regex naming one file" in problem
          for problem in schema.validate(_empty, known_platforms=(), imported=True)),
      True)


if __name__ == "__main__":
    summary()
