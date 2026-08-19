#!/usr/bin/env python3
"""Every emulator entry is well formed, and the catalog is the only launch table.

    python scripts/tests/test_catalog.py

Run this after adding an emulator. Everything it checks fails silently
otherwise: a misspelt field is ignored rather than rejected, an `args` string
with no `{rom}` starts the emulator with no game, and a system missing from
`MANUAL_EXTENSIONS` leaves the emulator matching no ROM at all on a Deck whose
cached libretro index happens to predate that database.

The failure that prompted the last check here is worth stating plainly, because
it is the one a second table always produces. Launch recipes were written twice
-- once per catalog entry and once in `emulators.LAUNCH_HINTS` -- and drifted:
installing RPCS3 from the catalog set `--fullscreen`, while registering the same
flatpak by hand was told the fullscreen switch was `--no-gui`. Four of the seven
emulators in both lists disagreed. The hints are derived from the catalog now,
and this file checks that they stay derived.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402  -- installs the decky stub

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402
import platforms  # noqa: E402
from emulator_catalog import schema  # noqa: E402

section("the emulator catalog -- every entry is well formed")

_KNOWN_PLATFORMS = [label for label, _full, _short in platforms.NO_LIBRETRO_PLATFORMS]

_problems = []
for _entry in emulator_catalog.CATALOG:
    _problems.extend(schema.validate(_entry, _KNOWN_PLATFORMS))
check("no entry has a problem the schema can see", _problems, [])

# Not a tautology: the validator must actually reject things. If `validate` ever
# returns [] unconditionally the check above passes and means nothing.
check("and the validator rejects a broken entry",
      len(schema.validate({"id": "Bad Id", "name": "x", "summary": "x",
                           "source": {"kind": "flatpak"},
                           "args": "--go", "fullscreen_arg": "-f"})) >= 5,
      True)
check("a misspelt field is named, not ignored",
      any("fullscreen_arg" in problem
          for problem in schema.validate({"id": "x", "name": "x", "summary": "x",
                                          "source": {"kind": "flatpak", "id": "a.b"},
                                          "args": "{rom}", "databases": ["A"],
                                          "fullscreen_arg": "-f"})),
      True)

check("ids are unique",
      len({entry["id"] for entry in emulator_catalog.CATALOG}),
      len(emulator_catalog.CATALOG))
check("every id is usable as a directory name",
      [entry["id"] for entry in emulator_catalog.CATALOG
       if not emulator_catalog.is_safe_id(entry["id"])],
      [])

# Each module contributes exactly one entry, and none was written and then left
# out of `_MODULES` -- which is the way this package fails now that adding an
# emulator is two edits rather than one.
check("every module in the package is in the catalog",
      sorted(module.__name__.rsplit(".", 1)[-1]
             for module in emulator_catalog._MODULES),
      sorted(name[:-3] for name in os.listdir(os.path.dirname(emulator_catalog.__file__))
             if name.endswith(".py")
             and name not in ("__init__.py", "schema.py", "steam_pad.py",
                              "imported.py")))

# Stated in the package docstring as the thing no entry may depend on: the
# derived extension list can come back empty from a stale libretro index, so
# every system an entry claims needs a floor.
_unfloored = sorted(
    key
    for entry in emulator_catalog.CATALOG
    for key in emulator_catalog._system_keys(entry)
    if key not in emulator_catalog.MANUAL_EXTENSIONS
)
check("every system an entry claims has a MANUAL_EXTENSIONS floor", _unfloored, [])
check("so an entry still matches ROMs with no libretro data at all",
      [entry["id"] for entry in emulator_catalog.CATALOG
       if not emulator_catalog.extensions_for(entry, {})],
      [])


section("launch recipes -- written once")

_hints = emulator_catalog.launch_hints()
check("the hints are derived, not a second table",
      emulators.launch_hints is emulator_catalog.launch_hints, True)

# The check that would have caught the drift. Every catalog entry must be
# described by its own recipe when looked up the way a hand-registered emulator
# is looked up -- by flatpak id, and by the binary name inside it.
_disagree = []
for _entry in emulator_catalog.CATALOG:
    for _target in {_entry["id"], (_entry.get("source") or {}).get("id") or _entry["id"]}:
        _got = emulators.suggest_launch_options(_target)
        _want = {"args": _entry.get("args") or "{rom}",
                 "fullscreen_args": _entry.get("fullscreen_args") or ""}
        if _got != _want:
            _disagree.append((_entry["id"], _target, _got, _want))
check("every entry suggests its own arguments", _disagree, [])

check("RPCS3's fullscreen switch is the one the catalog installs",
      emulators.suggest_launch_options("net.rpcs3.RPCS3")["fullscreen_args"],
      "--fullscreen")
check("PCSX2 is suggested the recipe that skips the GUI",
      emulators.suggest_launch_options("net.pcsx2.PCSX2")["args"],
      "-nogui -- {rom}")

# A binary is matched by name, so a path to one works as well as a flatpak id.
check("an emulator is recognised from its path",
      emulators.suggest_launch_options("/x/Dolphin-x86_64.AppImage")["args"],
      "-b -e {rom}")
check("case insensitively",
      emulators.suggest_launch_options("/x/DUCKSTATION.AppImage")["args"],
      "-nogui -- {rom}")
# Nothing outside the catalog gets a recipe. A launch recipe is support for the
# emulator it names, so it lives on that emulator's entry or nowhere.
check("and an emulator that is not in the catalog gets nothing rather than a guess",
      emulators.suggest_launch_options("/x/mystery"),
      {"args": "", "fullscreen_args": ""})

check("every recipe places the ROM",
      [needle for needle, args, _fs in _hints if "{rom}" not in args], [])
check("and no fullscreen switch swallows it",
      [needle for needle, _a, fullscreen in _hints if "{rom}" in fullscreen], [])

# Every recipe traces back to an entry. Without this the table could regrow a
# side list of emulators the catalog does not install, which is the arrangement
# that let the two halves drift in the first place.
check("every recipe belongs to a catalog entry",
      [needle for needle, _a, _f in _hints
       if not any(needle in entry["id"].lower()
                  or needle in ((entry.get("source") or {}).get("id") or "").lower()
                  for entry in emulator_catalog.CATALOG)],
      [])




section("the messages an emulator writes over somebody's game")

# Dolphin prints its version, controller connections, save states and speed
# changes into the top-left corner of the game. On a desktop that is a status
# line; on a game Steam just launched it is text over the first seconds of
# play, about things nobody asked and cannot act on -- the same argument that
# turns RetroArch's on-screen chatter off by default.
_dolphin = emulator_catalog.find("dolphin")
_ini = next(
    spec for path, spec in _dolphin["setup"]["files"].items() if path.endswith("Dolphin.ini")
)

# The section is the part worth pinning: a key under the wrong heading is not an
# error, it is silently ignored, and the setting stays on. Confirmed twice --
# the string is in the installed binary, and RetroDECK's own Deck-tested
# Dolphin.ini carries it under [Interface].
check("Dolphin's on-screen messages are turned off",
      _ini.get("Interface", {}).get("OnScreenDisplayMessages", {}).get("value"), "False")
check("and the setting says what Dolphin's own default is, so a chosen value survives",
      _ini["Interface"]["OnScreenDisplayMessages"].get("default"), "True")
# Recommended settings are applied once, at install, and `needs_setup` compares
# this number -- so a change to the values that does not raise it reaches
# nobody who already has the emulator, silently.
check("the setup version rose with them", _dolphin["setup"]["version"] >= 4, True)


if __name__ == "__main__":
    from harness import summary

    summary()
