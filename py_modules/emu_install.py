"""Installing a catalog emulator, through whichever channel it publishes on.

Two channels, and the split is not arbitrary.

**Flatpak is preferred wherever Flathub carries the emulator.** `--user` scope
needs no password, which is the only reason installing RetroArch from the panel
works at all, and the same argument applies here. It also means this plugin never
tracks a version of its own: updating, going back to a past build and pinning one
are all questions flatpak already answers about its own installs, so they are
asked rather than reimplemented.

**GitHub releases are the fallback**, for RPCS3, Azahar and Vita3K, which publish
no flatpak. It is deliberately not the default: an AppImage is a file this plugin
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

import json
import os
import re
import shutil
import subprocess

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


def flatpak_uninstall_argv(app_id, delete_data=False):
    """Remove a user-scope flatpak. Never `--system`, for the usual reason.

    Data is kept unless asked for. Uninstalling an emulator from this panel
    normally means "I do not want it in my list", and destroying saves and
    configuration on the way out is not what that says -- so `--delete-data` is
    a separate answer to a separate question, defaulted off, exactly as it is
    for RetroArch.

    What it removes is `~/.var/app/<id>` entire: configuration, saves, save
    states, memory cards, and anything the emulator unpacked into itself.
    Nothing else brings the emulator back to never-installed, which is why the
    option exists at all -- without it a reinstall inherits whatever the last
    one left, and flatpak keeps that directory even when the application is
    gone.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    argv = [flatpak, "uninstall", "--user", "-y", "--noninteractive"]
    if delete_data:
        argv.append("--delete-data")
    argv.append(app_id)
    return argv


_APP_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(\.[A-Za-z][A-Za-z0-9_-]*)+$")


def _valid_app_id(app_id):
    return bool(_APP_ID_RE.match(app_id or ""))


#: An OSTree commit. Checked before it reaches a command line, for the same
#: reason `_valid_app_id` is: both arrive from the frontend.
_COMMIT_RE = re.compile(r"^[0-9a-f]{64}$")


def valid_commit(commit):
    return bool(_COMMIT_RE.match(commit or ""))


def flatpak_update_argv(app_id):
    """Update one user-scope flatpak to the newest build on its remote."""
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    return [flatpak, "update", "--user", "-y", "--noninteractive", app_id]


def flatpak_downgrade_argv(app_id, commit):
    """Deploy one specific past build.

    `flatpak update --commit=` is the documented way back, and it is an *update*
    rather than a separate verb -- flatpak treats "move this app to that commit"
    as one operation in both directions.

    Refuses a commit that is not a bare hash. This value comes from the frontend,
    which read it from `flatpak_history`, and a command line is the wrong place to
    find out that something else arrived.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id) or not valid_commit(commit):
        return []
    return [
        flatpak, "update", "--user", "-y", "--noninteractive",
        "--commit=%s" % commit, app_id,
    ]


def flatpak_hold_argv(app_id, held):
    """Pin an app at its current build, or release it.

    Load-bearing rather than a nicety. Without a mask the next update -- ours, or
    anything else on the device that runs one -- silently undoes a downgrade, so
    somebody rolls back, plays fine, and finds the same game broken a week later
    with nothing to connect it to. A version this plugin was asked to go back to
    has to be a version it will not move again.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    if held:
        return [flatpak, "mask", "--user", app_id]
    return [flatpak, "mask", "--user", "--remove", app_id]


