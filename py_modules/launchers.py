"""Generate a tiny shell script per game and point the Steam shortcut at it.

Steam stores a shortcut's arguments as a single LaunchOptions string, which it
re-splits on launch. ROM filenames are full of spaces, apostrophes, brackets and
ampersands, so round-tripping them through that field is a reliable source of
"game won't start" bugs. A generated script sidesteps the quoting problem
entirely and gives us one obvious place to look when a launch misbehaves.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import stat
import time

import decky

import cheevos
import emu_config
import emu_install
import emulator_catalog
from emulator_catalog import hotkeys
import emulators
import ra_detect
import sysenv

LAUNCHER_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "launchers")

#: What the emulator said on its last run, one file per game.
#:
#: **This exists because the plugin took the emulator's own error channel away.**
#: `hide_osd` defaults to "all" so a game launched from Steam looks like a game
#: from Steam, and `store.py` records the cost in the same breath: RetroArch's
#: error text goes with the chatter, so a core that cannot find its BIOS fails
#: quietly. The stated replacement is the firmware check, which runs when a game
#: is *added* and answers nothing afterwards -- a BIOS moved, a card unmounted,
#: an emulator build that regressed, all present as a black screen and silence.
#:
#: One run, not a history: the file is truncated as the launcher starts, so what
#: is here is always the launch somebody is asking about. See `LAUNCH_LOG_CAP`
#: for what stops a long session filling the disk with it.
LAUNCH_LOG_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "launch-logs")

#: How much of one is worth keeping, swept at startup.
#:
#: The redirect is unbounded while a game runs -- capping it in shell needs a
#: pipe, and a pipe whose reader exits sends the emulator SIGPIPE, which is a
#: real crash traded for a diagnostic. So the size is dealt with afterwards
#: instead: a log over this is truncated to its tail at startup, and the reader
#: only ever asks for the last few thousand characters anyway. A verbose
#: emulator can still write more than this during one session; it is one file
#: per game and the next launch truncates it.
LAUNCH_LOG_CAP = 2 * 1024 * 1024

#: Where the launch gate leaves its notes. Two kinds of one-line file, both
#: named after the Steam app id: `bounced-<id>`, written by a launcher that
#: refused to start and listing what was already running, and `approved-<id>`,
#: written by the panel when the user said go and consumed by the next launch.
#:
#: A third kind joins them for cloud saves: `cloudwait` says the panel is
#: fetching saves for this game and the launcher should hold, and
#: `cloudready-<id>` says it may go. See `_CLOUD_GATE`.
#:
#: Files rather than a socket because the other end is `/bin/sh` with Steam's
#: runtime stripped out of its environment. A file it can read with `[ -f ]` is
#: the whole protocol, and nothing in the launch path depends on the plugin
#: being loaded, or even installed.
LAUNCH_GATE_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "launch")

# Bumped whenever a change here means existing launchers are wrong rather than
# merely old. Nothing rewrites launchers on upgrade, so without this a fix only
# reaches a game the next time some unrelated launch setting is changed -- which
# is indistinguishable from the fix not working.
#
#   1  the original format
#   2  standalone emulators exported SDL_JOYSTICK_HIDAPI=1
#   3  that export removed again -- measured inside Steam it changes nothing,
#      and the controller fault was in the bindings, not the environment
#   4  flatpak emulators are handed the gamescope socket, without which the
#      bypass layer fails to connect and the emulator shows a Vulkan error
#   5  emulators can carry environment into the sandbox, which shadPS4 needs to
#      stop picking the software rasteriser out of four Vulkan devices. The
#      argv is baked into every launcher when it is written, so fixing how it
#      is built reaches nothing already on disk until they are rewritten --
#      which is the whole reason this number exists.
#   6  the default OSD mode became `all`. A launcher names the override file it
#      was written with, so a game added under the old default went on pointing
#      at retroarch-overrides-startup.cfg however the setting read afterwards --
#      the panel would have said "Hide all on-screen messages" while the games
#      already in the library kept showing them. Rewritten, each game resolves
#      its own options again, so anything overridden per game is kept.
#   7  the launch gate. Steam will not warn before launching one of these over
#      a running game -- its check is gated on an app_type a non-Steam shortcut
#      does not carry -- and nothing on the Steam side can stop the launch
#      either, so the script does it. Existing games need this or the warning
#      only ever appears for games added afterwards.
#   8  the menu shortcut clears a quit binding on the same buttons. EmuDeck
#      binds Start+Select to quitting -- twice, as a combo and as a hotkey
#      pair -- which is the same press as the default menu shortcut, so opening
#      the menu also quit. The override file carries the fix and is written
#      when a launcher is, so an existing library needs rewriting or the
#      shortcut goes on quitting for everyone who already had one.
#   9  an emulator's environment can now suppress Steam's on-screen keyboard,
#      which SDL2 opens over the game on a Deck unless the hint says otherwise.
#      The environment is baked into the argv when a launcher is written, so
#      like version 5 this reaches nothing already on disk until they are
#      rewritten -- and a game already added is exactly where it was seen.
#  10  and the same environment carries the joystick hint an emulator needs to
#      read a pad at all when its window has no input focus. Same reason as 9:
#      the argv is baked in when the launcher is written.
#  11  save RAM reaches disk every second rather than every ten. Steam's Stop
#      is not a clean exit -- the signal goes to `flatpak run` and the process
#      inside never sees it -- so whatever has not been flushed is lost, and a
#      Deck produced a Pokemon save with 11 of the 14 sectors it needed. The
#      setting rides in the override file, written when a launcher is, so like
#      version 8 an existing library keeps losing saves until they are
#      rewritten.
#  12  the launcher keeps what the emulator says. Nothing did, so a game that
#      started and died left no trace at all -- and `hide_osd` had already
#      taken away the on-screen text that would have explained it. Baked into
#      the script, so like every version above it reaches nothing already on
#      disk until the launchers are rewritten.
#  13  RetroArch is launched with `--verbose`, which is the only thing that
#      makes it say why a game did not start -- without it a missing ROM
#      produced an empty log and version 12 collected nothing. **The argv is
#      built in `ra_detect`, not here**, and that is exactly why this bump was
#      missed the first time: the version governs everything baked into the
#      script, wherever the code that bakes it lives. Anything that changes what
#      the launcher runs needs a number here, or it reaches only games added
#      afterwards -- which on a device that already has a library is nothing.
#  14  and again, because 13 could not reach the game it was for. `rebuild`
#      skipped any game whose ROM was missing, so the broken game kept its old
#      launcher while the *number* was recorded as done -- and this number is
#      the only thing that decides whether launchers are rewritten, so nothing
#      would ever have retried. The skip is gone (see `_write_launchers`); this
#      bump is what carries the fix to a device that already recorded 13.
#
#      Worth keeping in mind whenever a rebuild is fixed: the version says an
#      upgrade *ran*, not that it reached every game, so a bug in the rebuild
#      itself always costs two numbers.
#  15  an emulator that reads motion off a socket starts its server here and
#      stops it afterwards, which costs the `exec` for that emulator only. The
#      server is named in the script, so a game added before it was fetched has
#      a launcher with no motion in it and needs rewriting -- and fetching the
#      server is exactly when that is true of every game already added.
#  16  and again, for the reason version 14 gives: 15 ran on a Deck where the
#      server had not downloaded yet -- GitHub was rate-limiting the address --
#      so every launcher was rewritten without motion and the version recorded
#      itself as done. Nothing would ever have retried. `_upgrade_emulator_setups`
#      now rebuilds when the server *arrives*, which covers every future case;
#      this number is what reaches the Decks that already recorded 15.
#  17  the motion block execs when the server binary is missing, instead of
#      running the emulator as a child for a cleanup that has nothing to clean.
#      Only reachable when the binary is deleted from outside the panel, but the
#      `exec` is deliberate everywhere else and a launcher should not give it up
#      for nothing.
#  18  the launcher checks that the game's ROM and its emulator are actually
#      there, and refuses with a note instead of starting something that cannot
#      run. Existing games need rewriting or the check only ever covers games
#      added afterwards, which on a library that already exists is nothing.
#  19  the note the preflight leaves names the emulator, so the dialog can say
#      which one is gone rather than "the emulator". Baked into the script,
#      because the name is known when it is written and may not be afterwards.
#  20  that name is the emulator's, not its package's. A record registered
#      with the link button carries its flatpak id in `name`, so the dialog
#      said "io.github.ryubing.Ryujinx"; the catalog is asked first now. And a
#      libretro core is described as a core rather than as the emulator.
#  21  and again, because 20 was wrong for the case that prompted it. An
#      emulator game whose emulator has no record arrives with `emulator` empty
#      and its flatpak id in `core_path`, which version 20 read as a libretro
#      core -- so the dialog said "The io.github.ryubing.Ryujinx core". Only a
#      `.so` is a core now; anything else is looked up in the catalog by target.
#  22  the launcher waits for cloud saves to come down, when the panel says a
#      launch is worth waiting for. A file check that finds nothing on a Deck
#      with cloud saves off, so it costs an existing game nothing -- but the
#      line has to be in the script, and a game added before this has no line.
#  23  and it waits for the panel to *claim* the launch first. 22 asked once,
#      at the moment the script started, which is before the panel can have
#      answered -- so the game began while the save was still coming down.
#  24  and 23 lost the same race with a longer grace on it, measured on the
#      device. The script now *announces itself* and waits; nothing has to
#      hear about the launch from Steam in time to claim it.
#  25  the wait follows the work rather than a fixed ceiling. 24 gave up at 8
#      seconds and the fetch answered at 8.2 -- three network round trips,
#      measured on the device. The backend now says it is still working and
#      this waits while it keeps saying so.
#  26  and a save conflict can answer "do not start", which is the third thing
#      Steam's own cloud dialog offers and the only one that needed the script.
#  27  the wait writes what it did to `lastwait.log`. The gate runs before the
#      launch log is opened, so a launch that went wrong left nothing to read.
#      It also clears its own leftovers before waiting, so a stop written after
#      a launcher had gone cannot refuse the launch after it.
#  28  and it says when a launch actually reached the emulator. Without that,
#      a launch stopped at the save conflict still uploaded afterwards -- which
#      overwrote the very saves the person had declined to overwrite.
#  29  the wait is a stopped process rather than a conversation over files.
#      Every timing bug 22-27 fixed was in that conversation; a stopped process
#      has no timing. See `_CLOUD_GATE`.
#  30  and refusing a launch wakes it to exit rather than killing it. Steam is
#      waiting on that process: killed, the loading screen stayed up and the
#      launch never finished.
#  31  the wait believes `cloud-on` only while it is fresh, so a dialog can
#      wait for a person instead of for a clock. 30 gave somebody 30 seconds to
#      read it and then started the game anyway.
#  32  a program that reads its game from its own config is told which game by
#      the launcher, not when the game was added. Two games on one such program
#      wrote the same key, so the second added repointed the first.
#  33  the hotkey helper is told which button is its own, because the one it
#      picks by default is half of the gesture it is there to provide: Start
#      plus that button quits it, hardcoded, so the first press was the last.
#  34  the previous run's output is kept beside the last one. A game that fails
#      is launched again at once, and the retry was truncating the only account
#      of what went wrong.
#  35  an approval is honoured only while it is fresh. One left behind by a
#      launch that never happened let the next one past the two-games gate
#      without asking.
FORMAT_VERSION = 35

# One file per OSD mode rather than one shared file. Games can override the
# global setting individually, and a single file would mean the last game
# written decided the behaviour of every other one.
#
# The menu shortcut below also lands in these files but is deliberately not part
# of the key: it is a global setting, so every file written in one pass carries
# the same value. Make it overridable per game and this has to be keyed by both.
OVERRIDE_CONFIGS = {
    "startup": os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "retroarch-overrides-startup.cfg"),
    "all": os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "retroarch-overrides-all.cfg"),
    # "keep" suppresses nothing, so this file exists only when some other
    # setting -- today the menu shortcut -- still needs to reach RetroArch.
    "keep": os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "retroarch-overrides-keep.cfg"),
}

# Launchers written before per-game OSD settings existed still reference this
# path, so it is left in place. Nothing writes it any more; those launchers move
# to a mode file the next time they are rebuilt.
OVERRIDE_CONFIG = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "retroarch-overrides.cfg")

# A controller profile for the pad Steam actually hands a game, and the
# directory RetroArch is pointed at to find it.
#
# RetroArch ships 1035 profiles and matches them on vendor and product id. The
# pad a Steam-launched game sees is Steam Input's virtual one, which calls
# itself "Microsoft X-Box 360 pad" but carries Valve's ids -- 0x28de/0x11ff --
# so the X-Box 360 profile whose bindings are exactly right is rejected before
# its name is even considered. RetroArch then reports:
#
#   [Autoconf] Microsoft X-Box 360 pad 0 (10462/4607) not configured.
#
# and an unconfigured pad has no bindings at all: the game runs and nothing
# responds. Read off a Deck rather than reasoned about, after a RetroArch data
# directory was deleted and took the downloaded profiles with it.
#
# The bindings below are the bundled "Microsoft X-Box 360 pad.cfg" verbatim,
# under Valve's ids. Confirmed on hardware before being written down here.
#
# One profile rather than a mirror of all 1035: RetroArch reads exactly one
# autoconfig directory, and pointing at ours means the bundled set is not
# consulted for these launches. Under Steam Input that costs nothing, because
# the virtual pad is the only pad a Steam-launched game can see -- Steam hides
# the real ones. Turn Steam Input off for such a game and its own pad would
# find no profile here; mirroring 4.2MB of somebody else's data on every launch
# to cover that is the worse trade.
#
# The `udev` folder name is not decoration and is also not a bug. RetroArch
# reads profiles from the autoconfig directory and from
# `<autoconfig dir>/<joypad driver>`, and nowhere else below it -- the scan is
# not recursive and a profile's own `input_driver` line is not what selects it
# (tasks/task_autodetect.c, matching is on vendor/product/name/phys). So under a
# config set to `sdl2` -- which is exactly what EmuDeck's retroarch.cfg does --
# RetroArch looks in `<ours>/sdl2` and finds nothing.
#
# **That is fine, and forcing the driver back to udev to "fix" it is a
# regression.** The sdl2 joypad driver needs no profile at all: SDL recognises
# Steam's virtual pad as a game controller, so RetroArch opens it with
# SDL_GameControllerOpen and exposes normalised SDL_CONTROLLER_BUTTON_* indices
# that its built-in default binds already cover (input/drivers_joypad/
# sdl_joypad.c). Measured on a Deck with EmuDeck installed: config says sdl2,
# only `udev/` exists here, controller works.
#
# The "unconfigured pad has no bindings at all" failure above is real but is a
# *udev* failure -- that driver has no normalised layout to fall back on. Do not
# generalise it to the other drivers, and do not add a line that names a joypad
# driver: it would move a working sdl2 setup onto udev, where the controller
# then depends entirely on the single profile below matching. A whole commit
# went in and back out on that reasoning.
AUTOCONFIG_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "autoconfig")

_STEAM_PAD_PROFILE = """\
input_driver = "udev"
input_device = "Microsoft X-Box 360 pad"
input_vendor_id = "10462"
input_product_id = "4607"

