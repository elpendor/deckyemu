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

import decky

import cheevos
import emulators
import ra_detect
import sysenv

LAUNCHER_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "launchers")

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
FORMAT_VERSION = 5

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


def write_override_config(hide_osd, menu_combo="off", cheevos_settings=None):
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


def launcher_path(title, rom_path):
    digest = hashlib.sha1(rom_path.encode("utf-8")).hexdigest()[:8]
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    return os.path.join(LAUNCHER_DIR, "%s-%s.sh" % (_slug(title), digest))


def split_extra_args(extra_args):
    """Parse a free-text argument string the way a shell would.

    Raises ValueError on unbalanced quotes, so a typo is reported when the game
    is saved rather than silently producing a launcher that will not start.
    """
    text = (extra_args or "").strip()
    return shlex.split(text) if text else []


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
        override = write_override_config(hide_osd, menu_combo, cheevos_settings)
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
    path = os.path.join(LAUNCHER_DIR, "open-%s.sh" % _slug(emulator.get("id") or title))

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
