#!/usr/bin/env python3
"""Switch updates and DLC: told apart without keys, and handed to Ryujinx.

    python scripts/tests/test_game_content.py

Every package here is built from the PFS0 layout, with made-up title ids,
rather than taken from anything real.
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import gamecontent  # noqa: E402
import switch_content  # noqa: E402
from emulator_catalog import ryujinx, schema  # noqa: E402

_ROOT = os.path.join(TMP, "game-content")
_INBOX = os.path.join(_ROOT, "transfer")
_GAMES = os.path.join(_ROOT, "Ryujinx", "games")
_ELSEWHERE = os.path.join(_ROOT, "sdcard")
for _folder in (_INBOX, _GAMES, _ELSEWHERE):
    os.makedirs(_folder, exist_ok=True)

_GAME = 0x01009990AB12C000
_UPDATE = _GAME | 0x800
_DLC = _GAME + 0x1003
_OTHER = 0x0100777712340000
_GAME_HEX = "%016x" % _GAME
_APP = "4000000001"


def nsp(path, files):
    """A PFS0 package holding `files`, a list of (name, bytes)."""
    names = b""
    name_offsets = []
    for name, _blob in files:
        name_offsets.append(len(names))
        names += name.encode("utf-8") + b"\0"
    table = b""
    data = b""
    for (_name, blob), name_at in zip(files, name_offsets):
        table += struct.pack("<QQII", len(data), len(blob), name_at, 0)
        data += blob
    header = b"PFS0" + struct.pack("<II", len(files), len(names)) + b"\0\0\0\0"
    with open(path, "wb") as handle:
        handle.write(header + table + names + data)
    return path


def ticket(title_id):
    return ("%016x%016x.tik" % (title_id, 12), b"t" * 64)


def cnmt(kind, title_id, version=0, original=None):
    """A `.cnmt.xml` shaped like a real one: `OriginalId` after the contents."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n<ContentMeta>\n'
        "  <Type>%s</Type>\n  <Id>0x%016x</Id>\n  <Version>%d</Version>\n"
        "  <Content>\n    <Type>Program</Type>\n    <Id>aaaa</Id>\n  </Content>\n"
        % (kind, title_id, version)
    )
    if original is not None:
        body += "  <OriginalId>0x%016x</OriginalId>\n" % original
    body += "</ContentMeta>\n"
    return ("%032x.cnmt.xml" % title_id, body.encode("utf-8"))


def game_file(folder, name="Some Game.nsp"):
    return nsp(os.path.join(folder, name), [
        ticket(_GAME), ("11.nca", b"program"), ("22.cnmt.nca", b"meta")])


def update_file(folder, version_label, release, name=None):
    return nsp(os.path.join(folder, name or "Some Game v%s.nsp" % version_label), [
        ticket(_UPDATE), cnmt("Patch", _UPDATE, release, _GAME),
        ("33.nca", b"program"), ("44.cnmt.nca", b"meta")])


def dlc_file(folder, name="Some Game [DLC Extra].nsp"):
    return nsp(os.path.join(folder, name), [
        ticket(_DLC), ("55.cnmt.nca", b"meta"), ("66.nca", b"data")])


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def ryujinx_files():
    folder = os.path.join(_GAMES, _GAME_HEX)
    updates = os.path.join(folder, "updates.json")
    dlc = os.path.join(folder, "dlc.json")
    return (read_json(updates) if os.path.exists(updates) else None,
            read_json(dlc) if os.path.exists(dlc) else None)


section("what a package is, read from its unencrypted listing")

_base = switch_content.inspect(game_file(_ROOT))
check("a game with only a ticket is a game",
      (_base["kind"], _base["base_id"], _base["evidence"]), ("base", _GAME_HEX, "ticket"))

_upd = switch_content.inspect(update_file(_ROOT, "2.0.2", 6 << 16))
check("an update says so in its XML, and names the game it patches",
      (_upd["kind"], _upd["base_id"], _upd["evidence"]), ("update", _GAME_HEX, "cnmt"))
check("even though the game's id comes after the content list, where real ones put it",
      _upd["base_id"], _GAME_HEX)
