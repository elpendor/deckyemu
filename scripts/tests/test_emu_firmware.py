#!/usr/bin/env python3
"""BIOS files and keys, matched by name and put where the emulator reads them.

    python scripts/tests/test_emu_firmware.py

Firmware is the one thing this project will never carry, so every path here is
about somebody else's file: recognising it from its name alone, copying it
without consuming it, and refusing to claim an emulator is ready when it is not.
The matching is by filename because that is what removes the picker -- and a PS1
and a PS2 BIOS are both `scph<digits>.bin`, four digits against five, so the
count is the only thing telling them apart.

Was 795 lines in the middle of test_backend.py. It reaches for nothing that file
sets up, which is what made it movable.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import SAMPLE_SFO, TMP, check, failures, section, summary  # noqa: E402

import emu_install  # noqa: E402
import emulator_catalog as emu_catalog  # noqa: E402
import net  # noqa: E402
import ps3_games  # noqa: E402
import sysenv  # noqa: E402


section("firmware -- the user's own dumps, put where the emulator reads them")
import emu_firmware  # noqa: E402

_fw_home = os.path.join(TMP, "fwhome")
_real_user_home = sysenv.user_home
sysenv.user_home = lambda: _fw_home
try:
    _fw_dir = emu_install.firmware_dir()

    def _send(name, size=16):
        with io.open(os.path.join(_fw_dir, name), "wb") as handle:
            handle.write(b"\0" * size)

    # A PS1 and a PS2 BIOS are both scph<digits>.bin -- four digits for the PS1,
    # five for the PS2. That count is the only thing telling them apart by name,
    # and getting it wrong files a PS1 BIOS into PCSX2 where it does nothing.
    _send("scph39001.bin")
    _send("scph5501.bin")
    _send("Super Mario 3D Land.cci", 32)

    _ps2 = emu_firmware.status(emu_catalog.find("pcsx2"))[0]
    _ps1 = emu_firmware.status(emu_catalog.find("duckstation"))[0]
    check("a five-digit BIOS is offered to PCSX2", _ps2["waiting"], ["scph39001.bin"])
    check("a four-digit one is offered to DuckStation", _ps1["waiting"], ["scph5501.bin"])
    check("and neither claims the other's", "scph5501.bin" in _ps2["waiting"], False)
    # Anything else in the folder is not firmware and must not be offered.
    check("a ROM sitting in the folder is ignored",
          any("cci" in name for name in _ps2["waiting"] + _ps1["waiting"]), False)

    _result = emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")
    check("installing reports what it copied", _result["copied"], ["scph39001.bin"])
    check(
        "into the path the emulator reads",
        _result["dest"].endswith(os.path.join("net.pcsx2.PCSX2", "config", "PCSX2", "bios")),
        True,
    )
    check(
        "the file is really there",
        os.path.isfile(os.path.join(_result["dest"], "scph39001.bin")),
        True,
    )
    # Moved, not copied: copying left the transfer folder holding a duplicate of
    # every BIOS ever sent, which then needed a panel to explain which
    # duplicates were safe to delete.
    check(
        "and the transfer folder no longer holds a duplicate",
        os.path.isfile(os.path.join(_fw_dir, "scph39001.bin")),
        False,
    )
    _after = emu_firmware.status(emu_catalog.find("pcsx2"))[0]
    check("and it now reports as in place", _after["installed"], ["scph39001.bin"])
    check("with nothing left waiting", _after["waiting"], [])

    # Nothing left to install, because the file moved.
    check(
        "installing again with nothing sent is refused",
        emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")["ok"],
        False,
    )

    # A BIOS already at the destination is never replaced: the user may have put
    # a better dump there, and swapping one under an emulator silently is not
    # something an install button should do.
    _send("scph39001.bin")
    _again = emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")
    check("a second install replaces nothing", _again["copied"], [])
    check("and says what it kept", _again["kept"], ["scph39001.bin"])
    check(
        "leaving the newly sent one where it is",
        os.path.isfile(os.path.join(_fw_dir, "scph39001.bin")),
        True,
    )
    emu_firmware.remove(["scph39001.bin"])

    # A requirement the emulator unpacks itself. RPCS3 turns one PUP into
    # several thousand files under dev_flash, so there is nothing to copy --
    # `--headless --installfw` does the whole thing in about six seconds with no
    # window -- and the row is installable the moment the file arrives even
    # though it names no destination folder.
    _send("PS3UPDAT.PUP")
    _pup = emu_firmware.status(emu_catalog.find("rpcs3"))[0]
    check("a PUP is recognised", _pup["waiting"], ["PS3UPDAT.PUP"])
    check("and installing it is offered", _pup["can_install"], True)
    check("as an import rather than a copy", _pup["imported"], True)
    # Copying can be undone by copying back; unpacking a firmware image into a
    # tree cannot, so the trash button is not offered next to it.
    check("with no removal offered", _pup["can_remove"], False)
    check("and nothing installed until it runs", _pup["installed"], [])

    # Which requirements count as "this emulator is not ready". Exactly one row
    # in the whole catalog is optional -- RPCS3's .rap -- because a licence
    # belongs to a game rather than to the emulator, and without this every PS3
    # game added would warn that RPCS3 was missing something it does not need.
    _rpcs3_rows = emu_firmware.status(emu_catalog.find("rpcs3"), emu_firmware.available())
    check("the firmware is required",
          [r["optional"] for r in _rpcs3_rows if r["name"].startswith("PS3 firmware")], [False])
    check("and the licence row is not",
          [r["optional"] for r in _rpcs3_rows if r["name"].startswith("Game licences")], [True])
    # Not knowing whether something is installed is not the same as knowing it
    # is not, and only one of the two may be reported. Ryujinx's firmware is
    # installed through its own interface and used to have nowhere named to
    # look, so it read as absent forever -- and the add flow warned about it
    # under a Switch game that launched perfectly.
    _ryu = emu_firmware.status(emu_catalog.find("ryujinx"), emu_firmware.available())
    _ryu_fw = next(r for r in _ryu if r["name"] == "Switch firmware")
    check("a manually installed firmware is still detectable", _ryu_fw["detectable"], True)
    check("and reports absent while its folder is empty", _ryu_fw["installed"], [])
    _registered = os.path.join(
        _fw_home, ".var", "app", "io.github.ryubing.Ryujinx", "config", "Ryujinx",
        "bis", "system", "Contents", "registered")
    os.makedirs(_registered, exist_ok=True)
    check("an existing but empty folder is not firmware",
          next(r for r in emu_firmware.status(emu_catalog.find("ryujinx"),
                                              emu_firmware.available())
               if r["name"] == "Switch firmware")["installed"], [])
    os.makedirs(os.path.join(_registered, "2f8531a91b713716aa989427090ddfe4.nca"))
    check("and one with contents is",
          next(r for r in emu_firmware.status(emu_catalog.find("ryujinx"),
                                              emu_firmware.available())
               if r["name"] == "Switch firmware")["installed"], ["installed"])

    # Installed by Ryujinx itself, and removable all the same: which of those
    # two is true was never the question -- knowing where the files are is.
    # Keying removal on "did we copy this" is what left it, and RPCS3's
    # firmware, stuck as permanent while a .rap beside them could be taken out.
    check("a firmware the emulator installed itself can still be removed",
          next(r for r in emu_firmware.status(emu_catalog.find("ryujinx"),
                                              emu_firmware.available())
               if r["name"] == "Switch firmware")["can_remove"], True)
    _ryu_gone = emu_firmware.uninstall(emu_catalog.find("ryujinx"), "Switch firmware")
    check("removing it succeeds", _ryu_gone["ok"], True)
    check("and the registered contents are gone", os.path.isdir(_registered), False)
    check("games and their updates are elsewhere and untouched",
          os.path.isdir(os.path.join(
              _fw_home, ".var", "app", "io.github.ryubing.Ryujinx", "config",
              "Ryujinx", "bis", "system", "Contents")), True)

    # Every requirement in the catalog must be answerable one way or the other,
    # or the add flow is guessing about it.
    check("nothing in the catalog is undetectable",
          [r["name"] for e in emu_catalog.CATALOG
           for r in emu_firmware.status(e, emu_firmware.available())
           if not r["detectable"]],
          [])

    # A whitelist rather than a count, so marking something optional has to be
    # argued for here. `optional` is what stops the add flow reporting an
    # emulator as missing something, so a careless one hides a real gap: the
    # game then fails to boot with the panel insisting everything is in place.
    #
    # Both entries earn it the same way -- they belong to a *game* rather than
    # to the emulator. A .rap unlocks one PS3 title, and title.keys is needed
    # only by the Switch games that carry one; most boot on prod.keys alone,
    # which is not optional and is not on this list.
    check("only what belongs to a game, not to the emulator, is optional",
          sorted({r["name"] for e in emu_catalog.CATALOG
                  for r in emu_firmware.status(e, emu_firmware.available())
                  if r["optional"]}),
          ["Game licences (.rap)", "title.keys"])

    # The copy path must refuse it outright rather than half-doing something:
    # `install` moves files, and there is no destination to move this to.
    _refused = emu_firmware.install(
        emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)"
    )
    check("copying it is refused", _refused["ok"], False)
    check("saying who does the work", "RPCS3 installs" in _refused["error"], True)
    check(
        "and taking it back out finds nothing to take",
        emu_firmware.uninstall(emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)")["ok"],
        False,
    )

    # Removing an imported firmware means deleting the tree the emulator wrote,
    # which is only offered where the catalog names that tree. It is the only
    # route back from a firmware that installed badly -- and, now that an
    # installed row no longer shows an Install button, the only route at all.
    _flash = os.path.join(_fw_home, ".config", "rpcs3", "dev_flash", "vsh", "etc")
    os.makedirs(_flash, exist_ok=True)
    with io.open(os.path.join(_flash, "version.txt"), "w") as _handle:
        _handle.write("release:04.9300:\n")
    _pup_in = emu_firmware.status(emu_catalog.find("rpcs3"), emu_firmware.available())[0]
    check("with the firmware unpacked it reports the version",
          _pup_in["installed"], ["4.93"])
    check("and now offers to remove it", _pup_in["can_remove"], True)
    _gone = emu_firmware.uninstall(emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)")
    check("removing it succeeds", (_gone["ok"], _gone["removed"]), (True, ["dev_flash"]))
    check("the whole tree is gone",
          os.path.isdir(os.path.join(_fw_home, ".config", "rpcs3", "dev_flash")), False)
    check("and it reports what that recovered", _gone["freed"] > 0, True)
    check("with nothing left, removal is offered no more",
          emu_firmware.status(emu_catalog.find("rpcs3"),
                              emu_firmware.available())[0]["can_remove"], False)

    # The catalog decides what a removal deletes, so a wrong path in it must
    # fail to find anything rather than delete from wherever it points. Both
    # guards are load-bearing: named by the catalog, and under the home.
    _outside = os.path.join(TMP, "notmyhome")
    os.makedirs(_outside, exist_ok=True)
    _rogue = {"name": "rogue", "removes": [
        os.path.join("..", "..", os.path.basename(TMP), "notmyhome")]}
    check("a removal pointing outside the home deletes nothing",
          emu_firmware._uninstall_tree({"name": "x", "id": "x"}, _rogue)["ok"], False)
    check("and the directory it pointed at is untouched",
          os.path.isdir(_outside), True)

    # A .rap is sixteen bytes of key material with nothing inside naming the
    # game it unlocks, and RPCS3 finds it by filename alone -- but the file is
    # moved into exdata by this plugin, so it can be renamed on the way and the
    # name it arrives under does not have to be the one RPCS3 needs.
    _pkg_probe = os.path.join(_fw_dir, "braid.pkg")
    _hdr = bytearray(b"\0" * 0x54)
    _hdr[0:4] = b"\x7fPKG"
    _hdr[0x30:0x30 + 36] = b"UP4049-NPUB30133_00-BRAID00000000001"
    with io.open(_pkg_probe, "wb") as _handle:
        _handle.write(bytes(_hdr))
    check("the content id is read whole, not just the title id",
          ps3_games.package_content_id(_pkg_probe),
          "UP4049-NPUB30133_00-BRAID00000000001")
    check("with no licence anywhere it reports nothing",
          ps3_games.licence_state("UP4049-NPUB30133_00-BRAID00000000001", _fw_dir), "")
    # Not the same as missing, and never shown as one: without a content id
    # there is nowhere to look, which is every game installed outside this
    # plugin. "No licence" there would be a guess, wrong for licence-free games.
    check("no content id is unknown, not missing",
          ps3_games.licence_state("", _fw_dir), "unknown")
    # Recorded at install because it cannot be recovered later: an installed
    # game's PARAM.SFO has TITLE_ID and no CONTENT_ID -- checked against a real
    # install -- and the package that carried it is deleted.
    check("a title with nothing recorded has no content id",
          ps3_games.content_id_for("NPUB99999"), "")
    ps3_games.remember_content_id("NPUB30133", "UP4049-NPUB30133_00-BRAID00000000001")
    check("and one recorded at install is remembered",
          ps3_games.content_id_for("NPUB30133"),
          "UP4049-NPUB30133_00-BRAID00000000001")

    # A licence sent with its game lands beside the game, not in the firmware
    # folder -- which is the obvious thing to do and is what the Vita flow
    # already expects. Looking only in the firmware folder made a correctly
    # named .rap sitting next to its own package invisible.
    _beside = os.path.join(TMP, "besidepkg")
    os.makedirs(_beside, exist_ok=True)
    _CID = "UP4415-NPUB31749_00-GOATSIMULATORPS3"
    _pkg_beside = os.path.join(_beside, _CID + "_bg_1_abcdef.pkg")
    io.open(_pkg_beside, "w").close()
    io.open(os.path.join(_beside, _CID + ".rap"), "w").close()
    _dirs = ps3_games.licence_dirs(_pkg_beside, _fw_dir)
    check("the licence beside a package is seen",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "waiting")
    # And installed by the same press that installs the game, so "send both
    # together" is all there is to it.
    check("installing it puts it where RPCS3 reads licences",
          ps3_games.install_licence(_CID, _dirs, _pkg_beside), _CID + ".rap")
    check("after which it reports as in place",
          ps3_games.licence_state(_CID), "installed")
    check("and it is gone from beside the package",
          os.path.isfile(os.path.join(_beside, _CID + ".rap")), False)
    os.remove(os.path.join(ps3_games.exdata_dir(), _CID + ".rap"))

    # Named anything at all. The Vita side already accepts "I sent both files"
    # without demanding they match, and there is no reason this cannot: the
    # rename happens here, so the only real question is which file is meant.
    _loose = os.path.join(_beside, "goat licence.rap")
    io.open(_loose, "w").close()
    check("a lone .rap beside the package is the one meant, whatever it is called",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "waiting")
    check("and it is renamed to what RPCS3 reads as it goes in",
          ps3_games.install_licence(_CID, _dirs, _pkg_beside), _CID + ".rap")
    check("under the content id, not the name it arrived with",
          os.path.isfile(os.path.join(ps3_games.exdata_dir(), _CID + ".rap")), True)
    os.remove(os.path.join(ps3_games.exdata_dir(), _CID + ".rap"))

    # Two of them is not an unambiguous answer, and picking wrong installs a
    # licence that fails exactly like a bad dump.
    io.open(os.path.join(_beside, "one.rap"), "w").close()
    io.open(os.path.join(_beside, "two.rap"), "w").close()
    check("two unnamed licences beside a package is a guess, so nothing is taken",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "")
    # Unless one of them says which game it is for, which settles it.
    os.rename(os.path.join(_beside, "one.rap"), os.path.join(_beside, "NPUB31749.rap"))
    check("a licence named for the title id wins over the ambiguity",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "waiting")
    check("and installs under the content id",
          ps3_games.install_licence(_CID, _dirs, _pkg_beside), _CID + ".rap")
    os.remove(os.path.join(ps3_games.exdata_dir(), _CID + ".rap"))
    os.remove(os.path.join(_beside, "two.rap"))
    io.open(os.path.join(_fw_dir, "UP4049-NPUB30133_00-BRAID00000000001.rap"), "w").close()
    check("a sent licence is waiting",
          ps3_games.licence_state("UP4049-NPUB30133_00-BRAID00000000001", _fw_dir),
          "waiting")
    # The lone-candidate sweep is deliberately limited to the folder the package
    # is in. The firmware folder collects licences for every game ever sent, so
    # "the only .rap here" means nothing there -- and with no package to be
    # beside, there is no folder to sweep at all.
    os.rename(os.path.join(_fw_dir, "UP4049-NPUB30133_00-BRAID00000000001.rap"),
              os.path.join(_fw_dir, "braid.rap"))
    check("a renamed licence in the firmware folder is not guessed at",
          ps3_games.licence_state("UP4049-NPUB30133_00-BRAID00000000001", _fw_dir), "")
    os.remove(os.path.join(_fw_dir, "braid.rap"))
    os.remove(_pkg_probe)

    # Installed is read from what the emulator produced, not from a record of
    # the button being pressed. RPCS3 writes its firmware version into
    # dev_flash, and that file is the only thing that says a PUP was unpacked.
    _rpcs3_import = emu_catalog.find("rpcs3")["firmware"][0]["import"]
    _version_txt = emu_firmware.under_home(_rpcs3_import["installed"])
    os.makedirs(os.path.dirname(_version_txt), exist_ok=True)
    with open(_version_txt, "w", encoding="utf-8") as _handle:
        # Copied from a real Deck, digit for digit.
        _handle.write(
            "release:04.9300:\nbuild:68500,20260108:tetsu@tetsu-linux17\n"
            "target:0001:CEX-ww\n"
        )
    check(
        "the firmware version is read out of RPCS3's own record",
        emu_firmware.imported(_rpcs3_import),
        ["4.93"],
    )
    check(
        "and the row now reports it as installed",
        emu_firmware.status(emu_catalog.find("rpcs3"))[0]["installed"],
        ["4.93"],
    )
    # A marker whose contents will not parse is still an install: the version is
    # a nicety, the file existing is the fact.
    with open(_version_txt, "w", encoding="utf-8") as _handle:
        _handle.write("something else entirely\n")
    check(
        "an unreadable version still counts as installed",
        emu_firmware.imported(_rpcs3_import),
        ["version.txt"],
    )
    os.remove(_version_txt)
    check("and a missing marker is not installed", emu_firmware.imported(_rpcs3_import), [])

    # Nothing may resolve outside the user's own home, because these paths are
    # read from a table and then written to and deleted.
    check(
        "a marker path escaping the home is refused",
        emu_firmware.under_home("../../etc/passwd"),
        "",
    )

    # A game licence lands under a name RPCS3 will actually read. It only
    # accepts a lowercase .rap and says so nowhere until the game fails to boot
    # with "Failed to decrypt content", so a .RAP sent from a phone that
    # uppercased it would sit at the destination reporting as installed and
    # decrypt nothing.
    _rap_name = "UP4049-NPUB30133_00-BRAID00000000001.RAP"
    _send(_rap_name)
    _rap_result = emu_firmware.install(emu_catalog.find("rpcs3"), "Game licences (.rap)")
    check("an uppercase licence is installed lowercase",
          _rap_result["copied"], [_rap_name[:-4] + ".rap"])
    _rap_dest = emu_firmware._destination(
        emu_firmware.find_requirement(emu_catalog.find("rpcs3"), "Game licences (.rap)")
    )
    check("and that is the name on disk",
          os.path.isfile(os.path.join(_rap_dest, _rap_name[:-4] + ".rap")), True)
    # Read from the directory listing rather than with isfile, which answers
    # yes to either spelling on the case-insensitive filesystem these tests run
    # on and so could never see the rename fail.
    check("and the only name there", os.listdir(_rap_dest), [_rap_name[:-4] + ".rap"])
    # Recorded under the name it landed as, or removing it would not recognise
    # its own work and would report the user's own file as somebody else's.
    _rap_status = emu_firmware.status(emu_catalog.find("rpcs3"))[1]
    check("the licence reports as installed", _rap_status["installed"],
          [_rap_name[:-4] + ".rap"])
    check("and as this plugin's own work", _rap_status["foreign"], [])
    check("removing it takes it back out",
          emu_firmware.uninstall(emu_catalog.find("rpcs3"), "Game licences (.rap)")["removed"],
          [_rap_name[:-4] + ".rap"])
    # Everything else keeps the name it arrived with.
    check("a requirement without the rule renames nothing",
          emu_firmware._dest_name({}, "SCPH39001.BIN"), "SCPH39001.BIN")

    # ---- xemu: told apart by size, and pointed at afterwards ---------------
    # An MCPX boot ROM and an Xbox BIOS are both a .bin under whatever the
    # dumper called them. There is no naming convention to match on, but an MCPX
    # ROM is exactly 512 bytes and a BIOS never is, so the file itself says
    # which it is.
    _xemu = emu_catalog.find("xemu")
    _send("dump-a.bin", 512)
    _send("dump-b.bin", 262144)
    _xemu_rows = {row["name"]: row for row in emu_firmware.status(_xemu)}
    check("the 512-byte file is recognised as the boot ROM",
          _xemu_rows["MCPX boot ROM"]["waiting"], ["dump-a.bin"])
    check("and the 256KB one as the BIOS",
          _xemu_rows["Xbox BIOS"]["waiting"], ["dump-b.bin"])
    # Both rows match `*.bin`, so without the size rule each would claim both
    # files and a boot ROM would be installed as a BIOS.
    check("neither claims the other's file",
          (len(_xemu_rows["MCPX boot ROM"]["waiting"]),
           len(_xemu_rows["Xbox BIOS"]["waiting"])),
          (1, 1))

    # Copying is not enough for xemu: it reads all three from paths in
    # xemu.toml, and an unset one means it will not start. So the install
    # writes the path it just landed on.
    _mcpx = emu_firmware.install(_xemu, "MCPX boot ROM")
    check("installing the boot ROM works", _mcpx["copied"], ["dump-a.bin"])
    check("and points xemu at it", _mcpx["configured"], "bootrom_path")
    _xemu_toml = emu_firmware.under_home(emu_catalog.xemu._XEMU_TOML)
    with io.open(_xemu_toml, encoding="utf-8") as _handle:
        _toml_text = _handle.read()
    # TOML strings are quoted, and an unquoted one is not a parse error there --
    # it is a different type, so xemu would reject the whole file.
    check("with the path written as a quoted TOML string",
          "bootrom_path = '%s'" % os.path.join(
              emu_firmware.under_home(emu_catalog.xemu._XEMU_DATA), "dump-a.bin"
          ) in _toml_text,
          True)
    check("under the table xemu reads it from", "[sys.files]" in _toml_text, True)

    emu_firmware.install(_xemu, "Xbox BIOS")
    with io.open(_xemu_toml, encoding="utf-8") as _handle:
        check("and a second requirement joins it rather than replacing it",
              _handle.read().count("rom_path = "), 2)

    # The disk image is the one prerequisite here that is nobody's dump, so it
    # is the only one with a source to fetch from.
    check("a dump is never downloaded",
          "never downloads" in emu_firmware.fetch(_xemu, "Xbox BIOS")["error"], True)

    # Sony's PUPs are published by Sony at the addresses their own consoles
    # update from, so they are fetchable where a BIOS is not. The PS3's is read
    # from Sony's update list each time because they still publish versions;
    # the Vita's is pinned because its last firmware was 3.74 in 2022.
    _ps3_fw = emu_firmware.find_requirement(
        emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)")
    check("the PS3 firmware is fetched from Sony's own index",
          _ps3_fw["fetch"]["kind"], "index")
    check("and the Vita's from a fixed address",
          emu_firmware.find_requirement(
              emu_catalog.find("vita3k"), "PS Vita firmware")["fetch"]["kind"],
          "url")
    # Vita3K needs two PUPs, not one. PSVUPDAT.PUP is the firmware and
    # PSP2UPDAT.PUP is the font package, and without the fonts Vita3K reports
    # itself unconfigured -- which is what a welcome screen that kept coming
    # back turned out to mean. Each row must claim only its own file: an
    # earlier version accepted both names for the firmware and would have had
    # the two rows fighting over each other's downloads.
    _vita_fw = emu_firmware.find_requirement(
        emu_catalog.find("vita3k"), "PS Vita firmware")
    _vita_font = emu_firmware.find_requirement(
        emu_catalog.find("vita3k"), "PS Vita font package")
    check("the firmware row takes only the firmware",
          [emu_firmware._matching(_vita_fw, [{"name": n}])
           for n in ("PSVUPDAT.PUP", "PSP2UPDAT.PUP")],
          [["PSVUPDAT.PUP"], []])
    check("and the font row only the fonts",
          [emu_firmware._matching(_vita_font, [{"name": n}])
           for n in ("PSVUPDAT.PUP", "PSP2UPDAT.PUP")],
          [[], ["PSP2UPDAT.PUP"]])
    check("each fetches the file it matches",
          (_vita_fw["fetch"]["name"], _vita_font["fetch"]["name"]),
          ("PSVUPDAT.PUP", "PSP2UPDAT.PUP"))
    # Sony serve the font package over plain http, and Vita3K's own downloader
    # asks for it over https and fails the certificate. Fetching it at the
    # address Vita3K's quickstart gives is what avoids that.
    check("the font package is fetched over the scheme Sony serve",
          _vita_font["fetch"]["url"].startswith("http://"), True)
    # Both install the same way, and both need a display to do it.
    check("both are installed by Vita3K itself",
          (_vita_fw["import"]["args"], _vita_font["import"]["args"]),
          (["--firmware", "{file}"], ["--firmware", "{file}"]))
    # Neither is copied anywhere, so neither has a `dest`. A fetch must still
    # know where to put it: the transfer folder, exactly where the same file
    # would have arrived had it been sent from another device.
    check("a requirement with no destination still has somewhere to land",
          bool(emu_firmware._destination(_ps3_fw)), False)

    # Vita3K installs its own firmware too, with no window -- six seconds and
    # exit 0 on a Deck. It records no version anywhere, and its marker file is
    # `psp2bootconfig.skprx`, which is not a thing to show anybody.
    _vita_import = _vita_fw["import"]
    check("Vita3K installs its firmware itself", _vita_import["args"],
          ["--firmware", "{file}"])
    _vita_marker = emu_firmware.under_home(_vita_import["installed"])
    check("and reports nothing installed before it has",
          emu_firmware.imported(_vita_import, "PS Vita firmware"), [])
    os.makedirs(os.path.dirname(_vita_marker), exist_ok=True)
    io.open(_vita_marker, "w").close()
    check("then names the requirement rather than the marker file",
          emu_firmware.imported(_vita_import, "PS Vita firmware"), ["PS Vita firmware"])
    check("with the row agreeing",
          {r["name"]: r for r in emu_firmware.status(emu_catalog.find("vita3k"))}
          ["PS Vita firmware"]["installed"],
          ["PS Vita firmware"])
    # RPCS3 does record a version, and must still report it rather than a name.
    check("while a version that can be read still wins",
          emu_firmware.imported(_rpcs3_import, "PS3 firmware"), [])
    os.remove(_vita_marker)

    # The display is opt-in. Handing one to a run that asked to be headless
    # invites it to open a window, which is the opposite of the point.
    check("only Vita3K asks for a display",
          sorted({e["id"] for e in emu_catalog.CATALOG
                  for r in e.get("firmware") or []
                  if (r.get("import") or {}).get("needs_display")}),
          ["vita3k"])

    # A console firmware is far bigger than anything this folder held when the
    # cap was written, and the cap silently excluded all of them: a row with a
    # 128MB PUP beside it reported nothing waiting, so its Install button could
    # never appear. Every firmware this catalog fetches has to be visible.
    # Checked against the cap rather than by writing one: a real PUP is 128MB
    # and a PS3 one around 200MB, and writing that on every run left a
    # gigabyte-scale pile of temp directories behind. The two facts that matter
    # are that the cap clears the largest thing that belongs here, and that the
    # filter it feeds actually excludes by size.
    check("the cap clears the largest firmware that belongs here",
          emu_firmware.MAX_FIRMWARE_BYTES > 220 * 1024 * 1024, True)
    _pup = os.path.join(_fw_dir, "PSVUPDAT.PUP")
    _send("PSVUPDAT.PUP", 4096)
    check("a firmware image under the cap is visible",
          [f["name"] for f in emu_firmware.available() if f["name"] == "PSVUPDAT.PUP"],
          ["PSVUPDAT.PUP"])
    check("and the row that wants it reports it as waiting",
          {r["name"]: r for r in emu_firmware.status(emu_catalog.find("vita3k"))}
          ["PS Vita firmware"]["waiting"],
          ["PSVUPDAT.PUP"])
    _real_cap = emu_firmware.MAX_FIRMWARE_BYTES
    emu_firmware.MAX_FIRMWARE_BYTES = 1024
    check("while one over it is filtered out, which is what hid every PUP",
          [f["name"] for f in emu_firmware.available() if f["name"] == "PSVUPDAT.PUP"],
          [])
    emu_firmware.MAX_FIRMWARE_BYTES = _real_cap
    os.remove(_pup)

    # A real zip, unpacked by the real code path. The names inside it are the
    # interesting part: an archive fetched over the network must not be able to
    # place a file anywhere but where this intends.
    import shutil as _shutil  # noqa: E402
    import zipfile as _zipfile  # noqa: E402
    _fetch_zip = os.path.join(TMP, "hdd.zip")
    with _zipfile.ZipFile(_fetch_zip, "w") as _bundle:
        _bundle.writestr("xbox_hdd.qcow2", b"QFI\xfb" + b"\0" * 64)
        _bundle.writestr("../../../escaped.qcow2", b"nope")
        _bundle.writestr("readme.txt", b"ignored")

    _real_resolve = emu_install.resolve_github_asset
    _real_net_download = net.download
    emu_install.resolve_github_asset = lambda repo, pattern: (
        {"name": "xbox_hdd.qcow2.zip", "url": "https://example.test/hdd.zip",
         "tag": "1.0", "size": 0},
        "",
    )
    net.download = lambda url, path, max_bytes=None, on_progress=None: (
        (_shutil.copyfile(_fetch_zip, path), (True, ""))[1]
    )
    try:
        _fetched = emu_firmware.fetch(_xemu, "Xbox hard disk image")
    finally:
        emu_install.resolve_github_asset = _real_resolve
        net.download = _real_net_download

    check("the disk image is fetched", _fetched["ok"], True)
    check("taking only what was asked for", _fetched["copied"], ["xbox_hdd.qcow2"])
    check("and pointing xemu at it", _fetched["configured"], "hdd_path")
    _xemu_dir = emu_firmware.under_home(emu_catalog.xemu._XEMU_DATA)
    check("a member with a path in its name cannot escape",
          os.path.isfile(os.path.join(os.path.dirname(_xemu_dir), "escaped.qcow2")),
          False)
    check("and nothing unmatched is written",
          "readme.txt" in os.listdir(_xemu_dir), False)
    check("the downloaded archive is not left behind",
          [n for n in os.listdir(_xemu_dir) if n.endswith(".zip")], [])
    check("and the row now reports it as in place",
          {row["name"]: row for row in emu_firmware.status(_xemu)}
          ["Xbox hard disk image"]["installed"],
          ["xbox_hdd.qcow2"])

    # Nothing sent yet is not an error, it is just nothing to do.
    check(
        "an unmatched requirement offers nothing",
        emu_firmware.install(emu_catalog.find("azahar"), "aes_keys.txt")["ok"],
        False,
    )
    _send("aes_keys.txt")
    check(
        "and works once the file arrives",
        emu_firmware.install(emu_catalog.find("azahar"), "aes_keys.txt")["copied"],
        ["aes_keys.txt"],
    )

    # Cemu writes keys.txt itself the first time it starts -- three comments and
    # one example key -- so the file exists long before the user has supplied
    # anything. Treating that as "in place" would report the requirement as met,
    # offer no way to send a real one, and leave every disc image undecryptable.
    _cemu_entry = emu_catalog.find("cemu")
    _cemu_keys_dir = emu_firmware._destination(_cemu_entry["firmware"][0])
    os.makedirs(_cemu_keys_dir, exist_ok=True)
    _cemu_keys = os.path.join(_cemu_keys_dir, "keys.txt")
    _CEMU_STUB = (
        "# this file contains keys needed for decryption of disc file system data (WUD/WUX)\n"
        "# 1 key per line, any text after a '#' character is considered a comment\n"
        "# the emulator will automatically pick the right key\n"
        "541b9889519b27d363cd21604b97c67a # example key (can be deleted)\n"
    )
    with io.open(_cemu_keys, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(_CEMU_STUB)
    _keys_state = emu_firmware.status(_cemu_entry)[0]
    check("Cemu's own empty keys.txt is not counted as installed",
          _keys_state["installed"], [])
    check("so the requirement still asks for one", _keys_state["can_install"], True)

    # And installing over it is allowed, or the requirement could never be met.
    with io.open(os.path.join(_fw_dir, "keys.txt"), "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("00112233445566778899aabbccddeeff # my own dump\n")
    _keys_result = emu_firmware.install(_cemu_entry, _cemu_entry["firmware"][0]["name"])
    check("a real keys.txt replaces the placeholder", _keys_result["copied"], ["keys.txt"])
    with io.open(_cemu_keys, encoding="utf-8") as _handle:
        check("and it is the user's file that is there now",
              "00112233445566778899aabbccddeeff" in _handle.read(), True)
    check("which now reads as installed",
          emu_firmware.status(_cemu_entry)[0]["installed"], ["keys.txt"])

    # A key the user added by hand is not a stub, and must never be replaced.
    with io.open(_cemu_keys, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(_CEMU_STUB + "aabbccddeeff00112233445566778899 # added by hand\n")
    check("a placeholder the user has added to is theirs",
          emu_firmware._is_stub(_cemu_keys, _cemu_entry["firmware"][0]["stub"]),
          False)
    with io.open(os.path.join(_fw_dir, "keys.txt"), "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("ffffffffffffffffffffffffffffffff\n")
    check("so a send does not overwrite it",
          emu_firmware.install(_cemu_entry, _cemu_entry["firmware"][0]["name"])["kept"],
          ["keys.txt"])
    emu_firmware.remove(["keys.txt"])

    # A destination is joined onto the user's home, so a malformed catalog entry
    # must not be able to write outside it.
    check(
        "a traversing destination is refused",
        emu_firmware._destination({"dest": "../../etc"}),
        "",
    )
    check("an absent destination is not a path", emu_firmware._destination({}), "")
    # Asking for something the emulator never wanted must not write anything.
    check(
        "an unknown requirement is refused",
        emu_firmware.install(emu_catalog.find("pcsx2"), "Nonsense")["ok"],
        False,
    )

    # Removing an install is what makes Install repeatable -- retrying a wrong
    # destination, or testing the flow twice. It deletes at the destination and
    # leaves the transfer folder alone, so a second Install puts it back.
    check(
        "an installed requirement can be taken back out",
        emu_firmware.uninstall(emu_catalog.find("pcsx2"), "PS2 BIOS")["removed"],
        ["scph39001.bin"],
    )
    check(
        "the emulator no longer has it",
        os.path.isfile(os.path.join(_result["dest"], "scph39001.bin")),
        False,
    )
    # Gone, not returned. Installing moved the file, so there is no second copy
    # anywhere and supplying it again means sending it again -- which is what
    # the confirm dialog says, since a trash button would not imply it.
    check(
        "and no copy is left behind anywhere",
        os.path.isfile(os.path.join(_fw_dir, "scph39001.bin")),
        False,
    )
    _send("scph39001.bin")
    check(
        "sending it again is what puts it back",
        emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")["copied"],
        ["scph39001.bin"],
    )

    # A file the plugin did not install is still removable -- one installed
    # before the record existed would otherwise be stuck forever -- but it is
    # counted separately so the UI can warn before anything happens.
    with io.open(os.path.join(_result["dest"], "scph70012.bin"), "wb") as _handle:
        _handle.write(b"\0")
    _byhand = emu_firmware.status(emu_catalog.find("pcsx2"))[0]
    check("a hand-placed file is reported as not ours", _byhand["foreign"], ["scph70012.bin"])
    _pulled = emu_firmware.uninstall(emu_catalog.find("pcsx2"), "PS2 BIOS")
    check("ours is removed as ours", _pulled["removed"], ["scph39001.bin"])
    check("and theirs is counted separately", _pulled["foreign"], ["scph70012.bin"])
    check(
        "removing what is not there is not an error",
        emu_firmware.uninstall(emu_catalog.find("pcsx2"), "PS2 BIOS")["removed"],
        [],
    )
    emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")

    # Only two things are left in the transfer folder after a successful
    # install: a file the emulator has to import itself, and one nothing
    # recognised. Deleting is still reachable for those -- the PUP sent above is
    # exactly the first case, and is a couple of hundred megabytes in reality.
    check(
        "a file waiting for a manual import can be deleted",
        emu_firmware.remove(["PS3UPDAT.PUP"])["removed"],
        ["PS3UPDAT.PUP"],
    )

    # The names arrive from the frontend and this is a delete, so anything that
    # is not a bare filename in that one folder must be refused outright.
    for _bad in ("../secret", "sub/dir.bin", "/etc/passwd", "", ".", ".."):
        if emu_firmware.remove([_bad])["ok"]:
            failures.append("delete accepted a bad name: %r" % _bad)
    print("PASS %-52s %r" % ("a delete cannot escape the firmware folder", True))

    # Matching is on the filename, so a dump under any other name is silently
    # never recognised. Every requirement has to say which names it takes, or
    # the rule is invisible and the user has no way to find out.
    for _entry in emu_catalog.CATALOG:
        for _req in _entry.get("firmware") or []:
            if not _req.get("expects"):
                failures.append("%s/%s says nothing about expected filenames"
                                % (_entry["id"], _req.get("name")))
    print("PASS %-52s %r" % ("every requirement names the files it accepts", True))
    check(
        "and it reaches the panel",
        bool(emu_firmware.status(emu_catalog.find("pcsx2"))[0]["expects"]),
        True,
    )
    # The match pattern is the plugin's business, not the frontend's.
    _listed = emu_catalog.listing({}, ())
    _pcsx2_listed = next(item for item in _listed if item["id"] == "pcsx2")
    check(
        "the listing carries the expected names",
        bool(_pcsx2_listed["firmware"][0]["expects"]),
        True,
    )
    check(
        "but not the match pattern or destination",
        [key for key in _pcsx2_listed["firmware"][0] if key in ("match", "dest", "manual")],
        [],
    )

    # Every placeable requirement in the catalog must name a destination and a
    # pattern, or the row would offer an Install button that does nothing. An
    # imported one is copied nowhere, so what it must name instead is the
    # command and the file the emulator leaves behind -- without that marker the
    # row could never report the install as having happened.
    for _entry in emu_catalog.CATALOG:
        for _req in _entry.get("firmware") or []:
            if _req.get("manual"):
                continue
            if not _req.get("match"):
                failures.append(
                    "%s/%s is installable but names no pattern"
                    % (_entry["id"], _req.get("name"))
                )
                continue
            _import = _req.get("import")
            if _import:
                if not _import.get("args") or not _import.get("installed"):
                    failures.append(
                        "%s/%s is imported but names no %s"
                        % (
                            _entry["id"],
                            _req.get("name"),
                            "command" if not _import.get("args") else "marker",
                        )
                    )
                elif "{file}" not in " ".join(_import["args"]):
                    # Without the placeholder the emulator would be run with no
                    # file at all, which for RPCS3 means opening its interface.
                    failures.append(
                        "%s/%s never passes the file to the emulator"
                        % (_entry["id"], _req.get("name"))
                    )
            elif not _req.get("dest"):
                failures.append(
                    "%s/%s is installable but names no destination"
                    % (_entry["id"], _req.get("name"))
                )
    print("PASS %-52s %r" % ("every installable requirement is complete", True))

    # A flatpak reads and writes inside its own sandbox, so both the firmware
    # destination and anything the setup edits have to be under it. Getting the
    # branch of that path wrong is the live failure mode -- DuckStation's BIOS
    # folder was under `data/` when it follows XDG_CONFIG_HOME and is really
    # under `config/` -- and this at least catches a path aimed at the wrong
    # application entirely, which looks identical in review.
    for _entry in emu_catalog.CATALOG:
        _src = _entry.get("source") or {}
        if _src.get("kind") != "flatpak":
            continue
        _sandbox = ".var/app/%s/" % _src["id"]
        _paths = [_req["dest"] for _req in _entry.get("firmware") or [] if _req.get("dest")]
        # A requirement that points a setting at what it installed writes into
        # the emulator's own config, which is inside the sandbox too.
        _paths += [
            _req["configure"]["path"]
            for _req in _entry.get("firmware") or []
            if _req.get("configure")
        ]
        _paths += list(((_entry.get("setup") or {}).get("files") or {}))
        for _path in _paths:
            if not _path.startswith(_sandbox):
                failures.append(
                    "%s writes to %s, outside %s" % (_entry["id"], _path, _sandbox)
                )
    print("PASS %-52s %r" % ("every path stays inside the emulator's sandbox", True))
finally:
    sysenv.user_home = _real_user_home


if __name__ == "__main__":
    summary()
