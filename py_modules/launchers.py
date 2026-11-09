"""Generate a tiny shell script per game and point the Steam shortcut at it.

Steam re-splits a shortcut's launch options string, which breaks on the
spaces, quotes and brackets ROM names are full of. A script quotes each
argument properly, and is one obvious place to look when a launch misbehaves.
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

import appenv

import cheevos
import emu_config
import emu_install
import emulator_catalog
from emulator_catalog import hotkeys
import emulators
import ra_detect
import sysenv

LAUNCHER_DIR = os.path.join(appenv.DATA_DIR, "launchers")

#: What the emulator said on its last run, one file per game. Hiding the OSD
#: also hides RetroArch's errors, so this is where a silent failure is read.
#: Truncated at each launch; see `LAUNCH_LOG_CAP`.
LAUNCH_LOG_DIR = os.path.join(appenv.DATA_DIR, "launch-logs")

#: How much of one is kept: longer logs are cut to their tail at startup. Not
#: capped while the game runs, as a pipe that closes would SIGPIPE it.
LAUNCH_LOG_CAP = 2 * 1024 * 1024

#: Where launchers and the panel leave each other notes, named by app id:
#: `bounced-<id>` (refused, with what was running), `approved-<id>` (the user
#: said go) and the cloud-save files of `_CLOUD_GATE`. Files, because the other
#: end is `/bin/sh`, and launches must work without the plugin loaded.
LAUNCH_GATE_DIR = os.path.join(appenv.DATA_DIR, "launch")

# Bumped whenever existing launchers are wrong rather than merely old: startup
# rewrites them all when it changes. A bump records that a rewrite ran, not
# that it reached every game, so a fix to the rebuild itself costs two numbers.
#
#   1  the original format
#   2  standalone emulators exported SDL_JOYSTICK_HIDAPI=1
#   3  that export removed again; it changed nothing inside Steam
#   4  flatpak emulators get the gamescope socket, or Vulkan fails
#   5  emulators can carry environment into the sandbox
#   6  the default OSD mode became `all`; each game resolves its options again
#   7  the launch gate: a second game is refused while one runs
#   8  the menu shortcut clears a quit binding on the same buttons
#   9  an emulator's environment can suppress Steam's on-screen keyboard
#  10  and carries the joystick hint for reading a pad without window focus
#  11  save RAM reaches disk every second, as Steam's Stop is not a clean exit
#  12  the launcher keeps what the emulator says, in the launch log
#  13  RetroArch runs with `--verbose` (built in ra_detect, baked in here)
#  14  13 again, for games skipped while their ROM was missing
#  15  emulators that read motion off a socket start their server here
#  16  15 again, for Decks where the server had not downloaded yet
#  17  the motion block execs when the server binary is missing
#  18  the launcher checks its ROM and emulator exist, and leaves a note
#  19  that note names the emulator
#  20  the name is the emulator's, not its package's
#  21  only a `.so` is described as a libretro core
#  22  the launcher can wait for cloud saves to come down
#  23  and waits for the panel to claim the launch first
#  24  the script announces itself and waits, rather than racing the panel
#  25  the wait follows the work, not a fixed ceiling
#  26  a save conflict can answer "do not start"
#  27  the wait logs to `lastwait.log` and clears its own leftovers
#  28  the launcher says when a launch actually reached the emulator
#  29  the wait is a stopped process, not a conversation over files
#  30  refusing a launch wakes it to exit, so Steam's loading screen ends
#  31  `cloud-on` counts only while fresh, so a dialog can wait for a person
#  32  a program that reads its game from its config is told it at launch
#  33  the hotkey helper is told which button is its own
#  34  the previous run's output is kept beside the last one
#  35  an approval counts only while fresh
#  36  launchers read ~/deckyemu/env.d; flatpak ones carry Vulkan layer vars
#  37  those variables are matched by prefix, not by name
#  38  the missing-file check runs before the wait for saves
#  39  the reached-the-emulator marker makes its own directory
#  40  no motion block on a machine without Deck sensors
#  41  a port's window carries a class a compositor rule can match
#  42  withdrawn: unsetting WAYLAND_DISPLAY broke gamescope's Vulkan layer
#  43  past the withdrawal, so a device holding 42 rewrites its launchers
FORMAT_VERSION = 43

# One file per OSD mode, as games can override it individually. The menu
# shortcut also lands in these but is global; if it ever becomes per game,
# key these by both.
OVERRIDE_CONFIGS = {
    "startup": os.path.join(appenv.DATA_DIR, "retroarch-overrides-startup.cfg"),
    "all": os.path.join(appenv.DATA_DIR, "retroarch-overrides-all.cfg"),
    # Suppresses nothing; written only when another setting must reach
    # RetroArch.
    "keep": os.path.join(appenv.DATA_DIR, "retroarch-overrides-keep.cfg"),
}

# Named by launchers older than per-game OSD settings; no longer written.
OVERRIDE_CONFIG = os.path.join(appenv.DATA_DIR, "retroarch-overrides.cfg")

# A controller profile for the pad Steam hands a game, and the directory
# RetroArch is pointed at to find it. Steam's virtual pad calls itself an Xbox
# 360 pad but carries Valve's ids (0x28de/0x11ff), so RetroArch's own Xbox 360
# profile never matches and, under the udev joypad driver, the pad has no
# bindings at all. These are that profile's bindings under Valve's ids.
#
# One profile, not a mirror of RetroArch's set: under Steam Input the virtual
# pad is the only one a game sees.
#
# The `udev` folder is right, and must not be "fixed" by naming a joypad driver.
# RetroArch looks in `<dir>/<driver>`, so with `sdl2` (EmuDeck's choice) it
# finds nothing here, which is fine: SDL recognises the virtual pad and needs
# no profile. Forcing udev would make every controller depend on this file.
AUTOCONFIG_DIR = os.path.join(appenv.DATA_DIR, "autoconfig")

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

    Returns the directory to hand RetroArch, or '' if it could not be written,
    in which case the launcher leaves autoconfig alone.
    """
    folder = os.path.join(AUTOCONFIG_DIR, "udev")
    path = os.path.join(folder, "Steam Virtual Gamepad.cfg")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_STEAM_PAD_PROFILE)
    except OSError as error:
        appenv.logger.warning("Could not write the pad profile: %s", error)
        return ""
    return AUTOCONFIG_DIR

