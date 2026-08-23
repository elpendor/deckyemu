#!/usr/bin/env python3
"""Emulator definitions supplied by the user, and what they are not allowed to do.

    python scripts/tests/test_imported.py

A catalog entry is not data the plugin reads -- it is a list of actions the
plugin performs, with the user's privileges. A bundled entry is written by
someone with commit access and reviewed as code. An imported one arrives as a
file from anywhere, so `schema.validate(..., imported=True)` refuses the actions
that fetch software or delete things, and confines every write to the one
directory the entry declares.

Most of this file is that refusal, checked one capability at a time. They are
worth checking individually because each is a different consequence and a
blanket "the entry was rejected" would pass even if only the first rule fired.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402  -- installs the decky stub

import emulator_catalog  # noqa: E402
from emulator_catalog import imported, schema  # noqa: E402

_KNOWN = ["Nintendo - Switch"]


def _definition(**overrides):
    """A definition that is valid, so a test can make exactly one thing wrong."""
    entry = {
        "id": "testemu",
        "name": "Test Emulator",
        "summary": "Nintendo Switch.",
        "source": {"kind": "byo"},
        "args": "-g {rom}",
        "fullscreen_args": "-f",
        "platform": "Nintendo - Switch",
        "root": ".config/testemu",
    }
    entry.update(overrides)
    return entry


def _problems(**overrides):
    return schema.validate(_definition(**overrides), _KNOWN, imported=True)


section("an imported definition -- the shape that is accepted")

check("a plain bring-your-own definition is accepted", _problems(), [])
# Bundled entries may be bring-your-own too -- that is how this project would
# ship a recipe for an emulator it will not distribute. The strict rules are
# about where an entry came from, not about its source kind.
check("and the same shape is valid as a bundled entry",
      schema.validate(_definition(), _KNOWN), [])
# The check above is only worth something if validate rejects things at all.
check("while a bundled entry with a bad source kind is still caught",
      any("not one of" in p for p in schema.validate(
          _definition(source={"kind": "torrent"}), _KNOWN)),
      True)

_entry, _error = imported.parse(json.dumps(_definition()), _KNOWN)
check("it parses", _error, "")
check("and is marked as imported, which is what the panel shows",
      _entry["imported"], True)

check("a format from the future is refused rather than half-read",
      "understands up to" in imported.parse(
          json.dumps(_definition(format=99)), _KNOWN)[1],
      True)
check("and text that is not JSON says so",
      "not valid JSON" in imported.parse("{oops", _KNOWN)[1], True)
check("and a JSON array is not a definition",
      "has to be a JSON object" in imported.parse("[]", _KNOWN)[1], True)


section("a setup block has to name what it writes")

# emu_config._files_of reads `files`, or else subscripts `path` and `sections`
# directly. A block with neither raised KeyError part-way through the install
# instead of being refused here -- naming a private function rather than the
# definition that caused it, and for an imported entry that is a file from
# outside crashing an install somebody asked for.
check("a block with neither files nor path is refused",
      any("either 'files'" in p for p in _problems(setup={"format": "ini"})), True)
check("a path with no sections is refused too, since nothing would be written",
      any("no 'sections'" in p for p in _problems(setup={"path": ".config/x/y.ini"})),
      True)
# Both shapes are in real use by the bundled catalog, so neither may be broken.
check("the files shape is accepted",
      _problems(setup={"files": {".config/testemu/a.ini": {"S": {}}}}), [])
check("and so is path with sections",
      _problems(setup={"path": ".config/testemu/a.ini", "sections": {"S": {}}}), [])
check("a misspelt setup key is caught rather than ignored",
      any("'sctions'" in p for p in
          _problems(setup={"path": ".config/testemu/a.ini", "sctions": {}})),
      True)
# The rule applies to bundled entries as well: this file is the reference for
# writing one, and a bundled block with neither shape fails the same way.
check("a bundled entry is held to it too",
      any("either 'files'" in p
          for p in schema.validate(_definition(setup={"format": "ini"}), _KNOWN)),
      True)
# And the confinement rule still runs over whichever shape is used.
check("a setup file outside the declared root is still refused",
      any("outside this entry's root" in p
          for p in _problems(setup={"files": {".ssh/authorized_keys": {"S": {}}}})),
      True)

section("what an imported definition may not do")

# Installing the emulator it describes is allowed, and is the point: the
# alternative is downloading a build by hand and re-pointing at it on every
# update, which is friction rather than safety. Someone importing a definition
# has already decided to trust it, and is told so before anything is fetched.
check("it may install the emulator it describes, from a flatpak",
      _problems(source={"kind": "flatpak", "id": "dev.example.App"}), [])
check("or from a release",
      _problems(source={"kind": "github", "repo": "x/y", "asset": r"^a\.AppImage$"}), [])
check("or from a release on a forge that is not GitHub",
      _problems(source={"kind": "github", "host": "git.example.com",
                        "repo": "x/y", "asset": r"^a\.AppImage$"}), [])
check("a release source without an asset pattern is refused, since the wrong "
      "architecture installs and then dies at exec time",
      any("'asset'" in p for p in _problems(source={"kind": "github", "repo": "x/y"})),
      True)
check("and a host has to be a host, not a URL",
      any("not a URL" in p for p in _problems(
          source={"kind": "github", "host": "https://git.example.com/x",
                  "repo": "x/y", "asset": "^a$"})),
      True)

# What stays refused is everything that is not "install the emulator you asked
# for". Each fails differently on a real device.

# `removes` is passed to a delete that only checks the path stays under the
# home directory -- which also holds Steam's data and the user's ssh keys.
check("it may not delete anything",
      any("removes" in p and "deletes directory trees" in p
          for p in _problems(firmware=[{"name": "f", "dest": ".config/testemu/f",
                                        "removes": [".local/share/Steam"]}])),
      True)
check("nor name paths for the reset tab to wipe",
      any("'data'" in p for p in _problems(data=[".local/share/Steam"])), True)
check("nor fetch a helper binary",
      any("'helper'" in p for p in _problems(helper={"name": "x", "url": "http://x"})),
      True)

# Writes are confined to the entry's own root rather than merely to the home
# directory, which is the difference between overwriting its own config and
# overwriting .bashrc.
check("it may not write outside its declared root",
      any(".bashrc" in p and "outside this entry's root" in p
          for p in _problems(firmware=[{"name": "f", "dest": ".bashrc"}])),
      True)
check("and that applies to seeded settings too",
      any("outside this entry's root" in p for p in _problems(
          setup={"format": "plain-ini", "path": ".config/other/x.ini",
                 "sections": {"S": {}}})),
      True)
check("writing inside the root is fine",
      _problems(firmware=[{"name": "f", "dest": ".config/testemu/keys/prod.keys"}]),
      [])
check("a definition with no root is refused, since nothing could be confined",
      any("needs 'root'" in p for p in _problems(root=None)), True)

# Emulators that follow the XDG layout do not have one directory: settings go
# under ~/.config/<name> and keys and saves under ~/.local/share/<name>. A
# definition that seeds bindings *and* says where a key file goes needs both,
# which a single root could not express.
check("root may be a list, for emulators that split config and data",
      _problems(root=[".config/testemu", ".local/share/testemu"],
                firmware=[{"name": "keys", "dest": ".local/share/testemu/keys"}],
                setup={"format": "plain-ini", "path": ".config/testemu/qt-config.ini",
                       "sections": {"S": {}}}),
      [])
check("and a path outside every one of them is still refused",
      any("outside this entry's roots" in p for p in _problems(
          root=[".config/testemu", ".local/share/testemu"],
          firmware=[{"name": "keys", "dest": ".config/other/keys"}])),
      True)
check("and a root that escapes home is refused",
      any("must be a plain relative path" in p for p in _problems(root="../../etc")),
      True)
check("a root that is a prefix by string but not by path does not count",
      any("outside this entry's root" in p for p in _problems(
          root=".config/testemu",
          firmware=[{"name": "f", "dest": ".config/testemu-evil/f"}])),
      True)

# An installer route hands a file to the emulator and lets it run. Fine for a
# recipe this project tested; not something to accept on the word of a file.
check("it may not use an installer route",
      any("installer route" in p for p in _problems(
          firmware=[{"name": "f", "gui_install": {"prompt": "go"}}])),
      True)


section("loading them, and living beside the bundled ones")

check("the store lives under the plugin's settings, not the user's home",
      imported.STORE.endswith(os.path.join("emulators.d")), True)
# Against BUNDLED rather than a literal count. The claim is that nothing has
# been imported yet, and a number tests that only by accident -- it was 11,
# and the sole thing it ever caught was somebody adding an emulator.
check("the catalog starts as exactly the bundled entries",
      list(emulator_catalog.CATALOG), list(emulator_catalog.BUNDLED))

# The clash rule. Without it a definition could shadow a bundled emulator, which
# is a way to replace a recipe this project tested with one it did not.
imported.store_dir()
_clash = imported.path_for("dolphin")
with open(_clash, "w", encoding="utf-8") as _handle:
    json.dump(_definition(id="dolphin", name="Not Dolphin"), _handle)
emulator_catalog.reload_imported()
check("a definition may not shadow a built-in emulator",
      any("already a built-in" in p for p in emulator_catalog.import_problems), True)
check("and the built-in one is the one still in the catalog",
      next(e["name"] for e in emulator_catalog.CATALOG if e["id"] == "dolphin"),
      "Dolphin")
os.remove(_clash)

# The happy path, end to end through the store.
_saved, _save_error = imported.save(json.dumps(_definition()), _KNOWN)
check("a good definition saves", _save_error, "")
check("saving again without replace is refused rather than overwriting "
      "something the user may not be able to obtain again",
      "already imported" in imported.save(json.dumps(_definition()), _KNOWN)[1],
      True)
check("and with replace it is allowed",
      imported.save(json.dumps(_definition(summary="Updated.")), _KNOWN, True)[1],
      "")

emulator_catalog.reload_imported()
check("it reaches the catalog", "testemu" in [e["id"] for e in emulator_catalog.CATALOG], True)
check("with nothing refused", emulator_catalog.import_problems, [])
check("and the bundled entries are still all there",
      len(emulator_catalog.CATALOG), len(emulator_catalog.BUNDLED) + 1)

_listing = emulator_catalog.listing({"Nintendo - Switch": ["nsp"]})
_made = next(item for item in _listing if item["id"] == "testemu")
check("the panel is told it was imported", _made["imported"], True)
check("and is never told it was verified -- nobody here has run it",
      _made["verified"], False)
check("and it still gets extensions, which is the whole point",
      "nsp" in _made["extensions"], True)

# The registration path an imported entry actually goes through. `to_emulator`
# is what `locate_emulator` hands to `emulators.save`, and a bring-your-own
# entry has to come out of it looking like any other path-launched emulator --
# otherwise it registers and then never appears in the add-game picker.
_shaped = emulator_catalog.to_emulator(
    next(e for e in emulator_catalog.CATALOG if e["id"] == "testemu"),
    "/home/deck/Applications/TestEmu.AppImage",
    {"Nintendo - Switch": ["nsp", "xci"]},
)
check("a located binary registers as a path emulator", _shaped["kind"], "path")
check("pointed at what the user picked",
      _shaped["target"], "/home/deck/Applications/TestEmu.AppImage")
check("with the definition's launch recipe", _shaped["args"], "-g {rom}")
check("its fullscreen switch", _shaped["fullscreen_args"], "-f")
# The display name rather than the raw "Nintendo - Switch" the entry declares:
# an imported entry gets the same label treatment a bundled one does, which is
# what makes its games land in the same collection as everything else.
check("and a system label, so its games group somewhere sensible",
      (_shaped["platform"], _shaped["platform_full"]), ("Switch", "Nintendo Switch"))
check("and extensions, without which no ROM would ever match it",
      "nsp" in _shaped["extensions"], True)

check("removing it takes it out of the catalog",
      (imported.remove("testemu")[0],
       emulator_catalog.reload_imported() == []),
      (True, True))
check("and removing one that is not there says so rather than succeeding",
      imported.remove("testemu")[1] != "", True)

# A bad file must not take the catalog -- and every bundled emulator -- with it.
with open(imported.path_for("broken"), "w", encoding="utf-8") as _handle:
    _handle.write("{ not json")
emulator_catalog.reload_imported()
check("an unreadable definition is skipped, not fatal",
      len(emulator_catalog.CATALOG), len(emulator_catalog.BUNDLED))
check("and it is reported, because an emulator that never appears is "
      "indistinguishable from sending the wrong file",
      len(emulator_catalog.import_problems), 1)
os.remove(imported.path_for("broken"))
emulator_catalog.reload_imported()


section("forgetting a definition takes its install with it")

# The leak this closes. Removing the definition drops the catalog entry, and
# with it the row and every button on it -- so an emulator this plugin
# downloaded would sit in ~/deckyemu/emulators with nothing able to reach it: a
# hundred megabytes made unreachable through the UI that put it there. The
# uninstall therefore has to happen while the entry still exists.
import emu_install  # noqa: E402

_downloading = _definition(
    id="fetchemu",
    source={"kind": "github", "repo": "x/y", "asset": r"^a\.AppImage$"},
    root=".config/fetchemu",
)
imported.save(json.dumps(_downloading), _KNOWN, True)
emulator_catalog.reload_imported()

# Stand in for a completed download: the folder an AppImage install creates.
_dir = emu_install.emulators_dir("fetchemu")
with open(os.path.join(_dir, "a.AppImage"), "w", encoding="utf-8") as _handle:
    _handle.write("#!/bin/sh" + chr(10))
check("an imported definition can have an install of its own",
      bool(emu_install.installed_appimage("fetchemu")), True)
check("which is reachable only while the entry exists",
      emulator_catalog.find("fetchemu") is not None, True)

check("removing that install works",
      (emu_install.remove_appimage("fetchemu")[0], os.path.isdir(_dir)),
      (True, False))

imported.remove("fetchemu")
emulator_catalog.reload_imported()
check("and afterwards the entry is gone, so nothing could have reached it",
      emulator_catalog.find("fetchemu"), None)


section("the documented example is a working one")

# docs/emulator-definitions.md tells people to copy this block. An example that
# no longer validates is worse than none: it sends the reader hunting for their
# own mistake. Parsed straight out of the document, so the two cannot drift.
import re  # noqa: E402

_doc = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "emulator-definitions.md")
with open(_doc, "r", encoding="utf-8") as _handle:
    _text = _handle.read()

_fence = chr(96) * 3
_block = re.search(_fence + r"json\n(\{.*?\n\})\n" + _fence, _text, re.S)
check("the document still carries a worked example", _block is not None, True)
_parsed, _doc_error = imported.parse(_block.group(1), _KNOWN)
check("and it validates", _doc_error, "")
# Not just syntactically valid: an example that matches no ROM teaches nothing.
check("and would actually match a ROM",
      bool(emulator_catalog.extensions_for(_parsed, {})), True)

# Every field the document names in a table must be one the schema knows, or the
# reader is being told to write something that will be rejected as misspelt.
_named = set(re.findall(r"^\| `([a-z_]+)`", _text, re.M))
_known = set(schema.REQUIRED) | set(schema.OPTIONAL)
check("every documented entry field exists in the schema",
      sorted(_named - _known - {"name", "note", "match", "expects", "optional",
                                "dest", "manual", "detect", "sizes", "lower_ext"}),
      [])


section("the two halves agree on what a definition file is called")

# The frontend decides whether to offer Import by matching this suffix. If the
# two disagree the button never appears and the file looks like a ROM the picker
# cannot read -- silent on both sides.
_transfer = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src", "TransferModal.tsx")
with open(_transfer, "r", encoding="utf-8") as _handle:
    _source = _handle.read()
check("the frontend uses the suffix the backend writes",
      'const DEFINITION_SUFFIX = "%s";' % imported.SUFFIX in _source, True)


if __name__ == "__main__":
    from harness import summary

    summary()
