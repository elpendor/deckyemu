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
import time
import zipfile

import decky

import emu_patch
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


def flatpak_files_dir(app_id):
    """The deployed `files/` tree of an installed flatpak, or "".

    `<root>/app/<id>/current/active/files` -- the same symlinks
    `sysenv.flatpak_deployed` follows, one level further in, so what comes back
    is whatever build is installed right now rather than a path recorded when it
    was.
    """
    if not _valid_app_id(app_id):
        return ""
    for root in sysenv.flatpak_roots():
        if not sysenv.flatpak_deployed(root, app_id):
            continue
        files = os.path.join(root, "app", app_id, "current", "active", "files")
        if os.path.isdir(files):
            return files
    return ""


def seed_bundled_files(app_id, seed):
    """Copy files a flatpak ships into the place its application looks for them.

    For the case where those are not the same place. Supermodel is why this
    exists and states the problem exactly: the Flathub build installs its
    `Assets` to `/app/bin/Assets`, while `FileSystemPath::GetPath(Assets)`
    resolves under the application's own data directory, and nothing bridges the
    two. The result is not a degraded feature -- `CCrosshair::Init` loads both
    crosshair bitmaps unconditionally, whatever the crosshair setting, and
    aborts the program when it cannot. So a stock install launches every game,
    prints "Unable to load bitmap crosshair texture", and exits before the
    emulator is built. There is no flag for it, unlike `Games.xml`, which has
    the same fault and can at least be pointed at the packaged copy.

    Only what is missing is copied, so a file the user replaced is theirs and
    stays. Only regular files directly inside the source directory: this is for
    small data an application ships beside itself, and a recursive copy of an
    arbitrary tree is a bigger promise than anything needs.

    Returns (paths copied, error).
    """
    if not seed:
        return [], ""
    files = flatpak_files_dir(app_id)
    if not files:
        return [], "%s is not installed" % app_id

    copied = []
    for source, destination in sorted(seed.items()):
        origin = os.path.join(files, *source.split("/"))
        target = os.path.join(sysenv.user_home(), *destination.split("/"))
        if not os.path.isdir(origin):
            # The package moved its data, which is a thing to say rather than a
            # thing to fail over: everything else about the install is fine, and
            # the emulator may well have been fixed upstream.
            decky.logger.warning(
                "%s ships no %s to seed from", app_id, source)
            continue
        try:
            os.makedirs(target, exist_ok=True)
            for name in sorted(os.listdir(origin)):
                one = os.path.join(origin, name)
                if not os.path.isfile(one):
                    continue
                landing = os.path.join(target, name)
                if os.path.exists(landing):
                    continue
                shutil.copyfile(one, landing)
                copied.append(landing)
        except OSError as error:
            return copied, "could not place %s: %s" % (source, error)

    if copied:
        decky.logger.info("Seeded %d file(s) %s ships but does not find",
                          len(copied), app_id)
    return copied, ""


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


