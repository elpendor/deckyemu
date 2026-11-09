"""The override file RetroArch reads over its own config for our launches.

Passed with --appendconfig, so the user's retroarch.cfg is never written:
on-screen message modes, the Steam pad's controller profile, the menu
shortcut, a fix for exit bindings on the same buttons, achievements, and how
often save RAM reaches disk.
"""

import os
import stat

import appenv

import cheevos
import ra_detect


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
