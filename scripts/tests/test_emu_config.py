#!/usr/bin/env python3
r"""Recommended settings, written into a config file the user owns.

    python scripts/tests/test_emu_config.py

The rule for when this may write at all is not invented, and it is why the
section is worth its length: Azahar writes a companion `<key>\default` line
beside every setting and ignores the stored value entirely when it reads true.
So true or absent means nothing of the user's is at stake, false means somebody
set it -- and a write that does not also clear the flag is silently discarded,
which looks exactly like the bug being fixed.

Five formats, each with its own writer -- qt ini, plain ini, json, yaml, whole
file -- and the checks below are what stop a fix to one of them being a fix to
only one of them.

The tail covers the folder tokens a setup block may write (`{roms}`, `{firmware}`
and the rest) and therefore the records those tokens point at: PARAM.SFO, the
installed PS3 listing, and the short-named staging links. Those grew here because
a token is only right if the folder it names is the one the console reads from,
and checking that needs both halves.

Was 807 lines in the middle of test_backend.py, and the largest single section
in it. It reaches for nothing that file sets up.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import SAMPLE_SFO, TMP, check, failures, section, summary  # noqa: E402

import emu_install  # noqa: E402
import emulator_catalog as emu_catalog  # noqa: E402
import json as _json  # noqa: E402
import sysenv  # noqa: E402


section("recommended settings -- writing into a config the user owns")
import emu_config  # noqa: E402


def _toml_tables(path):
    """Read a TOML file as {table: {key: literal}}, values left as written.

    Enough of TOML for a config xemu wrote, and deliberately no more: the point
    is which table a key ended up in and whether its value went in bare or
    quoted, and a real parser would normalise both of those away.
    """
    tables = {}
    current = tables.setdefault("", {})
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = tables.setdefault(line[1:-1], {})
        elif "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            current[key.strip()] = value.strip()
    return tables


# Azahar reads a value only when its companion `\default` line is absent or
# true; `\default=true` means the stored value is thrown away entirely. So a
# value written without clearing that flag does nothing at all, and this is the
# check that would catch it.
_cfg_home = os.path.join(TMP, "cfghome")
_cfg_path = os.path.join(_cfg_home, ".config", "azahar-emu", "qt-config.ini")
os.makedirs(os.path.dirname(_cfg_path), exist_ok=True)


def _write_cfg(text):
    with io.open(_cfg_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _read_cfg():
    with io.open(_cfg_path, encoding="utf-8") as handle:
        return handle.read()


_real_user_home = sysenv.user_home
sysenv.user_home = lambda: _cfg_home
try:
    _write_cfg(
        "[Controls]\n"
        "profile=0\n"
        'profiles\\1\\button_a="code:65,engine:keyboard"\n'
        "profiles\\1\\button_a\\default=true\n"
        'profiles\\1\\button_b="code:83,engine:keyboard"\n'
        "profiles\\1\\button_b\\default=false\n"
        "\n"
        "[UI]\n"
        "fullscreen=false\n"
        "fullscreen\\default=true\n"
        "hideInactiveMouse=false\n"
        "hideInactiveMouse\\default=true\n"
    )
    _result = emu_config.apply_setup(emu_catalog.find("azahar"))
    _text = _read_cfg()
    check("the setup reports success", _result["ok"], True)
    check("fullscreen is turned on", "fullscreen=true" in _text, True)
    # Without this line Azahar reads its own default and the write above is
    # silently discarded -- the failure would look exactly like doing nothing.
    check(
        "and its default flag is cleared, or the value is ignored",
        "fullscreen\\default=false" in _text,
        True,
    )
    # The exact string matters. Azahar 2125.1.3 has no `maptype`/`api` support:
    # it reads params.Get("guid", "0") and resolves "0" to a placeholder
    # joystick, so a binding without a real GUID reads false forever. That is
    # what shipped once, from reading master instead of the installed tag.
    check(
        "an untouched binding is replaced",
        'profiles\\1\\button_a="button:1,engine:sdl,'
        'guid:030079f6de280000ff11000001000000,port:0"' in _text,
        True,
    )
    check("bindings name a real pad, never guid 0", 'guid:0"' in _text or "guid:0," in _text, False)
    # The D-pad is a hat on this pad and the C-stick is axes 3/4 -- read off the
    # device with SDL_GameControllerMappingForGUID, not from SDL's
    # GameController numbering, which disagrees about both.
    check("the D-pad is bound as a hat", "hat:0,port:0" in _text, True)
    check("the C-stick uses the pad's own axes", "axis_x:3,axis_y:4" in _text, True)
    # The whole safety rule: `\default=false` means the value differs from the
    # emulator's own default because somebody set it. Not ours to overwrite.
    check(
        "a binding the user changed is left alone",
        'profiles\\1\\button_b="code:83,engine:keyboard"' in _text,
        True,
    )
    check(
        "and is reported as skipped rather than silently dropped",
        "Controls/profiles\\1\\button_b" in _result["skipped"],
        True,
    )
    # Anything not named in the spec must survive untouched, so this stays a
    # line editor rather than a parser that rewrites what it did not understand.
    check("unrelated settings survive", "hideInactiveMouse=false" in _text, True)
    check("the profile index is untouched", "\nprofile=0\n" in _text, True)

    # 15, not 16: button_b is the one the user changed, and it was left alone.
    check(
        "every binding names Steam Input's virtual pad",
        _text.count("guid:030079f6de280000ff11000001000000"),
        15,
    )

    # Applying twice must not duplicate keys or drift. It must also still do
    # something: writing a value requires clearing its `\default` flag, so a
    # naive rule would read our own writes back as the user's and skip
    # everything, leaving the re-apply action doing nothing.
    _again = emu_config.apply_setup(emu_catalog.find("azahar"))
    check("applying twice changes nothing further", _read_cfg(), _text)
    check("our own writes are not mistaken for the user's", len(_again["skipped"]), 1)
    # 16: every key in the spec except the one binding the user had changed.
    check("so re-applying still re-applies", len(_again["applied"]), 16)

    # A missing file is the fresh-install case: Azahar has not run yet, and a
    # partial file is fine because it fills in whatever it does not find.
    os.remove(_cfg_path)
    _fresh = emu_config.apply_setup(emu_catalog.find("azahar"))
    _text = _read_cfg()
    check("a missing config is created", _fresh["ok"], True)
    check("with the sections it needs", "[Controls]" in _text and "[UI]" in _text, True)
    check("and nothing skipped", _fresh["skipped"], [])
    check(
        "every written key carries a cleared default flag",
        _text.count("\\default=false"),
        len(_fresh["applied"]),
    )

    # Correcting our own past mistakes is the case that matters most here. An
    # earlier version wrote `maptype:all` bindings, which the released Azahar
    # does not understand; they carry `\default=false` like any written value,
    # so without the supersede rule they would be read as the user's own choice
    # and left broken forever. This is the check that a wrong setting shipped
    # once can still be fixed.
    _write_cfg(
        "[Controls]\n"
        'profiles\\1\\button_a="engine:sdl,maptype:all,api:controller,button:1"\n'
        "profiles\\1\\button_a\\default=false\n"
        'profiles\\1\\button_b="code:83,engine:keyboard"\n'
        "profiles\\1\\button_b\\default=false\n"
    )
    os.remove(emu_config.STATE_PATH)
    _fixed = emu_config.apply_setup(emu_catalog.find("azahar"))
    _text = _read_cfg()
    check(
        "a binding this plugin got wrong before is corrected",
        "guid:030079f6de280000ff11000001000000" in _text.split("button_a=")[1].splitlines()[0],
        True,
    )
    check(
        "while a real user binding beside it is still left alone",
        'profiles\\1\\button_b="code:83,engine:keyboard"' in _text,
        True,
    )
    check("and only that one is reported skipped", _fixed["skipped"], ["Controls/profiles\\1\\button_b"])

    # What was written is recorded, which is what lets the *next* correction
    # tell this plugin's work from the user's without a pattern for every past
    # mistake.
    check("what was written is recorded", os.path.isfile(emu_config.STATE_PATH), True)
    with io.open(emu_config.STATE_PATH, encoding="utf-8") as _handle:
        _state = _json.load(_handle)
    check("under the emulator's id", "azahar" in _state, True)
    check(
        "and the user's untouched binding is not claimed as ours",
        "Controls/profiles\\1\\button_b" in _state["azahar"],
        False,
    )

    # Settings are applied when an emulator is installed, and an emulator is
    # installed once -- so without a version to compare against, a *correction*
    # to those settings could only ever reach someone who had not installed it
    # yet. This is what replaced a button the user had to know to press.
    check("a version is recorded once applied", _state["azahar"][emu_config.VERSION_KEY],
          emu_catalog.find("azahar")["setup"]["version"])
    check("so nothing is re-applied at the next startup",
          emu_config.needs_setup(emu_catalog.find("azahar")), False)

    _bumped = _json.loads(_json.dumps(_state))
    _bumped["azahar"][emu_config.VERSION_KEY] = 0
    with io.open(emu_config.STATE_PATH, "w", encoding="utf-8") as _handle:
        _json.dump(_bumped, _handle)
    check("but a newer version is picked up",
          emu_config.needs_setup(emu_catalog.find("azahar")), True)
    # Never installed at all is also "needs applying", which is what makes the
    # first install write them.
    os.remove(emu_config.STATE_PATH)
    check("and so is an emulator that has never had them",
          emu_config.needs_setup(emu_catalog.find("azahar")), True)
    # A bare entry rather than a named emulator: every one of them grows a setup
    # block sooner or later, and this is about the absence, not about who.
    _no_setup = {"id": "nosetup", "name": "No Setup"}
    check("while one with no settings never asks",
          emu_config.needs_setup(_no_setup), False)

    # Recorded even when every key was left as the user set them, or the attempt
    # would repeat at every single startup for no gain.
    _write_cfg(
        "[Controls]\n"
        'profiles\\1\\button_a="code:65,engine:keyboard"\n'
        "profiles\\1\\button_a\\default=false\n"
    )
    emu_config.apply_setup(emu_catalog.find("azahar"))
    check("a run that changed nothing still settles the version",
          emu_config.needs_setup(emu_catalog.find("azahar")), False)

    # PCSX2 writes no bindings of its own -- only `Type` -- so an absent `Up`
    # means nobody has configured the pad, and that is what the anchor keys off.
    _pcsx2_ini = os.path.join(
        _cfg_home, ".var", "app", "net.pcsx2.PCSX2", "config", "PCSX2", "inis", "PCSX2.ini"
    )
    os.makedirs(os.path.dirname(_pcsx2_ini), exist_ok=True)
    with io.open(_pcsx2_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Pad1]\nType = DualShock2\n\n[InputSources]\nSDL = false\n")
    emu_config.apply_setup(emu_catalog.find("pcsx2"))
    with io.open(_pcsx2_ini, encoding="utf-8") as _handle:
        _p_text = _handle.read()
    check("an unconfigured PCSX2 pad is bound", "Cross = SDL-0/A" in _p_text, True)
    # PCSX2 runs a setup wizard until told otherwise. It is modal, a gamepad
    # cannot complete it, and its first run rewrote the whole config.
    check("and the setup wizard is answered", "SetupWizardIncomplete = false" in _p_text, True)

    # That rewrite is the case that shipped broken: PCSX2's own first run put
    # keyboard defaults in the pad, which are neither absent nor ours, so the
    # section would have been skipped forever.
    with io.open(_pcsx2_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Pad1]\nUp = Keyboard/Up\nCross = Keyboard/X\n")
    emu_config.apply_setup(emu_catalog.find("pcsx2"))
    with io.open(_pcsx2_ini, encoding="utf-8") as _handle:
        _p_after = _handle.read()
    check("a pad PCSX2 reset to its keyboard defaults is rebound",
          "Cross = SDL-0/A" in _p_after, True)
    # Without SDL as an input source the bindings above address nothing.
    check("and SDL is switched on as an input source", "SDL = true" in _p_text, True)
    check("the pad type is left as PCSX2 set it", "Type = DualShock2" in _p_text, True)

    # A pad somebody has already bound is theirs, whole.
    with io.open(_pcsx2_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Pad1]\nUp = Keyboard/W\nCross = Keyboard/Space\n")
    emu_config.apply_setup(emu_catalog.find("pcsx2"))
    with io.open(_pcsx2_ini, encoding="utf-8") as _handle:
        _p_kept = _handle.read()
    check("a pad already bound by hand is untouched", "Up = Keyboard/W" in _p_kept, True)
    check("all of it", "Cross = Keyboard/Space" in _p_kept, True)

    # An emulator with sensible defaults has no setup block, and that is not an
    # error.
    check("no setup block is not a failure",
          emu_config.apply_setup({"id": "nosetup", "name": "No Setup"}),
          {"ok": True, "applied": [], "skipped": [], "changed": False})

    # DuckStation shares PCSX2's input manager, and a real install confirmed it
    # shares the trap too: its own defaults are `Up = Keyboard/Up`, so without
    # that listed as replaceable the pad is skipped key by key.
    _duck_ini = os.path.join(
        _cfg_home, ".var", "app", "org.duckstation.DuckStation",
        "config", "duckstation", "settings.ini",
    )
    os.makedirs(os.path.dirname(_duck_ini), exist_ok=True)
    with io.open(_duck_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "[Main]\nSetupWizardIncomplete = true\nConfirmPowerOff = true\n\n"
            "[Pad1]\nType = AnalogController\nUp = Keyboard/Up\nCross = Keyboard/K\n"
        )
    emu_config.apply_setup(emu_catalog.find("duckstation"))
    with io.open(_duck_ini, encoding="utf-8") as _handle:
        _duck_text = _handle.read()
    check("DuckStation's keyboard pad is rebound", "Cross = SDL-0/A" in _duck_text, True)
    check("its setup wizard is answered too",
          "SetupWizardIncomplete = false" in _duck_text, True)
    # Otherwise quitting asks "are you sure", and a Steam shortcut never stops.
    check("and it stops asking before powering off",
          "ConfirmPowerOff = false" in _duck_text, True)
    # It checks GitHub for a release on every start and puts the answer in a
    # dialog in front of the game -- a link nobody can follow from Game Mode.
    check("and stops checking GitHub for updates",
          "CheckAtStartup = false" in _duck_text, True)

    # PPSSPP's ini carries a UTF-8 BOM. Read as plain utf-8 the mark stays glued
    # to the first line, `[General]` matches no section, and a second `[General]`
    # is appended -- a whole section silently duplicated.
    _pp_ini = os.path.join(
        _cfg_home, ".var", "app", "org.ppsspp.PPSSPP",
        "config", "ppsspp", "PSP", "SYSTEM", "ppsspp.ini",
    )
    os.makedirs(os.path.dirname(_pp_ini), exist_ok=True)
    with io.open(_pp_ini, "w", encoding="utf-8-sig", newline="\n") as _handle:
        _handle.write("[General]\nFirstRun = False\nCheckForNewVersion = True\n")
    emu_config.apply_setup(emu_catalog.find("ppsspp"))
    with io.open(_pp_ini, encoding="utf-8-sig") as _handle:
        _pp_text = _handle.read()
    check("a value is written past a byte order mark",
          "CheckForNewVersion = False" in _pp_text, True)
    check("without duplicating the section it sits in",
          _pp_text.count("[General]"), 1)
    check("and the mark itself survives",
          io.open(_pp_ini, "rb").read(3), b"\xef\xbb\xbf")
    check("with everything around it left alone", "FirstRun = False" in _pp_text, True)

    # xemu answers an unknown key with a warning on stderr and then carries on,
    # so a setting in the wrong table is not an error -- it is a setting that
    # quietly does nothing, which in Game Mode is indistinguishable from the
    # feature not existing. `show_menubar` sat in `[general]` for a release for
    # exactly that reason. These checks are about the table each key lands in,
    # because that is the part that was wrong and the part nothing else catches.
    _xemu_toml = os.path.join(
        _cfg_home, ".var", "app", "app.xemu.xemu",
        "data", "xemu", "xemu", "xemu.toml",
    )
    os.makedirs(os.path.dirname(_xemu_toml), exist_ok=True)
    with io.open(_xemu_toml, "w", encoding="utf-8", newline="\n") as _handle:
        # What xemu itself leaves behind after one run: only the values that
        # differ from its own defaults, in dotted-table form.
        _handle.write(
            "[general]\nshow_welcome = false\n\n"
            "[input.bindings]\nport1_driver = 'usb-xbox-gamepad'\n"
        )
    emu_config.apply_setup(emu_catalog.find("xemu"))
    _xemu_tables = _toml_tables(_xemu_toml)
    check("xemu's menu bar is turned off in the table xemu reads",
          _xemu_tables["display.ui"].get("show_menubar"), "false")
    check("and not in [general], where it is an unrecognized key",
          "show_menubar" in _xemu_tables["general"], False)
    # "Connected '<pad>' to port 1", over the boot of every launch from Steam.
    check("the notification toasts go with it",
          _xemu_tables["display.ui"].get("show_notifications"), "false")
    # The most xemu offers: hidden after three seconds of not moving. The Deck's
    # right trackpad can still bring the pointer back, so this is a floor.
    check("and the mouse pointer hides itself when idle",
          _xemu_tables["display.ui"].get("hide_cursor"), "true")
    check("while the welcome panel stays in [general], where it does work",
          _xemu_tables["general"].get("show_welcome"), "false")
    # Quoted, `show_menubar = 'false'` is the string "false" -- which is true.
    check("all of them written as TOML booleans rather than strings",
          sorted(_xemu_tables["display.ui"].values()), ["false", "false", "true"])
    check("with what xemu wrote for itself untouched",
          _xemu_tables["input.bindings"].get("port1_driver"), "'usb-xbox-gamepad'")

    # Cemu ships no controller profile and writes no settings until it is used,
    # so there is nothing to edit and nothing to parse -- the file is supplied
    # whole, and owning it means "absent, or exactly what we last wrote".
    _cemu_dir = os.path.join(_cfg_home, ".var", "app", "info.cemu.Cemu", "config", "Cemu")
    _cemu_profile = os.path.join(_cemu_dir, "controllerProfiles", "controller0.xml")
    _cemu_settings = os.path.join(_cemu_dir, "settings.xml")
    _cemu = emu_config.apply_setup(emu_catalog.find("cemu"))
    check("Cemu's profile is created from nothing", _cemu["ok"], True)
    check("including the directory it lives in", os.path.isfile(_cemu_profile), True)
    with io.open(_cemu_profile, encoding="utf-8") as _handle:
        _cemu_text = _handle.read()
    # Wii U puts A on the right, where SDL puts B. Getting this "obvious" would
    # swap confirm and cancel in every game.
    check("with A on the right face button",
          "<mapping>1</mapping>\n\t\t\t\t<button>1</button>" in _cemu_text, True)
    check("and the Steam virtual pad's guid",
          emu_catalog.steam_pad._STEAM_PAD_GUID in _cemu_text, True)
    # Cemu decides it has never run by whether settings.xml exists, so writing
    # the file at all is what stops the Getting Started dialog.
    check("and settings.xml exists so it is not a first start",
          os.path.isfile(_cemu_settings), True)

    # Cemu's loader falls back to a different value than the setting is declared
    # with, and assigns unconditionally -- so a key missing from our file
    # *replaces* Cemu's default rather than leaving it alone. An absent TVDevice
    # selects no audio output, which is why a game ran with picture and no
    # sound. These keys therefore look redundant and are not, which is exactly
    # how they would get deleted again.
    with io.open(_cemu_settings, encoding="utf-8") as _handle:
        _settings_text = _handle.read()
    for _key, _value, _why in (
        ("TVDevice", "default", "an empty device name is no audio output at all"),
        ("api", "3", "audio_api defaults to Windows-only DirectSound, so the "
                     "device lookup throws and the game is silent"),
        ("api", "1", "an absent Graphic/api quietly downgrades Vulkan to OpenGL"),
        ("TVVolume", "50", "an absent TVVolume drops the volume to 20"),
        ("InputVolume", "50", "an absent InputVolume drops it to 20"),
    ):
        if "<%s>%s</%s>" % (_key, _value, _key) not in _settings_text:
            failures.append("Cemu settings.xml must pin %s: %s" % (_key, _why))
    check("every default our own file would displace is restated",
          [f for f in failures if "settings.xml must pin" in f], [])

    # Applying again is a no-op, and does not report the file as the user's.
    _cemu_again = emu_config.apply_setup(emu_catalog.find("cemu"))
    check("applying again changes nothing", _cemu_again["changed"], False)
    check("and claims nothing was skipped", _cemu_again["skipped"], [])

    # RPCS3 ships no input config at all -- a headless first run writes config.yml
    # and never creates input_configs -- so the pad file is supplied whole, and
    # everything in it that is not a binding has to be there too.
    _rpcs3_pad_file = os.path.join(
        _cfg_home, ".config", "rpcs3", "input_configs", "global", "Default.yml",
    )
    _rpcs3 = emu_config.apply_setup(emu_catalog.find("rpcs3"))
    check("RPCS3's pad file is created where there was none", _rpcs3["ok"], True)
    with io.open(_rpcs3_pad_file, encoding="utf-8") as _handle:
        _rpcs3_text = _handle.read()
    check("player one uses the evdev handler",
          "Player 1 Input:\n  Handler: Evdev\n" in _rpcs3_text, True)
    # RPCS3 matches the pad by the name the kernel reports, not by a guid, so
    # this string is the whole binding -- and it is the same one SDL checksums
    # into the guid every other entry uses.
    check("and names the Steam pad exactly as the kernel reports it",
          "  Device: %s\n" % emu_catalog.rpcs3._RPCS3_PAD_DEVICE in _rpcs3_text, True)
    check("with Cross on the bottom face button, uncrossed",
          "    Cross: A\n" in _rpcs3_text, True)
    check("and every player slot present",
          _rpcs3_text.count("Input:\n"), emu_catalog.rpcs3._RPCS3_PLAYERS)
    check("the slots nobody is holding are explicitly empty",
          _rpcs3_text.count('  Handler: "Null"\n'), emu_catalog.rpcs3._RPCS3_PLAYERS - 1)
    # A profile is only live if it is the active one, and RPCS3's fallback stops
    # being Default the moment somebody saves a second profile.
    _rpcs3_active = os.path.join(os.path.dirname(os.path.dirname(_rpcs3_pad_file)),
                                 "active_profiles.yml")
    with io.open(_rpcs3_active, encoding="utf-8") as _handle:
        check("and the written profile is the active one",
              "global: Default" in _handle.read(), True)
    # RPCS3's GUI settings are the one place a setup mixes formats: a pad file
    # written whole, plus two keys inside a Qt ini that already holds the user's
    # language. Both have to land, and the ini has to keep what was there.
    _rpcs3_gui = os.path.join(
        _cfg_home, ".config", "rpcs3", "GuiConfigs", "CurrentSettings.ini",
    )
    with io.open(_rpcs3_gui, encoding="utf-8") as _handle:
        _gui_text = _handle.read()
    check("the modal welcome box is answered in advance",
          "infoBoxEnabledWelcome = false" in _gui_text, True)
    # RPCS3 reopens each picker where it was last used, so this is what puts a
    # sent PUP or PKG on screen instead of a file browser at the home directory.
    check("and the firmware picker opens on the transfer folder",
          "lastExplorePathPUP = %s" % emu_install.firmware_dir() in _gui_text, True)
    import fileserver  # noqa: E402
    import ps3_games  # noqa: E402

    # The package picker opens on the staged links, not on the ROM folder.
    # RPCS3's install dialog is as wide as the filename it prints inline, and a
    # real 101-character name made it 1539px across on a 1280px screen -- the
    # Install button off the right edge, visible because gamescope scales the
    # picture, unreachable because it does not scale the pointer.
    check("the package picker opens on the staged links",
          "lastExplorePathPKG = %s" % ps3_games.stage_dir() in _gui_text, True)
    # The tokens resolve by rebuilding the path rather than importing the module
    # that owns it, because that import would be a cycle. These keep them honest.
    check("the firmware token is the firmware folder",
          emu_config._firmware_dir(), emu_install.firmware_dir())
    check("and the transfer token is where uploads land",
          emu_config._transfer_dir(), fileserver.default_dir())
    check("and the packages token is the staging folder",
          emu_config._packages_dir(), ps3_games.stage_dir())

    # ---- PARAM.SFO ----------------------------------------------------------
    # The bytes come from harness.make_sfo, built from the documented layout
    # rather than lifted off a game. Three files need the same container, so it
    # lives there; see its docstring for why a generated fixture is the right
    # one here and not a shortcut.
    _sfo_path = os.path.join(_cfg_home, "made-up-PARAM.SFO")
    with io.open(_sfo_path, "wb") as _handle:
        _handle.write(SAMPLE_SFO)

    _sfo = ps3_games.read_sfo(_sfo_path)
    check("a PARAM.SFO gives up its title", _sfo.get("TITLE"), "Braid")
    check("and its title id", _sfo.get("TITLE_ID"), "NPUB30133")
    check("strings and integers are told apart", _sfo.get("BOOTABLE"), 1)
    check("padding after a string is not read back as part of it",
          _sfo.get("CATEGORY"), "HG")
    check("something that is not an SFO is skipped, not raised",
          ps3_games.read_sfo(os.path.join(_cfg_home, "nope.sfo")), {})

    # ---- the installed game listing ----------------------------------------
    _ps3_root = os.path.join(_cfg_home, "ps3games")
    _installed = os.path.join(_ps3_root, "NPUB30133")
    os.makedirs(os.path.join(_installed, "USRDIR"), exist_ok=True)
    with io.open(os.path.join(_installed, "PARAM.SFO"), "wb") as _dst:
        _dst.write(SAMPLE_SFO)
    io.open(os.path.join(_installed, "USRDIR", "EBOOT.BIN"), "w").close()
    io.open(os.path.join(_installed, "ICON0.PNG"), "w").close()
    # RPCS3 creates this placeholder itself and there is no PARAM.SFO in it.
    os.makedirs(os.path.join(_ps3_root, "TEST12345", "USRDIR"), exist_ok=True)

    _ps3 = ps3_games.installed_games(_ps3_root)
    check("the installed game is found by name", [g["title"] for g in _ps3], ["Braid"])
    check("with the path that actually boots",
          _ps3[0]["eboot"].endswith(os.path.join("NPUB30133", "USRDIR", "EBOOT.BIN")), True)
    # The package carries its own art, so a PKG game needs nothing downloaded.
    check("and the artwork the package brought with it",
          _ps3[0]["icon"].endswith("ICON0.PNG"), True)
    check("a background that is not there is not claimed", _ps3[0]["background"], "")
    check("RPCS3's own empty placeholder is not offered as a game",
          any(g["title_id"] == "TEST12345" for g in _ps3), False)
    # A title whose EBOOT never unpacked would be a row that cannot start.
    os.remove(os.path.join(_installed, "USRDIR", "EBOOT.BIN"))
    check("nor is a title with no EBOOT", ps3_games.installed_games(_ps3_root), [])
    io.open(os.path.join(_installed, "USRDIR", "EBOOT.BIN"), "w").close()

    # ---- staging packages under a short name -------------------------------
    _pkg_src = os.path.join(_cfg_home, "pkgin")
    _pkg_out = os.path.join(_cfg_home, "pkgout")
    os.makedirs(_pkg_src, exist_ok=True)
    os.makedirs(_pkg_out, exist_ok=True)
    # A header shaped like the real one: magic, then the content id at 0x30.
    _pkg_header = bytearray(b"\x00" * 0x54)
    _pkg_header[0:4] = b"\x7fPKG"
    _pkg_header[0x30:0x30 + 36] = b"UP4049-NPUB30133_00-BRAID00000000001"
    _long_name = "vaMJjYU6mQ1N6kXDWKoKPuqgXJ8UaINGi5N6oYoRp9M9hpwWvKDB9WhkQpaf5HgK7l7HdHQGp8qb2BVY9lMVeaoCIM39cXSe8XUPl.pkg"
    with io.open(os.path.join(_pkg_src, _long_name), "wb") as _handle:
        _handle.write(bytes(_pkg_header))

    _staged = ps3_games.stage_packages(_pkg_src, _pkg_out)
    if _staged:
        check("a package is staged under its title id",
              os.path.basename(_staged[0]), "NPUB30133.pkg")
        # The whole point: what RPCS3 prints in its dialog is now 13 characters
        # instead of 105, which is the difference between a dialog that fits on
        # a 1280px screen and one whose buttons are off the edge.
        check("which is far shorter than what the user sent",
              len(os.path.basename(_staged[0])) < len(_long_name) / 4, True)
        check("and staging again does not pile up links",
              len(ps3_games.stage_packages(_pkg_src, _pkg_out)), 1)
    else:
        # Symlinks need a privilege Windows does not grant by default, and the
        # tests run there. Not a failure -- but say so rather than pass quietly.
        print("SKIP package staging (symlinks unavailable on this platform)")

    # ---- the packages waiting to be installed ------------------------------
    # Two folders are searched, because a package is a game that arrives looking
    # like firmware: the picker for it is in the ROM folder, but anyone who used
    # the PS3 firmware row's send button put it beside PS3UPDAT.PUP instead, and
    # a file that seems to vanish is the exact friction this removes.
    _pkg_alt = os.path.join(_cfg_home, "pkgalt")
    os.makedirs(_pkg_alt, exist_ok=True)
    with io.open(os.path.join(_pkg_alt, "Some Other Game.pkg"), "wb") as _handle:
        _handle.write(b"not a package at all")
    io.open(os.path.join(_pkg_src, "notes.txt"), "w").close()

    _waiting = ps3_games.packages([_pkg_src, _pkg_alt], installed={"NPUB30133"})
    check("packages are found across every folder searched",
          [item["name"] for item in _waiting],
          ["Some Other Game.pkg", _long_name])
    check("anything that is not a package is left out",
          any(item["name"] == "notes.txt" for item in _waiting), False)
    _braid_pkg = next(item for item in _waiting if item["name"] == _long_name)
    check("a package names the title inside it", _braid_pkg["title_id"], "NPUB30133")
    check("and says its game is already installed", _braid_pkg["installed"], True)
    # A header that will not parse still gets offered: with no title id there is
    # nothing to compare against, and offering it is the recoverable half of
    # that guess -- installing again is harmless, hiding a game is not.
    _other_pkg = next(item for item in _waiting if item["name"] != _long_name)
    check("a package with no readable header is still offered",
          (_other_pkg["title_id"], _other_pkg["installed"]), ("", False))
    check("with the size, so a truncated transfer is visible",
          _other_pkg["size"], len(b"not a package at all"))
    if _staged:
        # The staging folder holds symlinks to these same files. Without the
        # realpath check the panel would offer every package twice.
        _both = ps3_games.packages([_pkg_src, _pkg_out], installed=set())
        check("a staged link is not offered beside the file it points at",
              [item["name"] for item in _both], [_long_name])
    check("a folder that is not there is not an error",
          ps3_games.packages([os.path.join(_cfg_home, "nowhere")], installed=set()), [])
    # QT_INI's `\default` flag is an Azahar convention; RPCS3 has none, and
    # writing them would leave keys it does not recognise.
    check("with none of Azahar's default flags", "\\default" in _gui_text, False)

    _rpcs3_again = emu_config.apply_setup(emu_catalog.find("rpcs3"))
    check("applying RPCS3 again claims nothing was skipped",
          _rpcs3_again["skipped"], [])
    with io.open(_rpcs3_pad_file, encoding="utf-8") as _handle:
        check("and leaves the pad file exactly as it was",
              _handle.read() == _rpcs3_text, True)

    # Ryujinx keeps everything in JSON and rewrites the file wholesale, so it is
    # parsed rather than line-edited. Its one shipped input config is a keyboard,
    # which is why nothing on a Deck moves out of the box.
    _ryu_cfg = os.path.join(
        _cfg_home, ".var", "app", "io.github.ryubing.Ryujinx",
        "config", "Ryujinx", "Config.json",
    )
    os.makedirs(os.path.dirname(_ryu_cfg), exist_ok=True)
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "show_confirm_exit": True,
            "docked_mode": True,
            "input_config": [{"backend": "WindowKeyboard", "id": "0", "name": "Keyboard"}],
        }))
    _ryu = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    check("Ryujinx's config is written", _ryu["ok"], True)
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        _ryu_data = _json.load(_handle)
    check("the keyboard input config is replaced by a pad",
          _ryu_data["input_config"][0]["backend"], "GamepadSDL2")
    # Ryujinx is C#, and .NET reverses the first GUID fields, so this is not the
    # SDL spelling used everywhere else in the catalog. It also drops SDL's crc
    # field, which the derivation further down is what actually pins.
    check("bound to the Steam virtual pad in Ryujinx's own spelling",
          _ryu_data["input_config"][0]["id"], emu_catalog.ryujinx._RYUJINX_PAD_ID)
    # Switch A is on the right, where SDL has B.
    check("with A on the right face button",
          _ryu_data["input_config"][0]["right_joycon"]["button_a"], "B")
    check("and the exit confirmation answered", _ryu_data["show_confirm_exit"], False)
    check("while everything else in the file survives", _ryu_data["docked_mode"], True)

    # Ryujinx rewrites Config.json on exit and fills in fields it did not find,
    # so a config this plugin wrote comes back changed and stops matching what
    # was recorded. A correction was skipped as "the user's" -- while still
    # recording itself as applied -- and the pad stayed bound to an id that
    # matched no controller. The id we wrote before survives that rewrite.
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "input_config": [{
                "backend": "GamepadSDL2",
                "id": "0-f7390003-28de-0000-ff11-000001000000",
                "player_index": "Player1",
                "normalised_by_ryujinx": True,
            }],
        }))
    _state = _json.loads(io.open(emu_config.STATE_PATH, encoding="utf-8").read())
    _state["ryujinx"][emu_config.VERSION_KEY] = 0
    io.open(emu_config.STATE_PATH, "w", encoding="utf-8").write(_json.dumps(_state))
    _ryu_fixed = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        check("a superseded pad id is still recognised as ours after a rewrite",
              _json.load(_handle)["input_config"][0]["id"], emu_catalog.ryujinx._RYUJINX_PAD_ID)
    check("and is not reported as the user's",
          "Config.json/input_config" in _ryu_fixed["skipped"], False)

    # The same for the second wrong id, which is the one installs are carrying
    # now: it kept SDL's crc field, and Ryujinx zeroes that before matching.
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "input_config": [{
                "backend": "GamepadSDL2",
                "id": "0-f6790003-28de-0000-ff11-000001000000",
                "player_index": "Player1",
                "normalised_by_ryujinx": True,
            }],
        }))
    _state = _json.loads(io.open(emu_config.STATE_PATH, encoding="utf-8").read())
    _state["ryujinx"][emu_config.VERSION_KEY] = 0
    io.open(emu_config.STATE_PATH, "w", encoding="utf-8").write(_json.dumps(_state))
    _ryu_crc = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        check("the crc-bearing pad id is corrected too",
              _json.load(_handle)["input_config"][0]["id"], emu_catalog.ryujinx._RYUJINX_PAD_ID)
    check("and it is not reported as the user's",
          "Config.json/input_config" in _ryu_crc["skipped"], False)

    # Ryujinx's id is the Steam pad's guid with SDL's crc field -- bytes 2 and 3
    # -- zeroed, then read back little-endian by .NET. Deriving it here rather
    # than comparing two constants is what would catch putting the crc back.
    _guid_bytes = [int(emu_catalog.steam_pad._STEAM_PAD_GUID[_i:_i + 2], 16) for _i in range(0, 32, 2)]
    _guid_bytes[2] = _guid_bytes[3] = 0
    _expected_pad_id = "0-%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%s" % (
        _guid_bytes[3], _guid_bytes[2], _guid_bytes[1], _guid_bytes[0],
        _guid_bytes[5], _guid_bytes[4], _guid_bytes[7], _guid_bytes[6],
        _guid_bytes[8], _guid_bytes[9],
        "".join("%02x" % _b for _b in _guid_bytes[10:]),
    )
    check("Ryujinx's pad id is the Steam pad with SDL's crc dropped",
          emu_catalog.ryujinx._RYUJINX_PAD_ID, _expected_pad_id)

    # A pad somebody has already configured is theirs: the list stops being
    # all-keyboard, so it is left alone entirely.
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "input_config": [{"backend": "GamepadSDL2", "id": "mine", "name": "Mine"}],
        }))
    _state = _json.loads(io.open(emu_config.STATE_PATH, encoding="utf-8").read())
    _state["ryujinx"][emu_config.VERSION_KEY] = 0
    io.open(emu_config.STATE_PATH, "w", encoding="utf-8").write(_json.dumps(_state))
    _ryu_mine = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        check("a pad already configured by hand is untouched",
              _json.load(_handle)["input_config"][0]["id"], "mine")
    check("and is reported as left alone",
          "Config.json/input_config" in _ryu_mine["skipped"], True)

    # A profile somebody has edited is theirs, whole.
    with io.open(_cemu_profile, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("<emulated_controller><type>Wii U Pro Controller</type></emulated_controller>\n")
    with io.open(emu_config.STATE_PATH, encoding="utf-8") as _handle:
        _state = _json.load(_handle)
    _state["cemu"][emu_config.VERSION_KEY] = 0
    with io.open(emu_config.STATE_PATH, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps(_state))
    _cemu_edited = emu_config.apply_setup(emu_catalog.find("cemu"))
    with io.open(_cemu_profile, encoding="utf-8") as _handle:
        _kept_text = _handle.read()
    check("a hand-edited profile is left alone", "Wii U Pro Controller" in _kept_text, True)
    check("and says so", "controller0.xml/content" in _cemu_edited["skipped"], True)

    # Plain INI has no `\default` marker, so a written False cannot be told from
    # a False the user chose. A key therefore states the default it may replace,
    # and anything else is left alone.
    _dolphin_ini = os.path.join(
        _cfg_home, ".var", "app", "org.DolphinEmu.dolphin-emu",
        "config", "dolphin-emu", "Dolphin.ini",
    )
    _pad_ini = os.path.join(os.path.dirname(_dolphin_ini), "GCPadNew.ini")
    os.makedirs(os.path.dirname(_dolphin_ini), exist_ok=True)
    with io.open(_dolphin_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Display]\nFullscreen = False\nRenderToMain = True\n")

    _dol = emu_config.apply_setup(emu_catalog.find("dolphin"))
    with io.open(_dolphin_ini, encoding="utf-8") as _handle:
        _dol_text = _handle.read()
    check("the setup writes across both of Dolphin's files", _dol["ok"], True)
    check("Dolphin's own default is replaced", "Fullscreen = True" in _dol_text, True)
    check("and a neighbouring setting is untouched", "RenderToMain = True" in _dol_text, True)
    with io.open(_pad_ini, encoding="utf-8") as _handle:
        _pad_text = _handle.read()
    # An explicit Device line is the tell that Dolphin does not find a pad by
    # itself -- an emulator that auto-detected would not need one.
    check("the pad names the device SDL reports on a Deck",
          "Device = SDL/0/Steam Deck Controller" in _pad_text, True)
    # GameCube A sits where the Deck prints B, and Dolphin names buttons by
    # compass point, so `Button E` is the right-hand face button.
    check("GameCube A is the right-hand face button", "Buttons/A = `Button E`" in _pad_text, True)
    check("the D-pad is bound", "D-Pad/Up = `Pad N`" in _pad_text, True)

    # Wii reads a different file entirely, so a working GameCube pad says
    # nothing about it -- which is exactly how it shipped unconfigured once.
    _wii_ini = os.path.join(os.path.dirname(_dolphin_ini), "WiimoteNew.ini")
    with io.open(_wii_ini, encoding="utf-8") as _handle:
        _wii_text = _handle.read()
    check("the Wiimote is bound too", "Device = SDL/0/Steam Deck Controller" in _wii_text, True)
    check("with a nunchuk attached", "Extension = Nunchuk" in _wii_text, True)
    # The Deck's own gyro stands in for a real Wiimote's motion.
    check("and the Deck's motion sensors", "IMUGyroscope/Yaw Left = `Gyro Yaw Left`" in _wii_text, True)

    # Dolphin's first-run dialog asks whether it may report usage data. It is
    # modal and a gamepad cannot dismiss it, so a game launched from Steam stops
    # before it starts.
    check("the analytics prompt is answered", "PermissionAsked = True" in _dol_text, True)
    check("and answered no", "Enabled = False" in _dol_text, True)

    # The case that shipped broken: Dolphin writes its own bindings the first
    # time it runs, so every key existed with a value that was neither absent nor
    # ours and a whole Wiimote profile was skipped one key at a time. A profile
    # is judged by its Device line instead -- still the X11 pointer means nobody
    # has configured it.
    with io.open(_wii_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "[Wiimote1]\n"
            "Device = XInput2/0/Virtual core pointer\n"
            "Buttons/A = `Click 1`\n"
            "Buttons/B = `Click 3`\n"
        )
    emu_config.apply_setup(emu_catalog.find("dolphin"))
    with io.open(_wii_ini, encoding="utf-8") as _handle:
        _redone = _handle.read()
    check(
        "a profile still on the emulator's own device is replaced wholesale",
        "Device = SDL/0/Steam Deck Controller" in _redone,
        True,
    )
    check("including the bindings under it", "Buttons/A = `Button S`" in _redone, True)
    # Not "Click 1": our own Buttons/A binds the mouse click alongside the face
    # button, so its presence proves nothing. Buttons/B is unambiguous.
    check("and Dolphin's own binding under it is replaced", "Click 3" in _redone, False)
    check("with ours", "Buttons/B = `Button E`" in _redone, True)

    # But a profile pointed at a device we did not choose belongs to whoever
    # chose it, and none of it is touched.
    with io.open(_wii_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "[Wiimote1]\nDevice = SDL/0/My Own Fightstick\nButtons/A = `Button Z`\n"
        )
    _mine = emu_config.apply_setup(emu_catalog.find("dolphin"))
    with io.open(_wii_ini, encoding="utf-8") as _handle:
        _kept_text = _handle.read()
    check("a profile someone else configured is left alone",
          "Device = SDL/0/My Own Fightstick" in _kept_text, True)
    check("every key of it, not just the device",
          "Buttons/A = `Button Z`" in _kept_text, True)
    check("and the whole section is reported skipped",
          len([n for n in _mine["skipped"] if n.startswith("WiimoteNew.ini/Wiimote1/")]) > 10,
          True)

    # Back to a state this plugin owns, so the idempotence check below is about
    # repeat application rather than about the fightstick left above.
    os.remove(_wii_ini)
    emu_config.apply_setup(emu_catalog.find("dolphin"))
    check("applying twice changes nothing", emu_config.apply_setup(emu_catalog.find("dolphin"))["skipped"], [])
    with io.open(_dolphin_ini, encoding="utf-8") as _handle:
        check("and the file is identical", _handle.read(), _dol_text)

    # A value that is neither the emulator's default nor ours was chosen by
    # somebody, and windowed is a perfectly reasonable thing to have chosen.
    with io.open(_dolphin_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Display]\nFullscreen = Maybe\n")
    _kept = emu_config.apply_setup(emu_catalog.find("dolphin"))
    check("an unrecognised value is left alone",
          "Dolphin.ini/Display/Fullscreen" in _kept["skipped"], True)
    with io.open(_dolphin_ini, encoding="utf-8") as _handle:
        check("really left alone", "Fullscreen = Maybe" in _handle.read(), True)

    # Two files in one setup must not collide on the same section and key name,
    # which is what the per-file prefix in the recorded state is for.
    check(
        "state keys are scoped per file",
        all(
            name.startswith(("Dolphin.ini/", "GCPadNew.ini/", "WiimoteNew.ini/"))
            for name in _dol["applied"]
        ),
        True,
    )
finally:
    sysenv.user_home = _real_user_home


if __name__ == "__main__":
    summary()


section("a TOML value with the emulator's own comment after it")

# Xenia writes a description after every setting, and reading the value back
# without stripping it made every key look like one the user had set: `false`
# plus forty characters of prose equals neither the literal nor the default.
# Nothing failed and nothing was logged -- the emulator just kept its own
# settings, and a Deck got a windowed game with a menu bar over it.
_commented = os.path.join(TMP, "commented.toml")
_lines = [
    "[Display]",
    "fullscreen = false                    \t# Whether to launch in fullscreen.",
    "[Storage]",
    "content_root = 'C:/games/#1 hits'     # A path with a hash in it.",
]
with open(_commented, "w", encoding="utf-8") as _handle:
    _handle.write("\n".join(_lines) + "\n")

_applied, _skipped, _written, _error = emu_config._apply_toml_keys(
    _commented,
    {"Display": {"fullscreen": {"value": "true", "default": "false", "raw": True}}},
)
check("the commented default is recognised and replaced", _applied, ["Display/fullscreen"])
check("and nothing was skipped as somebody else's", _skipped, [])

_text = open(_commented, encoding="utf-8").read()
check("the value really changed", "fullscreen = true" in _text, True)
check("and the emulator's own description survived the rewrite",
      "# Whether to launch in fullscreen." in _text, True)

# A `#` inside a quoted string is part of the path, not a comment. xemu stores
# filesystem paths this way and a folder may certainly contain one.
check("a hash inside a quoted value is not read as a comment",
      emu_config._read_value("content_root = 'C:/games/#1 hits'  # note", quoted=True),
      "C:/games/#1 hits")
check("while a bare value stops at the hash",
      emu_config._read_value("fullscreen = false   # note", quoted=True), "false")
check("and an unquoted format is left exactly as it was",
      emu_config._read_value("Fullscreen = False   # note"), "False   # note")