def installed_build(entry):
    """Which build of `entry` is installed, as something comparable, or "".

    The one fact that lets a notice about an emulator be *observed* rather than
    believed. A workaround names the build that fixed it; without knowing what
    is actually on this Deck, saying "no longer needed" is a claim about
    somebody's install made from a plugin release, and it is wrong for everyone
    who updated the plugin and not the emulator.

    Empty is a real answer and the important one: it means we cannot tell, and
    nothing is then claimed. An install predating the build record has none, and
    a rolling release with no version to compare is the same case.
    """
    source = (entry or {}).get("source") or {}
    if source.get("kind") == "flatpak":
        app_id = source.get("id") or ""
        if not _valid_app_id(app_id):
            return ""
        for line in _flatpak_lines(["info", "--user", app_id]):
            label, sep, value = line.partition(":")
            if sep and label.strip().lower() == "version":
                return _clean_value(value)
        return ""
    return str(read_build_record(entry.get("id") or "").get("tag") or "")


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
    the same mistake `ra_detect.flatpak_scope` avoids. Nor is the deploy
    directory alone -- a failed operation leaves one standing with nothing
    deployed in it, and `sysenv.flatpak_deployed` is what tells the two apart.
    """
    if not _valid_app_id(app_id):
        return False
    return any(sysenv.flatpak_deployed(root, app_id) for root in sysenv.flatpak_roots())


def flatpak_scope(app_id):
    """'user', 'system' or '' -- which install we are looking at.

    A system-scope flatpak cannot be removed without root, so the UI has to be
    able to say why the button is not there instead of showing a dead one.
    """
    if not _valid_app_id(app_id):
        return ""
    system_root, user_root = sysenv.flatpak_roots()
    if sysenv.flatpak_deployed(user_root, app_id):
        return "user"
    if sysenv.flatpak_deployed(system_root, app_id):
        return "system"
    return ""


#: What flatpak says when asked to remove something it does not have.
#:
#: Matched rather than inferred from the exit code, which is the same 1 as
#: every other failure. The distinction is worth making because "there was
#: nothing to remove" is the goal already met, and reporting it as a failed
#: removal is what leaves somebody pressing a button that can never work.
_NOTHING_INSTALLED = re.compile(r"no installed refs? found", re.I)


def nothing_to_uninstall(error):
    """Whether a failed `flatpak uninstall` failed only by having no work."""
    return bool(_NOTHING_INSTALLED.search(error or ""))


def remove_flatpak_husk(app_id):
    """Delete a deploy directory flatpak has disowned. Returns bytes freed.

    The leftover of an operation that failed partway: the commit trees are
    still on disk, with no `current` and no `active` pointing at any of them,
    so flatpak considers the application not installed and will neither run it
    nor remove it. Two full deploys of DuckStation sat there that way.

    Guarded on flatpak having disowned it rather than on the uninstall having
    just run, because that guard is what makes deleting inside flatpak's own
    store safe: with nothing deployed there is nothing for flatpak to be using,
    and a real install -- mid-download included, since the ref is written
    first -- is left alone.
    """
    if not _valid_app_id(app_id):
        return 0
    freed = 0
    # The user's own installation only. A system one belongs to root, and the
    # plugin could not have created that mess or be trusted to tidy it.
    _system, user_root = sysenv.flatpak_roots()
    if sysenv.flatpak_deployed(user_root, app_id):
        return 0
    path = os.path.join(user_root, "app", app_id)
    if not os.path.isdir(path):
        return 0
    freed = sysenv.directory_bytes(path)
    try:
        shutil.rmtree(path)
    except OSError as error:
        decky.logger.warning("Could not remove the leftover %s: %s", path, error)
        return 0
    decky.logger.info("Removed the leftover deploy directory %s (%d bytes)", path, freed)
    return freed


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


def resolve_release_asset(repo, pattern, host="", failure=None):
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
    return _resolve_asset(api, pattern, "%s on %s" % (repo, host) if host else repo,
                          failure=failure)


#: Releases rather than only the newest one, for choosing a build to go back to.
GITHUB_RELEASES = "https://api.github.com/repos/%s/releases"
SELF_HOSTED_RELEASES = "https://%s/api/v1/repos/%s/releases"

#: A release tag on its way to becoming a folder-free download URL. Tags are the
#: projects' own strings, so this is deliberately permissive about shape and
#: strict about characters -- it arrives from the frontend like a commit does.
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def valid_tag(tag):
    return bool(_TAG_RE.match(tag or ""))


def resolve_release_list(repo, pattern, host="", limit=30):
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
    if not host:
        # GitHub returns 30 releases by default. That was every release anybody
        # cared about while emulators tagged a handful a year -- Vita3K-builds
        # publishes one per build, several a week, so 30 was about a fortnight.
        api += "?per_page=100"
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


def _resolve_asset(api_url, pattern, label, failure=None):
    # The caller may want the reply's details as well as the message -- a rate
    # limit carries the moment it lifts, which is the difference between backing
    # off correctly and guessing.
    failure = {} if failure is None else failure
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

    # Patched builds are derived from the build that was just installed, and the
    # cleanup above has already taken the previous ones -- which is the point.
    # A patched copy of yesterday's build left beside today's would be an
    # emulator that silently stopped updating.
    #
    # Deliberately not part of the install's success: a build this patch does
    # not fit still installs and still runs, and `emu_patch.unapplied` is how
    # the panel says the fix could not be applied to it.
    emu_patch.refresh(entry, path)

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
        path = os.path.join(directory, name)
        try:
            # Patching unpacks a 186MB tree beside the build. It clears up after
            # itself, but a kill in the middle leaves one behind, and a
            # directory here is otherwise a warning on every install forever.
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
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


def _extract_tool(archive, destination, pattern):
    """Pull one file out of a downloaded zip by basename. Returns (path, error).

    Members are written by basename into `destination`, never by the path the
    archive carries: this is fetched over the network, and `extractall` would
    honour a directory inside it. Same rule, and the same reason, as the
    firmware unpacker.

    One file, because a tool is one binary. An archive matching the pattern
    twice is a pattern that does not say what was meant, and taking the first of
    them would decide it silently.
    """
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = os.path.basename(info.filename)
                if info.is_dir() or not name or not matcher.match(name):
                    continue
                found.append(info)
        if len(found) != 1:
            return "", ("The download did not contain what was expected."
                        if not found else
                        "The download contained %d files matching %r; expected "
                        "one." % (len(found), pattern))
        target = os.path.join(destination, os.path.basename(found[0].filename))
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open(found[0]) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return "", "Could not unpack the download: %s" % error
    return target, ""


def install_tool(name, asset, on_progress=None, extract=""):
    """Download a helper binary. Returns (path, error).

    Same shape as `install_appimage`, including the execute bit: a downloaded
    AppImage without it fails at exec time with nothing that names the cause.

    `extract` names the member to keep when the release ships a zip rather than
    a bare binary -- which is the only shape some projects publish. The archive
    is deleted once the file is out of it, so `installed_tool` cannot answer
    with it: that returns the first file in the directory, and a leftover zip
    sorting before the binary would be handed to a launcher as the tool.
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

    if extract:
        member, error = _extract_tool(path, target_dir, extract)
        try:
            os.remove(path)
        except OSError:
            pass
        if error:
            return "", error
        path = member

    try:
        os.chmod(path, 0o755)
    except OSError as error:
        return "", "Downloaded but could not make it executable: %s" % error

    _remove_others(target_dir, keep=os.path.basename(path))
    decky.logger.info("Installed tool %s to %s", name, path)
    return path, ""