# The banner and notices RetroArch shows when content loads, turned off for
# games launched from here without touching the user's retroarch.cfg.
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

# How to reach RetroArch's menu from a controller. RetroArch has no combo by
# default, and the Guide button never reaches it on a Deck (Steam takes it).
# Values are RetroArch's `input_combo_type` enum (input/input_defines.h); "off"
# writes nothing, leaving the user's own setting.
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


#: RetroArch's button numbers for Select and Start, from which EmuDeck builds
#: its exit hotkey.
_SELECT_BTN = "4"
_START_BTN = "6"

#: Which of Start and Select each menu combo uses, by its combo value. Combos
#: using neither cannot collide with an exit hotkey and are absent.
_COMBO_BUTTONS = {
    "3": {_SELECT_BTN, _START_BTN},   # L1+R1+Start+Select
    "4": {_SELECT_BTN, _START_BTN},   # Start+Select
    "7": {_START_BTN},                # hold Start
    "8": {_SELECT_BTN},               # hold Select
    "9": {_SELECT_BTN},               # Down+Select
}


def _quit_bindings_that_collide(config_dir, combo):
    """Settings that neutralise a quit binding sharing buttons with `combo`.

    EmuDeck binds Start+Select to quit, both as a combo and as a hotkey pair,
    which is our default menu shortcut: opening the menu would quit the game.
    Only in the per-launch override, so EmuDeck's binding still holds outside
    this plugin. Returns [] when nothing collides, the usual case.
    """
    wanted = _COMBO_BUTTONS.get(combo)
    if not wanted or not config_dir:
        return []

    config = ra_detect.parse_cfg(os.path.join(config_dir, "retroarch.cfg"))
    if not config:
        return []

    settings = []

    # The quit combo, compared by buttons: L1+R1+Start+Select includes
    # Start+Select.
    quit_combo = config.get("input_quit_gamepad_combo", "0")
    if _COMBO_BUTTONS.get(quit_combo, set()) & wanted:
        settings.append(("input_quit_gamepad_combo", "0"))

    # The hotkey pair: the exit key is unbound, not the modifier, which every
    # other hotkey shares.
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

    # Always: see AUTOCONFIG_DIR.
    autoconfig = write_pad_profile()
    if autoconfig:
        settings.append(("joypad_autoconfig_dir", autoconfig))

    # Global like the menu combo, so it rides in the same per-OSD-mode files.
    settings.extend(cheevos.config_lines(cheevos_settings or {}))

    # Nothing to add: no --appendconfig at all.
    if not settings:
        return ""

    # RetroArch saves its merged config on exit, which would make these
    # overrides permanent in the user's retroarch.cfg. The cost: menu changes
    # made during these sessions are not saved either.
    settings.append(("config_save_on_exit", "false"))

    # Save RAM reaches disk every second, not every ten: Steam's Stop kills
    # RetroArch without a flush, and a save interrupted mid-write is corrupt.
    settings.append(("autosave_interval", "1"))

    path = OVERRIDE_CONFIGS.get(hide_osd, OVERRIDE_CONFIGS["keep"])
    os.makedirs(appenv.DATA_DIR, exist_ok=True)
    lines = [
        "# Generated by %s -- appended over RetroArch's own config at launch."
        % appenv.NAME,
        "# Only affects games launched from this plugin.",
        "",
    ]
    lines.extend('%s = "%s"' % (key, value) for key, value in settings)
    lines.append("")

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    # 0600, always: it can hold the RetroAchievements token, a password.
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as error:
        appenv.logger.warning("Could not restrict %s: %s", path, error)
    return path


