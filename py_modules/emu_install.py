"""Installing a catalog emulator, through whichever channel it publishes on.

Two channels, and the split is not arbitrary.

**Flatpak is preferred wherever Flathub carries the emulator.** `--user` scope
needs no password, which is the only reason installing RetroArch from the panel
works at all, and the same argument applies here. It also hands updates to
flatpak, so this plugin never has to track a version, compare a tag or offer an
"update available" badge for eleven separate projects.

**GitHub releases are the fallback**, for Azahar and Vita3K, which publish no
flatpak. It is deliberately not the default: an AppImage is a file this plugin
then owns forever, and browser-downloaded AppImages arriving without an execute
bit is already the single most common way a registered emulator silently does
nothing (see `emulators.ensure_executable`).

Two things were learned building this and are worth keeping. Both Ryujinx
mirrors answer **HTTP 451** from the GitHub API -- they were taken down and now
self-host their git -- so no amount of asset-pattern work reaches a Switch
emulator that way; `io.github.ryubing.Ryujinx` on Flathub is the route
that works. And release assets carry aarch64 builds beside x86_64 ones, so the
asset pattern must be anchored rather than a substring match: installing the
wrong architecture fails at exec time with nothing that names the cause.
"""

import os
import re
import shutil

import decky

import emulator_catalog
import net
import sysenv

FLATHUB_REPO = "https://flathub.org/repo/flathub.flatpakrepo"

# Well above the largest emulator AppImage published today (Vita3K is around
# 90MB), and low enough that a redirect to something unexpected is refused
# rather than written to the user's home directory.
MAX_APPIMAGE_BYTES = 400 * 1024 * 1024


def emulators_dir(*parts, create=True):
    """Where AppImage emulators live: `~/deckyemu/emulators`.

    Under the user's own directory rather than DECKY_PLUGIN_RUNTIME_DIR, which
    decky wipes on uninstall. A libretro core is a few megabytes and trivially
    re-downloaded; a 200MB emulator that vanishes because the plugin was
    reinstalled is a different thing entirely.
    """
    return sysenv.user_dir("emulators", *parts, create=create)


def firmware_dir():
    """Where BIOS files, keys and firmware the user supplies are collected.

    Nothing here is shipped or downloaded -- these are the user's own dumps. The
    folder exists so there is somewhere to send them to that is not the ROM
    folder, and so the transfer flow has a destination to name.
    """
    return sysenv.user_dir("firmware")


# ------------------------------------------------------------------- flatpak


def flatpak_binary():
    return shutil.which("flatpak") or ""


def flatpak_install_steps(app_id):
    """Commands that install `app_id` for the current user.

    Same shape and same reasoning as `installer.retroarch_install_argv`: the
    remote is added first because a Deck that has never used flatpak has no
    flathub remote, and `--if-not-exists` makes that a no-op when it does.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    return [
        [flatpak, "remote-add", "--if-not-exists", "--user", "flathub", FLATHUB_REPO],
        [flatpak, "install", "--user", "-y", "--noninteractive", "flathub", app_id],
    ]


def flatpak_uninstall_argv(app_id):
    """Remove a user-scope flatpak. Never `--system`, for the usual reason.

    Data is always kept. Uninstalling an emulator from this panel means "I do not
    want it in my list", and destroying its saves and configuration on the way out
    is not what that says.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    return [flatpak, "uninstall", "--user", "-y", "--noninteractive", app_id]


_APP_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z][A-Za-z0-9_-]*)+$")


def _valid_app_id(app_id):
    return bool(_APP_ID_RE.match(app_id or ""))


