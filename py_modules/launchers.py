"""Generate a tiny shell script per game and point the Steam shortcut at it.

Steam stores a shortcut's arguments as a single LaunchOptions string, which it
re-splits on launch. ROM filenames are full of spaces, apostrophes, brackets and
ampersands, so round-tripping them through that field is a reliable source of
"game won't start" bugs. A generated script sidesteps the quoting problem
entirely and gives us one obvious place to look when a launch misbehaves.
"""

import hashlib
import os
import re
import shlex
import stat
import time

import decky

import cheevos
import emulators
import ra_detect
import sysenv

LAUNCHER_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "launchers")

#: Where the launch gate leaves its notes. Two kinds of one-line file, both
#: named after the Steam app id: `bounced-<id>`, written by a launcher that
#: refused to start and listing what was already running, and `approved-<id>`,
#: written by the panel when the user said go and consumed by the next launch.
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
FORMAT_VERSION = 11

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
  if [ -f "$_dke_gate/approved-$_dke_self" ]; then
    # The panel asked and the answer was yes. One shot: taken now, so a later
    # launch is judged on its own.
    rm -f "$_dke_gate/approved-$_dke_self"
  else
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


def launch_gate():
    """The gate, with this install's paths in it."""
    return _LAUNCH_GATE.replace("{gate}", LAUNCH_GATE_DIR)


def _gate_file(kind, app_id):
    return os.path.join(LAUNCH_GATE_DIR, "%s-%d" % (kind, int(app_id)))


#: How old a bounce note may be and still be answered.
#:
#: The panel asks for it a moment after the launch it belongs to, so anything
#: older is from a launch nobody is waiting on any more -- a bounce while the
#: plugin was reloading, or one written and never collected. Answering a stale
#: one would put a dialog about a game on screen minutes after the user gave up
#: on it.
BOUNCE_SECONDS = 30


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
    try:
        os.remove(normalized)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        decky.logger.warning("Could not remove launcher %s: %s", normalized, error)
        return False