check("its version is the one in the filename", _upd["version"], "2.0.2")
check("and its release counter is kept to order two updates", _upd["release"], 6 << 16)

_dlc = switch_content.inspect(dlc_file(_ROOT))
check("a DLC with only a ticket still belongs to its game",
      (_dlc["kind"], _dlc["base_id"]), ("dlc", _GAME_HEX))
check("and what Ryujinx loads from it is every NCA but the meta one",
      _dlc["data_ncas"], ["/66.nca"])

_named = nsp(os.path.join(_ROOT, "Converted [%016X][v0].nsp" % _UPDATE),
             [("77.nca", b"program"), ("88.cnmt.nca", b"meta")])
check("a package with no ticket and no XML falls back to the id in its name",
      (switch_content.inspect(_named)["kind"], switch_content.inspect(_named)["evidence"]),
      ("update", "filename"))

_merged = nsp(os.path.join(_ROOT, "Merged.nsp"), [ticket(_GAME), ticket(_UPDATE)])
check("a package carrying the game and its update is the game",
      switch_content.inspect(_merged)["kind"], "base")

_two_games = nsp(os.path.join(_ROOT, "Odd.nsp"), [ticket(_GAME), ticket(_OTHER)])
check("two games in one file is not something to guess about",
      switch_content.inspect(_two_games)["kind"], "")

with open(os.path.join(_ROOT, "notes.nsp"), "wb") as _handle:
    _handle.write(b"hello, this is not a package")
check("a file that is not a package is nothing",
      switch_content.inspect(os.path.join(_ROOT, "notes.nsp"))["kind"], "")

with open(os.path.join(_ROOT, "huge.nsp"), "wb") as _handle:
    _handle.write(b"PFS0" + struct.pack("<II", 10_000_000, 16) + b"\0" * 8)
check("and a header claiming millions of files is refused rather than believed",
      switch_content.entries(os.path.join(_ROOT, "huge.nsp")), None)

check("a release counter in a filename is not a version anybody reads",
      switch_content.version_label("Some Game [v393216].nsp"), "")


section("installing refuses what is not this game's")

_other_update = nsp(os.path.join(_INBOX, "Other Game v1.0.1.nsp"),
                    [ticket(_OTHER | 0x800)])
check("a game is not an update",
      "Add it as a game" in gamecontent.check(game_file(_INBOX), _GAME_HEX)[1], True)
check("an update for another game is refused",
      "different game" in gamecontent.check(_other_update, _GAME_HEX)[1], True)
check("so is a file that cannot be identified",
      "Could not tell" in gamecontent.check(os.path.join(_ROOT, "notes.nsp"), _GAME_HEX)[1],
      True)
check("and a file that is not an NSP at all",
      "Only .nsp" in gamecontent.check(os.path.join(_ROOT, "x.xci"), _GAME_HEX)[1]
      or "not there" in gamecontent.check(os.path.join(_ROOT, "x.xci"), _GAME_HEX)[1],
      True)
check("nothing was kept for any of them", gamecontent.listing(_APP), [])


section("installing takes the file out of the transfer folder, and copies from anywhere else")

_sent = update_file(_INBOX, "1.0.1", 1 << 16)
_row, _error = gamecontent.add(_APP, _sent, _GAME_HEX, _INBOX)
check("an update sent to the Deck is kept", (bool(_row), _error), (True, ""))
check("and is no longer in the transfer folder", os.path.exists(_sent), False)

_kept_on_card = update_file(_ELSEWHERE, "2.0.2", 6 << 16)
_row, _error = gamecontent.add(_APP, _kept_on_card, _GAME_HEX, _INBOX)
check("an update somebody keeps elsewhere is kept too", (bool(_row), _error), (True, ""))
check("without moving theirs", os.path.exists(_kept_on_card), True)

_again = update_file(_INBOX, "2.0.2", 6 << 16)
_row, _error = gamecontent.add(_APP, _again, _GAME_HEX, _INBOX)
check("the same package sent twice is not kept twice",
      len(gamecontent.listing(_APP)), 2)
check("and the second copy leaves the transfer folder anyway", os.path.exists(_again), False)

