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

import hashlib
import os
import posixpath
import re
import shlex
import stat

import decky

import emu_install
import emu_patch
import emulator_catalog
import jsonstore

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
    return jsonstore.read_json(EMULATORS_PATH, [])


def _write(emulators):
    jsonstore.write_json(EMULATORS_PATH, emulators)


def slugify(name):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-").lower()
    return slug[:40] or "emulator"


def fix_notices(emulator, entry, options=None):
    """Anything to say about the fixes this emulator, or one of its games, runs.

    One place, so the Emulators tab and the launch dialog cannot word the same
    fact differently or disagree about which fixes are on. `options` narrows it
    to a single game; without it the answer is the emulator's own.

    Only fixes still *switched on*. One that is off is already in the state we
    would be asking for, and saying so would be noise. Nothing is said about a
    fix that is on and working, either -- the moment is worth spending only on
    the gap between what was asked for and what is happening.
    """
    off = _effective_off(emulator, options, entry)
    unavailable = {}
    stock = emu_patch.stock_path((emulator.get("target") or "").strip(), entry)
    for row in emu_patch.unapplied(entry):
        if not (stock and emu_patch.target_for(stock, row["id"])):
            unavailable[row["id"]] = row["error"]
    return [
        {"id": row["id"], "name": row["name"], "state": row["state"],
         "note": row["note"]}
        for row in emulator_catalog.workaround_state(
            entry, off, unavailable, emu_install.installed_build(entry))
        if row["state"] and row["enabled"]
    ]


def list_emulators():
    """Every registered emulator, each carrying anything to say about its fixes.

    `fix_notices` is computed rather than stored, because none of what decides
    it lives in the record: it is the catalog, the build installed, and what is
    on disk beside it.

    It is here rather than left to whoever opens the editor because a message
    nobody sees is not a message. The Emulators tab is where somebody would act
    on any of them -- by updating the emulator -- so they have to be legible
    from there without opening anything.
    """
    emulators = _read()
    for emulator in emulators:
        entry = emulator_catalog.find(emulator.get("id") or "")
        if not entry:
            continue
        emulator["fix_notices"] = fix_notices(emulator, entry)
    return emulators


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
        "catalog_extensions", "command", "env", "installed_args", "layout",
        "splits_args",
        # Which corrections this install has switched off. Carried like the
        # rest: the editor never sends it, so a save from there would drop
        # the choice and quietly switch motion back on.
        "workarounds_off",
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
        # The system this emulator runs, as a label that does not move. Distinct
        # from `system_name` above, which follows the user's short/long naming
        # setting -- fine for a caption, wrong for anything that becomes a path.
        # `roms/ps3` and `roms/playstation-3` for the same console, depending on
        # a display preference, is how a library ends up split in two.
        #
        # Empty for a libretro-backed emulator, which has `databases` to say it
        # better.
        "platform_full": emulator.get("platform_full", ""),
        "extensions": emulator.get("extensions") or [],
        "has_info": True,
        "source": "emulator",
    }


# `{plugin}` in an env value becomes the directory this plugin is installed in,
# so a catalog entry can point at a file the plugin ships without knowing where
# Decky put it. shadPS4's `LD_PRELOAD` is the only user: the shim in `shim/` has
# to be named by absolute path, and that path is not knowable when the entry is
# written.
PLUGIN_PLACEHOLDER = "{plugin}"


def _plugin_dir():
    return getattr(decky, "DECKY_PLUGIN_DIR", "") or ""


def resolved_env(emulator):
    """An emulator's `env` with `{plugin}` expanded, dropping what is not there.

    A value naming a file the plugin ships is dropped when that file is missing
    rather than passed on. Without this a build made without the shim -- a
    `deploy.sh` run against a Deck with no flatpak SDK, say -- would hand the
    dynamic linker a path to nothing on every launch, and the only sign would be
    a loader warning nobody reads. Dropping it degrades to "no motion", which is
    the truth.
    """
    resolved = {}
    for name, value in sorted((emulator.get("env") or {}).items()):
        if not name:
            continue
        if PLUGIN_PLACEHOLDER in str(value):
            expanded = str(value).replace(PLUGIN_PLACEHOLDER, _plugin_dir())
            if not _plugin_dir() or not os.path.exists(expanded):
                continue
            value = expanded
        resolved[name] = value
    return resolved


