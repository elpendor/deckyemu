"""Run system binaries outside Steam's bundled libraries.

Decky loads plugins inside Steam's environment, which points LD_LIBRARY_PATH at
the Steam Runtime. System executables then resolve their libraries from there
instead of from the OS, and the versions do not match:

    flatpak: /usr/lib/libcrypto.so.3: version `OPENSSL_3.4.0' not found

The binary dies before doing any work, in milliseconds, with a non-zero exit and
nothing that looks like a normal error. Clearing the loader variables makes the
dynamic linker use the system paths again.

The same applies to anything Steam launches, which is why the generated launcher
scripts unset these too -- see SHELL_PREAMBLE.
"""

import os

# Variables Steam injects to redirect library loading. LD_PRELOAD is included
# because Steam's overlay preloads into it.
def user_home():
    """The user's home directory.

    The single place this is worked out. `os.path.expanduser("~")` is not enough:
    decky can run the backend as root, where it returns /root, and every path
    derived from it -- the flatpak data directory, RetroArch's config, the ROM
    picker's starting point -- would then point somewhere the user never sees.
    DECKY_USER_HOME is the loader telling us who it is really acting for.

    Resolved on each call rather than at import, so a test or a service change can
    set it and be believed.
    """
    return os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~")


USER_DIR_NAME = "deckyemu"


def user_dir(*parts, create=True):
    """A folder under `<home>/deckyemu`, created on demand.

    The plugin's user-visible working area, kept separate from
    DECKY_PLUGIN_RUNTIME_DIR (`~/homebrew/data/deckyemu`) which decky owns and
    wipes on uninstall. Anything the *user* is meant to see or keep goes here, so
    `deckyemu` itself stays a container: `transfer/` is the inbox files arrive
    in, `roms/<system>/` is where a game's ROM is moved once it is added, and
    there is room for whatever else needs a home without moving either.

    Returns the home directory if the folder cannot be created, so a caller always
    gets somewhere usable rather than a path that does not exist.
    """
    path = os.path.join(user_home(), USER_DIR_NAME, *parts)
    if create and not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            return user_home()
    return path


LOADER_VARS = (
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "LD_AUDIT",
    "GTK_PATH",
    "GIO_MODULE_DIR",
    "GST_PLUGIN_SYSTEM_PATH",
    "GST_PLUGIN_SYSTEM_PATH_1_0",
)

# Steam saves the pre-runtime value here on some setups; it is the better
# starting point when present.
_ORIGINAL_PATH_VARS = ("SYSTEM_LD_LIBRARY_PATH",)

SHELL_PREAMBLE = (
    "# Steam's runtime libraries break system binaries such as flatpak:\n"
    "#   libcrypto.so.3: version `OPENSSL_3.4.0' not found\n"
    "# Clearing these makes the dynamic linker use the system libraries.\n"
    "unset " + " ".join(LOADER_VARS)
)

# There was an `export SDL_JOYSTICK_HIDAPI=1` here, on the theory that emulators
# turning SDL's HIDAPI driver off cannot see the Deck's controller. Over SSH
# that is true -- SDL_NumJoysticks() really is 0 with HIDAPI disabled. Inside
# Steam it is not: Steam Input hides the built-in controller and publishes a
# virtual pad that SDL enumerates either way, measured from the launcher itself
# at 1 joystick with the hint on and 1 with it off.
#
# Nothing replaces it, because there is nothing to fix here. If an emulator sees
# no controller, look at how its bindings name the pad -- that is where the real
# fault was (emulator_catalog.steam_pad).


# Where gamescope writes the variables that reach the session's display. Steam
# writes this file when Game Mode starts, and it is the only place a process
# outside the session can learn how to talk to it.
GAMESCOPE_ENVIRONMENT = "/run/user/%d/gamescope-environment"

# Only display-related variables are taken. The file also carries things about
# Steam's own process that have no business being forced onto an emulator.
SESSION_KEYS = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY")


def session_env(path=None):
    """Display variables for the running Game Mode session, or {}.

    Some emulators refuse to start without a display even when asked to do
    something that draws nothing: Vita3K's Qt aborts with "could not connect to
    display" before it has looked at its arguments, so installing firmware from
    the panel needs this even though nothing appears on screen.

    Empty is a normal answer -- Desktop Mode, or a plugin started before Steam
    wrote the file -- and callers should carry on without it.
    """
    try:
        path = path or GAMESCOPE_ENVIRONMENT % os.getuid()
    except AttributeError:
        # No getuid on Windows, where the tests run.
        return {}

    found = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip()
                if name in SESSION_KEYS:
                    found[name] = value.strip().strip("'\"")
    except OSError:
        return {}
    return found


def directory_bytes(path):
    """How much a folder occupies. Missing or unreadable counts as nothing.

    Shared because both console modules need it for the same sentence: a delete
    dialog that says "240 MB" rather than "some files".
    """
    total = 0
    for base, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                continue
    return total


def flatpak_roots():
    """Where flatpak keeps installed applications: (system, user).

    A function rather than a constant, and that is not style. As a constant this
    used `os.path.expanduser("~")` evaluated at import time, which ignores
    DECKY_USER_HOME and freezes the per-user root at whatever home the backend
    process happened to have -- running as root it looked in /root and reported
    everything as absent.
    """
    return (
        "/var/lib/flatpak",
        os.path.join(user_home(), ".local", "share", "flatpak"),
    )


def flatpak_deployed(root, app_id):
    """Whether `<root>/app/<app_id>` is a deployment flatpak still owns.

    The directory existing is not enough, and the gap is not theoretical. A
    `flatpak update --commit=` that fails partway leaves the commit trees where
    they are while the ref goes: `flatpak info` then reports the application as
    not installed, `flatpak uninstall` answers "no installed refs found", and
    the files stay. Read as an install, that husk is permanent -- the panel goes
    on offering Remove for an emulator that is not there, every press fails, and
    nothing in the plugin can ever take the row away. That is what happened to
    DuckStation after a version switch failed with "Directory not empty".

    What flatpak itself follows is the symlinks: `<id>/current` pointing at the
    arch and branch in use, and `<id>/<arch>/<branch>/active` at the deployed
    commit. A husk has neither, only the commit directories. `current` first,
    because this is asked for every catalog entry each time the panel opens and
    the usual answer should cost one stat.

    `lexists` rather than `exists` throughout: these are symlinks, and one left
    dangling still says flatpak deployed something here.
    """
    base = os.path.join(root, "app", app_id)
    if os.path.lexists(os.path.join(base, "current")):
        return True
    # No `current` also describes an install for an architecture that is not the
    # default one, so the branches are worth walking before answering no.
    try:
        for arch in os.listdir(base):
            branches = os.path.join(base, arch)
            if not os.path.isdir(branches):
                continue
            for branch in os.listdir(branches):
                if os.path.lexists(os.path.join(branches, branch, "active")):
                    return True
    except OSError:
        return False
    return False


def clean_env(base=None):
    """A copy of the environment with Steam's library redirection removed."""
    env = dict(base if base is not None else os.environ)

    for name in LOADER_VARS:
        env.pop(name, None)

    # If Steam preserved the original search path, put it back rather than
    # leaving the variable unset entirely.
    for name in _ORIGINAL_PATH_VARS:
        original = env.get(name)
        if original:
            env["LD_LIBRARY_PATH"] = original
            break

    return env