gamecontent.add(_APP, dlc_file(_INBOX), _GAME_HEX, _INBOX)
check("the list is the newest update first, then the DLC",
      [(one["label"], one["used"]) for one in gamecontent.rows(_APP)],
      [("Update v2.0.2", True), ("Update v1.0.1", False), ("DLC", True)])


section("what Ryujinx is told")

_theirs = update_file(_ELSEWHERE, "0.9.0", 0, name="Added in Ryujinx.nsp")
_gone = os.path.join(_ELSEWHERE, "Deleted since.nsp")
_their_dlc = dlc_file(_ELSEWHERE, name="Their DLC.nsp")
os.makedirs(os.path.join(_GAMES, _GAME_HEX), exist_ok=True)
with open(os.path.join(_GAMES, _GAME_HEX, "updates.json"), "w", encoding="utf-8") as _handle:
    json.dump({"selected": _theirs, "paths": [_theirs, _gone]}, _handle)
with open(os.path.join(_GAMES, _GAME_HEX, "dlc.json"), "w", encoding="utf-8") as _handle:
    json.dump([{"path": _their_dlc, "dlc_nca_list": [
        {"path": "/66.nca", "title_id": _DLC, "is_enabled": True}]}], _handle)

check("writing succeeds", gamecontent.sync(_APP, _GAME_HEX, _GAMES), "")
_updates, _dlcs = ryujinx_files()
_newest = os.path.join(gamecontent.store_dir(_APP), "Some Game v2.0.2.nsp")
check("the newest update kept here is the one Ryujinx runs", _updates["selected"], _newest)
check("an update added in Ryujinx's own window is still on its list",
      _theirs in _updates["paths"], True)
check("one pointing at a file that is gone is dropped", _gone in _updates["paths"], False)
check("the DLC is listed with its data NCA and its own title id as a number",
      [one for one in _dlcs if one["path"].startswith(gamecontent.store_dir(_APP))][0]
      ["dlc_nca_list"],
      [{"path": "/66.nca", "title_id": _DLC, "is_enabled": True}])
check("and a DLC Ryujinx got from elsewhere is kept", _their_dlc in [one["path"] for one in _dlcs],
      True)

_ours = [one for one in _dlcs if one["path"].startswith(gamecontent.store_dir(_APP))][0]
_ours["dlc_nca_list"][0]["is_enabled"] = False
with open(os.path.join(_GAMES, _GAME_HEX, "dlc.json"), "w", encoding="utf-8") as _handle:
    json.dump(_dlcs, _handle)
gamecontent.sync(_APP, _GAME_HEX, _GAMES)
check("a DLC switched off in Ryujinx stays off when the list is rewritten",
      [one for one in ryujinx_files()[1] if one["path"] == _ours["path"]][0]
      ["dlc_nca_list"][0]["is_enabled"], False)

check("removing the newest update", gamecontent.remove(_APP, "Some Game v2.0.2.nsp"), "")
gamecontent.sync(_APP, _GAME_HEX, _GAMES)
check("puts the one before it in charge",
      os.path.basename(ryujinx_files()[0]["selected"]), "Some Game v1.0.1.nsp")
check("and the removed one is off the list",
      any("v2.0.2" in path for path in ryujinx_files()[0]["paths"]), False)

check("a game with nothing kept gets no files written for it",
      (gamecontent.sync("4000000002", "%016x" % _OTHER, _GAMES),
       os.path.exists(os.path.join(_GAMES, "%016x" % _OTHER))),
      ("", False))


section("removing the game takes its updates and DLC with it")

_freed = gamecontent.forget(_APP, _GAMES)
check("the kept files are deleted and counted", (_freed > 0, gamecontent.listing(_APP)),
      (True, []))
_updates, _dlcs = ryujinx_files()
check("Ryujinx's list no longer names them",
      (_updates["selected"], [os.path.basename(path) for path in _updates["paths"]]),
      ("", ["Added in Ryujinx.nsp"]))
check("while what came from elsewhere is left", [one["path"] for one in _dlcs], [_their_dlc])


section("the catalog says where, and only somewhere the emulator owns")

check("Ryujinx's entry is valid with it",
      [one for one in schema.validate(ryujinx.ENTRY) if "game_content" in one], [])
