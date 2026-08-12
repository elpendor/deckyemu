"""User-defined standalone emulators -- Dolphin, PCSX2, Cemu, RPCS3 and friends.

RetroArch does not cover everything, so an emulator can be registered by hand.
The important field is `databases`: the libretro system name this emulator
emulates. Artwork lookup keys on exactly that string, for both libretro
thumbnails and SteamGridDB's release-era sanity check, so declaring it once makes
a custom emulator behave like any core -- same naming, same boxart, same
collection grouping.

Emulators are deliberately shaped like the dicts `ra_cores.list_cores` returns.
Everything downstream -- ROM probing, extension matching, artwork resolution,
collection naming -- then works without knowing the difference.
"""

import json
import os
import posixpath
import re
import shlex
import stat

import decky

import emulator_catalog

EMULATORS_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "emulators.json")

# `{rom}` is substituted per argument, after splitting, so a ROM path containing
# spaces cannot break the argument list.
ROM_PLACEHOLDER = "{rom}"

FLATPAK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z][A-Za-z0-9_-]*)+$")

# Game Mode runs every window through gamescope, and gamescope's Vulkan layer --
# "Gamescope WSI (XWayland Bypass)" -- talks to the compositor over a socket in
# the runtime directory. A flatpak cannot see that socket unless its manifest
# asks for it, and whether a manifest does is pure luck: PCSX2 declares
# `xdg-run/gamescope-0`, DuckStation does not.
#
# Where it is missing the layer loads, fails to connect, and the emulator throws
# a Vulkan error the user has to dismiss before the game will start:
#
#   [Gamescope WSI] Failed to connect to gamescope socket: gamescope-0.
#                   Bypass layer will be unavailable.
#
# Granting it here rather than through `flatpak override` keeps the change to
# the launches this plugin makes: read-only access to one socket, for the run
# that needs it, with nothing left behind on the user's flatpak configuration.
GAMESCOPE_SOCKET_ARG = "--filesystem=xdg-run/gamescope-0:ro"

# Launch recipes come from the catalog, which is the only place they are
# written. This used to be a second table, and the two drifted: it offered
# `--no-gui` as RPCS3's fullscreen switch while the catalog installed RPCS3 with
# `--fullscreen` and passed `--no-gui` as an ordinary argument, and four of the
# seven emulators listed in both disagreed. An emulator registered by hand was
# given a different recipe from the same emulator installed with one tap.
#
# Kept re-exported here because this is where a reader looks for how an emulator
# is launched. `launch_hints` is a function rather than the tuple this once was:
# it is derived from the catalog on each call, so there is no constant to hold.
launch_hints = emulator_catalog.launch_hints
suggest_launch_options = emulator_catalog.suggest_launch_options


def suggest_fullscreen_args(target):
    """A likely fullscreen switch for `target`, or '' when unknown."""
    return suggest_launch_options(target)["fullscreen_args"]