def motion_server(entry):
    """The installed motion server for a catalog entry, or ''.

    Its own function because two callers must agree: the launcher writer, which
    starts it beside the emulator, and whatever offers to fetch it. An emulator
    with no `motion` block, or one whose server has not been downloaded yet,
    answers '' -- and a launcher written then is the ordinary one, so motion is
    the only thing missing rather than the game.
    """
    server = ((entry or {}).get("motion") or {}).get("server") or {}
    name = server.get("name") or ""
    return installed_tool(name) if name else ""


#: When it is worth asking GitHub about a motion server again, by tool name.
#:
#: **Because the same file is wanted by more than one emulator, and the startup
#: check runs more than once.** Two emulators share one server, and the routine
#: that calls this runs on every `get_status` -- so a Deck with both installed
#: asked GitHub four times in under a second for one binary, against an
#: unauthenticated budget of sixty an hour for the whole address. That budget is
#: shared with everything else on the network, so spending it four at a time on
#: a question already answered is how a download fails for somebody who was
#: never near the limit.
#:
#: In memory rather than on disk: the point is to stop a burst, and a plugin
#: reload is a fine moment to try again.
_MOTION_RETRY_AFTER = {}


def motion_configured(entry):
    """Whether the emulator itself is pointed at the motion server.

    **The binary being present is not the same as motion working, and the gap is
    silent.** `emu_config` refuses to write a file the user has made their own,
    which is right -- but it means somebody who configured their controller by
    hand keeps their config and gets no motion, with nothing saying so. Cemu is
    where this bites: its profile is supplied whole, so one save in its own
    controller settings takes ownership of the file for good.

    Answers True when there is nothing to check, so an emulator that declares no
    verification is never reported as misconfigured.
    """
    verify = ((entry or {}).get("motion") or {}).get("verify") or {}
    path, needle = verify.get("path"), verify.get("contains")
    if not path or not needle:
        return True
    full = os.path.join(sysenv.user_home(), *path.split("/"))
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as handle:
            return needle in handle.read()
    except OSError:
        # No file yet is not "misconfigured": the emulator has not run and the
        # settings pass has not reached it. Saying otherwise would report every
        # fresh install as broken.
        return True


