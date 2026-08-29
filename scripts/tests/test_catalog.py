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
import steam_layouts  # noqa: E402
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
                              "deck_gyro.py", "imported.py")))

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

# An entry with no fullscreen switch has to reach fullscreen some other way, and
# the only other way is its own config. This is the failure with no symptom:
# drop the setup block and nothing errors, no test fails, and every game just
# launches in a window on a handheld that has no way to un-window it.
#
# Dolphin and Azahar have no fullscreen flag at all, so their config is the only
# route. Xenia is not in this list even though it also seeds one: it has a real
# flag *and* a config key, because the config only takes effect once Xenia has
# written a file to merge into, and the first launch happens before that.
def _mentions_fullscreen(value):
    if isinstance(value, dict):
        return any(_mentions_fullscreen(k) or _mentions_fullscreen(v)
                   for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_mentions_fullscreen(item) for item in value)
    return isinstance(value, str) and "fullscreen" in value.lower()


_no_switch = [entry["id"] for entry in emulator_catalog.CATALOG
              if not (entry.get("fullscreen_args") or "")]
check("the entries with no fullscreen switch are the ones expected to have none",
      sorted(_no_switch), ["azahar", "dolphin"])
check("and each of them sets fullscreen in the emulator's own config instead",
      [entry_id for entry_id in _no_switch
       if not _mentions_fullscreen(
           emulator_catalog.find(entry_id).get("setup") or {})],
      [])

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


section("Vita3K reads the Deck's own pad, which is where its gyro is")

# Measured inside a running Gravity Rush, not read anywhere: Steam's virtual pad
# reports no sensors, and it claims the physical pad's own `28de:1205`, so
# hiding it by id is impossible and both would be visible at once -- which
# Vita3K resolves by summing their axes. Both variables are load-bearing.
_vita_entry = emulator_catalog.find("vita3k")
# Motion is a workaround now, so the environment lives in its delta rather
# than on the entry. Resolved with nothing disabled, which is what a fresh
# install gets.
_vita_on = emulator_catalog.resolve_workarounds(_vita_entry)
_vita_env = _vita_on.get("env") or {}
check("the virtual pad is denied the real controller's identity",
      _vita_env.get("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD"), "0")
check("and Steam's ignore list is replaced, which hands back the real one",
      _vita_env.get("SDL_GAMECONTROLLER_IGNORE_DEVICES"), "0x28de/0x11ff")

# An AppImage got no environment at all until this shipped, so the entry could
# carry both and every launch still see neither.
_vita_emu = emulator_catalog.to_emulator(_vita_entry, "/tmp/Vita3K.AppImage", {})
# Motion is off on a fresh install -- it costs Steam Input for every Vita
# game -- so the launch is checked against a record that has been switched on.
_vita_emu_on = dict(_vita_emu, env=_vita_env,
                    layout=_vita_on.get("layout", ""))
_vita_argv = emulators.launch_argv(_vita_emu_on, "", True, "PCSA00011")
check("it reaches the launch, ahead of the emulator",
      (_vita_argv[0], sorted(a.split("=")[0] for a in _vita_argv[1:4])),
      ("env", ["SDL_GAMECONTROLLERCONFIG",
               "SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD",
               "SDL_GAMECONTROLLER_IGNORE_DEVICES"]))
# Pressing Steam is a GUIDE press, and Vita3K toggles pause on it -- so the
# mapping it launches with must not name that button at all.
check("and the mapping it launches with hides the guide button",
      "guide:" in _vita_env.get("SDL_GAMECONTROLLERCONFIG", ""), False)
check("while keeping the buttons a game needs",
      all(part in _vita_env.get("SDL_GAMECONTROLLERCONFIG", "")
          for part in ("a:b0", "start:b6", "leftx:a0", "righttrigger:a5")),
      True)
check("and the game still starts by title id behind it",
      _vita_argv[-2:], ["-r", "PCSA00011"])
# `env` is only copied onto an installed emulator when the recipe moves, so
# shipping the variables without raising it reaches nobody who already has it.
check("the recipe rose with them", _vita_entry.get("recipe", 1) >= 6, True)