input_b_btn = "0"
input_a_btn = "1"
input_y_btn = "2"
input_x_btn = "3"
input_l_btn = "4"
input_r_btn = "5"
input_select_btn = "6"
input_start_btn = "7"
input_menu_toggle_btn = "8"
input_l3_btn = "9"
input_r3_btn = "10"
input_up_btn = "h0up"
input_down_btn = "h0down"
input_left_btn = "h0left"
input_right_btn = "h0right"
input_l2_axis = "+2"
input_r2_axis = "+5"
input_l_x_plus_axis = "+0"
input_l_x_minus_axis = "-0"
input_l_y_plus_axis = "+1"
input_l_y_minus_axis = "-1"
input_r_x_plus_axis = "+3"
input_r_x_minus_axis = "-3"
input_r_y_plus_axis = "+4"
input_r_y_minus_axis = "-4"
"""


def write_pad_profile():
    """Put the Steam pad's controller profile where RetroArch will look.

    Returns the directory to hand RetroArch, or '' if it could not be written --
    in which case the launcher says nothing about autoconfig and RetroArch
    behaves exactly as it did before this existed.
    """
    folder = os.path.join(AUTOCONFIG_DIR, "udev")
    path = os.path.join(folder, "Steam Virtual Gamepad.cfg")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_STEAM_PAD_PROFILE)
    except OSError as error:
        decky.logger.warning("Could not write the pad profile: %s", error)
        return ""
    return AUTOCONFIG_DIR

# RetroArch announces itself when content loads: an animated banner with the
# game and core, followed by notices about controller autoconfig, refresh rate
# and so on. Passing these through --appendconfig suppresses them for games
# launched from here without editing the user's own retroarch.cfg.
_STARTUP_QUIET = (
    ("menu_show_load_content_animation", "false"),
    ("notification_show_autoconfig", "false"),
    ("notification_show_config_override_load", "false"),
    ("notification_show_refresh_rate", "false"),
    ("notification_show_set_initial_disk", "false"),
    ("notification_show_patch_applied", "false"),
    ("notification_show_remap_load", "false"),
    ("notification_show_cheats_applied", "false"),
)

# Kills every on-screen message, including save-state confirmations and errors.
_ALL_QUIET = _STARTUP_QUIET + (("video_font_enable", "false"),)

# How to reach RetroArch's menu from a controller. Out of the box there is no
# combo at all: RetroArch defaults this to 0, and its other default -- the Guide
# button, bound by the controller autoconfig -- never reaches RetroArch on a
# Deck, because Steam takes the Steam button first. So a game launched from here
# has no way back to the menu unless we set one.
#
# RetroArch takes a fixed enum here rather than a free-form binding; the numbers
# are `input_combo_type` in input/input_defines.h and are positional, so they
# live next to their names here instead of being spelled out in the UI. "off"
# writes nothing at all, which leaves whatever the user set in retroarch.cfg.
MENU_COMBOS = {
    "off": "",
    "down_y_l_r": "1",
    "l3_r3": "2",
    "l1_r1_start_select": "3",
    "start_select": "4",
    "l3_r": "5",
    "l1_r1": "6",
    "hold_start": "7",
    "hold_select": "8",
    "down_select": "9",
    "l2_r2": "10",
}


#: RetroArch's button numbers for the pad, as its config writes them.
#:
#: Only the two the exit hotkey is built from are needed: EmuDeck binds
#: `input_enable_hotkey_btn` to Select and `input_exit_emulator_btn` to Start,
#: which is the same press as the `start_select` menu combo.
_SELECT_BTN = "4"
_START_BTN = "6"

#: The buttons each menu combo uses, for the ones that can collide with an exit
#: hotkey. Keyed by the value written to `input_menu_toggle_gamepad_combo`.
#:
#: Only Start and Select matter here: an exit hotkey is a modifier plus a
#: button, and every layout worth worrying about builds it from those two.
#: A combo using neither cannot collide, so it is absent rather than empty.
_COMBO_BUTTONS = {
    "3": {_SELECT_BTN, _START_BTN},   # L1+R1+Start+Select
    "4": {_SELECT_BTN, _START_BTN},   # Start+Select
    "7": {_START_BTN},                # hold Start
    "8": {_SELECT_BTN},               # hold Select
    "9": {_SELECT_BTN},               # Down+Select
}


def _quit_bindings_that_collide(config_dir, combo):
    """Settings that neutralise a quit binding sharing buttons with `combo`.

    **The problem this exists for is EmuDeck, and it is not an edge case.**
    EmuDeck's RetroArch config binds Start+Select to quit twice over -- once as
    `input_quit_gamepad_combo = "4"`, and once as the hotkey pair
    `input_enable_hotkey_btn = "4"` (Select) with `input_exit_emulator_btn =
    "6"` (Start). This plugin's default menu shortcut is the same press. With
    both installed, opening the menu also quits: RetroArch tears the core down
    and the user sees their game vanish. On a core that aborts in
    `retro_deinit` -- Beetle bsnes does -- it vanishes with a crash instead,
    which reads as the game being broken.

    Measured on a device: a config from before EmuDeck ran was 661 bytes with
    no combo lines at all, and the menu shortcut worked. The one EmuDeck wrote
    is 111KB and carries all three bindings.

    Written into the per-launch override and nowhere else, so what EmuDeck set
    still holds for everything started outside this plugin -- the same rule the
    rest of this file follows, and the reason `config_save_on_exit` is turned
    off beside it.

    Returns [] when there is no collision, which is the ordinary case: a config
    RetroArch wrote itself has no quit combo at all.
    """
    wanted = _COMBO_BUTTONS.get(combo)
    if not wanted or not config_dir:
        return []

    config = ra_detect.parse_cfg(os.path.join(config_dir, "retroarch.cfg"))
    if not config:
        return []

    settings = []

    # The standalone combo. Compared by the buttons it means rather than by the
    # number, so `3` (L1+R1+Start+Select) and `4` (Start+Select) are seen to
    # overlap -- pressing the four includes pressing the two.
    quit_combo = config.get("input_quit_gamepad_combo", "0")
    if _COMBO_BUTTONS.get(quit_combo, set()) & wanted:
        settings.append(("input_quit_gamepad_combo", "0"))

    # And the hotkey pair, which is a second way to spell the same press.
    # Cleared by unbinding the exit key rather than the modifier: the modifier
    # is shared by every other hotkey the user has, and taking it away would
    # cost them all of those.
    hotkey = config.get("input_enable_hotkey_btn", "nul")
    exit_btn = config.get("input_exit_emulator_btn", "nul")
    if hotkey in wanted and exit_btn in wanted and hotkey != exit_btn:
        settings.append(("input_exit_emulator_btn", "nul"))

    return settings


def write_override_config(hide_osd, menu_combo="off", cheevos_settings=None,
                          config_dir=""):
    """Write the --appendconfig file for these settings, or '' to pass nothing.

    `cheevos_settings` is the whole settings dict; RetroAchievements contributes
    nothing unless it is switched on and signed in (see cheevos.config_lines).
    """
    if hide_osd == "all":
        settings = list(_ALL_QUIET)
    elif hide_osd == "startup":
        settings = list(_STARTUP_QUIET)
    else:
        settings = []

    combo = MENU_COMBOS.get(menu_combo, "")
    if combo:
        settings.append(("input_menu_toggle_gamepad_combo", combo))
        # A menu shortcut that also quits is worse than no menu shortcut.
        settings.extend(_quit_bindings_that_collide(config_dir, combo))

    # Always, regardless of the OSD mode: without it the pad Steam hands the
    # game matches no profile and nothing responds. See AUTOCONFIG_DIR.
    autoconfig = write_pad_profile()
    if autoconfig:
        settings.append(("joypad_autoconfig_dir", autoconfig))

    # Global like the menu combo, so it rides in the same per-OSD-mode files.
    settings.extend(cheevos.config_lines(cheevos_settings or {}))

    # Nothing to say: pass no --appendconfig rather than an empty file, so the
    # launcher stays as close to a plain RetroArch invocation as possible.
    if not settings:
        return ""

    # Stop RetroArch writing our overrides into the user's own retroarch.cfg.
    #
    # `--appendconfig` merges these values into the running configuration, and
    # RetroArch ships with `config_save_on_exit = "true"`, so on quit it saves
    # the *merged* result -- silently making every override here permanent and
    # global. It is not theoretical: a Deck used for a few days had
    # `input_menu_toggle_gamepad_combo = "4"`, `menu_show_load_content_animation`
    # and `notification_show_autoconfig` sitting in its own config, none of which
    # the user had set, all of them ours. The comment above about only affecting
    # games launched from here was simply not true.
    #
    # The cost is that changes made from RetroArch's menu during one of these
    # sessions are not saved either. That is the right trade -- silently
    # rewriting a config we were asked not to touch is worse -- and RetroArch
    # still has an explicit "Save Current Configuration" for anyone who wants it.
    settings.append(("config_save_on_exit", "false"))

    # How long a save can be lost for. RetroArch holds the cartridge's save RAM
    # in memory and writes it to disk on this interval, or on a clean exit --
    # and a game launched from here gets no clean exit. There is no quit binding
    # (see `_quit_bindings_that_collide`), so the only way out is Steam's Stop,
    # which kills the process without RetroArch ever flushing.
    #
    # RetroArch's default is 10 seconds, and losing ten seconds means losing the
    # save somebody just made. Measured on a Deck: Pokemon Sapphire wrote 11 of
    # the 14 sectors a Gen-III save needs, and the game reported "the save file
    # has been deleted" on the next launch -- an interval that caught the write
    # half done. Waiting fifteen seconds before quitting kept it.
    #
    # One second rather than zero-and-flush-on-write: this is a whole-buffer
    # write, at most 128KB, and only when the buffer is dirty, so a second costs
    # nothing worth measuring on a device that is idle between saves anyway.
    settings.append(("autosave_interval", "1"))

    path = OVERRIDE_CONFIGS.get(hide_osd, OVERRIDE_CONFIGS["keep"])
    os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
    lines = [
        "# Generated by %s -- appended over RetroArch's own config at launch."
        % decky.DECKY_PLUGIN_NAME,
        "# Only affects games launched from this plugin.",
        "",
    ]
    lines.extend('%s = "%s"' % (key, value) for key, value in settings)
    lines.append("")

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    # 0600 because this file can hold the RetroAchievements Connect token, which
    # is password-equivalent. Set unconditionally: a mode that depends on the
    # contents is one that will be wrong the first time the contents change.
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as error:
        decky.logger.warning("Could not restrict %s: %s", path, error)
    return path


def _slug(title):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return slug[:60] or "game"


def _flat(text):
    """A value safe to put on a `#` line of a generated script.

    The `exec` line is shlex-quoted, so the arguments are safe. The header
    comments are not: they are built with `%`, and a newline in one closes the
    comment and leaves whatever follows as a command in a script Steam runs.
    Neither value is ours -- a title is whatever was typed, and a ROM filename
    may contain a newline on Linux -- so both are flattened here rather than
    trusted. Same reasoning as `fileserver.safe_name`, one layer further in.
    """
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).strip()


#: How much of the hash goes in a launcher's name. Long enough that two ROMs
#: will not collide, short enough to leave the title readable.
DIGEST_LENGTH = 8


def launch_log_path(launcher):
    """Where this launcher's last run is kept.

    Named from the launcher rather than from the appid, because the launcher is
    what the script knows about itself -- the appid is read out of `/proc` by the
    gate and is empty whenever that read fails, which is not a thing to hang a
    filename on.
    """
    stem = os.path.splitext(os.path.basename(launcher))[0]
    return os.path.join(LAUNCH_LOG_DIR, "%s.log" % stem)


def previous_launch_log_path(launcher):
    """Where the run before the last one is kept.

    A `.prev.log` beside the log itself, which is what makes it free: the sweep
    and the report both work from the directory listing and a name ending in
    `.log`, so neither had to learn about this.
    """
    stem = os.path.splitext(os.path.basename(launcher))[0]
    return os.path.join(LAUNCH_LOG_DIR, "%s.prev.log" % stem)


def log_capture(launcher):
    """The shell that keeps what the emulator says, or "" if it cannot.

    **Redirects the shell's own descriptors and then execs into them**, rather
    than running the emulator as a child and reading its pipes. The process tree
    is unchanged -- Steam's reaper still sees what it saw before, and Stop still
    signals what it signalled -- which is the whole reason this is three lines of
    redirection instead of a wrapper.

    **Fails open, every branch.** A log that cannot be truncated, a directory
    that cannot be made, a full disk: each leaves the redirect undone and the
    game launches exactly as it did before. This runs in front of every game in
    the library, and a game that will not start is a far worse failure than a
    diagnostic that was not collected -- the same rule the launch gate above
    follows for the same reason.
    """
    log = launch_log_path(launcher)
    # Joined with a plain newline, never `os.linesep`: this is a shell script for
    # the Deck, and CRLF in it is `#!/bin/sh\r`, which fails to execute at all.
    return "\n".join([
        "# What the emulator says, for the panel to show when a game dies on",
        "# startup. Truncated here, so this is always the last run.",
        "_dke_log=%s" % shlex.quote(log),
        "mkdir -p %s 2>/dev/null" % shlex.quote(LAUNCH_LOG_DIR),
        # **The run before this one is kept, because the retry is what erases
        # it.** A game that fails and is launched again straight away is the
        # ordinary way a person meets a failure, and truncating on the way in
        # meant the working run wrote over the only account of the broken one.
        # Twice now that has left a failure with nothing to read.
        "_dke_prev=%s" % shlex.quote(previous_launch_log_path(launcher)),
        'if [ -s "$_dke_log" ]; then mv -f "$_dke_log" "$_dke_prev" 2>/dev/null;'
        " fi",
        'if : > "$_dke_log" 2>/dev/null; then exec >>"$_dke_log" 2>&1; fi',
        "",
    ])


#: Where `motion_server` splices the emulator's own command line.
#:
#: The block needs that command twice -- once to `exec` when there is no server
#: to wait for, once to run as a child when there is -- and building the block
#: around an argv passed in would mean two places that must not disagree about
#: what the game is.
COMMAND_PLACEHOLDER = "@@COMMAND@@"


def motion_server(binary):
    """The shell that runs a motion server for exactly as long as the game does.

    The Deck's gyro reaches an emulator one of two ways. Through SDL, which
    means handing over the physical pad and losing Steam Input for everything
    that emulator runs -- what `deck_gyro.motion_env` costs. Or over a local
    socket from a server reading the controller's HID frames directly, which
    Steam neither notices nor minds. This is the second, so the pad binding and
    the layout stay exactly as they were.

    **The server is a child of the launcher, not a daemon.** It reads the
    controller whenever it runs, so a permanent one would leave the Deck's
    sensor powered for every game in the library including the ones with no
    motion. Started here, it exists for one game and dies with it.

    **And it is not backgrounded behind an `exec`.** Measured on the Deck rather
    than assumed: Steam's `reaper` waits for every descendant, so a server still
    alive when the emulator exits keeps the reaper alive too -- the game stays
    "Running" in the library until somebody presses Stop, with nothing on screen
    to stop. So the emulator is run as a child of this script and the trap is
    what guarantees the server goes with it, whether the game exited on its own
    or Steam signalled it.

    **Failing to start it must not fail the game.** A missing or unrunnable
    server costs motion; refusing to launch costs the game. The same rule the
    launch gate and the log capture above follow, for the same reason.
    """
    return "\n".join([
        "# Motion, over a local socket rather than through SDL -- see",
        "# launchers.motion_server. Dies with the game, and never outlives it:",
        "# Steam's reaper waits for it, so a survivor hangs the library entry.",
        "_dke_motion=%s" % shlex.quote(binary),
        'if [ -x "$_dke_motion" ]; then',
        '  # One left by a launch that was killed outright. The trap below',
        '  # covers every ending a script can see; SIGKILL runs nothing, and a',
        '  # survivor holds the DSU port, so the next game gets no motion at',
        '  # all. Measured: TERM leaves nothing, KILL leaves it running.',
        '  pkill -f "^$_dke_motion" 2>/dev/null',
        '  "$_dke_motion" >/dev/null 2>&1 &',
        "  _dke_motion_pid=$!",
        "  trap 'kill \"$_dke_motion_pid\" 2>/dev/null' EXIT INT TERM",
        "else",
        "  # Nothing to clean up afterwards, so nothing to stay alive for: exec",
        "  # into the emulator and leave the process tree exactly as Steam",
        "  # expects it. Removing the server through the panel rewrites this",
        "  # script without any of this, so the case here is the other one -- a",
        "  # binary deleted from under a launcher that still names it.",
        "  exec %s" % COMMAND_PLACEHOLDER,
        "fi",
        "",
    ])


def stop_stray_helpers():
    """Kill helpers that outlived their game. Returns how many went.

    A launcher stops the processes it started on every ending a script can see,
    and on the one it cannot -- SIGKILL -- nothing runs at all. Both helpers
    then cost something: a hotkey helper types into whatever is open next, and a
    motion server holds the DSU port, so the next game has no gyro. Swept at
    startup as well as before each launch, because the launch that would have
    cleared it may never come.
    """
    killed = 0
    for name in (hotkeys.KEYBOARD_SERVER["name"],
                 emulator_catalog.deck_gyro.DSU_SERVER["name"]):
        binary = emu_install.installed_tool(name)
        if not binary:
            continue
        try:
            found = subprocess.run(["pkill", "-c", "-f", "^%s" % re.escape(binary)],
                                   capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as error:
            decky.logger.warning("Could not look for stray %s processes: %s", name, error)
            continue
        killed += int((found.stdout or "0").strip() or 0)
    if killed:
        decky.logger.info("Stopped %d helper(s) left over from a killed launch", killed)
    return killed


def read_launch_log(launcher, limit=8000, previous=False):
    """The tail of what this launcher's game last said, or "".

    The tail rather than the whole file: what explains a failure is the last
    thing said before it, and a verbose emulator's first eight thousand
    characters are its own startup banner.

    `previous` reads the run before that one. A flag rather than a stem ending
    in `.prev`, because that reads back as the current log: the path is built by
    replacing an extension, and `.prev` is an extension.
    """
    path = (previous_launch_log_path(launcher) if previous
            else launch_log_path(launcher))
    return _read_tail(path, limit)


def _read_tail(path, limit):
    """The last `limit` characters of a log file, or "", on a line boundary."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            if size > limit:
                handle.seek(size - limit)
            tail = handle.read()
    except OSError:
        return ""

    # The seek lands mid-line, which is noise at the top of a report -- so the
    # first partial line goes, *if there is a line to lose*. Dropping it
    # unconditionally with `readline()` returned nothing at all for a log with
    # no newline in its tail, which is not exotic: an emulator that redraws a
    # progress line with carriage returns writes exactly that, and so does one
    # that dies before finishing its first line.
    if size > limit and "\n" in tail:
        tail = tail.split("\n", 1)[1]
    return tail.strip()