def _slug(title):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return slug[:60] or "game"


def _flat(text):
    """A value safe to put on a `#` line of a generated script.

    The script's header comments are built with `%`, and a newline in a title
    or ROM name would end the comment and run what follows as a command.
    """
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).strip()


#: How much of the hash goes in a launcher's name. Long enough that two ROMs
#: will not collide, short enough to leave the title readable.
DIGEST_LENGTH = 8


def launch_log_path(launcher):
    """Where this launcher's last run is kept.

    Named after the launcher, which the script always knows; its app id comes
    from `/proc` and can be empty.
    """
    stem = os.path.splitext(os.path.basename(launcher))[0]
    return os.path.join(LAUNCH_LOG_DIR, "%s.log" % stem)


def previous_launch_log_path(launcher):
    """Where the run before the last one is kept.

    A `.prev.log` beside the log, which the sweep and the report already
    handle as any `.log`.
    """
    stem = os.path.splitext(os.path.basename(launcher))[0]
    return os.path.join(LAUNCH_LOG_DIR, "%s.prev.log" % stem)


def log_capture(launcher):
    """The shell that keeps what the emulator says, or "" if it cannot.

    Redirects the shell's own output before the emulator is exec'd, so the
    process tree Steam watches is unchanged. Fails open: if the log cannot be
    written, the game launches without one.
    """
    log = launch_log_path(launcher)
    # "\n", never `os.linesep`: a CRLF shell script does not run.
    return "\n".join([
        "# What the emulator says, for the panel to show when a game dies on",
        "# startup. Truncated here, so this is always the last run.",
        "_dke_log=%s" % shlex.quote(log),
        "mkdir -p %s 2>/dev/null" % shlex.quote(LAUNCH_LOG_DIR),
        # The previous run is kept: a failed game is usually retried at once,
        # which would otherwise overwrite the only account of the failure.
        "_dke_prev=%s" % shlex.quote(previous_launch_log_path(launcher)),
        'if [ -s "$_dke_log" ]; then mv -f "$_dke_log" "$_dke_prev" 2>/dev/null;'
        " fi",
        'if : > "$_dke_log" 2>/dev/null; then exec >>"$_dke_log" 2>&1; fi',
        "",
    ])


#: Where `motion_server` splices the emulator's command line, which its block
#: needs twice: once to `exec`, once to run as a child.
COMMAND_PLACEHOLDER = "@@COMMAND@@"


