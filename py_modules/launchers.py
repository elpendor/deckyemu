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
from ra_overrides import (  # noqa: F401 -- re-exported; see ra_overrides.py
    AUTOCONFIG_DIR,
    MENU_COMBOS,
    OVERRIDE_CONFIG,
    OVERRIDE_CONFIGS,
    _ALL_QUIET,
    _COMBO_BUTTONS,
    _SELECT_BTN,
    _STARTUP_QUIET,
    _START_BTN,
    _STEAM_PAD_PROFILE,
    _quit_bindings_that_collide,
    write_override_config,
    write_pad_profile,
)
from launch_gate import (  # noqa: F401 -- re-exported; see launch_gate.py
    APPROVAL_SECONDS,
    BOUNCE_SECONDS,
    CLOUD_ALIVE_SECONDS,
    CLOUD_MAX_SECONDS,
    CLOUD_ON_FILE,
    CLOUD_STALE_SECONDS,
    LAUNCH_GATE_DIR,
    RAN_MARKER,
    _CLOUD_GATE,
    _LAUNCH_GATE,
    _LAUNCH_PREFLIGHT,
    _SIGCONT,
    _gate_file,
    _is_ours,
    _presence_label,
    _presence_test,
    _waiting,
    approve_launch,
    cloud_gate,
    forget_launch,
    gone,
    launch_gate,
    launches_waiting,
    preflight,
    ran_marker,
    refuse_launch,
    say_alive,
    set_cloud_wanted,
    take_bounce,
    take_missing,
    took_off,
    wake_launch,
    which_launch,
)



LAUNCHER_DIR = os.path.join(appenv.DATA_DIR, "launchers")

#: What the emulator said on its last run, one file per game. Hiding the OSD
#: also hides RetroArch's errors, so this is where a silent failure is read.
#: Truncated at each launch; see `LAUNCH_LOG_CAP`.
LAUNCH_LOG_DIR = os.path.join(appenv.DATA_DIR, "launch-logs")

#: How much of one is kept: longer logs are cut to their tail at startup. Not
#: capped while the game runs, as a pipe that closes would SIGPIPE it.
LAUNCH_LOG_CAP = 2 * 1024 * 1024


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
    path=None,
):
    """Write (or overwrite) the launcher for this game and return its path.

    `path` keeps a game's existing script, whose name can predate its ROM path.

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

    path = path or launcher_path(title, rom_path)
    command = " ".join(shlex.quote(arg) for arg in argv)
    forward, command = forward_layer_env(argv, command)

    # Only for emulators that read motion off a socket, once the server is
    # fetched: the wrapper costs the `exec` (see `motion_server`).
    entry = emulator_catalog.find((emulator or {}).get("id") or "") if emulator else {}
    server = emu_install.motion_server(entry) if emulator else ""

    # A port whose menu opens with a key, and the helper that puts that key on
    # the pad. Same shape as the motion server and for the same reasons: a child
    # of this script, not a daemon, and never left behind.
    keys = hotkey_helper(entry, path=path)

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