def plugin_grants(emulator):
    """`--filesystem=` for a sandbox that has to read a file the plugin ships.

    Read-only, and only when something actually points into the plugin
    directory: a flatpak cannot see it otherwise, and `LD_PRELOAD` naming a file
    the sandbox cannot open fails silently apart from a loader warning.
    """
    directory = _plugin_dir()
    if not directory:
        return []
    for value in resolved_env(emulator).values():
        if str(value).startswith(directory):
            return ["--filesystem=%s:ro" % directory]
    return []


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
    for name, value in sorted(resolved_env(emulator).items()):
        argv.append("--env=%s=%s" % (name, value))
    argv.extend(plugin_grants(emulator))
    argv.extend(extra)
    argv.append(emulator.get("target", ""))
    return argv


def env_prefix(emulator):
    """`env NAME=VALUE ...` for an emulator that is not in a sandbox.

    The same job `--env=` does in `flatpak_prefix`, for the other half of the
    catalog. It was missing: `env` reached a flatpak and was silently dropped
    for every AppImage, so an entry could declare one, pass validation, and
    launch without it. Vita3K is the entry that found this.

    `/usr/bin/env` rather than shell assignments because a launcher is written
    as one `exec` line of quoted argv -- see `launchers.write_launcher` -- and
    an assignment ahead of `exec` would have to be spliced in as raw text.
    Empty when there is nothing to set, so the common launcher is unchanged.
    """
    settings = [
        "%s=%s" % (name, value)
        for name, value in sorted(resolved_env(emulator).items())
    ]
    return ["env"] + settings if settings else []


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
    return env_prefix(emulator) + [emulator.get("target", "")] + list(args)


#: Where the space-free links below are kept. decky's runtime directory rather
#: than the user's own folder: nothing here is theirs to look at or keep, and it
#: being wiped on uninstall is correct.
ARG_LINK_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "argpaths")


def space_free(path):
    """`path`, or a symlink to it whose own path holds no space.

    For an emulator whose launcher word-splits its arguments. Vita3K's AppImage
    is one: its `AppRun.wrapped` ends in

        "${APPDIR}/usr/bin/Vita3K" $@

    with `$@` unquoted, so the shell inside the AppImage re-splits every
    argument the shell outside it took care to keep together. A game at
    `.../GRAVITY RUSH (PCSA00011).pkg` reaches the emulator as three arguments
    and it reports the second word as unsupported content -- which reads as a
    bad dump rather than as a quoting fault, and cost an evening the first time.

    A link rather than a rename, because the file is the user's and where they
    sent it is where they will look for it. Falls back to the original path if
    a link cannot be made: the call then fails exactly as it does today, which
    is no worse than not trying.
    """
    path = path or ""
    if " " not in path:
        return path

    try:
        os.makedirs(ARG_LINK_DIR, exist_ok=True)
        # Named from the path rather than the file, so the same file sent twice
        # under different names keeps one link each and neither shadows the
        # other. The extension is kept: every one of these emulators decides
        # what it has been handed by looking at it.
        digest = hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:12]
        link = os.path.join(ARG_LINK_DIR, digest + os.path.splitext(path)[1])

        if os.path.islink(link):
            if os.readlink(link) == path:
                return link
            os.unlink(link)
        elif os.path.exists(link):
            return link
        os.symlink(path, link)
        return link
    except OSError as error:
        decky.logger.warning("Could not link %s without spaces: %s", path, error)
        return path