def motion_server(binary):
    """The shell that runs a motion server for exactly as long as the game does.

    The gyro reaches the emulator over a local socket from a server reading
    the controller directly, so Steam Input keeps the pad. The server lives
    only as long as the game, so the sensor is not powered for others.

    The emulator runs as a child here, not after an `exec`, and a trap stops
    the server with it: Steam's reaper waits for every descendant, so a
    surviving server would leave the game "Running". A server that cannot
    start costs motion, never the game.
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

    A launcher killed with SIGKILL cannot stop its helpers: a hotkey helper
    then types into whatever opens next, and a motion server holds its port.
    Swept at startup too, as the next launch may never come.
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
            appenv.logger.warning("Could not look for stray %s processes: %s", name, error)
            continue
        killed += int((found.stdout or "0").strip() or 0)
    if killed:
        appenv.logger.info("Stopped %d helper(s) left over from a killed launch", killed)
    return killed


def read_launch_log(launcher, limit=8000, previous=False):
    """The tail of what this launcher's game last said, or "".

    The tail, where a failure is explained. `previous` reads the run before.
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

    # Drop the partial first line the seek landed in, but only if there is a
    # newline: a log of carriage-return redraws has none.
    if size > limit and "\n" in tail:
        tail = tail.split("\n", 1)[1]
    return tail.strip()


def sweep_launch_logs():
    """Trim anything that grew past `LAUNCH_LOG_CAP`. Returns how many were cut.

    At startup, as capping while writing would need a pipe that can SIGPIPE.
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
            # By path, not name, so `.prev.log` files are trimmed themselves.
            tail = _read_tail(path, LAUNCH_LOG_CAP // 2)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(tail)
            cut += 1
        except OSError as error:
            appenv.logger.warning("Could not trim %s: %s", path, error)
    if cut:
        appenv.logger.info("Trimmed %d oversized launch log(s)", cut)
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

    A launcher is `<title>-<digest>.sh`; the digest says which ROM it runs, so
    compare this, not names, which change on rename.
    """
    stem = os.path.splitext(os.path.basename(launcher or ""))[0]
    tail = stem.rsplit("-", 1)[-1] if "-" in stem else ""
    # Only hex of the right length: "Quest 3" must not offer "3".
    if len(tail) != DIGEST_LENGTH:
        return ""
    return tail.lower() if all(c in "0123456789abcdef" for c in tail.lower()) else ""


def split_extra_args(extra_args):
    """Parse a free-text argument string the way a shell would.

    Raises ValueError on unbalanced quotes, so a typo is caught on save.
    """
    text = (extra_args or "").strip()
    return shlex.split(text) if text else []



# The gate that stops a second game starting, spliced into every launcher
# before the exec. Steam's own warning skips non-Steam shortcuts, and stopping
# a launch from outside (CancelGameAction, CancelLaunch) does not work, so the
# script decides. It fails open at every step: a missed warning beats a game
# that will not start.
#
# A raw string: the backslashes are for `tr` and `sed`, not Python.
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


#: The most a launch will wait to be woken, in seconds: a watchdog, generous
#: because a person may be reading a dialog. A plugin that is gone is caught by
#: `cloud-on` going stale instead.
CLOUD_MAX_SECONDS = 600

#: How often the plugin touches `cloud-on` to say it is alive, and how old that
#: file may get before a launch stops believing it. This tells "nobody has
#: answered yet" from "nobody is there".
CLOUD_ALIVE_SECONDS = 30
CLOUD_STALE_SECONDS = 120

#: Present while cloud saves have somewhere to go: how a launcher knows, without
#: the plugin being up, whether waiting could be worth it.
CLOUD_ON_FILE = "cloud-on"

#: The shell that waits for the panel to bring saves down before the game starts.
#: The panel does the fetching, where it can show a dialog; this only waits,
#: and only when the panel has written `cloudwait` for this launch.
_CLOUD_GATE = r"""# Saves coming down before the game opens them. See launchers.py.
# **This script stops itself and waits to be woken.** Three versions negotiated
# with the plugin over files -- announce, heartbeat, poll, give up after a
# ceiling -- and each one had a timing bug of its own: two lost a race with
# Steam, one gave up 0.2s before the answer arrived, and one left a stop note
# that refused the *next* launch. None of that exists here. A stopped process
# waits exactly as long as it is left stopped, at no cost, and the plugin says
# when by resuming it. Other cloud-save tools for the Deck reach the same
# conclusion
# from the other end, suspending the game once it has started; stopping before
# the emulator runs is the same idea without the window where it could already
# have read a save.
# `-newermt` rather than a plain `-f`: the file says cloud saves are on, and
# its timestamp says the plugin is still there to answer. Without the second
# half, a Deck with the service restarting would stop every launch and wait out
# the
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
  # Nobody there -- the service restarting, or not installed -- and the game
  # still
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


#: Written just before the emulator runs, so a refused launch is not mistaken
#: for a session and its saves are not uploaded afterwards. Makes its own
#: directory; `2>` before `>`, so a failed redirection stays quiet.
RAN_MARKER = r"""# Past every gate: what happens after this is the game itself.
if [ -n "$_dke_self" ]; then
  mkdir -p '{gate}' 2>/dev/null
  printf 1 2>/dev/null > '{gate}/ran-'"$_dke_self"
