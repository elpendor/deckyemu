#!/usr/bin/env python3
"""RetroArch's BIOS files, read off each core's .info and shown with the rest.

    python scripts/tests/test_ra_firmware.py

A libretro core says what it reads: `firmware0_path = "scph5501.bin"`, relative
to RetroArch's system folder, with `firmware0_opt` saying whether it boots
without it. So the rows need no table, and the only rules here are where the
system folder really is (EmuDeck moves it), which name the file lands as (the
core opens exactly one), and which rows are worth showing on a Deck with a
hundred cores installed.

Every file here is a few made-up bytes.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import emu_firmware  # noqa: E402
import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import ra_cores  # noqa: E402
import ra_detect  # noqa: E402
import ra_firmware  # noqa: E402
import sysenv  # noqa: E402


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


section("RetroArch firmware -- what a core's .info declares")

_info = ra_cores._parse_info  # noqa: SLF001 -- the parser the scan uses
_home = os.path.join(TMP, "rafw")
_real_home = sysenv.user_home
sysenv.user_home = lambda: _home
_saved_state = emu_firmware.read_state()
emu_firmware._write_state({})
try:
    _info_path = os.path.join(_home, "info", "dummy_libretro.info")
    _write(_info_path, "\n".join([
        'firmware_count = 4',
        'firmware0_desc = "dummy_bios.bin (Dummy BIOS)"',
        'firmware0_path = "dummy_bios.bin"',
        'firmware0_opt = "false"',
        'firmware1_desc = "extra.bin (Extra ROM)"',
        'firmware1_path = "extra.bin"',
        'firmware1_opt = "true"',
        'firmware2_desc = "dc/boot.bin (Boot ROM)"',
        'firmware2_path = "dc/boot.bin"',
        'firmware3_desc = "a whole folder"',
        'firmware3_path = "dummy/bios"',
        "",
    ]))
    _fw = ra_cores._firmware(_info(_info_path))
    check("every declared file is read", [item["path"] for item in _fw],
          ["dummy_bios.bin", "extra.bin", "dc/boot.bin", "dummy/bios"])
    check("opt false is required", _fw[0]["optional"], False)
    # Most cores mark every file optional, and a missing opt must not make a
    # core warn under every game it runs.
    check("opt absent counts as optional", _fw[2]["optional"], True)
    check("a core with no firmware declares none", ra_cores._firmware({}), [])
    check("a nonsense count is none rather than an error",
          ra_cores._firmware({"firmware_count": "many"}), [])

    # Where the files go. EmuDeck points system_directory at ~/Emulation/bios,
    # and a BIOS put in the default folder there is never read.
    _config = os.path.join(_home, ".var", "app", "org.libretro.RetroArch", "config", "retroarch")
    _write(os.path.join(_config, "retroarch.cfg"), 'system_directory = "default"\n')
    check("an unset system folder is <config>/system",
          ra_detect.system_dir(_config), os.path.join(_config, "system"))
    _write(os.path.join(_config, "retroarch.cfg"), 'system_directory = "~/Emulation/bios"\n')
    check("a moved one is read from retroarch.cfg",
          ra_detect.system_dir(_config), os.path.normpath(_home + "/Emulation/bios"))

    _install = {"kind": "flatpak", "config_dir": _config}
    _cores = [
        {"id": "dummy", "short_name": "Dummy", "firmware": _fw},
        {"id": "twin", "short_name": "Twin", "firmware": [
            {"path": "dummy_bios.bin", "desc": "dummy_bios.bin (Dummy BIOS)", "optional": True},
        ]},
        {"id": "plain", "short_name": "Plain", "firmware": []},
    ]
    _entry = ra_firmware.entry(_install, _cores)
    _rows = {spec["name"]: spec for spec in _entry["firmware"]}
    check("one entry, filed as RetroArch", (_entry["id"], _entry["name"]),
          ("retroarch", "RetroArch"))
    check("a folder requirement is left out, a file in a subfolder is not",
          sorted(_rows), ["dc/boot.bin", "dummy_bios.bin", "extra.bin"])
    check("a file two cores read is one row naming both",
          _rows["dummy_bios.bin"]["core_ids"], ["dummy", "twin"])
    check("required if any core that reads it needs it",
          _rows["dummy_bios.bin"]["optional"], False)
    check("and the note says what it is and who needs it",
          _rows["dummy_bios.bin"]["note"], "Dummy BIOS. Needed by Dummy, Twin.")
    check("into the system folder EmuDeck chose", _rows["dummy_bios.bin"]["dest"],
          "Emulation/bios")
    check("keeping the subfolder the core reads from", _rows["dc/boot.bin"]["dest"],
          "Emulation/bios/dc")
    check("narrowed to one core for the add-game warning",
          [spec["name"] for spec in ra_firmware.for_core(_install, _cores, "twin")["firmware"]],
          ["dummy_bios.bin"])
    check("a core declaring nothing gives no entry at all",
          ra_firmware.for_core(_install, _cores, "plain"), None)

    _write(os.path.join(_config, "retroarch.cfg"), 'system_directory = "/mnt/elsewhere"\n')
    check("a system folder outside the home is not written to",
          ra_firmware.entry(_install, _cores), None)
    _write(os.path.join(_config, "retroarch.cfg"), 'system_directory = "~/Emulation/bios"\n')

    section("RetroArch firmware -- sent, renamed, shown and shared")

    _inbox = emu_install.firmware_dir()
    for _name in os.listdir(_inbox):
        os.remove(os.path.join(_inbox, _name))
    with io.open(os.path.join(_inbox, "DUMMY_BIOS.BIN"), "wb") as _handle:
        _handle.write(b"made up")

    _report = emu_firmware.status(_entry, shared=[])
    _row = next(row for row in _report if row["name"] == "dummy_bios.bin")
    check("a file sent in other capitals is recognised", _row["waiting"], ["DUMMY_BIOS.BIN"])

    # Which rows show: a library using the core, or a file just sent. Installed
    # alone is not enough -- EmuDeck's folder holds dozens nobody uses.
    _library = {
        "1": {"core_id": "twin"},
        "2": {"core_id": "emu:duckstation"},
    }
    _used = ra_firmware.library_core_ids(_library)
    check("the library's cores exclude standalone emulators", _used, {"twin"})
    _shown, _folded = ra_firmware.visible(_entry, _report, set())
    check("a file just sent shows even for a core nothing uses",
          ([row["name"] for row in _shown], _folded), (["dummy_bios.bin"], []))
    # Measured on a Deck: six cores in use declared 27 files, every one
    # optional. As rows that was 27 warnings about nothing; folded, it is one
    # line with a Send button.
    _shown, _folded = ra_firmware.visible(_entry, _report, {"dummy"})
    check("an optional file nobody sent is folded, not shown",
          ([row["name"] for row in _shown], [item["name"] for item in _folded]),
          (["dummy_bios.bin"], ["dc/boot.bin", "extra.bin"]))
    check("saying what each is and which cores read it",
          _folded[1], {"name": "extra.bin", "label": "Extra ROM", "cores": ["Dummy"]})
    check("a core nothing uses contributes neither",
          ra_firmware.visible(_entry, _report, {"twin"})[1], [])
    _required = [dict(row, waiting=[]) for row in _report]
    check("a required file shows for a core in use, sent or not",
          [row["name"] for row in ra_firmware.visible(_entry, _required, {"dummy"})[0]],
          ["dummy_bios.bin"])
    check("a description with brackets of its own keeps them",
          ra_firmware._label("x.bin (Satellaview (Japan) (Rev 1))", "x.bin"),
          "Satellaview (Japan) (Rev 1)")

    _result = emu_firmware.install(_entry, "dummy_bios.bin", shared=[])
    _landed = os.path.join(_home, "Emulation", "bios", "dummy_bios.bin")
    # The core opens exactly the name its .info gives; nothing else is read.
    check("it lands under the exact name the core opens", os.path.isfile(_landed), True)
    check("and is reported that way", _result["copied"], ["dummy_bios.bin"])
    check("and now reads as in place",
          next(r for r in emu_firmware.status(_entry, shared=[])
               if r["name"] == "dummy_bios.bin")["installed"],
          ["dummy_bios.bin"])

    # A file placed by hand under other capitals is not in place for the core.
    _write(os.path.join(_home, "Emulation", "bios", "EXTRA.BIN"), "made up")
    check("a file in the wrong capitals does not count as installed",
          next(r for r in emu_firmware.status(_entry, shared=[])
               if r["name"] == "extra.bin")["installed"],
          [])

    # The reason the two halves of this came together: a PS1 BIOS DuckStation
    # already holds is one press from being RetroArch's too, and back.
    _ps1 = emulator_catalog.find("duckstation")
    _ps1_entry = ra_firmware.entry(_install, [
        {"id": "psx", "short_name": "PSX", "firmware": [
            {"path": "scph5501.bin", "desc": "scph5501.bin (PS1 US BIOS)", "optional": True},
        ]},
    ])
    with io.open(os.path.join(_inbox, "scph5501.bin"), "wb") as _handle:
        _handle.write(b"made up")
    emu_firmware.install(_ps1, "PS1 BIOS", shared=[])
    _shared = emu_firmware.installed_elsewhere(list(emulator_catalog.CATALOG) + [_ps1_entry])
    _offer = emu_firmware.status(_ps1_entry, shared=_shared)[0]
    check("RetroArch is offered the BIOS DuckStation holds",
          _offer["elsewhere"], [{"name": "scph5501.bin", "from": "DuckStation"}])
    _shared_result = emu_firmware.install(_ps1_entry, "scph5501.bin", shared=_shared)
    check("and installing it shares it", _shared_result["linked"], ["scph5501.bin"])
    # Named differently on each side is still one file kept by the other.
    with io.open(os.path.join(_inbox, "SCPH5501.BIN"), "wb") as _handle:
        _handle.write(b"made up")
    _upper = emulator_catalog.find("duckstation")
    emu_firmware.uninstall(_upper, "PS1 BIOS")
    emu_firmware.install(_upper, "PS1 BIOS", shared=[])
    _shared = emu_firmware.installed_elsewhere(list(emulator_catalog.CATALOG) + [_ps1_entry])
    check("a copy in other capitals still counts as kept elsewhere",
          emu_firmware.status(_ps1_entry, shared=_shared)[0]["kept_by"], ["DuckStation"])
finally:
    emu_firmware._write_state(_saved_state)
    sysenv.user_home = _real_home


if __name__ == "__main__":
    summary()