# Upstream's *builds* repo, and both halves matter. It has to be upstream: this
# named a fork for as long as the motion fix could only be had by building one,
# and that fix is four bytes applied to upstream's own build now. And it has to
# be the numbered one: `Vita3K/Vita3K` publishes a single rolling `continuous`
# release, and a build with no number cannot be compared with `fixed_in`, cannot
# be listed in the build picker, and cannot be recorded as anything useful.
check("Vita3K installs from upstream's numbered builds",
      _vita_entry["source"]["repo"], "Vita3K/Vita3K-builds")
check("and still asks for the x86_64 AppImage",
      _vita_entry["source"]["asset"], r"^Vita3K-x86_64\.AppImage$")
# Nothing else here points anywhere but upstream, and a second one appearing
# without a reason in its own comment is worth failing over.
# The Deck powers its gyro down unless the running game's Steam layout binds it,
# so the entry names the one stock template that does. Without this the emulator
# reads a sensor that never moves and everything else here is wasted.
check("Vita3K asks for a layout that binds gyro",
      _vita_on.get("layout"), steam_layouts.DERIVED_URL)
check("and it survives onto the installed emulator",
      _vita_emu_on.get("layout"), steam_layouts.DERIVED_URL)
# Derived on the device from Valve's own file rather than shipped: the source is
# theirs, and a copy taken today would rot against the next Steam update.
_stock = """"controller_mappings"
{
	"controller_type"		"controller_neptune"
	"localization" { "english" { "title" "Gamepad with Gyro"
	"description" "Valve's words." } }
	"group" { "id" "14" "mode" "gyro_to_mouse" }
}"""
_derived = steam_layouts.rewrite(_stock)
check("the derived layout sends the gyro to a stick, not the mouse",
      ('"gyro_to_joystick"' in _derived, "gyro_to_mouse" in _derived), (True, False))
check("and says whose it is, so nobody wonders what put it in Steam's list",
      "DeckyEmu" in _derived, True)
# Steam changing its template out from under this is a thing to notice, not to
# half-apply: a layout rewritten on a guess is worse than the stock one.
check("a template it does not recognise is refused",
      steam_layouts.rewrite('"controller_mappings" { "mode" "joystick_move" }'), "")
# Every other entry leaves Steam's own choice alone.
check("only the entries that read the Deck's sensors pin a layout",
      [e["id"] for e in emulator_catalog.CATALOG
       if emulator_catalog.resolve_workarounds(e).get("layout")],
      ["shadps4", "vita3k"])

check("and nothing in the catalog installs from a fork",
      [e["id"] for e in emulator_catalog.CATALOG
       if (e.get("source") or {}).get("repo", "").startswith("elpendor/")],
      [])


section("shadPS4 reads the same pad, and needs its axes rotated")

# Measured on a Deck, not read anywhere: SDL calls a DualShock's face normal +Y
# and the Deck's top-edge direction +Y, so yaw and roll land on each other and
# only pitch survives. A real 90 degree yaw arrived as -89.1 on z[2] against
# +23.5 on y[1]. `shim/gyroshim.c` rotates it back.
_shad = emulator_catalog.find("shadps4")
_shad_on = emulator_catalog.resolve_workarounds(_shad)
_shad_env = _shad_on.get("env") or {}
check("shadPS4 is handed the physical pad, which is the one with sensors",
      (_shad_env.get("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD"),
       _shad_env.get("SDL_GAMECONTROLLER_IGNORE_DEVICES")),
      ("0", "0x28de/0x11ff"))
check("and asks for the layout that powers the sensor on",
      _shad_on.get("layout"), steam_layouts.DERIVED_URL)
# The shim is named by a token because the plugin's install directory is not
# knowable when the entry is written.
check("the axis shim is preloaded, by a path resolved at launch",
      _shad_env.get("LD_PRELOAD"), "{plugin}/bin/gyroshim.so")
# The variable that was already here and decides whether anything renders at
# all. Folding motion in beside it is where it would get dropped.
check("without losing the Vulkan driver pin",
      "radeon_icd" in _shad_env.get("VK_DRIVER_FILES", ""), True)
# `env` is copied onto an installed emulator only when the recipe moves.
check("the recipe rose with them", _shad.get("recipe", 1) >= 3, True)
# Shared with Vita3K rather than copied, so there is no second copy to drift.
check("both entries launch with the same mapping",
      _shad_env.get("SDL_GAMECONTROLLERCONFIG"),
      _vita_env.get("SDL_GAMECONTROLLERCONFIG"))