fi
"""


def ran_marker():
    """The line that records that a launch got as far as the emulator."""
    return RAN_MARKER.replace("{gate}", LAUNCH_GATE_DIR)


def took_off(app_id):
    """Whether that launch reached the emulator, consuming the answer."""
    try:
        os.remove(_gate_file("ran", app_id))
        return True
    except OSError:
        return False


def launch_gate():
    """The two-games gate, with this install's paths in it."""
    return (_LAUNCH_GATE.replace("{gate}", LAUNCH_GATE_DIR)
            .replace("{approved}", str(APPROVAL_SECONDS)))


def cloud_gate():
    """The wait for saves to come down, with this install's paths in it.

    Placed after the two-games gate and the preflight, which refuse at once:
    there is no point fetching saves for a launch that will not happen, and the
    panel expects their notes within four seconds.
    """
    # The wait counts in steps rather than seconds, so the numbers written into
    # the script are the seconds divided by the step.
    return (_CLOUD_GATE
            .replace("{onfile}", CLOUD_ON_FILE)
            .replace("{stale}", str(CLOUD_STALE_SECONDS))
            .replace("{cap}", str(CLOUD_MAX_SECONDS)))


def _gate_file(kind, app_id):
    return os.path.join(LAUNCH_GATE_DIR, "%s-%d" % (kind, int(app_id)))