def _flatpak_lines(args, timeout=60):
    """Run a read-only flatpak query and return its stdout lines.

    Its own helper because every one of these is the same shape and the same three
    failure modes -- no flatpak, a non-zero exit, a timeout -- none of which is
    exceptional enough to raise over. An empty list means "could not tell", which
    every caller has to treat as different from "nothing found".
    """
    flatpak = flatpak_binary()
    if not flatpak:
        return []
    try:
        done = subprocess.run(
            [flatpak] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=sysenv.clean_env(),
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    return done.stdout.decode("utf-8", errors="replace").splitlines()


# The parsers are separate from the commands that produce their input, so the
# suite can hold flatpak's real output against them without a device or a
# subprocess. That is where the risk is: these formats are what they are, and a
# parser written from the documentation is one that works until it meets the tool.


def _parse_ids(lines):
    """App ids out of a one-per-line listing."""
    found = set()
    for line in lines:
        app_id = line.strip().split("\t")[0].strip()
        if _valid_app_id(app_id):
            found.add(app_id)
    return found


#: Fields worth reading out of `remote-info` for one build. `download` is the
#: one that changes a decision: switching build re-fetches the whole app, and
#: 409MB is a different proposition on a handheld from a config tweak.
_DETAIL_KEYS = ("version", "license", "download", "installed", "subject", "date",
                "commit", "parent")


def _clean_value(value):
    """One field's value, with flatpak's formatting made safe to display.

    Sizes are printed with a narrow no-break space between the number and the
    unit, and flatpak substitutes `?` for it when it runs without a UTF-8 locale
    -- which is how it runs from here, since the plugin does not inherit a login
    shell. Both forms become a plain space, so "409.0?MB" and "409.0 MB"
    read the same on screen.
    """
    value = re.sub(r"(?<=\d)(\?|[^\x20-\x7e])(?=[A-Za-z])", " ", value)
    value = re.sub(r"[^\x20-\x7e]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_fields(lines):
    """`remote-info`'s labelled lines as a dict, for the fields worth showing.

    First occurrence wins. The header repeats the app's name and description
    above the fields, and a `Subject:` further down belongs to the build rather
    than to anything above it.
    """
    found = {}
    for line in lines:
        label, sep, value = line.partition(":")
        if not sep:
            continue
        key = label.strip().lower()
        if key in _DETAIL_KEYS and key not in found:
            found[key] = _clean_value(value)
    return found


def flatpak_build_details(app_id, commit):
    """Everything flatpak knows about one build. Empty when it cannot be read.

    Deliberately not part of `flatpak_history`: this is a call per build, and the
    list is drawn before anybody has said which one they are interested in.
    """
    if not _valid_app_id(app_id) or not valid_commit(commit):
        return {}
    return _parse_fields(
        _flatpak_lines(
            ["remote-info", "--user", "flathub", app_id, "--commit=%s" % commit],
            timeout=90,
        )
    )


def _parse_commit(lines):
    """The `Commit:` value out of `flatpak info`, or ''."""
    for line in lines:
        label, _, value = line.partition(":")
        if label.strip().lower() == "commit":
            candidate = value.strip()
            # A truncated hash is what `--columns` prints and `--commit=` will
            # not take, so half an answer is worse than none.
            return candidate if valid_commit(candidate) else ""
    return ""


def _parse_history(lines, limit=12):
    """`{commit, date, subject}` per build out of `remote-info --log`."""
    builds = []
    current = {}
    for line in lines:
        label, sep, value = line.partition(":")
        if not sep:
            continue
        key = label.strip().lower()
        value = value.strip()
        if key == "commit":
            # Every Commit line starts a record, including the first -- which
            # describes the newest build rather than a past one, so the whole
            # list is the menu and not its tail.
            if current.get("commit"):
                builds.append(current)
            current = {"commit": value if valid_commit(value) else "", "date": "", "subject": ""}
        elif key in ("date", "subject") and current:
            current[key] = value
    if current.get("commit"):
        builds.append(current)

    return [build for build in builds if build["commit"]][:limit]


def flatpak_hold(app_id, held):
    """Pin `app_id` at its current build, or release it. Returns (ok, message).

    Run and waited for rather than streamed: masking is instantaneous, and a
    progress bar for it would be a bar that appears and vanishes. The output is
    kept because a mask that did not take must not read as one that did -- the
    whole value of holding is that somebody can trust the version stopped moving.
    """
    argv = flatpak_hold_argv(app_id, held)
    if not argv:
        return False, "flatpak is not available on this system."
    try:
        done = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=sysenv.clean_env(),
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, "Could not run flatpak: %s" % error

    text = done.stdout.decode("utf-8", errors="replace").strip()
    for line in text.splitlines():
        decky.logger.info("flatpak: %s", line)
    if done.returncode != 0:
        lines = [line for line in text.splitlines() if line.strip()]
        return False, lines[-1] if lines else "flatpak exited with %d" % done.returncode
    return True, ""


def flatpak_updates():
    """App ids with a newer build waiting, as a set.

    One command for every app rather than one per app. `remote-info` costs about
    two seconds each -- which is flatpak's own startup, not the network -- so
    asking per emulator would be fourteen seconds to draw one tab.

    Compares commits, not version strings, and that distinction is not academic:
    RetroArch was observed offering an update whose `Version:` was character for
    character the one already installed. Anything keyed on the version would have
    called that up to date. flatpak does the comparing here, which is the reason
    to ask it rather than work it out.

    Runtimes and extensions come back in the same listing. Callers intersect with
    ids they already know, so this is deliberately not "things to update".
    """
    return _parse_ids(
        _flatpak_lines(
            ["remote-ls", "--user", "--updates", "flathub", "--columns=application"]
        )
    )


def flatpak_held():
    """App ids pinned against updates, as a set."""
    return _parse_ids(_flatpak_lines(["mask", "--user"]))


def flatpak_installed_commit(app_id):
    """The commit currently deployed for `app_id`, or ''."""
    if not _valid_app_id(app_id):
        return ""
    return _parse_commit(_flatpak_lines(["info", "--user", app_id]))


def flatpak_history(app_id, limit=12):
    """Past builds available on the remote, newest first.

    The remote keeps this, which is what makes going back possible at all --
    including to a build this device never had, since the local copy of an old one
    is pruned as soon as it is replaced.

    The date and subject are the point. A list of hashes is not something anybody
    can choose from with a controller; "2026-07-26 -- Install metainfo to
    share/metainfo" is.
    """
    if not _valid_app_id(app_id):
        return []
    return _parse_history(
        _flatpak_lines(["remote-info", "--user", "--log", "flathub", app_id], timeout=90),
        limit=limit,
    )


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


#: Releases rather than only the newest one, for choosing a build to go back to.
GITHUB_RELEASES = "https://api.github.com/repos/%s/releases"
SELF_HOSTED_RELEASES = "https://%s/api/v1/repos/%s/releases"

#: A release tag on its way to becoming a folder-free download URL. Tags are the
#: projects' own strings, so this is deliberately permissive about shape and
#: strict about characters -- it arrives from the frontend like a commit does.
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def valid_tag(tag):
    return bool(_TAG_RE.match(tag or ""))


def resolve_release_list(repo, pattern, host="", limit=12):
    """Recent releases carrying an asset that matches, newest first.

    Returns (builds, error). Each build is {tag, name, url, size, published}.

    Separate from `resolve_release_asset` because the questions differ: that one
    asks "what should I install", which is always the newest, while this one asks
    "what else is there", which is only ever asked once somebody has decided to
    move. Releases without a matching asset are skipped rather than listed as
    unavailable -- an aarch64-only release is not a build this device can choose.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo or ""):
        return [], "Not a valid repository name."
    if host and not _HOST_RE.match(host):
        return [], "Not a valid host name."

    api = SELF_HOSTED_RELEASES % (host, repo) if host else GITHUB_RELEASES % repo
    label = "%s on %s" % (repo, host) if host else repo
    failure = {}
    payload = net.get_json(api, failure=failure)
    if not isinstance(payload, list):
        # Same reasoning as `_resolve_asset`: the build list is the other place
        # a rate limit surfaced as a claim about the project having moved.
        return [], (
            net.failure_message(failure, "the builds of %s" % label)
            or "No releases came back for %s. The project may have moved off "
               "GitHub." % label
        )

    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return [], "Bad asset pattern: %s" % error

    builds = []
    for release in payload:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name") or ""
        if not valid_tag(tag):
            continue
        for asset in release.get("assets") or []:
            name = asset.get("name") or ""
            url = asset.get("browser_download_url")
            if not url or not matcher.match(name):
                continue
            builds.append({
                "tag": tag,
                "name": name,
                "url": url,
                "size": asset.get("size") or 0,
                "published": (release.get("published_at") or "")[:10],
                "prerelease": bool(release.get("prerelease")),
            })
            break
        if len(builds) >= limit:
            break
    if not builds:
        return [], "No release of %s carries a download this device can use." % label
    return builds, ""


def resolve_github_asset(repo, pattern):
    """`resolve_release_asset` against GitHub. Kept for the bundled entries."""
    return resolve_release_asset(repo, pattern)


def _resolve_asset(api_url, pattern, label):
    failure = {}
    payload = net.get_json(api_url, failure=failure)
    if payload is None:
        # Which failure it was decides what to say, and saying the wrong one is
        # worse than saying little: a rate-limited address was reported as the
        # project having moved off GitHub, which is a confident wrong answer
        # about somebody else's repository and sends the reader nowhere useful.
        # It cost an evening on xemu's hard disk image, which was never missing.
        #
        # 451 is what the Ryujinx mirrors answer and it has no status branch of
        # its own, so it falls to the line below -- which is still the right
        # thing for it, and better than blaming the connection.
        return None, (
            net.failure_message(failure, "the latest release of %s" % label)
            or "No release came back for %s. The project may have moved off "
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

    # After the cleanup, or it would be swept away with the old build. Written
    # even when the tag is empty: "installed, build unknown" is a different state
    # from "not installed", and only a record can tell them apart.
    write_build_record(entry["id"], asset.get("tag", ""), asset["name"])

    decky.logger.info("Installed %s to %s", entry["id"], path)
    return path, ""


def _remove_others(directory, keep):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        # The record describes the build being kept, so it survives too. It is
        # rewritten immediately after this either way; deleting it here would
        # only widen the window where an interrupted install looks unknown.
        if name in (keep, BUILD_RECORD):
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


#: What was installed, written beside the AppImage it describes.
#:
#: In the emulator's own folder rather than the settings directory so it travels
#: with the install: decky owns the settings directory and clears it on
#: uninstall, and an emulator whose build became unknown because the plugin was
#: reinstalled is exactly the case this exists to avoid.
BUILD_RECORD = ".build.json"


def build_record_path(entry_id):
    return os.path.join(emulators_dir(entry_id, create=False), BUILD_RECORD)


def read_build_record(entry_id):
    """{tag, asset} for an installed AppImage, or {} when it is not known.

    Empty is a real answer and not an error. Anything installed before this was
    recorded has no record, and reporting that honestly is what stops the panel
    claiming a build it cannot actually identify.
    """
    if not emulator_catalog.is_safe_id(entry_id):
        return {}
    try:
        with open(build_record_path(entry_id), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def write_build_record(entry_id, tag, asset_name):
    """Record which release an AppImage came from. Best effort."""
    if not emulator_catalog.is_safe_id(entry_id):
        return
    try:
        with open(build_record_path(entry_id), "w", encoding="utf-8") as handle:
            json.dump({"tag": tag or "", "asset": asset_name or ""}, handle, indent=2)
    except OSError as error:
        # Not fatal: the emulator is installed and runs. What is lost is the
        # ability to say which build it is, which degrades to "unknown".
        decky.logger.warning("Could not record the build of %s: %s", entry_id, error)


def installed_appimage(entry_id):
    """The AppImage installed for `entry_id`, or ''."""
    if not emulator_catalog.is_safe_id(entry_id):
        return ""
    # Not created on the way past: this is a question, and answering it should
    # not leave an empty folder behind for every emulator that is not installed.
    directory = emulators_dir(entry_id, create=False)
    try:
        for name in sorted(os.listdir(directory)):
            # The build record lives in here too, and sorts first because it
            # starts with a dot -- so without this every emulator would report
            # its metadata file as the binary to run.
            if name == BUILD_RECORD:
                continue
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
