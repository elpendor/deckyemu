"""How launchers and the panel talk through files around a launch.

Launchers are `/bin/sh` with Steam's runtime stripped, so notes in a
directory are the whole protocol, and nothing here needs the plugin loaded:
the two-games gate and its approvals, the missing-file preflight, and the
wait for cloud saves, where a launch stops itself until the panel wakes it.
"""

import os
import shlex
import time

import appenv

import emulator_catalog
import sysenv


#: Where launchers and the panel leave each other notes, named by app id:
#: `bounced-<id>` (refused, with what was running), `approved-<id>` (the user
#: said go) and the cloud-save files of `_CLOUD_GATE`. Files, because the other
#: end is `/bin/sh`, and launches must work without the plugin loaded.
LAUNCH_GATE_DIR = os.path.join(appenv.DATA_DIR, "launch")


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

#: The shell that waits for the panel to bring saves down before the game
#: starts. The panel does the fetching, where it can show a dialog; this only
#: waits, and only when the panel has written `cloudwait` for this launch.
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