#: What a game needs, checked before its emulator starts. A missing emulator or
#: unmounted SD card would otherwise drop back to the library with nothing on
#: screen; instead the launch is refused with a note the panel explains. Only
#: launches that would fail anyway are refused. Stats, never subprocesses, as
#: it runs before every game; fails open, as without an app id there is
#: nowhere to leave a note.
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

    A flatpak is a deployed directory; an executable is a file with the
    execute bit. For a libretro game it is the core that is checked, as
    RetroArch's `exe` is often `/usr/bin/flatpak`.
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

    Baked in when the launcher is written, as removing an emulator can take its
    record with it. A core is named without `_libretro.so`.
    """
    if emulator:
        # The catalog's name first: an adopted emulator's record may carry its
        # flatpak id as its name. The record for hand-registered ones.
        entry = emulator_catalog.find(emulator.get("id") or "")
        return ((entry or {}).get("name") or emulator.get("name") or "").strip()
    if not core_path:
        return ""

    stem = os.path.basename(core_path)

    # Only a `.so` is a core: an emulator game with no record arrives with the
    # emulator's flatpak id in `core_path`.
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


#: For a program that reads its game from its own config: the launcher sets the
#: key on each launch, as every game on that program shares it. Not fatal if it
#: fails; the program starts either way.
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

    Empty for everything that takes its game on the command line.
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


#: Put the game where a program that reads its own directory will find it: a
#: link, remade every launch. Other links there go first, as the program takes
#: whichever game it finds; real files are never touched.
_GAME_BESIDE = """find {dir} -maxdepth 1 -type l -delete 2>/dev/null
ln -sfn {rom} {dir}/{name} || echo "deckyemu: could not put the game beside the program" >&2
cd {dir} || exit 1"""


def beside_link(emulator, rom_path):
    """Where a `game_beside` program expects this game, as (dir, name).

    ("", "") for everything else. Shared by the launcher and removal.
    """
    if not emulator or not rom_path:
        return "", ""
    entry = emulator_catalog.find(emulator.get("id") or "") or {}
    beside = entry.get("game_beside")
    if not beside:
        return "", ""
    directory = os.path.dirname(emulator.get("target") or "")
    if not directory:
        return "", ""
    # A program that reads one name and no other -- sm64coopdx wants
    # `baserom.us.z64` -- gets the link under that name. Otherwise the game
    # keeps the name it arrived with, which is what the rest expect.
    wanted = (beside.get("as") if isinstance(beside, dict) else "") or         os.path.basename(rom_path)
    return directory, wanted


def forget_beside(emulator, rom_path):
    """Remove the link put beside a program for `rom_path`. True if one went.

    Otherwise a removed port game would leave a broken link. Only a link
    pointing at this game is removed.
    """
    directory, name = beside_link(emulator, rom_path)
    if not directory or not name:
        return False
    path = os.path.join(directory, name)
    try:
        if os.path.islink(path) and os.path.realpath(path) == os.path.realpath(rom_path):
            os.remove(path)
            return True
    except OSError as error:
        appenv.logger.warning("Could not remove the link at %s: %s", path, error)
    return False


def game_beside_setup(emulator, rom_path):
    """The shell that runs a program in its own folder with the game in it, or "".

    For a program that looks for its game in the directory it runs in rather
    than taking a path -- see `game_beside` in the schema.
    """
    directory, wanted = beside_link(emulator, rom_path)
    if not directory or not wanted:
        return ""
    return (_GAME_BESIDE
            .replace("{dir}", shlex.quote(directory))
            .replace("{name}", shlex.quote(wanted))
            .replace("{rom}", shlex.quote(rom_path)))


def first_run_argv(entry, rom_path):
    """The shell that hands a port its game once, to set itself up, or "".

    For a port that builds its own archive from the game: the argument is
    passed only while that archive is missing, as a later launch would ask to
    extract again. `set --` keeps a path with spaces as one argument.
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

    For ports that ask for their game through zenity's file picker: a zenity
    of ours goes first on PATH, answers a file selection with the game, and
    hands every other dialog to the real one.
    """
    if not (entry or {}).get("game_picker") or not rom_path:
        return ""
    real = shutil.which(_PICKER_TOOL) or ""
    if not real:
        return ""
    directory = os.path.join(appenv.DATA_DIR, "pickers", entry["id"])
    shim = os.path.join(directory, _PICKER_TOOL)
    body = "\n".join([
        "#!/bin/sh",
        "# Generated by %s -- answers this port's file picker with the game "
        "the shortcut was made for." % appenv.NAME,
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
        appenv.logger.warning("Could not write the picker shim for %s: %s",
                             entry["id"], error)
        return ""
    return "\n".join([
        "# This port asks for its game through a picker, which opens in",
        "# \"Recently Used\" wherever it is pointed. See launchers.picker_shim.",
        "DECKYEMU_GAME=%s" % shlex.quote(rom_path),
        "PATH=%s:$PATH" % shlex.quote(directory),
        "export DECKYEMU_GAME PATH",
    ])


#: Where anything else can add environment to every launch.
ENV_DIR = "deckyemu/env.d"


def env_hook():
    """Shell that reads `~/deckyemu/env.d/*.sh` before the emulator starts.

    How another tool (frame generation, say) can set variables for our games
    without fighting over the shortcut's launch options. Sourced in sorted
    order; a missing or broken file costs only its own variables.
    """
    return [
        "# Anything dropped in ~/%s is sourced here -- the seam another plugin" % ENV_DIR,
        "# or a hand-written file uses to set variables for every launch.",
        "# See launchers.env_hook.",
        'for _dke_env in "$HOME"/%s/*.sh; do' % ENV_DIR,
        '  [ -r "$_dke_env" ] && . "$_dke_env"',
        "done",
        "unset _dke_env",
    ]


#: Prefixes of the variables a Vulkan layer needs inside a flatpak sandbox:
#: each layer's own namespace, so new variables need no edit here, and nothing
#: outside them crosses.
LAYER_ENV_PREFIXES = ("LSFGVK_", "MAKO_")

#: The off switches, which are not under either prefix.
LAYER_ENV_NAMES = ("DISABLE_LSFGVK", "DISABLE_MAKO")


def forward_layer_env(argv, command):
    """(prelude lines, command) that carry a layer's environment into a sandbox.

    `flatpak run` drops the host's environment, so a layer switched on by a
    shortcut's launch options would never reach a flatpak emulator. Forwarded
    as `--env=` in `"$@"`, so values with spaces survive. Nothing is emitted for
    other emulators.
    """
    if not argv or os.path.basename(argv[0]) != "flatpak":
        return [], command
    lines = [
        "# A Vulkan layer switched on for this shortcut lives in the host's",
        "# environment, and `flatpak run` does not carry it in.",
        "set --",
    ]
    # `env` lists what is set and `case` keeps the prefixes; values are read
    # back by name in the shell, never re-parsed.
    lines.extend([
        'for _dke_var in $(env | sed -n "s/^\\([A-Za-z_][A-Za-z0-9_]*\\)=.*/\\1/p"); do',
        "  case \"$_dke_var\" in",
        "    %s)" % "|".join(
            [prefix + "*" for prefix in LAYER_ENV_PREFIXES] + list(LAYER_ENV_NAMES)
        ),
        '      eval "_dke_val=\\${$_dke_var}"',
        '      set -- "$@" "--env=$_dke_var=$_dke_val"',
        "      ;;",
        "  esac",
        "done",
        "unset _dke_var _dke_val",
    ])
    # After `flatpak run` and before the application id, which is where every
    # other option this builds already goes.
    head = " ".join(shlex.quote(arg) for arg in argv[:2])
    rest = " ".join(shlex.quote(arg) for arg in argv[2:])
    return lines, " ".join(p for p in (head, '"$@"', rest) if p)


def preflight(rom_path, emulator, install, core_path, title_id=""):
    """The shell that refuses a launch whose pieces are missing, or "".

    With `title_id` (Vita3K) there is no ROM file to test.
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

    `kind` is "rom", "emulator" or ""; `name` is the missing emulator's name as
    the launcher recorded it. Consumed by reading, and expires.
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
    # Capped, as it goes straight into a sentence on screen.
    return kind, (lines[1].strip()[:80] if len(lines) > 1 else "")