check("and neither names the guide button",
      "guide:" in _shad_env.get("SDL_GAMECONTROLLERCONFIG", ""), False)
# A fresh dict per entry. Sharing the object would have handed Vita3K shadPS4's
# Vulkan pin and its preload, which a passing suite would hide.
check("and shadPS4's own variables stayed out of Vita3K's",
      sorted(k for k in ("VK_DRIVER_FILES", "LD_PRELOAD") if k in _vita_env),
      [])

# The invariant that matters more than either list, and the one a third emulator
# will trip: motion is two halves and neither is worth anything alone. The
# environment with no layout reads a sensor Steam never powers on -- which is
# exactly how shadPS4 shipped once -- and the layout with no environment powers
# on a sensor the emulator cannot see.
check("no entry takes one half of motion without the other",
      [e["id"] for e in emulator_catalog.CATALOG
       for _on in [emulator_catalog.resolve_workarounds(e)]
       if ((_on.get("env") or {}).get("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD") == "0")
       != bool(_on.get("layout"))],
      [])

# The invariant, rather than the list: motion is two halves and neither is worth
# anything alone. The environment without a layout reads a sensor Steam never
# powers on, and the layout without the environment powers on a sensor the
# emulator cannot see, because Steam's virtual pad does not have one. shadPS4 was
# briefly given both and reverted, because the axes it reads had to be rotated
# first before either half was worth anything -- and this
# is here so the next emulator cannot arrive with one of them.
check("no entry takes one half of motion without the other",
      [e["id"] for e in emulator_catalog.CATALOG
       if ((e.get("env") or {}).get("SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD") == "0")
       != bool(e.get("layout"))],
      [])



section("Workarounds -- corrections a user can decline, and only those")

# The line this field draws is the whole point of it. Nearly every entry here
# corrects the emulator it describes -- shadPS4 is told which binary to run and
# which Vulkan driver to use -- and none of that belongs in `workarounds`: it is
# permanent, and switching it off would only break the emulator.
_with = [e for e in emulator_catalog.CATALOG if emulator_catalog.workarounds_for(e)]
check("only the two motion corrections are workarounds",
      sorted(e["id"] for e in _with), ["shadps4", "vita3k"])
check("and each entry declares exactly one",
      [len(emulator_catalog.workarounds_for(e)) for e in _with], [1, 1])

# The rule that stops this becoming a dumping ground, and the one that keeps a
# temporary fix from silently becoming permanent: no upstream reference, no
# workaround. Nobody can tell when to delete one otherwise.
for _entry in _with:
    for _item in emulator_catalog.workarounds_for(_entry):
        check("%s/%s names the fix that will retire it"
              % (_entry["id"], _item["id"]),
              _item.get("upstream", "").startswith("https://"), True)
        check("  and says what turning it on costs",
              bool(_item.get("costs")), True)
        # `apply` may only reach keys a relaunch can undo. `source` decides what
        # was installed, so a fork is not a workaround however temporary it is.
        check("  and only changes things a toggle can undo",
              sorted(set(_item.get("apply") or {})
                     - set(emulator_catalog.schema.WORKAROUND_APPLIES)),
              [])

# `source` is the line, and Vita3K is the case that proves it: which build was
# downloaded is not something a toggle can undo, so it stays out of `apply`
# however temporary the reason for it is.
check("no workaround decides what was installed",
      [e["id"] for e in emulator_catalog.CATALOG
       for w in emulator_catalog.workarounds_for(e)
       if "source" in (w.get("apply") or {})],
      [])

# Switching one off has to take *everything* it brought with it, or the halves
# come apart -- environment with no layout reads a sensor Steam never powers on.
_off = emulator_catalog.resolve_workarounds(_shad, ["ps4-motion"])
check("disabling a workaround removes its layout",
      _off.get("layout", ""), "")
check("and every variable it added",
      [k for k in _off.get("env", {}) if k.startswith("SDL_") or k == "LD_PRELOAD"],
      [])
# The one that would be easy to get wrong: shadPS4 pins its Vulkan driver on the
# entry, which is permanent and nothing to do with motion. A workaround that
# replaced `env` wholesale would put every PS4 game back on the software
# renderer the moment somebody turned the gyro off.
check("but leaves what the entry itself set",
      "radeon_icd" in _off.get("env", {}).get("VK_DRIVER_FILES", ""), True)