def flatpak_installed(app_id):
    """Whether `app_id` is installed for this user.

    Read off the filesystem rather than by running `flatpak list`, because this is
    called for every catalog entry whenever the panel opens and eleven
    subprocesses per mount is not a reasonable way to answer a question the
    directory layout already answers.

    A `.var/app/<id>` directory is deliberately *not* accepted: that is left
    behind by an uninstall that kept its data, and treating it as an install is
    the same mistake `ra_detect.flatpak_scope` avoids.
    """
    if not _valid_app_id(app_id):
        return False
    home = sysenv.user_home()
    candidates = (
        os.path.join(home, ".local", "share", "flatpak", "app", app_id),
        os.path.join("/var/lib/flatpak/app", app_id),
    )
    return any(os.path.isdir(path) for path in candidates)


def flatpak_scope(app_id):
    """'user', 'system' or '' -- which install we are looking at.

    A system-scope flatpak cannot be removed without root, so the UI has to be
    able to say why the button is not there instead of showing a dead one.
    """
    if not _valid_app_id(app_id):
        return ""
    home = sysenv.user_home()
    if os.path.isdir(os.path.join(home, ".local", "share", "flatpak", "app", app_id)):
        return "user"
    if os.path.isdir(os.path.join("/var/lib/flatpak/app", app_id)):
        return "system"
    return ""


# -------------------------------------------------------------------- github

GITHUB_API = "https://api.github.com/repos/%s/releases/latest"


#: Same call against a self-hosted forge. A project taken off GitHub tends to
#: run its own, and the common ones answer the same shape at a different
#: address -- `tag_name`, `assets[].name`, `assets[].browser_download_url` --
#: so one channel covers both and only the host differs. Not named after any
#: particular forge: what is being described is the reply shape.
SELF_HOSTED_API = "https://%s/api/v1/repos/%s/releases/latest"

#: A hostname, not a URL. An entry says *which server*, and cannot point the
#: plugin at an arbitrary path on it or drop to plain HTTP.
_HOST_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