def tool_argv(emulator, args, allow=(), env=None):
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

    An emulator that declares `splits_args` gets every argument that names an
    existing file replaced by a space-free link to it -- see `space_free`. Done
    here rather than at each call site because every tool call goes through this
    one function, and the three that exist for Vita3K -- a package, its
    firmware, its font package -- were each one spaced filename away from
    failing in a way that names nothing.
    """
    args = list(args)
    if emulator.get("splits_args"):
        args = [
            space_free(arg) if isinstance(arg, str) and os.path.exists(arg) else arg
            for arg in args
        ]

    if emulator.get("kind") == "flatpak":
        grants = ["--filesystem=%s" % folder for folder in allow if folder]
        # A sandbox does not inherit the caller's environment, so a variable a
        # run depends on has to be handed to `flatpak run` itself. Everything
        # outside one reads it from the process env the caller sets, which is
        # why this returns nothing for an AppImage.
        grants += ["--env=%s=%s" % (name, value) for name, value in sorted((env or {}).items())]
        grants += plugin_grants(emulator)
        return flatpak_prefix(emulator, grants) + args
    return [emulator.get("target", "")] + args


TITLE_PLACEHOLDER = "{title}"


def _effective_off(emulator, options, entry):
    """Which workarounds are switched off for one game: emulator, then its own.

    Shared by `for_game` and `retired_fixes` so the launch notice can never
    disagree with what the launch actually does -- a warning about a fix that is
    not running is worse than none.
    """
    off = set(emulator.get("workarounds_off") or ())
    for identifier, enabled in ((options or {}).get("workarounds") or {}).items():
        off.discard(identifier) if enabled else off.add(identifier)
    return off


def launch_notices(emulator, options=None):
    """What has to be said about this game's fixes as it starts.

    A fix that is switched on is either redundant or not running, and both are
    states the user asked to be in and is not. A fix that is on and working says
    nothing at all.

    The same helper the Emulators tab uses, narrowed to one game, so the two can
    never disagree about what is running -- and it shares `_effective_off` with
    `for_game`, so neither can disagree with the launch itself.
    """
    if not emulator:
        return []
    entry = emulator_catalog.find(emulator.get("id") or "")
    if not entry:
        return []
    return fix_notices(emulator, entry, options)


def for_game(emulator, options=None):
    """The emulator as *one game* will run it, with that game's choices applied.

    A workaround's cost lands per game -- reaching the Deck's sensors costs
    Steam Input for everything that emulator runs, including the many games with
    no motion at all -- so the emulator's setting is a default and a shortcut may
    differ from it. `options["workarounds"]` is `{id: bool}`, and an id absent
    from it follows the emulator rather than being off: a game that stopped
    tracking the default without saying so is the kind of thing nobody finds
    until it is confusing.

    Returns the emulator unchanged when there is nothing to decide, which is
    every emulator but the two with motion.
    """
    # A libretro core reaches the launcher writer as `None`, and a
    # hand-registered emulator matches no catalog entry. Neither has anything to
    # decide, and both used to arrive here only through paths that had already
    # checked -- which is not a thing to rely on in a helper this widely called.
    if not emulator:
        return emulator
    entry = emulator_catalog.find(emulator.get("id") or "")
    if not entry or not emulator_catalog.workarounds_for(entry):
        return emulator

    off = _effective_off(emulator, options, entry)
    effective = emulator_catalog.resolve_workarounds(entry, off)
    resolved = dict(
        emulator,
        env=dict(effective.get("env") or {}),
        layout=effective.get("layout", ""),
    )
    patched = _patched_target(emulator, entry, off)
    if patched:
        resolved["target"] = patched
    return resolved


def _patched_target(emulator, entry, off):
    """The patched build this game should run, or "" for the stock one.

    A workaround that edits the emulator's own binary is switched the same way
    every other one is -- by choosing which file the launcher execs. Both builds
    are on disk from install time, so this is a path lookup and not a thing that
    can fail halfway.

    The file is what is asked, not the record `emu_patch.refresh` wrote: the
    record says what happened at install, and a launcher needs what is true now.
    Absent means stock, which is also what a build the patch could not be
    applied to gets -- the fix is lost, the emulator is not.
    """
    stock = emu_patch.stock_path((emulator.get("target") or "").strip(), entry)
    if not stock:
        return ""
    for workaround_id, _ in emu_patch.patch_specs(entry):
        if workaround_id in set(off or ()):
            continue
        found = emu_patch.target_for(stock, workaround_id)
        if found:
            return found
    return ""


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

    return env_prefix(emulator) + [emulator.get("target", "")] + tokens