def _read():
    try:
        with open(EMULATORS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write(emulators):
    os.makedirs(os.path.dirname(EMULATORS_PATH), exist_ok=True)
    tmp = EMULATORS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(emulators, handle, indent=2)
    os.replace(tmp, EMULATORS_PATH)


def slugify(name):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-").lower()
    return slug[:40] or "emulator"


def list_emulators():
    return _read()


def parse_extensions(text):
    """`iso, rvz .gcm` -> ['iso', 'rvz', 'gcm']."""
    if isinstance(text, list):
        parts = text
    else:
        parts = re.split(r"[,\s]+", text or "")
    seen = []
    for part in parts:
        cleaned = part.strip().lstrip(".").lower()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def validate(emulator):
    """Returns an error string, or '' when the definition is usable."""
    name = (emulator.get("name") or "").strip()
    if not name:
        return "Give the emulator a name."

    kind = emulator.get("kind")
    target = (emulator.get("target") or "").strip()
    if kind == "flatpak":
        if not FLATPAK_ID_RE.match(target):
            return "That does not look like a Flatpak application id."
    elif kind == "path":
        if not target.startswith("/"):
            return "Choose the emulator's executable."
        if not os.path.isfile(target):
            return "No file exists at %s" % target
    else:
        return "Choose whether this is a Flatpak or an executable."

    if not emulator.get("extensions"):
        return "List at least one file extension, e.g. iso, rvz."

    args = emulator.get("args") or ROM_PLACEHOLDER
    if ROM_PLACEHOLDER not in args:
        return "The arguments must include %s so the ROM can be passed in." % ROM_PLACEHOLDER
    try:
        shlex.split(args)
    except ValueError:
        return "The arguments could not be parsed -- check the quoting."

    try:
        shlex.split(emulator.get("fullscreen_args") or "")
    except ValueError:
        return "The fullscreen arguments could not be parsed -- check the quoting."

    return ""


def save(emulator):
    """Add or update an emulator. Returns (saved_or_None, error)."""
    entry = {
        "id": (emulator.get("id") or "").strip() or slugify(emulator.get("name")),
        "name": (emulator.get("name") or "").strip(),
        "kind": emulator.get("kind"),
        "target": (emulator.get("target") or "").strip(),
        "args": (emulator.get("args") or ROM_PLACEHOLDER).strip() or ROM_PLACEHOLDER,
        "extensions": parse_extensions(emulator.get("extensions")),
        "databases": [db for db in (emulator.get("databases") or []) if db],
        # For systems libretro has no database for -- Switch, Wii U, PS3 and so
        # on -- the platform label cannot be derived, so it is stored directly.
        # Only used for collection naming; artwork falls to SteamGridDB.
        "platform": (emulator.get("platform") or "").strip(),
        "platform_full": (emulator.get("platform_full") or "").strip(),
        # Applied when the "launch fullscreen" setting is on. Per-emulator
        # because no flag is common to all of them.
        "fullscreen_args": (emulator.get("fullscreen_args") or "").strip(),
    }

    existing = find(entry["id"])
    # What the catalog's recipe said when this was installed, kept so a later
    # correction to that recipe can tell an untouched value from one edited
    # here. Carried over when the caller does not supply it, which is every save
    # from the editor: changing a name should not freeze the launch arguments.
    # `command` rides along for the same reason: it is set by the catalog and
    # never by the editor, so a save from there must not drop it. shadPS4 is
    # the case -- without it every launch reaches a version picker instead of
    # the emulator.
    for key in (
        "catalog_recipe", "catalog_args", "catalog_fullscreen_args",
        "command", "env", "installed_args",
    ):
        value = emulator.get(key)
        if value is None and existing:
            value = existing.get(key)
        if value is not None:
            entry[key] = value

    error = validate(entry)
    if error:
        return None, error

    emulators = _read()
    replaced = False
    for index, existing in enumerate(emulators):
        # An edit keeps its own id; anything else must not collide.
        if existing.get("id") == entry["id"]:
            emulators[index] = entry
            replaced = True
            break

    if not replaced:
        taken = {existing.get("id") for existing in emulators}
        base = entry["id"]
        suffix = 2
        while entry["id"] in taken:
            entry["id"] = "%s-%d" % (base, suffix)
            suffix += 1
        emulators.append(entry)

    _write(emulators)
    decky.logger.info("Saved emulator %r (%s)", entry["name"], entry["id"])
    return entry, ""


def remove(emulator_id_value):
    emulators = _read()
    remaining = [item for item in emulators if item.get("id") != emulator_id_value]
    if len(remaining) == len(emulators):
        return False
    _write(remaining)
    decky.logger.info("Removed emulator %s", emulator_id_value)
    return True


def ensure_executable(path):
    """Make sure an emulator binary can actually be run.

    AppImages downloaded through a browser arrive without the execute bit, and
    the failure is invisible: the launcher script runs, `exec` returns
    "Permission denied", and Steam just shows the game closing immediately. This
    is the single most likely reason a freshly registered emulator does nothing.

    Returns (ok, changed, error).
    """
    if not path or not os.path.isfile(path):
        # validate() reports a missing file with a better message.
        return True, False, ""

    if os.access(path, os.X_OK):
        return True, False, ""

    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as error:
        return False, False, "%s is not executable and could not be changed: %s" % (path, error)

    if not os.access(path, os.X_OK):
        return False, False, (
            "%s is still not executable. It may be on a filesystem mounted "
            "without exec permission." % path
        )

    decky.logger.info("Added the execute bit to %s", path)
    return True, True, ""


def find(emulator_id_value):
    for emulator in _read():
        if emulator.get("id") == emulator_id_value:
            return emulator
    return None


# Emulator ids are namespaced so they cannot collide with a libretro core id.
_PREFIX = "emu:"


def is_emulator_id(core_id):
    return isinstance(core_id, str) and core_id.startswith(_PREFIX)


def emulator_id(core_id):
    return core_id[len(_PREFIX):] if is_emulator_id(core_id) else core_id


def to_core_entry(emulator, system_name=""):
    """Shape an emulator like a libretro core.

    Everything downstream keys off `databases` and `extensions`, so once those
    are set a custom emulator needs no special handling.
    """
    databases = emulator.get("databases") or []
    label = (
        system_name
        or (databases[0].split(" - ")[-1] if databases else "")
        # A libretro-less system carries its own label; the emulator's own name
        # is the last resort, and only when nothing else was set.
        or emulator.get("platform", "")
        or emulator.get("name", "")
    )
    return {
        "id": _PREFIX + (emulator.get("id") or ""),
        "path": emulator.get("target", ""),
        "display_name": emulator.get("name", ""),
        # Same value, but the key has to exist: anything listing cores by their
        # short name would otherwise join an undefined into the string and print
        # a dangling separator. That is exactly what happened in the RetroArch
        # tab's core list, where a registered emulator became an empty entry.
        "short_name": emulator.get("name", ""),
        "system_name": label,
        "databases": databases,
        "extensions": emulator.get("extensions") or [],
        "has_info": True,
        "source": "emulator",
    }


def flatpak_prefix(emulator, extra=()):
    """`flatpak run` plus whatever this emulator needs before its application id.

    `command` is the one that is not obvious. A flatpak runs whatever its
    manifest names, and that is not always the emulator: shadPS4's runs
    `shadPS4QtLauncher`, a picker for which build of shadPS4 to use, which reads
    a game path as the name of an emulator and fails. `--command=shadps4` goes
    straight to the thing that runs games.

    `env` exists for the other thing a sandbox gets wrong. shadPS4 enumerated
    four Vulkan devices on a Deck and picked llvmpipe -- the software
    rasteriser -- so every game rendered on the CPU and every game was slow.
    Restricting the loader to the AMD driver leaves one device to choose from.
    """
    argv = ["flatpak", "run"]
    command = (emulator.get("command") or "").strip()
    if command:
        argv.append("--command=%s" % command)
    for name, value in sorted((emulator.get("env") or {}).items()):
        argv.append("--env=%s=%s" % (name, value))
    argv.extend(extra)
    argv.append(emulator.get("target", ""))
    return argv


def gui_argv(emulator, args=(), allow=()):
    """Argv that opens an emulator's own interface, with no game.

    Deliberately not `launch_argv` with an empty ROM: the arguments in the
    catalog exist to get straight into a game and out again -- RPCS3's
    `--no-gui` is the clearest case -- and every one of them is wrong for
    reaching the interface. An empty ROM would also leave a stray empty
    argument where the path should be.

    This is the route to the things an emulator will only do through its own
    windows -- importing Switch firmware, and anything `tool_argv` below has no
    unattended equivalent for. A window is only ever shown by gamescope if Steam
    is what launched it, so the interface has to arrive as a Steam shortcut or it
    cannot be seen at all.

    `args` sends the interface somewhere in particular. Ryujinx's
    `--install-firmware <path>` is the case: it exists, and it is not a headless
    route -- the argument is read inside the main window's own template callback
    and then waits on a Yes/No dialog. So it needs the window either way, and
    what it buys is not automation but the file browser: without it the user
    must find Tools > Install Firmware and then steer a file picker to the right
    folder with a thumbstick.

    `allow` is folders the sandbox could not otherwise read. It matters more
    here than it looks: handed a path it cannot open, Ryujinx reports the
    firmware as invalid rather than as missing, which reads as a bad download.
    Read-only, unlike the grants `tool_argv` makes: an interface being sent to
    a file needs to read it and nothing more, and this one is being opened at
    the folder every dump the user has ever sent is sitting in.
    """
    extra = [GAMESCOPE_SOCKET_ARG]
    extra.extend("--filesystem=%s:ro" % folder for folder in allow if folder)
    if emulator.get("kind") == "flatpak":
        return flatpak_prefix(emulator, extra) + list(args)
    return [emulator.get("target", "")] + list(args)


def tool_argv(emulator, args, allow=()):
    """Argv that runs an emulator as a command-line tool, with no window at all.

    RPCS3 is the case this exists for. `--headless --installpkg` and `--headless
    --installfw` take a branch where every dialog sits behind `if (main_window)`,
    so a 240MB package unpacks in about five seconds and the PS3 firmware in six,
    with no window, no dialog and nothing to press. That is the whole reason the
    catalog installs upstream's AppImage: the Flathub build has no such branch
    and each of these waits on a modal dialog forever.

    `allow` is folders a flatpak could not otherwise read -- where the file being
    installed lives. Deliberately no `GAMESCOPE_SOCKET_ARG`: nothing is being
    displayed, and asking for a socket a headless run will never use only adds a
    way for it to fail.
    """
    if emulator.get("kind") == "flatpak":
        grants = ["--filesystem=%s" % folder for folder in allow if folder]
        return flatpak_prefix(emulator, grants) + list(args)
    return [emulator.get("target", "")] + list(args)


TITLE_PLACEHOLDER = "{title}"


def launch_argv(emulator, rom_path, fullscreen=True, title_id=""):
    """Argv that starts `rom_path` in this emulator.

    `title_id` is for the emulators that start an *installed* title rather than
    a file. Vita3K is the one: `-Fr PCSA00011` boots a game and handing it a
    path does not, and a title id has the useful property of never containing a
    space -- which matters because its AppImage word-splits its own arguments.
    An emulator says it works this way by carrying `installed_args`; everything
    else is unaffected.
    """
    installed = emulator.get("installed_args") or ""
    if installed and title_id:
        tokens = [
            token.replace(TITLE_PLACEHOLDER, title_id)
            for token in shlex.split(installed)
        ]
        rom_path = ""
    else:
        tokens = shlex.split(emulator.get("args") or ROM_PLACEHOLDER)
        # Substituted after splitting so a ROM path with spaces stays one argument.
        tokens = [token.replace(ROM_PLACEHOLDER, rom_path) for token in tokens]

    if fullscreen:
        try:
            extra = shlex.split(emulator.get("fullscreen_args") or "")
        except ValueError:
            extra = []
        # Before the ROM: emulators that take a positional path expect it last.
        tokens = extra + tokens

    if emulator.get("kind") == "flatpak":
        extra = []
        rom_dir = posixpath.dirname(rom_path)
        if rom_dir:
            # Same reasoning as the RetroArch flatpak: the sandbox cannot reach
            # the SD card or arbitrary folders unless told to.
            extra.append("--filesystem=%s" % rom_dir)
        extra.append(GAMESCOPE_SOCKET_ARG)
        return flatpak_prefix(emulator, extra) + tokens

    return [emulator.get("target", "")] + tokens
