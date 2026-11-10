#!/usr/bin/env python3
"""Compressing library games: what is offered, and what is deleted.

    python scripts/tests/test_romcompress.py

The tools are faked; what is checked is the part that touches the library
folder -- which games qualify, which files go, and that a failure or an undo
leaves the originals and the playlist as they were.
"""

import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- points appenv at scratch

sys.path.insert(0, REPO_ROOT)

import romcompress  # noqa: E402

PSX = "Sony - PlayStation"
GBA = "Nintendo - Game Boy Advance"

#: Stands in for chdman: "createcd -i src -o out" copies, "verify" passes.
FAKE_CHDMAN = '''
import shutil, sys
args = sys.argv[1:]
if args[0] == "verify":
    sys.exit(0)
src = args[args.index("-i") + 1]
out = args[args.index("-o") + 1]
print("Compressing, 50.0% complete... (ratio=80.0%)")
shutil.copyfile(src, out)
print("Compression complete ... final ratio = 10.0%")
'''


def write(folder, name, text="x"):
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def disc(folder, name):
    track = os.path.splitext(name)[0] + ".bin"
    write(folder, name, 'FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n' % track)
    write(folder, track, "sectors" * 100)


def entry(rom, system, extensions=(), libretro=True, patched=False):
    return {"app_id": 1, "title": "Made Up", "system": system, "rom_path": rom,
            "extensions": list(extensions), "libretro": libretro,
            "emulator": "Some Core", "patched": patched}


section("which games are offered")

with tempfile.TemporaryDirectory() as library:
    folder = os.path.join(library, "gba")
    os.makedirs(folder)
    write(folder, "Made Up.gba", "rom" * 1000)
    rom = os.path.join(folder, "Made Up.gba")

    kind, game = romcompress.plan_game(entry(rom, GBA, ["gba"]), library)
    check("a loose cartridge on a libretro core is zipped", (kind, game["format"]),
          ("ready", "zip"))
    check("and only the ROM itself goes", game["files"], ["Made Up.gba"])
    check("a standalone emulator's cartridge is left alone",
          romcompress.plan_game(entry(rom, GBA, ["gba"], libretro=False), library), None)
    check("a game outside the library folder is not ours to touch",
          romcompress.plan_game(entry(rom, GBA, ["gba"]), os.path.join(library, "x")), None)
    write(folder, "Already.zip")
    check("an archive is already compressed",
          romcompress.plan_game(entry(os.path.join(folder, "Already.zip"), GBA), library),
          None)

with tempfile.TemporaryDirectory() as library:
    folder = os.path.join(library, "psx")
    os.makedirs(folder)
    disc(folder, "Made Up.cue")
    write(folder, "Made Up.sbi")
    rom = os.path.join(folder, "Made Up.cue")

    kind, game = romcompress.plan_game(entry(rom, PSX, ["cue", "chd"]), library)
    check("a CD whose core reads CHD becomes one", (kind, game["method"], game["outputs"]),
          ("ready", "createcd", ["Made Up.chd"]))
    check("the sheet and its tracks go, a same-stem .sbi stays", game["files"],
          ["Made Up.bin", "Made Up.cue"])
    check("a core that can't read CHD is said so",
          romcompress.plan_game(entry(rom, PSX, ["cue"]), library),
          ("skip", "Some Core can't read .chd files."))
    check("a patched disc is skipped, since patches can't apply to a CHD",
          romcompress.plan_game(entry(rom, PSX, ["cue", "chd"], patched=True), library)[0],
          "skip")
    write(folder, "Made Up.chd")
    check("an output name already taken is skipped, never overwritten",
          romcompress.plan_game(entry(rom, PSX, ["cue", "chd"]), library),
          ("skip", "Made Up.chd is already there."))


section("compressing")

with tempfile.TemporaryDirectory() as library:
    folder = os.path.join(library, "gba")
    os.makedirs(folder)
    write(folder, "Made Up.gba", "rom" * 1000)
    write(folder, "Made Up.ips", "PATCH")
    _, game = romcompress.plan_game(entry(os.path.join(folder, "Made Up.gba"), GBA), library)
    result = romcompress.compress(game, {})
    check("a cartridge zips", result["ok"], True)
    with zipfile.ZipFile(os.path.join(folder, "Made Up.zip")) as archive:
        check("holding the ROM under its own name", archive.namelist(), ["Made Up.gba"])
    check("the original stays until the record is repointed",
          os.path.isfile(os.path.join(folder, "Made Up.gba")), True)
    romcompress.finish(game)
    check("then goes, and the patch beside it stays", sorted(os.listdir(folder)),
          ["Made Up.ips", "Made Up.zip"])

with tempfile.TemporaryDirectory() as scripts, tempfile.TemporaryDirectory() as library:
    fake = os.path.join(scripts, "chdman.py")
    write(scripts, "chdman.py", FAKE_CHDMAN)
    tools = {"chdman": [sys.executable, "-I", fake]}

    folder = os.path.join(library, "psx")
    os.makedirs(folder)
    disc(folder, "Made Up (Disc 1).cue")
    disc(folder, "Made Up (Disc 2).cue")
    write(folder, "Made Up.m3u", "Made Up (Disc 1).cue\nMade Up (Disc 2).cue\n")
    playlist = os.path.join(folder, "Made Up.m3u")

    _, game = romcompress.plan_game(entry(playlist, PSX, ["m3u", "cue", "chd"]), library)
    check("a two-disc set keeps its playlist and compresses both discs",
          (game["playlist"], game["outputs"]),
          ("Made Up.m3u", ["Made Up (Disc 1).chd", "Made Up (Disc 2).chd"]))
    seen = []
    result = romcompress.compress(game, tools, seen.append)
    check("the set compresses", (result["ok"], result["error"]), (True, ""))
    check("and the game still starts from its playlist", result["rom_path"], playlist)
    with open(playlist, encoding="utf-8") as handle:
        check("which now names the CHDs", handle.read(),
              "Made Up (Disc 1).chd\nMade Up (Disc 2).chd\n")
    check("progress came from the tool's own percentages", 0.25 in seen, True)
    check("and never went backwards, ratios included",
          seen == sorted(seen) and 0.05 not in seen, True)
    check("and the work folder is gone", os.path.exists(
        os.path.join(folder, romcompress.WORK_DIR)), False)

    romcompress.undo(game, result["created"])
    with open(playlist, encoding="utf-8") as handle:
        check("undo puts the playlist back", handle.read(),
              "Made Up (Disc 1).cue\nMade Up (Disc 2).cue\n")
    check("and removes what was made", sorted(os.listdir(folder)),
          ["Made Up (Disc 1).bin", "Made Up (Disc 1).cue", "Made Up (Disc 2).bin",
           "Made Up (Disc 2).cue", "Made Up.m3u"])

    tools = {"chdman": [sys.executable, "-I", "-c", "import sys; sys.exit(3)"]}
    result = romcompress.compress(game, tools)
    check("a failing tool reports and leaves the folder as it was",
          (result["ok"], sorted(os.listdir(folder))),
          (False, ["Made Up (Disc 1).bin", "Made Up (Disc 1).cue", "Made Up (Disc 2).bin",
                   "Made Up (Disc 2).cue", "Made Up.m3u"]))