def motion_state(entry, now=None):
    """What the panel says about this emulator's motion server.

    **Because nothing said anything, and that is how it went wrong once.** The
    server is fetched quietly and a failure only reached the log, so a Deck
    where GitHub had rate-limited the download looked identical to one where
    motion simply did not work -- and the only way to tell them apart was to
    read a log file over SSH. An emulator that needs a second file has to be
    able to say whether it has it, the same way a firmware requirement does.

    `waiting` is seconds until the next attempt, and it is the difference
    between "this is broken" and "this is coming": a rate-limited address fixes
    itself, and saying when turns a dead end into a wait.
    """
    server = ((entry or {}).get("motion") or {}).get("server") or {}
    name = server.get("name") or ""
    if not name:
        # Same shape whatever the answer, so a caller never has to ask which
        # keys exist before reading them.
        return {"declared": False, "ready": False, "configured": True, "waiting": 0}
    now = time.time() if now is None else now
    installed = bool(installed_tool(name))
    return {
        "declared": True,
        "ready": installed,
        # Only asked once the binary is here: before that the emulator not being
        # pointed at it is expected, and two faults where there is one reads as
        # a bigger problem than it is.
        "configured": motion_configured(entry) if installed else True,
        "waiting": max(0, int(_MOTION_RETRY_AFTER.get(name, 0.0) - now)),
    }


def ensure_motion_server(entry, now=None):
    """Fetch this emulator's motion server if it is not here yet. (path, error).

    Called from two places on purpose. Installing the emulator is the obvious
    one; startup is the one that matters, because an emulator installed before
    this existed would otherwise never get it, and there is no moment a user
    would think to ask for a file they have not been told about.

    **An error here is never fatal to anything.** What is lost is motion in an
    emulator that has never had it, and every caller carries on -- the same
    trade the launcher makes when the binary is missing at launch time.

    **A failure is remembered for a while, and a rate limit until it lifts.**
    GitHub says when its budget resets, so that is what is waited for rather
    than a number chosen here; anything else backs off briefly, which is enough
    to turn a burst into one attempt.
    """
    server = ((entry or {}).get("motion") or {}).get("server") or {}
    name = server.get("name") or ""
    if not name:
        return "", ""
    existing = installed_tool(name)
    if existing:
        return existing, ""

    now = time.time() if now is None else now
    until = _MOTION_RETRY_AFTER.get(name, 0.0)
    if now < until:
        return "", ""

    failure = {}
    asset, error = resolve_release_asset(server["repo"], server["asset"], failure=failure)
    if not asset:
        reset = net.rate_limit_reset(failure, now)
        _MOTION_RETRY_AFTER[name] = reset or (now + 300.0)
        return "", error or "No matching release asset."

    path, error = install_tool(name, asset, extract=server.get("extract", ""))
    if error:
        _MOTION_RETRY_AFTER[name] = now + 300.0
    return path, error


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


#: What the newest release of each AppImage emulator was, the last time somebody
#: asked. Beside the build record rather than in it: the record says what *this
#: device installed*, which is a fact about the install and must survive a failed
#: network call, while this says what the *project has published*, which is a
#: fact about somebody else's repository and is stale the moment it is written.
#:
#: In the settings directory, not the emulator's folder, because it is exactly
#: the thing that may be thrown away: losing it costs one press of the check
#: button, and losing the build record costs the ability to name the build at
#: all.
LATEST_TAGS = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "latest-tags.json")