def sweep_launch_logs():
    """Trim anything that grew past `LAUNCH_LOG_CAP`. Returns how many were cut.

    At startup rather than as they are written: capping the redirect itself needs
    a pipe, and a pipe whose reader goes away sends the emulator SIGPIPE.
    """
    cut = 0
    try:
        names = os.listdir(LAUNCH_LOG_DIR)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(LAUNCH_LOG_DIR, name)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) <= LAUNCH_LOG_CAP:
                continue
            # By path, not by name: a `.prev.log` stem read back as the
            # current log, so the sweep trimmed the wrong file and left the
            # oversized one exactly as it found it.
            tail = _read_tail(path, LAUNCH_LOG_CAP // 2)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(tail)
            cut += 1
        except OSError as error:
            decky.logger.warning("Could not trim %s: %s", path, error)
    if cut:
        decky.logger.info("Trimmed %d oversized launch log(s)", cut)
    return cut


def launcher_path(title, rom_path):
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    return os.path.join(
        LAUNCHER_DIR, "%s-%s.sh" % (_slug(title), _digest(rom_path))
    )


def _digest(rom_path):
    return hashlib.sha1(rom_path.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def rom_digest(launcher):
    """The ROM half of a launcher's name, or "" if it does not have one.

    A launcher is `<title>-<digest>.sh`, so the digest is what says which game
    it runs and the slug is only what it was called at the time. Anything that
    wants to know whether two launchers are the same game asks this rather than
    comparing filenames -- renaming a game changes the slug and nothing else.
    """
    stem = os.path.splitext(os.path.basename(launcher or ""))[0]
    tail = stem.rsplit("-", 1)[-1] if "-" in stem else ""
    # Only a hex run of the right length. A game called "Sonic 3" would
    # otherwise offer "3" as its digest and match every other game ending in a
    # short word.
    if len(tail) != DIGEST_LENGTH:
        return ""
    return tail.lower() if all(c in "0123456789abcdef" for c in tail.lower()) else ""


def split_extra_args(extra_args):
    """Parse a free-text argument string the way a shell would.

    Raises ValueError on unbalanced quotes, so a typo is reported when the game
    is saved rather than silently producing a launcher that will not start.
    """
    text = (extra_args or "").strip()
    return shlex.split(text) if text else []



# The gate that stops a second game starting, spliced into every launcher
# between the environment preamble and the exec.
#
# **This is the only place left that can stop it.** Steam warns before launching
# one game over another, but only for its own: the check is gated on
# `app_type & 1` and a non-Steam shortcut is `1073741824`, so it never fires for
# anything this plugin adds. Reaching that warning would mean replacing a
# function inside Steam's running code. Stopping the launch from outside does
# not work either, and both routes were tried on a real device --
# `CancelGameAction` terminates the game about a second after it starts, and
# `CancelLaunch` does not stop it at all, it only detaches Steam's tracking and
# leaves the emulator running with no Stop button. Measured, not assumed.
#
# By the time any of that happens this script is already running. The emulator
# is not: that is the next line. So the decision belongs here.
#
# **It fails open at every step.** No app id, no `pgrep`, an unwritable
# directory -- all of them fall through to launching normally. A game that will
# not start is a far worse failure than a warning that did not appear, and this
# runs in front of every game in the library.
# **Raw, and it has to be.** This is shell text: the backslash escapes in it
# are for `tr` and `sed` to read, not for Python. Written unraw once, and
# Python ate them before the shell ever saw them -- the NUL separator `tr`
# splits /proc/cmdline on became an actual NUL byte in this file, and sed's
# capture group became an invalid escape. The emitted script then found no app
# id, fell through, and launched: the right way to fail, but with the gate
# doing nothing whatsoever. The only complaint was a SyntaxWarning nobody was
# reading.
_LAUNCH_GATE = r"""# Two games at once. See launchers.py -- this is the last point that can decide
# not to start one, and it gets out of the way at the first sign of doubt.
_dke_gate='{gate}'
# Steam wraps every launch in `reaper SteamLaunch AppId=<id>`, and that reaper
# is this script's parent, so our own id is one read away and the other games
# are visible without asking Steam anything.
_dke_self=$(tr '\0' '\n' < /proc/$PPID/cmdline 2>/dev/null | sed -n 's/^AppId=//p' | head -1)
if [ -n "$_dke_self" ]; then
  # The panel asked and the answer was yes. One shot, and only a recent one:
  # taken now, so a later launch is judged on its own, and ignored past
  # {approved} seconds, because an approval whose launch never happened would
  # otherwise wave the *next* one through in silence.
  _dke_ok=$(find "$_dke_gate/approved-$_dke_self" -newermt '-{approved} seconds' 2>/dev/null)
  rm -f "$_dke_gate/approved-$_dke_self" 2>/dev/null
  if [ -z "$_dke_ok" ]; then
    _dke_others=$(pgrep -af 'SteamLaunch AppId=' 2>/dev/null \
      | sed -n 's/.*AppId=\([0-9][0-9]*\).*/\1/p' \
      | grep -v "^$_dke_self\$" | sort -u | tr '\n' ' ')
    if [ -n "$(printf %s "$_dke_others" | tr -d ' ')" ]; then
      mkdir -p "$_dke_gate" 2>/dev/null
      printf '%s' "$_dke_others" > "$_dke_gate/bounced-$_dke_self" 2>/dev/null
      # Nothing started. The panel takes it from here.
      exit 0
    fi
  fi
fi
"""


#: The most a launch will wait to be woken, in seconds.
#:
#: **A watchdog, not a schedule.** Nothing normally waits any of this: the
#: plugin resumes the launch the moment it is done, and a stopped process costs
#: nothing while it waits.
#:
#: Generous, because the thing it used to cut short was a person reading a
#: dialog. Waiting is not the failure -- a game that never starts is -- and the
#: case where nobody is coming is now answered by `cloud-on` going stale rather
#: than by this number being small.
CLOUD_MAX_SECONDS = 600

#: How often the plugin says it is alive by touching `cloud-on`, and how old
#: that file may be before a launch stops believing it.
#:
#: **This is what tells "nobody has answered yet" from "nobody is there".** The
#: two used to be one number and it had to be short, because a Deck with decky
#: reloading must still start its games -- so a dialog somebody was reading got
#: thirty seconds and then the game ran anyway. A file with a recent timestamp
#: on it answers the second question on its own, and leaves the first one to the
#: person.
CLOUD_ALIVE_SECONDS = 30
CLOUD_STALE_SECONDS = 120

#: Written while cloud saves have somewhere to go, and removed when they do not.
#:
#: The launcher's way of knowing whether waiting for anything is worth it,
#: without asking the plugin -- which is the whole point: a launch must not
#: depend on decky being up, and reading a file cannot.
CLOUD_ON_FILE = "cloud-on"

#: The shell that waits for the panel to bring saves down before the game starts.
#:
#: **Why the waiting is here and the asking is not.** Checking a remote takes a
#: network round trip, and doing that in the launcher would put it on the front
#: of every launch of every game, whether or not there is anything to fetch --
#: with Steam's runtime stripped, no rclone on the path, and nothing to show
#: somebody while it happened. So the panel does the asking, in decky's process,
#: where it can also put a dialog on screen; this waits for the answer.
#:
#: **And it only waits when it has been told to.** `cloudwait` is written by the
#: panel the moment it takes an interest in a launch. No file, no wait: a Deck
#: with cloud saves off, a plugin that is not loaded, or a game the panel does
#: not recognise all reach the emulator with nothing added to the launch at all.
_CLOUD_GATE = r"""# Saves coming down before the game opens them. See launchers.py.
# **This script stops itself and waits to be woken.** Three versions negotiated
# with the plugin over files -- announce, heartbeat, poll, give up after a
# ceiling -- and each one had a timing bug of its own: two lost a race with
# Steam, one gave up 0.2s before the answer arrived, and one left a stop note
# that refused the *next* launch. None of that exists here. A stopped process
# waits exactly as long as it is left stopped, at no cost, and the plugin says
# when by resuming it. Both decky cloud-save plugins reach the same conclusion
# from the other end, suspending the game once it has started; stopping before
# the emulator runs is the same idea without the window where it could already
# have read a save.
# `-newermt` rather than a plain `-f`: the file says cloud saves are on, and
# its timestamp says the plugin is still there to answer. Without the second
# half, a Deck with decky reloading would stop every launch and wait out the
# whole watchdog.
if [ -n "$_dke_self" ] && [ -n "$(find "$_dke_gate/{onfile}" \
      -newermt '-{stale} seconds' 2>/dev/null)" ]; then
  mkdir -p "$_dke_gate" 2>/dev/null
  _dke_me=$$
  # What this wait did, overwritten each launch. The gate runs before the launch
  # log is opened, so without this a launch that went wrong leaves nothing to
  # read -- which cost three rounds of guessing.
  _dke_trace="$_dke_gate/lastwait.log"
  echo "$(date +%H:%M:%S.%N) waiting as $_dke_me" > "$_dke_trace" 2>/dev/null
  # The pid is the whole protocol: whoever finds this file can wake this launch
  # or end it, and needs nothing else from it.
  printf '%s
%s' "$_dke_me" "$0" > "$_dke_gate/launching-$_dke_self" 2>/dev/null
  # Nobody there -- decky reloading, the plugin gone -- and the game still
  # starts, this late rather than never.
  #
  # **`setsid`, and its output thrown away, both for the same reason.** Steam's
  # reaper waits for every descendant, and anything holding this script's
  # stdout keeps whoever reads it waiting too: an ordinary `( sleep ) &` left a
  # `sleep` behind that outlived the game and held the library tile on
  # "Running". A new session is not a descendant, and a watchdog writing to
  # /dev/null holds nothing. Measured: the launch returns in 1.0s against 45s
  # of watchdog still to run.
  setsid sh -c "sleep {cap}; kill -CONT $_dke_me 2>/dev/null" >/dev/null 2>&1 &
  _dke_net=$!
  kill -STOP "$_dke_me"
  # Best effort, and nothing depends on it: the watchdog is in its own session
  # and ends by itself, so the worst this misses is one sleeping process that
  # nothing is waiting for.
  kill -- -"$_dke_net" 2>/dev/null || kill "$_dke_net" 2>/dev/null
  rm -f "$_dke_gate/launching-$_dke_self"
  # Told not to start. **Read only after being woken, which is why there is no
  # race left**: this process was stopped while whoever wrote it was writing,
  # so it cannot have looked too early. An earlier version raced for exactly
  # that reason and refused the *next* launch instead of this one.
  #
  # And it is an `exit 0`, not a kill from outside. Steam is waiting on this
  # process: a clean exit is the same thing the two-games gate does and returns
  # to the library, where a SIGKILL left the loading screen up and the launch
  # unfinished.
  if [ -f "$_dke_gate/cloudstop-$_dke_self" ]; then
    rm -f "$_dke_gate/cloudstop-$_dke_self"
    echo "$(date +%H:%M:%S.%N) told not to start" >> "$_dke_trace" 2>/dev/null
    exit 0
  fi
  echo "$(date +%H:%M:%S.%N) resumed" >> "$_dke_trace" 2>/dev/null
fi
"""


#: Written by the launcher at the last moment before the emulator runs.
#:
#: **Because "a game closed" is not "a game was played".** Steam counts an app
#: as running from the moment it starts the script, so a launch the two-games
#: gate refused, one declined at the save conflict, and one the preflight
#: stopped all end exactly like a session -- and every one of them was
#: uploading afterwards. In the conflict case that upload overwrote the other
#: device's saves and rewrote the record, which is the thing the person had
#: just declined; after two or three goes there was nothing left to decline.
#:
#: Only the script can answer this, because only the script knows whether it
#: reached the emulator. It is the line before it does.
RAN_MARKER = r"""# Past every gate: what happens after this is the game itself.
[ -n "$_dke_self" ] && printf 1 > '{gate}/ran-'"$_dke_self" 2>/dev/null
"""


def ran_marker():
    """The line that records that a launch got as far as the emulator."""
    return RAN_MARKER.replace("{gate}", LAUNCH_GATE_DIR)


def took_off(app_id):
    """Whether that launch reached the emulator, consuming the answer.

    Consumed like a bounce note and for the same reason: read once, so a
    session that has been accounted for cannot be counted again by the next
    thing that asks.
    """
    try:
        os.remove(_gate_file("ran", app_id))
        return True
    except OSError:
        return False


def launch_gate():
    """The gate, with this install's paths in it.

    Two gates, in the order they have to run. The two-games check can end the
    launch outright, so it goes first: waiting for saves to come down and then
    refusing to start is a wait nobody got anything for.
    """
    # Both waits count in steps rather than seconds, so the numbers written
    # into the script are the seconds divided by the step.
    return (_LAUNCH_GATE.replace("{gate}", LAUNCH_GATE_DIR)
            .replace("{approved}", str(APPROVAL_SECONDS))
            + _CLOUD_GATE
            .replace("{onfile}", CLOUD_ON_FILE)
            .replace("{stale}", str(CLOUD_STALE_SECONDS))
            .replace("{cap}", str(CLOUD_MAX_SECONDS)))


def _gate_file(kind, app_id):
    return os.path.join(LAUNCH_GATE_DIR, "%s-%d" % (kind, int(app_id)))


#: What a game needs, checked before its emulator is started.
#:
#: **Because the alternative is the worst failure this plugin can produce.**
#: Uninstall an emulator from Discover, or launch with the SD card holding the
#: ROMs unmounted, and the shortcut still starts: the script runs, the emulator
#: is not there, and the user is back at the library a second later with nothing
#: on screen. The error lands in the launch log, which is exactly the file
#: nobody reads. This is the same trade the launch gate above makes -- refuse,
#: leave a note, let the panel say why -- and for the same reason: a game that
#: cannot start loses nothing by not starting.
#:
#: **Refusing is only right because the launch was going to fail anyway.** The
#: rule that a launch notice must never block a launch (see `emulators.
#: launch_notices`) is about warnings on a game that would otherwise run.
#:
#: **Stats, never subprocesses.** This runs in front of every game in the
#: library, so `flatpak info` -- the honest question -- is the wrong way to ask
#: it; a deployed flatpak is a directory, and a directory is a stat. The probes
#: are built at write time by `_presence_test` so the paths match what the
#: backend itself reads.
#:
#: **Fails open at every step**, like the gate and the log capture. No app id
#: means no note can be left, and a refusal nobody can explain is worse than a
#: launch that fails loudly.
_LAUNCH_PREFLIGHT = r"""# What this game needs. See launchers.py -- a game whose emulator was
# uninstalled, or whose ROM is on a card that did not mount, otherwise starts
# and dies with nothing on screen to say why.
_dke_missing=''
{tests}
if [ -n "$_dke_missing" ] && [ -n "$_dke_self" ]; then
  mkdir -p "$_dke_gate" 2>/dev/null
  printf '%s\n%s' "$_dke_missing" {label} > "$_dke_gate/missing-$_dke_self" 2>/dev/null
  # Nothing started. The panel takes it from here.
  exit 0
fi
"""


def _presence_test(emulator, install, core_path):
    """The shell test for "the thing that runs this game is here", or "".

    A flatpak is a deployed directory under one of two roots; an executable is a
    file with the execute bit. For a libretro game the thing that goes missing is
    the **core**, not RetroArch -- `install["exe"]` is often `/usr/bin/flatpak`,
    which says nothing about whether RetroArch is installed, while a core is a
    file this plugin downloaded and can check directly.
    """
    if emulator:
        kind, target = emulator.get("kind"), (emulator.get("target") or "").strip()
        if kind == "flatpak" and target:
            return " || ".join(
                '[ -d %s ]' % shlex.quote(
                    os.path.join(root, "app", target, "current", "active"))
                for root in sysenv.flatpak_roots()
            )
        if kind == "path" and target:
            return "[ -x %s ]" % shlex.quote(target)
        return ""
    return "[ -f %s ]" % shlex.quote(core_path) if core_path else ""


def _presence_label(emulator, core_path):
    """What to call the thing that is missing, for the dialog to name.

    **Baked in when the launcher is written rather than looked up when the
    dialog opens.** The name is known now and may not be later: removing an
    emulator can take its record with it, and a message that says "the
    emulator" because it could no longer find out which one is the vaguer half
    of the problem this feature exists to fix.

    A libretro core is named without its filename furniture -- `snes9x` rather
    than `snes9x_libretro.so` -- because the file name is not what anybody
    calls it.
    """
    if emulator:
        # **The catalog first, the installed record second.** A record's `name`
        # is whatever it was registered under, and an emulator adopted with the
        # link button carries its flatpak id there -- so this said
        # "io.github.ryubing.Ryujinx is not installed any more", which is the
        # package and not the thing anybody calls it. The catalog knows it as
        # Ryujinx. The record is still the fallback, because a hand-registered
        # emulator has no catalog entry and its own name is the right one.
        entry = emulator_catalog.find(emulator.get("id") or "")
        return ((entry or {}).get("name") or emulator.get("name") or "").strip()
    if not core_path:
        return ""

    stem = os.path.basename(core_path)

    # **Only a `.so` is a core.** `core_path` carries the emulator's own target
    # for an emulator game -- `io.github.ryubing.Ryujinx` -- and a game whose
    # emulator has no record in `emulators.json` arrives here with `emulator`
    # empty and that id in hand. Treating it as a core produced "The
    # io.github.ryubing.Ryujinx core is not installed", which is the package
    # name twice over and the exact thing this was asked to stop saying.
    if stem.endswith(".so"):
        for suffix in ("_libretro.so", ".so"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        # Said as a core, because that is what it is. RetroArch is the emulator
        # and it is still installed; "snes9x is not installed" names something
        # the user has never seen a row for.
        return "The %s core" % stem if stem else ""

    # Not a core, so it is an emulator's target. The catalog is the only place
    # that maps one to a name a person would recognise.
    for entry in emulator_catalog.CATALOG:
        if core_path == ((entry.get("source") or {}).get("id") or None):
            return (entry.get("name") or "").strip()

    # Something registered by hand with no record left to name it. The dialog's
    # own fallback is "The emulator it needs", which is vague but true -- and
    # better than repeating a path back at somebody.
    return ""


#: Written by the launcher, not when the game is added.
#:
#: A program that takes its game from its own config has one config, and every
#: game on it writes the same key. Written at add time, the second game added
#: silently repointed the first game's shortcut: both launchers start the same
#: program, and the program reads whatever that key last said. So the key is set
#: on the way in, by the launcher that knows which game it is for.
#:
#: Failure is not fatal here. The program starts either way, and what it does
#: with a config it could not have is its own business to report -- refusing the
#: launch would turn a game that might still work into one that cannot.
_GAME_CONFIG = """python3 -c 'import json, os, sys
path, keys = sys.argv[1], json.loads(sys.argv[2])
try:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    data = {}
if not isinstance(data, dict):
    data = {}
data.update(keys)
directory = os.path.dirname(path)
if directory:
    os.makedirs(directory, exist_ok=True)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=4)
' {path} {keys} || echo "deckyemu: could not write {path}" >&2"""


def game_config_setup(emulator, rom_path):
    """The shell that puts this game where the program will read it, or "".

    Empty for everything that takes its game on the command line, which is every
    emulator and most ports.
    """
    if not emulator or not rom_path:
        return ""
    entry = emulator_catalog.find(emulator.get("id") or "") or {}
    path, keys = emu_config.game_config_values(entry, rom_path)
    if not path or not keys:
        return ""
    return (_GAME_CONFIG
            .replace("{keys}", shlex.quote(json.dumps(keys, sort_keys=True)))
            .replace("{path}", shlex.quote(path)))


#: Put the game where a program that reads its own directory will find it.
#:
#: Links rather than copies, because the game is already filed under `roms/` and
#: a second copy of a 32MB cartridge -- or a 1.4GB disc -- is a second thing to
#: keep in step. The link is remade every launch, so a game whose file moved is
#: corrected by starting it.
#:
#: Every link in that directory goes first. The program looks for *a* game
#: rather than a named one, so a link left by the last game played would still
#: be sitting there beside this one. Only links: the build, its config and
#: anything it generated are real files and are not touched.
_GAME_BESIDE = """find {dir} -maxdepth 1 -type l -delete 2>/dev/null
ln -sfn {rom} {dir}/{name} || echo "deckyemu: could not put the game beside the program" >&2
cd {dir} || exit 1"""


def game_beside_setup(emulator, rom_path):
    """The shell that runs a program in its own folder with the game in it, or "".

    For a program that looks for its game in the directory it runs in rather
    than taking a path -- see `game_beside` in the schema.
    """
    if not emulator or not rom_path:
        return ""
    entry = emulator_catalog.find(emulator.get("id") or "") or {}
    beside = entry.get("game_beside")
    if not beside:
        return ""
    directory = os.path.dirname(emulator.get("target") or "")
    if not directory:
        return ""
    # A program that reads one name and no other -- sm64coopdx wants
    # `baserom.us.z64` -- gets the link under that name. Otherwise the game
    # keeps the name it arrived with, which is what the rest expect.
    wanted = (beside.get("as") if isinstance(beside, dict) else "") or         os.path.basename(rom_path)
    return (_GAME_BESIDE
            .replace("{dir}", shlex.quote(directory))
            .replace("{name}", shlex.quote(wanted))
            .replace("{rom}", shlex.quote(rom_path)))


def first_run_argv(entry, rom_path):
    """The shell that hands a port its game once, to set itself up, or "".

    A port that builds its own archive from the game asks for it on the command
    line: Ship of Harkinian extracts and skips its own "no archive, build one?"
    question entirely. But asked again on a later launch it has something to
    say -- "that archive exists, extract again?" -- so the argument is passed
    only while the file it creates is missing.

    `set --` rather than a variable, because a game's path has spaces in it and
    an unquoted expansion would arrive as several arguments.
    """
    spec = (entry or {}).get("first_run") or {}
    args, unless = spec.get("args") or "", spec.get("unless") or []
    if not args or not unless or not rom_path:
        return ""
    tests = " && ".join("[ ! -f %s ]" % shlex.quote(name) for name in unless)
    filled = " ".join(
        shlex.quote(part.replace("{rom}", rom_path))
        for part in shlex.split(args)
    )
    return "\n".join([
        "# The run that sets this port up: it builds what it plays from the",
        "# game, and wants the game on the command line to do it. Only while",
        "# what it builds is missing -- see launchers.first_run_argv.",
        "set --",
        "if %s; then set -- %s; fi" % (tests, filled),
    ])


#: The program a port opens its file picker with. Only zenity is answered: it
#: is what a Deck has, and what the ports that ask this way use.
_PICKER_TOOL = "zenity"


def picker_shim(entry, rom_path):
    """The shell that answers a port's file picker with the game, or "".

    Some ports take no path and no argument: they ask, through a picker, which
    is a separate program found on PATH. On a Deck that picker opens in
    "Recently Used" whatever directory it was given, so the person is left
    hunting for a file the plugin already knows.

    So a zenity of our own goes first on PATH for this launch: a file selection
    is answered with the game, and every other dialog -- the questions the port
    asks, which are readable and worth reading -- is handed to the real one.
    """
    if not (entry or {}).get("game_picker") or not rom_path:
        return ""
    real = shutil.which(_PICKER_TOOL) or ""
    if not real:
        return ""
    directory = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "pickers", entry["id"])
    shim = os.path.join(directory, _PICKER_TOOL)
    body = "\n".join([
        "#!/bin/sh",
        "# Generated by %s -- answers this port's file picker with the game "
        "the shortcut was made for." % decky.DECKY_PLUGIN_NAME,
        "case \"$*\" in",
        "  *--file-selection*)",
        "    [ -n \"$DECKYEMU_GAME\" ] && { printf '%s\\n' \"$DECKYEMU_GAME\"; exit 0; }",
        "    ;;",
        "esac",
        "exec %s \"$@\"" % shlex.quote(real),
        "",
    ])
    try:
        os.makedirs(directory, exist_ok=True)
        with open(shim, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        os.chmod(shim, 0o755)
    except OSError as error:
        decky.logger.warning("Could not write the picker shim for %s: %s",
                             entry["id"], error)
        return ""
    return "\n".join([
        "# This port asks for its game through a picker, which opens in",
        "# \"Recently Used\" wherever it is pointed. See launchers.picker_shim.",
        "DECKYEMU_GAME=%s" % shlex.quote(rom_path),
        "PATH=%s:$PATH" % shlex.quote(directory),
        "export DECKYEMU_GAME PATH",
    ])


def preflight(rom_path, emulator, install, core_path, title_id=""):
    """The shell that refuses a launch whose pieces are missing, or "".

    `title_id` means the emulator is handed an installed title rather than a
    file -- Vita3K -- so there is no ROM path to test and testing one would
    refuse every launch of a game that works.
    """
    tests = []
    if rom_path and not title_id:
        tests.append(
            "[ -e %s ] || _dke_missing='rom'" % shlex.quote(rom_path))

    presence = _presence_test(emulator, install, core_path)
    if presence:
        # Only when the ROM is there, so a game missing both is reported as one
        # thing to fix rather than whichever was tested last.
        tests.append('if [ -z "$_dke_missing" ]; then\n'
                     "  %s || _dke_missing='emulator'\nfi" % presence)

    if not tests:
        return ""
    return (_LAUNCH_PREFLIGHT
            .replace("{tests}", "\n".join(tests))
            .replace("{label}", shlex.quote(_presence_label(emulator, core_path))))


def take_missing(app_id):
    """Which piece this game's launcher could not find: (kind, name).

    `kind` is "rom", "emulator" or "", and `name` is what to call the emulator
    that has gone -- written by the launcher, which knew it at the moment it was
    generated. ("", "") when nothing was stopped.

    Consumed like a bounce, and for the same reasons: read once so two askers
    cannot both be told, and expiring rather than accumulating.
    """
    path = _gate_file("missing", app_id)
    try:
        fresh = (time.time() - os.stat(path).st_mtime) <= BOUNCE_SECONDS
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except (OSError, ValueError):
        return "", ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    kind = lines[0].strip() if lines else ""
    if not fresh or kind not in ("rom", "emulator"):
        return "", ""
    # Capped rather than trusted for length: it goes straight into a sentence on
    # screen. The file is written by a script this plugin generated, so a wrong
    # one is a bug here rather than hostile input -- and a cap keeps that bug
    # from becoming a wall of text over the library.
    return kind, (lines[1].strip()[:80] if len(lines) > 1 else "")


#: How old a bounce note may be and still be answered.
#:
#: The panel asks for it a moment after the launch it belongs to, so anything
#: older is from a launch nobody is waiting on any more -- a bounce while the
#: plugin was reloading, or one written and never collected. Answering a stale
#: one would put a dialog about a game on screen minutes after the user gave up
#: on it.
BOUNCE_SECONDS = 30

#: How old an approval may be and still let a launch past the two-games gate.
#:
#: The panel writes it and launches in the same breath, so this only has to
#: cover Steam getting the script running. A launch that failed in between
#: leaves the file behind, and without a limit that stale yes answers a question
#: nobody asked -- the next launch over a running game, started silently.
APPROVAL_SECONDS = 30


def take_bounce(app_id):
    """What was running when this game's launcher refused, or "" if it did not.

    Consumed: read once and deleted, so the same bounce cannot be reported to
    two askers, and a note nobody collects expires instead of accumulating.
    """
    path = _gate_file("bounced", app_id)
    try:
        fresh = (time.time() - os.stat(path).st_mtime) <= BOUNCE_SECONDS
        with open(path, encoding="utf-8") as handle:
            others = handle.read().strip()
    except (OSError, ValueError):
        return ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return others if fresh else ""


def set_cloud_wanted(on):
    """Say whether a launch should wait for the panel at all.

    A file rather than a setting the launcher reads, because the launcher runs
    with Steam's environment stripped and nothing of ours on its path. Present
    means "there is somewhere for saves to go, so a panel will claim this
    launch"; absent means every launch goes straight through, which is what a
    Deck with cloud saves off must cost.
    """
    path = os.path.join(LAUNCH_GATE_DIR, CLOUD_ON_FILE)
    try:
        if on:
            os.makedirs(LAUNCH_GATE_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("1")
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
    except OSError as error:
        # Not fatal either way: with the file missing nothing waits, and with it
        # stale a launch costs the grace and then goes.
        decky.logger.warning("Could not record cloud saves as %s: %s",
                             "on" if on else "off", error)


def launches_waiting():
    """The app ids of launchers currently held, waiting for their saves.

    Written by the launcher itself as its first act, which is what makes this
    reliable: nothing has to hear about a launch from Steam in time to claim
    it. The backend watches this directory instead -- see
    `plugin_transfers._watch_launches`.
    """
    found = []
    try:
        names = os.listdir(LAUNCH_GATE_DIR)
    except OSError:
        return found
    for name in names:
        if not name.startswith("launching-"):
            continue
        rest = name[len("launching-"):]
        if rest.isdigit():
            found.append(int(rest))
    return found


#: The one signal a stopped launch understands, by number.
#:
#: Not `signal.SIGCONT`, because `signal` is not on the
#: list of stdlib modules proven to exist in decky's trimmed Python -- and one
#: that is not there is not a degraded feature, it is the backend failing to
#: import. The numbers are fixed by Linux on every architecture this runs on,
#: and `os.kill` takes an int.
_SIGCONT = 18


def say_alive():
    """Touch `cloud-on`, which is how a launch knows anyone is listening.

    Called on a timer while the plugin runs. A launch reads the timestamp, not
    just the name: the file existing says cloud saves are on, and it being
    recent says there is something there to answer -- which is what lets a
    dialog wait for a person rather than for a clock. See
    `CLOUD_STALE_SECONDS`.
    """
    path = os.path.join(LAUNCH_GATE_DIR, CLOUD_ON_FILE)
    try:
        if os.path.exists(path):
            os.utime(path, None)
    except OSError:
        pass


def _waiting(app_id):
    """The stopped launch for `app_id` as (pid, script), or (0, "").

    Read back rather than remembered, because the thing that wrote it is a
    shell script and the thing that reads it may have been restarted since.
    """
    try:
        with open(_gate_file("launching", app_id), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return 0, ""
    if not lines or not lines[0].strip().isdigit():
        return 0, ""
    return int(lines[0].strip()), (lines[1].strip() if len(lines) > 1 else "")


def _is_ours(pid, script):
    """Whether `pid` is still the launcher that wrote the file it came from.

    **The one check that matters here.** A pid comes out of a file, and the two
    things done with it are resuming and killing -- one of which is harmless
    and one of which is not. A file left behind by a launch whose process has
    since gone names a number the system is free to give to something else, and
    this plugin has no business signalling that.

    Checked against the script the file names rather than against the launcher
    directory: same guarantee, and it does not quietly stop being true for a
    launcher run from anywhere else -- which is how the suite runs it.
    """
    if not pid or not script:
        return False
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as handle:
            argv = handle.read().decode("utf-8", "replace")
    except OSError:
        return False
    return script in argv


def wake_launch(app_id):
    """Let a stopped launch carry on. Safe to call when nothing is stopped."""
    pid, script = _waiting(app_id)
    if not _is_ours(pid, script):
        return
    try:
        os.kill(pid, _SIGCONT)
    except OSError as error:
        # The watchdog in the script resumes it anyway; this only makes it
        # prompt.
        decky.logger.warning("Could not wake launch %s: %s", app_id, error)


def forget_launch(app_id):
    """Remove the file a stopped launch left, whatever became of the process.

    A launch that is woken clears its own file on the way past. A launch that
    is *killed* never gets there, and a file nothing clears is a launch the
    backend answers again on its next look -- which is the same conflict dialog,
    over and over, for a game that is not going to start.
    """
    try:
        os.remove(_gate_file("launching", app_id))
    except OSError:
        pass


def which_launch(app_id):
    """The pid currently waiting for `app_id`, or 0.

    Public so a wait can tell *its own* launch from a later one: there is one
    file per game, so relaunching replaces it, and a question still standing
    over the previous launch has nobody to answer it.
    """
    pid, script = _waiting(app_id)
    return pid if _is_ours(pid, script) else 0


def gone(app_id):
    """Whether the launch that wrote this file is no longer there.

    A file whose process has died -- killed, crashed, or the Deck suspended
    through it -- is not a launch waiting for anything, and answering it is
    work done at nobody.
    """
    pid, script = _waiting(app_id)
    return not _is_ours(pid, script)


def refuse_launch(app_id):
    """End a stopped launch without starting the game.

    For the one answer a save conflict has that neither copy settles. The
    process is stopped and has not reached the emulator, so ending it here
    costs nothing and starting cannot be undone.

    **Asked to exit, not killed.** Steam is waiting on that process, and a
    SIGKILL leaves it waiting -- the loading screen stays up and the launch
    never finishes. A note plus a wake-up gets a clean `exit 0`, which is what
    the two-games gate has always done and what Steam handles.

    The note cannot be read too early, which is the whole reason this shape
    works now: the process is stopped while it is being written.
    """
    pid, script = _waiting(app_id)
    if not _is_ours(pid, script):
        forget_launch(app_id)
        return False
    try:
        os.makedirs(LAUNCH_GATE_DIR, exist_ok=True)
        with open(_gate_file("cloudstop", app_id), "w", encoding="utf-8") as handle:
            handle.write("1")
        os.kill(pid, _SIGCONT)
        return True
    except OSError as error:
        decky.logger.warning("Could not refuse launch %s: %s", app_id, error)
        forget_launch(app_id)
        return False


def approve_launch(app_id):
    """Let this game past the gate once."""
    try:
        os.makedirs(LAUNCH_GATE_DIR, exist_ok=True)
        with open(_gate_file("approved", app_id), "w", encoding="utf-8") as handle:
            handle.write("1")
        return True
    except OSError as error:
        decky.logger.warning("Could not approve launch for %s: %s", app_id, error)
        return False


def write_launcher(
    install,
    title,
    core_path,
    rom_path,
    hide_osd="startup",
    emulator=None,
    fullscreen=True,
    extra_args="",
    menu_combo="off",
    cheevos_settings=None,
    title_id="",
):
    """Write (or overwrite) the launcher for this game and return its path.

    `emulator` selects a standalone emulator instead of RetroArch; the OSD
    overrides and the menu shortcut are RetroArch-specific and do not apply to
    it. There is no equivalent to reach for: a standalone emulator's own menu
    binding is that emulator's business, and nothing here can set it.

    `extra_args` is appended to the command line. Appended rather than inserted
    because there is no position that suits every emulator: several templates end
    in the ROM path (`-- {rom}`), where anything spliced in front of it would be
    read as content instead of as a flag.
    """
    if emulator:
        # `title_id` only matters to an emulator that starts installed titles
        # rather than files -- Vita3K -- and is ignored by every other.
        argv = emulators.launch_argv(emulator, rom_path, fullscreen, title_id)
        core_path = emulator.get("target", "")
    else:
        override = write_override_config(
            hide_osd, menu_combo, cheevos_settings,
            config_dir=(install or {}).get("config_dir", ""),
        )
        argv = ra_detect.launch_argv(install, core_path, rom_path, appendconfig=override)

    extra = split_extra_args(extra_args)
    argv = list(argv) + extra

    path = launcher_path(title, rom_path)
    command = " ".join(shlex.quote(arg) for arg in argv)

    # Only an emulator that reads motion off a socket, and only once its server
    # has been fetched. Every other launcher is written exactly as it was --
    # the wrapper below costs the `exec` (see `motion_server`), and nothing that
    # does not need it should pay that.
    entry = emulator_catalog.find((emulator or {}).get("id") or "") if emulator else {}
    server = emu_install.motion_server(entry) if emulator else ""

    # A port whose menu opens with a key, and the helper that puts that key on
    # the pad. Same shape as the motion server and for the same reasons: a child
    # of this script, not a daemon, and never left behind.
    keys = hotkey_helper(entry, path=launcher_path(title, rom_path))

    # Passed to the program when the block above decided to, and empty
    # otherwise, so an ordinary launch is the command line it always was.
    first_run = first_run_argv(entry, rom_path)
    if first_run:
        command = '%s "$@"' % command

    run = (
        [
            motion_server(server).replace(COMMAND_PLACEHOLDER, command),
            command,
            "_dke_status=$?",
            'exit "$_dke_status"',
        ]
        if server else ["exec %s" % command]
    )
    if keys:
        # Before the command and never behind an `exec`, so the trap that stops
        # it can run. A launcher that already wraps for motion is wrapped once:
        # the helper joins the same block.
        run = [keys] + (run if server else [command, "_dke_status=$?",
                                            'exit "$_dke_status"'])

    body = "\n".join(
        [
            "#!/bin/sh",
            "# Generated by %s -- edits will be overwritten." % decky.DECKY_PLUGIN_NAME,
            "# Game: %s" % _flat(title),
            "# ROM:  %s" % _flat(rom_path),
            "# Core: %s" % _flat(core_path),
        ]
        + (["# Args: %s" % _flat(" ".join(extra))] if extra else [])
        + [
            "",
            sysenv.SHELL_PREAMBLE,
            "",
            launch_gate(),
            preflight(rom_path, emulator, install, core_path, title_id),
            log_capture(path),
            ran_marker(),
            game_config_setup(emulator, rom_path),
            game_beside_setup(emulator, rom_path),
            picker_shim(entry, rom_path),
            first_run,
        ]
        + run
        + [""]
    )

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
    os.chmod(
        path,
        stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
    )

    decky.logger.info("Wrote launcher %s", path)
    return path


#: The name of the one Steam shortcut that opens an emulator's own window.
#:
#: Here because this module writes the launcher it points at. One shortcut
#: rather than one per emulator: gamescope composites nothing Steam did not
#: launch, so a shortcut is the only way to reach an emulator's UI -- but it is
#: a door used once to install firmware and never again, and N permanent library
#: entries is a poor trade for that. It is repointed at whichever emulator is
#: being opened, and hidden from the library, so this name only has to be
#: findable in the rare case where hiding did not take.
SETUP_SHORTCUT_TITLE = "DeckyEmu setup"


def gui_launcher_path(emulator, title=""):
    """Where the launcher that opens `emulator`'s own interface lives.

    Its own function because two very different things need to agree on it: the
    writer below, and the library check, which has to recognise this script as
    something in use rather than a leftover. It did not, so the one launcher the
    plugin writes for itself was reported as a stray -- and deleting it, which
    is what that finding offers, breaks the setup shortcut that runs it.

    Derived rather than pattern-matched for the same reason. `open-<id>.sh` looks
    like a rule a check could apply on its own, but a game called "Open Season"
    produces `open-season-<digest>.sh` and an imported emulator may call itself
    anything at all. Asking for the path of an emulator that actually exists has
    neither problem, and a script left behind by an emulator since removed is
    still correctly a stray.
    """
    return os.path.join(
        LAUNCHER_DIR, "open-%s.sh" % _slug((emulator or {}).get("id") or title)
    )


#: What runs the hotkey helper beside a port, and stops it with the game.
#:
#: The trap is the whole of it: Steam's reaper waits for every descendant, so a
#: helper still alive when the game exits keeps the library entry on "Running"
#: with nothing on screen to stop. The same rule `motion_server` follows.
#:
#: A missing helper costs the menu gesture, never the game.
_HOTKEYS = """# The port's own menu, on the pad: hold Select, press Start.
# See emulator_catalog/hotkeys.py. Dies with the game, never outlives it.
_dke_keys={binary}
if [ -x "$_dke_keys" ]; then
  # A helper from a launch that was killed outright. The trap below covers
  # every ordinary ending, but SIGKILL runs nothing, and what survives reads
  # the pad and types into whatever opens next. Measured: TERM leaves nothing,
  # KILL leaves it running.
  pkill -f "^$_dke_keys " 2>/dev/null
  LD_LIBRARY_PATH="$(dirname "$_dke_keys")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"     "$_dke_keys" {program} -H {hotkey} -c {config} >/dev/null 2>&1 &
  _dke_keys_pid=$!
  trap 'kill "$_dke_keys_pid" 2>/dev/null' EXIT INT TERM
fi"""


def hotkey_helper(entry, path=""):
    """The shell that puts a port's menu key on the pad, or "".

    Empty for everything that declares no keys, and for a port whose helper has
    not been fetched yet -- which is a launcher exactly as it was, so what is
    missing is the gesture rather than the game.
    """
    bindings = hotkeys.bindings_for(entry)
    if not bindings:
        return ""
    binary = emu_install.installed_tool(hotkeys.KEYBOARD_SERVER["name"])
    if not binary:
        return ""
    config = write_hotkey_config(entry["id"], bindings, hotkeys.modifier_for(entry))
    if not config:
        return ""
    return (_HOTKEYS
            .replace("{binary}", shlex.quote(binary))
            .replace("{config}", shlex.quote(config))
            .replace("{hotkey}", shlex.quote(hotkeys.HOTKEY_BUTTON))
            # What the helper watches to know the game is gone. It is told the
            # launcher rather than the program: the program is an AppImage whose
            # real process is named something else entirely once it mounts.
            .replace("{program}", shlex.quote(os.path.basename(path or "game"))))


def write_hotkey_config(entry_id, bindings, modifier=hotkeys.MODIFIER):
    """Write this port's hotkey config and return its path, or "".

    In the runtime directory rather than beside the program: it is derived from
    the entry, rewritten whenever a launcher is, and nothing of the user's is in
    it.
    """
    directory = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "hotkeys")
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "%s.ini" % entry_id)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(hotkeys.config_text(bindings, modifier))
    except OSError as error:
        decky.logger.warning("Could not write the hotkey config for %s: %s",
                             entry_id, error)
        return ""
    return path


def refresh_hotkey_configs():
    """Rewrite every port's hotkey config from the catalog.

    The config is the only place a port's `menu_key` lands, and it is written
    when a launcher is. So correcting one -- Starship's menu opens with F1, not
    the Esc it was first given -- would reach only games added afterwards, while
    the ones already in the library went on sending the wrong key. Rewriting the
    file is enough: the launcher names it and the helper reads it at every
    launch, so nothing on disk has to change.
    """
    for entry in emulator_catalog.CATALOG:
        bindings = hotkeys.bindings_for(entry)
        if bindings:
            write_hotkey_config(entry["id"], bindings, hotkeys.modifier_for(entry))


def _gui_working_dir(emulator):
    """`cd` into the program's own folder, for one that reads it, or "".

    No game is linked in: this opens the interface, and the game belongs to a
    launch. What the program finds beside it is its own -- which is the point.
    """
    entry = emulator_catalog.find((emulator or {}).get("id") or "") or {}
    if not entry.get("game_beside"):
        return ""
    directory = os.path.dirname((emulator or {}).get("target") or "")
    return "cd %s || exit 1" % shlex.quote(directory) if directory else ""


def write_gui_launcher(emulator, title, args=(), allow=(), errand=""):
    """Write (or overwrite) the launcher that opens an emulator's interface.

    Named off the emulator rather than a ROM, so re-opening it rewrites the one
    script instead of accumulating one per press.

    That rewriting is what lets `args` work without a second Steam shortcut.
    Sending the interface on an errand -- Ryujinx's `--install-firmware` -- only
    needs the argument present on the run that was asked for, and the next press
    of plain "open the emulator" writes the script back without it. One shortcut,
    one script, no entry appearing and disappearing from the user's library.

    `errand` is a line of explanation for whoever reads the script later, since
    otherwise the two versions of it differ by one argument and no reason.
    """
    argv = emulators.gui_argv(emulator, args=args, allow=allow)
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    path = gui_launcher_path(emulator, title)

    body = "\n".join(
        [
            "#!/bin/sh",
            "# Generated by %s -- edits will be overwritten." % decky.DECKY_PLUGIN_NAME,
            _flat(errand) or "# Opens %s's own interface, with no game." % _flat(title),
            "",
            sysenv.SHELL_PREAMBLE,
            "",
            # A program that reads the directory it runs in has to open in its
            # own folder, or its window comes up knowing nothing: no settings,
            # and no archive it built from the user's game, because both are
            # files beside the build. It would then offer to start again.
            _gui_working_dir(emulator),
            "exec %s" % " ".join(shlex.quote(arg) for arg in argv),
            "",
        ]
    )

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
    os.chmod(
        path,
        stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
    )

    decky.logger.info("Wrote GUI launcher %s", path)
    return path


def remove_launcher(path):
    if not path:
        return False
    # Only ever delete inside our own runtime directory.
    normalized = os.path.normpath(path)
    if not normalized.startswith(os.path.normpath(LAUNCHER_DIR) + os.sep):
        decky.logger.warning("Refusing to delete outside launcher dir: %s", path)
        return False
    # **The launch log is deliberately left behind.**
    #
    # It was briefly deleted here, on the grounds that a log whose launcher is
    # gone can never be matched to a game again and is therefore litter. That
    # argument is true and beside the point: *removing a game because it did not
    # work* is the likeliest reason anybody removes one, and it is exactly the
    # moment the log explaining why becomes the only evidence left. Deleting it
    # there threw the answer away at the moment it was wanted.
    #
    # What it costs to keep is a few kilobytes per game ever removed, in a
    # truncated file. `_last_launch` says when the game a log belongs to is no
    # longer installed, which is the useful half of what the deletion was for.
    try:
        os.remove(normalized)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        decky.logger.warning("Could not remove launcher %s: %s", normalized, error)
        return False