#: How old a bounce note may be and still be answered: older ones belong to a
#: launch nobody is waiting on.
BOUNCE_SECONDS = 30

#: How old an approval may be and still let a launch past the two-games gate,
#: so one left by a failed launch cannot wave the next one through.
APPROVAL_SECONDS = 30


def take_bounce(app_id):
    """What was running when this game's launcher refused, or "" if it did not.

    Consumed by reading; an uncollected note expires.
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

    A file the launcher can test. Absent, every launch goes straight through.
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
        appenv.logger.warning("Could not record cloud saves as %s: %s",
                             "on" if on else "off", error)


def launches_waiting():
    """The app ids of launchers currently held, waiting for their saves.

    Each launcher writes its own file first thing, so nothing has to hear of
    the launch from Steam in time; see `plugin_transfers._watch_launches`.
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


#: SIGCONT by number: `signal` may be missing from the loader's trimmed Python.
_SIGCONT = 18


def say_alive():
    """Touch `cloud-on`, which is how a launch knows anyone is listening.

    On a timer; a launch reads its age. See `CLOUD_STALE_SECONDS`.
    """
    path = os.path.join(LAUNCH_GATE_DIR, CLOUD_ON_FILE)
    try:
        if os.path.exists(path):
            os.utime(path, None)
    except OSError:
        pass