def resolve_release_asset(repo, pattern, host=""):
    """Newest release asset matching `pattern`, from GitHub or a self-hosted forge.

    `host` empty means GitHub. Anything else is a hostname running the same
    releases API, which is how a project that left GitHub stays reachable: its
    old repository answers 451 there, so no asset pattern gets near it.

    No token is used or wanted: these are other people's public repositories,
    and the plugin's own GitHub token is scoped to this project and has no
    business being sent to them.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo or ""):
        return None, "Not a valid repository name."
    if host and not _HOST_RE.match(host):
        return None, "Not a valid host name."
    api = SELF_HOSTED_API % (host, repo) if host else GITHUB_API % repo
    return _resolve_asset(api, pattern, "%s on %s" % (repo, host) if host else repo)


def resolve_github_asset(repo, pattern):
    """`resolve_release_asset` against GitHub. Kept for the bundled entries."""
    return resolve_release_asset(repo, pattern)


def _resolve_asset(api_url, pattern, label):
    payload = net.get_json(api_url)
    if payload is None:
        # 451 is what the Ryujinx mirrors answer, and "GitHub did not
        # respond" would send someone looking at their own connection.
        return None, (
            "No release came back for %s. The project may have moved off "
            "GitHub." % label
        )
    if not isinstance(payload, dict) or payload.get("message"):
        return None, payload.get("message", "Unexpected reply from %s." % label) if isinstance(
            payload, dict
        ) else "Unexpected reply from %s." % label

    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return None, "Bad asset pattern: %s" % error

    for asset in payload.get("assets") or []:
        name = asset.get("name") or ""
        if not matcher.match(name):
            continue
        url = asset.get("browser_download_url")
        if not url:
            continue
        return (
            {
                "name": name,
                "url": url,
                "tag": payload.get("tag_name") or "",
                "size": asset.get("size") or 0,
            },
            "",
        )

    return None, "No download in the latest release of %s matched what was expected." % label


def install_appimage(entry, asset, on_progress=None):
    """Download an AppImage into its own folder under `~/deckyemu/emulators`.

    Returns (path, error). A folder per emulator so a later version can replace
    the previous one without guessing which loose file belonged to what.
    """
    if not emulator_catalog.is_safe_id(entry.get("id")):
        return "", "Invalid emulator id."

    target_dir = emulators_dir(entry["id"])
    path = os.path.join(target_dir, asset["name"])

    ok, error = net.download(
        asset["url"],
        path,
        max_bytes=MAX_APPIMAGE_BYTES,
        on_progress=on_progress,
    )
    if not ok:
        return "", error or "Download failed."

    try:
        os.chmod(path, 0o755)
    except OSError as error:
        # Without the execute bit the launcher runs, exec says "Permission
        # denied", and Steam shows the game closing instantly. Fail here, where
        # it can be explained, rather than there.
        return "", "Downloaded but could not make it executable: %s" % error

    # A previous build in the same folder is now dead weight, and leaving it
    # means the folder grows by a couple of hundred megabytes per update.
    _remove_others(target_dir, keep=asset["name"])

    decky.logger.info("Installed %s to %s", entry["id"], path)
    return path, ""


def _remove_others(directory, keep):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if name == keep:
            continue
        try:
            os.remove(os.path.join(directory, name))
        except OSError as error:
            decky.logger.warning("Could not remove old build %s: %s", name, error)


def tools_dir(*parts, create=True):
    """Where helper binaries live: `~/deckyemu/tools`.

    Separate from `emulators` because these are not emulators and must not be
    listed as any: the PS4 package extractor plays nothing, it turns a .pkg into
    a folder shadPS4 can run. Same directory rules otherwise -- under the user's
    own home, so a plugin reinstall does not delete it.
    """
    return sysenv.user_dir("tools", *parts, create=create)


def installed_tool(name):
    """The helper binary installed under `name`, or ''."""
    if not emulator_catalog.is_safe_id(name):
        return ""
    directory = tools_dir(name, create=False)
    try:
        for entry in sorted(os.listdir(directory)):
            path = os.path.join(directory, entry)
            if os.path.isfile(path):
                return path
    except OSError:
        pass
    return ""


def install_tool(name, asset, on_progress=None):
    """Download a helper binary. Returns (path, error).

    Same shape as `install_appimage`, including the execute bit: a downloaded
    AppImage without it fails at exec time with nothing that names the cause.
    """
    if not emulator_catalog.is_safe_id(name):
        return "", "Invalid tool name."

    target_dir = tools_dir(name)
    path = os.path.join(target_dir, asset["name"])

    ok, error = net.download(
        asset["url"], path, max_bytes=MAX_APPIMAGE_BYTES, on_progress=on_progress
    )
    if not ok:
        return "", error or "Download failed."

    try:
        os.chmod(path, 0o755)
    except OSError as error:
        return "", "Downloaded but could not make it executable: %s" % error

    _remove_others(target_dir, keep=asset["name"])
    decky.logger.info("Installed tool %s to %s", name, path)
    return path, ""


def installed_appimage(entry_id):
    """The AppImage installed for `entry_id`, or ''."""
    if not emulator_catalog.is_safe_id(entry_id):
        return ""
    # Not created on the way past: this is a question, and answering it should
    # not leave an empty folder behind for every emulator that is not installed.
    directory = emulators_dir(entry_id, create=False)
    try:
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                return path
    except OSError:
        pass
    return ""


def remove_appimage(entry_id):
    """Delete the folder an AppImage emulator was installed into."""
    if not emulator_catalog.is_safe_id(entry_id):
        return False, "Invalid emulator id."

    # create=False matters: creating the folder on the way to deleting it makes
    # every removal "succeed", including the second one for an emulator that was
    # already gone.
    directory = emulators_dir(entry_id, create=False)
    # Refuse to delete anything that is not where we put it, so a future caller
    # passing something odd cannot turn this into a general-purpose rm -rf.
    root = os.path.normpath(emulators_dir(create=False))
    if not os.path.normpath(directory).startswith(root + os.sep):
        return False, "Refusing to remove %s" % directory

    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        return False, "Nothing was installed for that emulator."
    except OSError as error:
        return False, "Could not remove %s: %s" % (directory, error)
    return True, ""