# What the panel renders.
_state = emulator_catalog.workaround_state(_shad, [])
check("the panel is told the name, cost and where the real fix is",
      (_state[0]["name"], bool(_state[0]["costs"]), _state[0]["enabled"],
       _state[0]["upstream"].endswith("3871")),
      ("Motion controls", True, True, True))
check("and told when one is off",
      emulator_catalog.workaround_state(_shad, ["ps4-motion"])[0]["enabled"], False)

# A fresh install gets the defaults, which for both of these is "on".
# Off unless asked for. The cost -- Steam Input for every game of that system
# -- lands on people who never wanted motion, so it is not imposed by default.
check("a fresh install starts with motion off",
      emulator_catalog.to_emulator(_shad, "/x", {}).get("workarounds_off"),
      ["ps4-motion"])
check("and the same for Vita3K",
      emulator_catalog.to_emulator(_vita_entry, "/x", {}).get("workarounds_off"),
      ["vita-motion"])
# Which means the default resolution has neither half of motion in it.
_fresh = emulator_catalog.resolve_workarounds(
    _shad, emulator_catalog.default_disabled(_shad))
check("so a fresh shadPS4 has no layout and no motion variables",
      (_fresh.get("layout", ""),
       [k for k in _fresh.get("env", {}) if k.startswith("SDL_")]),
      ("", []))

# An entry with none of this is untouched, which is almost all of them.
_plain = emulator_catalog.find("dolphin")
check("an entry with no workarounds resolves to itself",
      emulator_catalog.resolve_workarounds(_plain) is _plain, True)


section("Retiring a workaround, rather than deleting it")

# Deletion is the wrong move the day upstream merges: the bug is still in the
# build somebody has not updated yet, so removing the workaround takes the fix
# from exactly the people who still need it. `fixed_in` keeps it working and
# says so only to the people it is true for.
_dep_entry = {
    "id": "example",
    "workarounds": [
        {"id": "live", "name": "Live", "because": "b", "costs": "c",
         "upstream": "https://example.invalid/1", "apply": {"layout": "template://x"}},
        {"id": "done", "name": "Done", "because": "b", "costs": "c",
         "upstream": "https://example.invalid/2", "fixed_in": "9",
         "apply": {"env": {"A": "1"}}},
    ],
}


def _state(build="", unavailable=None):
    return {w["id"]: w for w in emulator_catalog.workaround_state(
        _dep_entry, [], unavailable, build)}


# The defect this replaced a free-form string to fix. `fixed_in` ships with the
# *plugin*, so announcing it on its own told somebody their emulator no longer
# needed a fix nobody had looked at -- and acting on that broke the thing the
# message was about.
check("a build older than the fix is told nothing",
      (_state("8")["done"]["state"], _state("8")["done"]["note"]), ("", ""))
check("a build with the fix is told, once it is actually installed",
      _state("9")["done"]["state"], "retired")
check("and so is anything newer", _state("12")["done"]["state"], "retired")
# The answer that matters most: not knowing is not the same as "no", but it
# leads to the same silence, because a claim nobody can check is a guess.
check("an unidentifiable build is told nothing",
      [_state(b)["done"]["state"] for b in ("", "continuous", "nightly")],
      ["", "", ""])
check("and a workaround with no fixed_in is never retired",
      _state("999")["live"]["state"], "")

# It keeps working for whoever already has it -- that is the whole point.
check("a retired workaround still applies while it is on",
      emulator_catalog.resolve_workarounds(_dep_entry, []).get("env"), {"A": "1"})
check("and can still be switched off",
      emulator_catalog.resolve_workarounds(_dep_entry, ["done"]).get("env"), None)

# A build nobody can compare against would put the panel back to announcing
# things it cannot check.
check("a fixed_in that is not a build is refused",
      any("fixed_in must name" in problem for problem in emulator_catalog.validate(
          dict(_dep_entry, id="empty", name="E", kind="flatpak", target="x",
               workarounds=[dict(_dep_entry["workarounds"][1], fixed_in="soon")]))),
      True)

# The other state, and it is nearly the opposite: needed, and not running.
check("a fix this install could not take says so",
      (_state(unavailable={"live": "this build has changed"})["live"]["state"],
       _state(unavailable={"live": "x"})["live"]["note"]),
      ("unavailable", emulator_catalog.NOTICE_TEXT["unavailable"]))