def _waiting(app_id):
    """The stopped launch for `app_id` as (pid, script), or (0, "").

    Read back from the file the launcher wrote.
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

    A pid from a stale file may now belong to another process, which must
    never be signalled. Checked against the script the file names.
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
        appenv.logger.warning("Could not wake launch %s: %s", app_id, error)


def forget_launch(app_id):
    """Remove the file a stopped launch left, whatever became of the process.

    A killed launch never clears its own, and would be answered again.
    """
    try:
        os.remove(_gate_file("launching", app_id))
    except OSError:
        pass


def which_launch(app_id):
    """The pid currently waiting for `app_id`, or 0.

    So a wait can tell its own launch from a later one of the same game.
    """
    pid, script = _waiting(app_id)
    return pid if _is_ours(pid, script) else 0


def gone(app_id):
    """Whether the launch that wrote this file is no longer there.

    """
    pid, script = _waiting(app_id)
    return not _is_ours(pid, script)


def refuse_launch(app_id):
    """End a stopped launch without starting the game.

    For "do not start" at a save conflict. Asked to exit with a note and a
    wake-up, not killed: Steam waits on that process, and a SIGKILL leaves its
    loading screen up.
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
        appenv.logger.warning("Could not refuse launch %s: %s", app_id, error)
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
        appenv.logger.warning("Could not approve launch for %s: %s", app_id, error)
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

    `emulator` selects a standalone emulator instead of RetroArch, to which the
    OSD and menu settings do not apply. `extra_args` is appended, as some
    templates end in `-- {rom}`, where anything before would be read as content.
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
    forward, command = forward_layer_env(argv, command)

    # Only for emulators that read motion off a socket, once the server is
    # fetched: the wrapper costs the `exec` (see `motion_server`).
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
            "# Generated by %s -- edits will be overwritten." % appenv.NAME,
            "# Game: %s" % _flat(title),
            "# ROM:  %s" % _flat(rom_path),
            "# Core: %s" % _flat(core_path),
        ]
        + (["# Args: %s" % _flat(" ".join(extra))] if extra else [])
        + env_hook()
        + forward
        + [
            "",
            sysenv.SHELL_PREAMBLE,
            "",
            launch_gate(),
            preflight(rom_path, emulator, install, core_path, title_id),
            cloud_gate(),
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

    appenv.logger.info("Wrote launcher %s", path)
    return path


#: The name of the one hidden Steam shortcut that opens an emulator's own
#: window: in Game Mode only a shortcut can, so it is repointed at whichever
#: emulator is being opened.
SETUP_SHORTCUT_TITLE = "DeckyEmu setup"


def gui_launcher_path(emulator, title=""):
    """Where the launcher that opens `emulator`'s own interface lives.

    Shared with the library check, which must not report it as a stray. Ask
    this rather than matching `open-*.sh`, which a game called "Open Road"
    would also match.
    """
    return os.path.join(
        LAUNCHER_DIR, "open-%s.sh" % _slug((emulator or {}).get("id") or title)
    )


#: What runs the hotkey helper beside a port, and stops it with the game (as in
#: `motion_server`). A missing helper costs the gesture, never the game.
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

    Empty when the port declares no keys or its helper is not fetched yet.
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

    In the runtime directory: derived, and rewritten with each launcher.
    """
    directory = os.path.join(appenv.DATA_DIR, "hotkeys")
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "%s.ini" % entry_id)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(hotkeys.config_text(bindings, modifier))
    except OSError as error:
        appenv.logger.warning("Could not write the hotkey config for %s: %s",
                             entry_id, error)
        return ""
    return path


def refresh_hotkey_configs():
    """Rewrite every port's hotkey config from the catalog.

    So a corrected `menu_key` reaches games already added; the helper reads
    the file at every launch.
    """
    for entry in emulator_catalog.CATALOG:
        bindings = hotkeys.bindings_for(entry)
        if bindings:
            write_hotkey_config(entry["id"], bindings, hotkeys.modifier_for(entry))


def _gui_working_dir(emulator):
    """`cd` into the program's own folder, for one that reads it, or "".

    No game is linked in: this opens the interface, not a game.
    """
    entry = emulator_catalog.find((emulator or {}).get("id") or "") or {}
    if not entry.get("game_beside"):
        return ""
    directory = os.path.dirname((emulator or {}).get("target") or "")
    return "cd %s || exit 1" % shlex.quote(directory) if directory else ""


def write_gui_launcher(emulator, title, args=(), allow=(), errand=""):
    """Write (or overwrite) the launcher that opens an emulator's interface.

    One script per emulator, rewritten on each open, so `args` (an errand like
    Ryujinx's `--install-firmware`) apply to that run only. `errand` is a line
    in the script saying why.
    """
    argv = emulators.gui_argv(emulator, args=args, allow=allow)
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    path = gui_launcher_path(emulator, title)

    body = "\n".join(
        [
            "#!/bin/sh",
            "# Generated by %s -- edits will be overwritten." % appenv.NAME,
            _flat(errand) or "# Opens %s's own interface, with no game." % _flat(title),
            "",
            sysenv.SHELL_PREAMBLE,
            "",
            # Such a program finds its settings and archive in its own folder.
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

    appenv.logger.info("Wrote GUI launcher %s", path)
    return path


def remove_launcher(path):
    if not path:
        return False
    # Only ever delete inside our own runtime directory.
    normalized = os.path.normpath(path)
    if not normalized.startswith(os.path.normpath(LAUNCHER_DIR) + os.sep):
        appenv.logger.warning("Refusing to delete outside launcher dir: %s", path)
        return False
    # The launch log stays: a game is often removed because it failed, and its
    # log is then the only account of why.
    try:
        os.remove(normalized)
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        appenv.logger.warning("Could not remove launcher %s: %s", normalized, error)
        return False