def read_latest_tags():
    """{entry_id: tag} from the last update check, or {}.

    No timestamp, deliberately. A cached answer does not go wrong with age: the
    only thing that changes it is installing the update, and that rewrites the
    build record, which flips the comparison to "current" on its own. What a
    stale entry costs is a *newer* update going unnoticed until the next check,
    which is what the button is for.
    """
    try:
        with open(LATEST_TAGS, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
    except (OSError, ValueError):
        return {}
    return cached if isinstance(cached, dict) else {}


def write_latest_tags(tags):
    """Best effort. A cache that cannot be written costs a repeated check."""
    try:
        os.makedirs(os.path.dirname(LATEST_TAGS), exist_ok=True)
        with open(LATEST_TAGS, "w", encoding="utf-8") as handle:
            json.dump(tags, handle, indent=2)
    except OSError as error:
        decky.logger.warning("Could not record the latest tags: %s", error)


def latest_tag(entry):
    """The newest published tag for one AppImage emulator, or ('', reason).

    One network call. **Never call this per row or per tab open** -- that is the
    whole reason the answer is cached in a file and asked for by a button. Four
    catalog entries install from a release, so a check is four calls at worst,
    and none of them is a call anybody is waiting on a screen for.
    """
    source = entry.get("source") or {}
    if source.get("kind") != "github":
        return "", ""
    asset, error = resolve_release_asset(
        source.get("repo", ""), source.get("asset", ""), source.get("host", "")
    )
    if not asset:
        return "", error or "Could not read the latest release."
    return asset.get("tag", ""), ""


def update_state(installed_tag, published_tag):
    """"available", "current", or "unknown" for one AppImage emulator.

    **Unknown is the answer whenever either side is missing**, and it is a
    different answer from "current" rather than a softer version of it. An
    install made before the build record existed has no tag of its own, and a
    check that never ran -- or ran and failed -- has nothing published to compare
    it with. Both were previously reported as no update available, which is a
    claim the plugin was in no position to make: it reads as "you are up to date"
    and is the reason this function exists as its own named thing.

    String equality, not version ordering. These are the projects' own tags --
    `v0.9.1`, `2026-08-10`, `4074`, `canary_experimental` -- and there is no
    ordering that is right for all of them. Equality only ever claims the two
    are the same build, which is true whatever the shape.
    """
    if not installed_tag or not published_tag:
        return "unknown"
    return "current" if installed_tag == published_tag else "available"


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


def remove_tool(name):
    """Delete an installed helper binary. Returns (removed, error).

    Only ever inside `tools_dir`, and only a directory this plugin made: the
    name is checked the same way it is on the way in, so a name from the
    frontend cannot name a path.
    """
    if not emulator_catalog.is_safe_id(name):
        return False, "Invalid tool name."
    directory = tools_dir(name, create=False)
    if not os.path.isdir(directory):
        return False, ""
    try:
        shutil.rmtree(directory)
    except OSError as error:
        return False, "Could not remove %s: %s" % (name, error)
    # So a retry is not held off by a backoff from before it was removed.
    _MOTION_RETRY_AFTER.pop(name, None)
    decky.logger.info("Removed tool %s", name)
    return True, ""


def install_named_tool(name, on_progress=None):
    """Fetch one tool the catalog declares, by name. Returns (path, error)."""
    spec = emulator_catalog.tool_spec(name)
    if not spec:
        return "", "No tool called %r." % name
    asset, error = resolve_release_asset(spec["repo"], spec["asset"])
    if not asset:
        return "", error or "No matching release asset."
    return install_tool(name, asset, on_progress=on_progress,
                        extract=spec.get("extract", ""))


def tools_report(installed_emulator_ids=()):
    """Every fetched helper, with whether it is here and whether it is wanted.

    `wanted` is what keeps the section honest: a tool for an emulator nobody has
    installed is not missing, it is simply not needed yet, and showing it as
    absent would invent a chore. The same rule the firmware section follows.
    """
    present = set(installed_emulator_ids or ())
    rows = []
    for tool in emulator_catalog.tools():
        entry_ids = [
            entry["id"] for entry in emulator_catalog.CATALOG
            if entry["name"] in tool["needed_by"]
        ]
        path = installed_tool(tool["name"])
        size = 0
        if path:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        rows.append(dict(
            tool,
            installed=bool(path),
            path=path,
            size=size,
            wanted=any(entry_id in present for entry_id in entry_ids),
            waiting=max(0, int(_MOTION_RETRY_AFTER.get(tool["name"], 0.0) - time.time())),
        ))
    return rows