check("and nothing is claimed when every fix applied",
      [w["state"] for w in emulator_catalog.workaround_state(_dep_entry)],
      ["", ""])
# Retired wins: a fix the emulator has already made is not interesting for
# failing to apply, and one sentence is the whole point.
check("retired outranks unavailable when both are true",
      _state("9", {"done": "x"})["done"]["state"], "retired")

# The panel says "a corrected copy is made" for every fix that edits the
# emulator's own files, derived from the catalog rather than left to whoever
# writes the entry -- so it cannot be forgotten, and a fix that touches no file
# never claims otherwise.
_vita_state = {w["id"]: w for w in emulator_catalog.workaround_state(_vita_entry)}
_shad_state = {w["id"]: w for w in emulator_catalog.workaround_state(_shad)}
check("a fix that edits the emulator's files says so",
      _vita_state["vita-motion"]["patches"], True)
check("and one that only changes how it launches does not",
      _shad_state["ps4-motion"]["patches"], False)


section("An install from a source the catalog has stopped naming")

# Nothing moves such an install on its own. `source` is read live, but the
# AppImage already on disk is never re-fetched and AppImage updates are not
# offered at all -- so without saying something, an emulator downloaded from
# somewhere the catalog no longer names sits there indefinitely.
#
# Which install that is needs no record and no network call: the recipe already
# says. Vita3K's source has moved twice -- upstream's rolling release, then a
# fork, now upstream's numbered builds -- and every one of those installs is
# below recipe 10.
_moved = (_vita_entry.get("source_moved") or {})
check("Vita3K says when its source moved", _moved.get("recipe"), 10)
check("and the number is the recipe it moved at",
      _moved["recipe"], _vita_entry["recipe"])
check("and it carries the sentence the user is told",
      bool(str(_moved.get("note") or "").strip()), True)

# The note is the only thing anybody is told, and it is told once, so an empty
# one is a flag with no way to act on it.
check("a source_moved with no note is refused",
      any("needs a note" in problem for problem in emulator_catalog.validate(
          dict(_dep_entry, id="n", name="N",
               source_moved={"recipe": 2, "note": "  "}))),
      True)
check("and one with no recipe is refused",
      any("needs the recipe number" in problem for problem in emulator_catalog.validate(
          dict(_dep_entry, id="n", name="N", source_moved={"note": "x"}))),
      True)

# Nothing else has moved, and a second one appearing without a reason in its own
# comment is worth failing over.
check("Vita3K is the only entry whose source has moved",
      [e["id"] for e in emulator_catalog.CATALOG if e.get("source_moved")],
      ["vita3k"])


section("A patch is described strictly, because it edits somebody else's binary")


def _patch_problems(patch):
    """Only what the validator says about `patch`.

    The scaffold entry is deliberately not a complete emulator -- it exists to
    carry one workaround -- so its other complaints are noise here.
    """
    entry = dict(_dep_entry, id="p", name="P",
                 workarounds=[dict(_dep_entry["workarounds"][0], id="p",
                                   apply={"patch": patch})])
    return [problem for problem in emulator_catalog.validate(entry)
            if "patch" in problem]


_GOOD = {"file": "usr/bin/App", "within": "some_function",
         "find": "41030c24", "replace": "31c99090"}
check("a well-formed patch passes", _patch_problems(_GOOD), [])

# The one that matters most. Those four bytes occur nine times in Vita3K's
# binary; without a symbol to bound the search, a patch is applied to whichever
# of them comes first.
check("a patch with no symbol to search within is refused",
      any("within" in p for p in _patch_problems(dict(_GOOD, within=""))), True)
# Nothing may move: the file is full of addresses fixed at link time.
check("and one that would change the file's length is refused",
      any("must match" in p for p in _patch_problems(dict(_GOOD, replace="31c9"))),
      True)
check("and bytes that are not hex are refused",
      any("hex" in p for p in _patch_problems(dict(_GOOD, find="not hex"))), True)
check("and a patch that writes back what was already there is refused",
      any("with themselves" in p
          for p in _patch_problems(dict(_GOOD, replace=_GOOD["find"]))),
      True)
check("and one reaching outside the package is refused",
      any("inside the package" in p
          for p in _patch_problems(dict(_GOOD, file="../../etc/passwd"))),
      True)