check("a game's updates go under Ryujinx's own config folder",
      gamecontent.games_root_for("emu:ryujinx").replace("\\", "/")
      .endswith("io.github.ryubing.Ryujinx/config/Ryujinx/games"), True)
check("and a game on any other emulator has nowhere to put them",
      gamecontent.games_root_for("snes9x_libretro"), "")

_escaping = dict(ryujinx.ENTRY, game_content={"format": "ryujinx", "path": ".ssh"})
check("a path outside what the emulator owns is refused",
      any("game_content path" in one for one in schema.validate(_escaping)), True)
_unknown = dict(ryujinx.ENTRY, game_content={"format": "not-a-format",
                                             "path": ryujinx.ENTRY["game_content"]["path"]})
check("and so is a format nothing here writes",
      any("game_content format" in one for one in schema.validate(_unknown)), True)


section("a package sent to the Deck knows which added game it is for")

_library_rom = game_file(_ELSEWHERE, name="Library Game.nsp")
_library = {
    "5000000001": {"app_id": 5000000001, "title": "Some Game",
                   "core_id": "emu:ryujinx", "rom_path": _library_rom},
    "5000000002": {"app_id": 5000000002, "title": "A SNES game",
                   "core_id": "snes9x_libretro", "rom_path": _library_rom},
}
_waiting = update_file(_INBOX, "3.0.0", 7 << 16)
check("an update names the game it belongs to, so Install needs no question",
      gamecontent.owner(_waiting, _library),
      {"kind": "update", "label": "Update v3.0.0", "app_id": 5000000001,
       "title": "Some Game", "problem": ""})
check("a DLC does too", gamecontent.owner(dlc_file(_INBOX), _library)["app_id"], 5000000001)

_orphan = gamecontent.owner(_other_update, _library)
check("an update whose game is not in the library has nowhere to go, and says so",
      (_orphan["app_id"], "Add the game first" in _orphan["problem"]), (0, True))
check("only a game on an emulator that takes updates counts",
      gamecontent.owner(_waiting, {"1": dict(_library["5000000002"])})["app_id"], 0)
check("a game is nobody's update", gamecontent.owner(game_file(_INBOX), _library), None)
check("and nor is anything that is not an NSP",
      gamecontent.owner(os.path.join(_ROOT, "Some Game.xci"), _library), None)


section("a game sent with its updates and DLC finds them beside it")

_TOGETHER = os.path.join(_ROOT, "sent-together")
os.makedirs(_TOGETHER, exist_ok=True)
_together_game = game_file(_TOGETHER, name="Some Game.nsp")
update_file(_TOGETHER, "1.0.1", 1 << 16)
update_file(_TOGETHER, "2.0.2", 6 << 16)
dlc_file(_TOGETHER, name="Some Game [DLC].nsp")
nsp(os.path.join(_TOGETHER, "Other Game v1.0.1.nsp"), [ticket(_OTHER | 0x800)])
check("its updates, newest first, then its DLC -- and nothing for another game",
      [one["label"] for one in gamecontent.waiting_for(_together_game)],
      ["Update v2.0.2", "Update v1.0.1", "DLC"])
check("an update has nothing waiting for it, since it is not a game",
      gamecontent.waiting_for(os.path.join(_TOGETHER, "Some Game v2.0.2.nsp")), [])
check("and a file that cannot be identified finds nothing",
      gamecontent.waiting_for(os.path.join(_ROOT, "notes.nsp")), [])


section("only removing a game deletes its updates and DLC, not forgetting its record")

import inspect  # noqa: E402

import plugin_audit  # noqa: E402
import plugin_library  # noqa: E402

# The library check's Forget repairs a record that drifted -- a shortcut deleted
# in Steam, one pointing at the wrong game -- and says only the record goes. It
# briefly deleted a game's kept updates and DLC as well, gigabytes, silently.
check("forgetting a record leaves the game's updates and DLC",
      "gamecontent" in inspect.getsource(plugin_audit.Audit.forget_games), False)
check("removing the game deletes them",
      "gamecontent.forget" in inspect.getsource(plugin_library.Library.unregister_game), True)
check("and so does clearing the library",
      "gamecontent.forget" in inspect.getsource(plugin_library.Library.clear_library), True)


if __name__ == "__main__":
    summary()
