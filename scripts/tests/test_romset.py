#!/usr/bin/env python3
"""An arcade ROM set is the cartridge, not a wrapper round a game.

Every other `.zip` on the Deck holds one game and is opened by unpacking it --
which is what the plugin assumed, in two places. It matched a zip on whatever
the first file inside was called, so `scud.zip` reported `bin`, drew the
PlayStation and Mega Drive cores that claim it, and suggested SwanStation for
Scud Race while offering no arcade emulator at all. And it offered **Unpack this
zip** for it, which would have scattered forty chip dumps across the transfer
folder and then deleted the only file that could be played.

Both follow from telling the two kinds of archive apart, so that is what is
checked here -- against the shapes real sets have, and against the ordinary
archives the rule must keep its hands off.
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary, TMP  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402
import launchers  # noqa: E402
import libretro_meta  # noqa: E402
import model3_games  # noqa: E402
import platforms  # noqa: E402
import ra_cores  # noqa: E402
import sysenv  # noqa: E402

home = os.path.join(TMP, "romset")
os.makedirs(home, exist_ok=True)


def _zip(name, members):
    path = os.path.join(home, name)
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, b"\0" * 32)
    return path


section("the sets Supermodel actually reads")

# Member names taken from Supermodel's own Games.xml, which lists every file of
# all 63 Model 3 sets: numeric extensions for the EPROMs, `icN` for the mask
# ROMs by socket, and `bin` for the sound board.
check("a Model 3 set is one",
      ra_cores.is_romset(_zip("scud.zip", [
          "epr-19731.17", "epr-19732.18", "epr-19733.19",
          "mpr-20364.ic2", "mpr-20365.ic9", "snd.bin",
      ])),
      True)

# fvipers2 is the set that broke the first version of this rule: four of its
# members carry no extension at all, so "every member looks like a chip dump"
# had to mean "or has no name past the dot" as well.
check("including one with extensionless members",
      ra_cores.is_romset(_zip("fvipers2.zip", [
          "epr-20596a.20", "epr-20597a.21", "mpr-20576", "mpr-20577",
      ])),
      True)

check("and it is matched on the archive, not on what is inside it",
      ra_cores.content_extension(os.path.join(home, "scud.zip")), "zip")

section("the archives it must not touch")

for name, members, inner in (
    ("mario.zip", ["Mario.sfc"], "sfc"),
    # A readme beside the ROM is common and must not change the answer.
    ("zelda.zip", ["Zelda.sfc", "readme.txt"], "sfc"),
    # bin+cue is the shape a ROM set is closest to and the one it must never be
    # confused with. The cue sheet is what separates them.
    ("psx.zip", ["Game.bin", "Game.cue"], "bin"),
    # Several tracks and no cue: still not a set, because nothing in it is a
    # chip dump. Without this clause a multi-track rip would qualify on the
    # strength of having more than one `.bin` in it.
    ("tracks.zip", ["G (Track 1).bin", "G (Track 2).bin"], "bin"),
    # One file cannot be a set, whatever it is called.
    ("lone.zip", ["Game.bin"], "bin"),
    # And a stray numeric member does not make a game into one.
    ("patched.zip", ["Game.sfc", "patch.1"], "sfc"),
):
    path = _zip(name, members)
    check("%s is not a ROM set" % name, ra_cores.is_romset(path), False)
    check("and still resolves to %r" % inner,
          ra_cores.content_extension(path), inner)

section("what it does when the file will not open")

check("a file that is not a zip is not a ROM set",
      ra_cores.is_romset(os.path.join(home, "missing.zip")), False)
check("nor is something that is not an archive at all",
      ra_cores.is_romset(__file__), False)

section("the answer it gives pairs the file with an emulator")

# The same trap tests/test_xbox360_header.py guards: a rule that classifies a
# file correctly and then hands back a string nothing claims is worse than no
# rule, because an unmatched ROM is a panel with no button rather than an error.
_supermodel = emulator_catalog.find("supermodel")
check("Supermodel is in the catalog", bool(_supermodel), True)
check("its platform is one the picker knows",
      _supermodel["platform"] in
      [label for label, _full, _short in platforms.NO_LIBRETRO_PLATFORMS],
      True)
check("and `zip` -- what a ROM set resolves to -- is what it claims",
      "zip" in emulator_catalog.MANUAL_EXTENSIONS[_supermodel["platform"]],
      True)

# Without this argument the emulator installs, launches, and detects no ROM
# whatever: the flatpak keeps Games.xml in /app/bin/Config while Supermodel
# looks for it under the app's own config directory, and says "ROMs will not be
# detected" when it is not there. Nothing else in the plugin would report that
# -- the shortcut would be made, the game would be added, and it would fail on
# the Deck with an error nobody sees.
check("the launch arguments point at the packaged Games.xml",
      "-game-xml-file=/app/bin/Config/Games.xml" in _supermodel["args"], True)

section("and the emulators that can run one are the ones offered first")

# The wrong answer this replaces was on the device: probe_rom reported
# `suggested=cap32` for daytona2.zip -- an Amstrad CPC core preselected for
# Daytona USA 2, because it claims `zip` like the twenty-one others that merely
# unpack an archive to reach the game inside.
check("an arcade core reads ROM sets",
      platforms.reads_rom_sets({"databases": ["MAME"]}), True)
check("so does one declaring a libretro-less arcade board",
      platforms.reads_rom_sets({"databases": [], "platform_full": "Sega Model 3"}),
      True)
check("a home computer core does not",
      platforms.reads_rom_sets({"databases": ["Amstrad - CPC"]}), False)

# The registered emulator stores the *display* name, not the picker label an
# entry is written with. Matching on the label alone silently matched nothing,
# which is the failure this half exists to prevent -- Supermodel would have gone
# on losing the sort to cap32 with every test above still passing.
check("the display name maps back to the label the catalog uses",
      platforms.reads_rom_sets(
          {"databases": [], "platform_full": _supermodel["platform"]}),
      True)

# The folder table is the other half of the answer. Once a game is filed, its
# folder is evidence about that particular file rather than about the shape of
# it, and it sorts above the rule at the top of this section.
check("a filed Model 3 game is recognised by its folder",
      platforms.system_for_folder("/roms/model-3/scud.zip"), "Sega - Model 3")
check("and the folder that name is filed into round-trips",
      platforms.folder_name("Sega - Model 3"), "model-3")


section("a ROM set is named after the set, so the name has to come from somewhere")

# The whole point, and it is two problems rather than one: `daytona2` is a poor
# thing to see on a Steam shelf, and it is also what the artwork search is
# handed. SteamGridDB has a great deal of Daytona USA 2 and nothing at all
# under `daytona2`.
_deploy = os.path.join(
    sysenv.user_home(), ".local", "share", "flatpak", "app",
    model3_games.SUPERMODEL_APP, "current", "active", "files", "bin", "Config")
os.makedirs(_deploy, exist_ok=True)
with open(os.path.join(_deploy, "Games.xml"), "w", encoding="utf-8") as _handle:
    _handle.write(
        '<?xml version="1.0"?><games>'
        '<game name="daytona2" stepping="2.1">'
        '<identity><title>Daytona USA 2 - Battle on the Edge</title>'
        '<region>Japan</region><version>Revision A</version></identity>'
        '<roms><file name="epr-20864a.20"/></roms></game>'
        '<game name="scud"><identity><title>Scud Race</title>'
        '<region>Export</region></identity></game>'
        '</games>')
model3_games.forget_cached_games()

check("the set name resolves to the title the emulator knows",
      model3_games.title_for("daytona2"), "Daytona USA 2 - Battle on the Edge")
check("and cleans up by the same rules every other ROM does",
      libretro_meta.display_title(model3_games.title_for("daytona2")),
      "Daytona USA 2: Battle on the Edge")

# A MAME or FinalBurn set is a ROM set too and this list does not cover it, so
# it keeps the name its file has. A terse name beats a confident wrong one
# borrowed from another system.
check("a set Supermodel does not know is left alone",
      model3_games.title_for("sf2ce"), "")
check("and something that is not a set name is not looked up at all",
      model3_games.title_for("Daytona USA 2 (Japan)"), "")

# Read from the installed flatpak rather than bundled, so a build that adds
# games is right without a plugin release -- which also means it has to cope
# with the emulator not being installed at all.
_saved_app = model3_games.SUPERMODEL_APP
model3_games.SUPERMODEL_APP = "com.example.NotInstalled"
model3_games.forget_cached_games()
check("with the emulator absent nothing is claimed", model3_games.title_for("daytona2"), "")
model3_games.SUPERMODEL_APP = _saved_app
model3_games.forget_cached_games()


section("Steam's own keyboard, kept off the game")

# It opened over Daytona USA 2 and stayed there, and the chain is inside SDL2:
# Steam sets `SteamDeck=1` in every game's environment, SDL_x11video reads it
# into `is_steam_deck`, and `SDL_StartTextInput` then opens
# `steam://open/keyboard?...` because the hint below defaults to *true*. That
# URL is in the Deck's own console_log.txt, timestamped to each launch, so this
# is measured rather than reasoned. Supermodel never asks for text input itself
# -- the call comes from the ImGui backend it bundles.
check("the entry turns the SDL hint off",
      _supermodel.get("env", {}).get("SDL_ENABLE_SCREEN_KEYBOARD"), "0")

# The other half of the same environment, and the one without which the pad is
# dead. SDL2 drops joystick events while the window has no input focus, and
# Supermodel never asks for focus -- CreateGLScreen is called with
# focusWindow=false. Every other link was verified on the Deck: the virtual pad
# emits L3 and R3, Supermodel has that device open, and -print-inputs reports
# the binding. Only this one was dropping them.
# Without this the button numbers below are not the buttons they name.
# Supermodel has two SDL backends; only `sdlgamepad` reads the pad through
# SDL_GameControllerGetButton, where BUTTONn is a named button. The default
# `sdl` uses raw indices, and on Steam's virtual pad raw 8 -- which is what
# JOY1_BUTTON9 becomes -- is the Steam button, which never reaches a game.
_setup_keys = _supermodel["setup"]["sections"]["Global"]
check("the input backend is the one where a button number names a button",
      _setup_keys.get("InputSystem"), '"sdlgamepad"')
check("and Test is on the left stick, which that backend calls button 9",
      _setup_keys["InputTestA"]["value"], '"KEY_6,JOY1_BUTTON9"')

check("and lets the pad through without window focus",
      _supermodel.get("env", {}).get("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"),
      "1")

# And the half that makes it reach the sandbox. The environment is passed as
# `--env=` on the `flatpak run` line, so an entry declaring it and a launcher
# that drops it look identical from here.
_argv = emulators.flatpak_prefix(
    {"target": "com.supermodel3.Supermodel",
     "env": _supermodel.get("env") or {}})
check("and the launch line carries them into the sandbox",
      ["--env=SDL_ENABLE_SCREEN_KEYBOARD=0",
       "--env=SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS=1"],
      [a for a in _argv if a.startswith("--env=")])

# Both version numbers, because neither reaches a Deck that already has the
# emulator on its own. `env` is copied onto the stored record only when the
# recipe moves, and the argv is baked into each launcher when it is written --
# so a game already added keeps the old command line until the format bumps.
check("the recipe moved, so an installed emulator picks the environment up",
      _supermodel.get("recipe", 1) >= 3, True)
check("and the launcher format moved, so a game already added is rewritten",
      launchers.FORMAT_VERSION >= 10, True)


if __name__ == "__main__":
    summary()