check("and a misspelt field is refused rather than ignored",
      any("unknown field" in p for p in _patch_problems(dict(_GOOD, symbol="x"))),
      True)

# `source` is still the line. Which build was downloaded is not something a
# toggle can undo, and `patch` only earns its place because the stock build
# stays on disk beside the patched one.
check("apply still refuses anything that decides what was installed",
      sorted(emulator_catalog.schema.WORKAROUND_APPLIES),
      ["env", "layout", "patch"])


# Nothing is deprecated yet, and a test that quietly stops checking anything is
# worse than no test -- this fails the day one is, as a prompt to check the UI.
check("no shipped workaround is deprecated yet",
      [item["id"] for entry in emulator_catalog.CATALOG
       for item in emulator_catalog.workarounds_for(entry)
       if item.get("deprecated")],
      [])


section("what an emulator can open is not what its system uses")

# The derivation is about a *system*: `extensions_for` merges what every
# libretro core declaring that system supports. A standalone emulator therefore
# inherits anything any of those cores can read, which is right for almost
# everything and wrong wherever the two genuinely differ.
#
# **PCSX2 is the case that found this.** `pcsx2_libretro` declares `m3u`; the
# flatpak PCSX2 cannot open one -- its own file-type filter is `*.bin *.iso
# *.cue *.mdf *.chd *.cso *.zso *.gz *.dump` and `m3u` is nowhere in the binary.
# The multi-disc switch was offered for a two-disc PS2 game, the playlist was
# written, and the launcher handed PCSX2 a file it cannot read: one library
# entry that starts nothing.

_DB = {
    "Sony - PlayStation 2": ["iso", "chd", "cso", "cue", "bin", "m3u"],
    "Nintendo - GameCube": ["iso", "gcm", "rvz", "m3u"],
    "Sony - PlayStation": ["cue", "chd", "bin", "m3u"],
}

check("PCSX2 does not claim a playlist",
      "m3u" in emulator_catalog.extensions_for(emulator_catalog.find("pcsx2"), _DB),
      False)
# And the subtraction is surgical: everything else the core offered is still
# there, or the emulator would stop matching the files it does run.
check("but keeps everything else the system uses",
      emulator_catalog.extensions_for(emulator_catalog.find("pcsx2"), _DB),
      ["bin", "chd", "cso", "cue", "gz", "iso", "mdf", "zso"])

# The two that genuinely do read one, so a fix for PCSX2 cannot quietly take
# multi-disc away from the systems it works on.
for _id in ("dolphin", "duckstation"):
    check("%s still claims a playlist" % _id,
          "m3u" in emulator_catalog.extensions_for(emulator_catalog.find(_id), _DB),
          True)

# Subtracted after both sources, so a manual entry cannot put back what the
# emulator has said it cannot open.
check("a manual extension does not survive cannot_open",
      "m3u" in emulator_catalog.extensions_for(
          dict(emulator_catalog.find("pcsx2"), databases=["Nintendo - GameCube"]), _DB),
      False)

# Nothing else uses it yet. This fails the day something does, as a prompt to
# check that the reason is written down beside it rather than inferred later.
check("PCSX2 is the only entry that has to correct the derivation",
      [entry["id"] for entry in emulator_catalog.CATALOG if entry.get("cannot_open")],
      ["pcsx2"])

# **`changes_disc` is a claim that the other discs are reachable once the first
# is running**, and the cost of a wrong yes is a library entry that can only ever
# play disc one. Two mechanisms count and both were read off the installed
# binary: PCSX2 has `Change Disc` in its own menu, and Xenia implements
# `XamLoaderLaunchTitleOnDvd`, so a game split across its discs asks the console
# for the next one and Xenia serves it from the folder.
check("only the entries whose disc changing has been seen claim it",
      sorted(entry["id"] for entry in emulator_catalog.CATALOG
             if entry.get("changes_disc")),
      ["pcsx2", "xenia"])
# It only means anything where a playlist is impossible: an entry that can be
# handed one has no use for it, and setting both would be two answers to the
# same question.
check("and nothing claims both a playlist and a disc menu",
      [entry["id"] for entry in emulator_catalog.CATALOG
       if entry.get("changes_disc") and "m3u" in emulator_catalog.extensions_for(entry, _DB)],
      [])


if __name__ == "__main__":
    from harness import summary

    summary()
