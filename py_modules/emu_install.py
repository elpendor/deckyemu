"""Installing a catalog emulator, through whichever channel it publishes on.

Flatpak wherever Flathub carries the emulator: `--user` needs no password, and
updating, rolling back and pinning are flatpak's own questions to answer.
Release AppImages are the fallback for emulators with no flatpak, since an
AppImage is a file this plugin then owns forever.

Release asset patterns must be anchored: assets carry aarch64 builds beside
x86_64 ones, and the wrong one fails at exec time with no useful error.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tarfile
import threading
import zipfile
from urllib.parse import unquote

import appenv

import savedata
import sysenv

import emu_patch
import emulator_catalog
import hardware
import net
import sysenv

FLATHUB_REPO = "https://flathub.org/repo/flathub.flatpakrepo"

# Well above any emulator AppImage, low enough to refuse a redirect to
# something unexpected.
MAX_APPIMAGE_BYTES = 400 * 1024 * 1024


def emulators_dir(*parts, create=True):
    """Where AppImage emulators live: `~/deckyemu/emulators`.

    Not appenv.DATA_DIR, which a reset wipes.
    """
    return sysenv.user_dir("emulators", *parts, create=create)


def firmware_dir():
    """Where the user's own BIOS files, keys and firmware are collected."""
    return sysenv.user_dir("firmware")


# ------------------------------------------------------------------- flatpak


def flatpak_binary():
    return shutil.which("flatpak") or ""


def flatpak_install_steps(app_id):
    """Commands that install `app_id` for the current user.

    The remote is added first, since a fresh Deck has none. `-y` without
    `--noninteractive`, because `flatpak_progress` reads the percentages.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    return [
        [flatpak, "remote-add", "--if-not-exists", "--user", "flathub", FLATHUB_REPO],
        [flatpak, "install", "--user", "-y", "flathub", app_id],
    ]


def flatpak_files_dir(app_id):
    """The deployed `files/` tree of an installed flatpak, or "".

    Follows `current/active`, so it is the build installed right now.
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

    Supermodel's Flathub build installs `Assets` under `/app/bin` but looks for
    them in its data directory, and exits on launch without the crosshair
    bitmaps; no flag points it elsewhere.

    Copies only missing files, so a user's replacement stays, and only regular
    files directly inside the source directory. Returns (paths copied, error).
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
            # The package moved its data; the install is fine otherwise, and
            # upstream may have fixed it.
            appenv.logger.warning(
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
        appenv.logger.info("Seeded %d file(s) %s ships but does not find",
                          len(copied), app_id)
    return copied, ""


def flatpak_uninstall_argv(app_id, delete_data=False):
    """Remove a user-scope flatpak.

    Data is kept unless asked for. `--delete-data` removes `~/.var/app/<id>`
    whole, saves included, which is the only way back to never-installed.
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


#: An OSTree commit. Checked before a command line, since it comes from the
#: frontend.
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
    """Deploy one specific past build with `flatpak update --commit=`.

    Refuses anything but a bare hash.
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

    Without a mask, the next update from anywhere silently undoes a downgrade.
    """
    flatpak = flatpak_binary()
    if not flatpak or not _valid_app_id(app_id):
        return []
    if held:
        return [flatpak, "mask", "--user", app_id]
    return [flatpak, "mask", "--user", "--remove", app_id]


def _flatpak_lines(args, timeout=60):
    """Run a read-only flatpak query and return its stdout lines.

    Empty means "could not tell", which callers must not read as "nothing found".
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


# Parsers are kept apart from the commands so tests can feed them flatpak's real
# output.


def _parse_ids(lines):
    """App ids out of a one-per-line listing."""
    found = set()
    for line in lines:
        app_id = line.strip().split("\t")[0].strip()
        if _valid_app_id(app_id):
            found.add(app_id)
    return found


#: Fields worth reading out of `remote-info` for one build. `download` matters
#: most: switching build re-fetches the whole app.
_DETAIL_KEYS = ("version", "license", "download", "installed", "subject", "date",
                "commit", "parent")


def _clean_value(value):
    """One field's value, made safe to display.

    Sizes carry a narrow no-break space before the unit, printed as `?` without
    a UTF-8 locale, as here. Both become a plain space.
    """
    value = re.sub(r"(?<=\d)(\?|[^\x20-\x7e])(?=[A-Za-z])", " ", value)
    value = re.sub(r"[^\x20-\x7e]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_fields(lines):
    """`remote-info`'s labelled lines as a dict, for the fields worth showing.

    First occurrence wins.
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

    Separate from `flatpak_history` because it costs a call per build.
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
            # `--commit=` refuses a truncated hash.
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
            # Every Commit line starts a record; the first is the newest build.
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

    Waited for, not streamed, since masking is instant. A failure is reported.
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
        appenv.logger.info("flatpak: %s", line)
    if done.returncode != 0:
        lines = [line for line in text.splitlines() if line.strip()]
        return False, lines[-1] if lines else "flatpak exited with %d" % done.returncode
    return True, ""


def flatpak_updates():
    """App ids with a newer build waiting, as a set.

    One command for all apps, since each flatpak call costs about two seconds.
    flatpak compares commits, not versions: an update can carry the same
    `Version:` as the installed build. Runtimes are included; callers intersect
    with the ids they know.
    """
    cached = _UPDATES_CACHE.get("answer")
    # Already being asked: answer from the cache rather than hold a thread.
    if not _UPDATES_LOCK.acquire(blocking=False):
        return set(cached or ())
    try:
        marker = _flatpak_changed()
        if (cached is not None and _UPDATES_CACHE.get("marker") == marker
                and time.monotonic() - _UPDATES_CACHE["at"] < UPDATES_TTL):
            return set(cached)
        answer = _parse_ids(
            _flatpak_lines(
                ["remote-ls", "--user", "--updates", "flathub", "--columns=application"]
            )
        )
        _UPDATES_CACHE.update(answer=answer, marker=marker, at=time.monotonic())
        return set(answer)
    finally:
        _UPDATES_LOCK.release()


# One `remote-ls` at a time: on a cold cache it takes a minute, and retries
# once filled every executor thread.
UPDATES_TTL = 600
_UPDATES_LOCK = threading.Lock()
_UPDATES_CACHE: dict = {}


def _flatpak_changed():
    """Flatpak touches this on every install, update and removal."""
    try:
        return os.stat(os.path.join(sysenv.user_home(), ".local", "share", "flatpak", ".changed")).st_mtime_ns
    except OSError:
        return None


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

    Lets a workaround notice check the build on this Deck rather than assume
    one. Empty means we cannot tell, and then nothing is claimed.
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

    From the remote, so it includes builds this device never had. Date and
    subject are what the user chooses by.
    """
    if not _valid_app_id(app_id):
        return []
    return _parse_history(
        _flatpak_lines(["remote-info", "--user", "--log", "flathub", app_id], timeout=90),
        limit=limit,
    )


def flatpak_installed(app_id):
    """Whether `app_id` is installed for this user.

    Read off the filesystem, since it runs for every entry when the panel opens.
    Neither `.var/app/<id>` (kept data) nor a bare deploy directory (a failed
    operation) counts.
    """
    if not _valid_app_id(app_id):
        return False
    return any(sysenv.flatpak_deployed(root, app_id) for root in sysenv.flatpak_roots())


def flatpak_scope(app_id):
    """'user', 'system' or '' -- which install we are looking at.

    A system install needs root to remove, so the UI explains instead.
    """
    if not _valid_app_id(app_id):
        return ""
    system_root, user_root = sysenv.flatpak_roots()
    if sysenv.flatpak_deployed(user_root, app_id):
        return "user"
    if sysenv.flatpak_deployed(system_root, app_id):
        return "system"
    return ""


#: What flatpak says when asked to remove something it does not have. The exit
#: code is 1 either way, and nothing to remove is the goal already met.
_NOTHING_INSTALLED = re.compile(r"no installed refs? found", re.I)


def nothing_to_uninstall(error):
    """Whether a failed `flatpak uninstall` failed only by having no work."""
    return bool(_NOTHING_INSTALLED.search(error or ""))


def remove_flatpak_husk(app_id):
    """Delete a deploy directory flatpak has disowned. Returns bytes freed.

    A failed operation can leave commit trees with no `current` or `active`;
    flatpak then neither runs nor removes them. Safe because nothing is
    deployed: a real install, even mid-download, is left alone.
    """
    if not _valid_app_id(app_id):
        return 0
    freed = 0
    # User installation only; a system one belongs to root.
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
        appenv.logger.warning("Could not remove the leftover %s: %s", path, error)
        return 0
    appenv.logger.info("Removed the leftover deploy directory %s (%d bytes)", path, freed)
    return freed


# -------------------------------------------------------------------- github

GITHUB_API = "https://api.github.com/repos/%s/releases/latest"

#: The same question asked of the website, which redirects to
#: `/releases/tag/<tag>`. Off the API's hourly budget, and excludes
#: pre-releases as `latest` does.
GITHUB_LATEST_PAGE = "https://github.com/%s/releases/latest"

#: What that redirect lands on. No releases lands on `/releases`, which
#: this does not match.
_TAG_IN_URL = re.compile(r"/releases/tag/([^/?#]+)")


#: Same call against a self-hosted forge, which answers the same shape.
SELF_HOSTED_API = "https://%s/api/v1/repos/%s/releases/latest"

#: A hostname, not a URL, so an entry cannot name a path or plain HTTP.
_HOST_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


#: A feed is a few hundred bytes; anything this large is not one.
MAX_FEED_BYTES = 64 * 1024


def resolve_feed_build(feed_url, want):
    """The build `want` names in a publisher's own update feed. (asset, error).

    For a project with no releases API: BigPEmu's updater reads a plain-text
    feed with one line per platform, giving the download, an unused patch
    installer, then the file's 64-bit FNV-1a:

        BUILD_INFO 1
        VERSION 1.221
        Linux64 "http://.../BigPEmu_Linux64_v1221.tar.gz" "" C1B241BBFA5135CB ...

    The scheme is forced to https; the same files serve over TLS.
    """
    if not net.is_web_url(feed_url):
        return None, "That is not a usable address for an update feed."
    payload, _content_type = net.get_bytes(feed_url, max_bytes=MAX_FEED_BYTES)
    if not payload:
        return None, "The project's update feed could not be read."
    text = payload.decode("utf-8", "replace")

    version = ""
    for line in text.splitlines():
        if line.startswith("VERSION "):
            version = line.split(None, 1)[1].strip()
            break
    if not version:
        return None, "The project's update feed named no version."

    for line in text.splitlines():
        if not line.startswith(want + " "):
            continue
        quoted = re.findall(r'"([^"]*)"', line)
        if not quoted or not quoted[0]:
            return None, "The update feed lists %s with no download." % want
        url = re.sub(r"^http://", "https://", quoted[0].strip())
        if not net.is_web_url(url):
            return None, "The update feed's download address is not usable."
        digest = ""
        after = line.split('"')[-1].split()
        if after and re.match(r"^[0-9A-Fa-f]{16}$", after[0]):
            digest = "fnv1a64:" + after[0].lower()
        return {
            "name": url.rsplit("/", 1)[-1],
            "url": url,
            "digest": digest,
            "tag": version,
        }, ""
    return None, "The project publishes no %s build." % want


#: How many past builds a feed-installed emulator offers, as for releases.
FEED_HISTORY_LIMIT = 12


def _versions_named(notes_text):
    """Every version heading in a set of release notes, in the order written."""
    found = []
    for line in (notes_text or "").splitlines():
        match = re.match(r"^Version\s+([0-9][0-9.]*)\s*$", line)
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def _clip(text, limit):
    """`text` no longer than `limit`, cut at a word and marked as cut.

    A bare slice ends mid-word and looks like a rendering fault.
    """
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."


def _merged(known, *more):
    """One list of versions, in the order they were first met, without repeats."""
    out = [version for version in (known or ()) if version]
    for group in more:
        for version in group or ():
            if version and version not in out:
                out.append(version)
    return out


def remember_versions(entry, notes_text, extra=()):
    """Every version this device has ever seen of `entry`, merged and stored.

    The version list comes from the installed build's notes, so it shrinks
    when the build goes back; the build record keeps what has been seen.
    Called wherever a history is read, not only after an install.
    """
    record = read_build_record(entry["id"])
    known = _merged(record.get("versions"), _versions_named(notes_text), extra)
    if known != list(record.get("versions") or ()):
        write_build_record(entry["id"], record.get("tag", ""),
                           record.get("asset", ""), known)
    return known


def feed_history(entry, notes_text, probe=None, remembered=(), newest=None):
    """Past builds of a feed-installed emulator, newest first. (builds, error).

    The list is the `Version x.y` headings in the `ReadMe.txt` shipped beside
    the binary, the only enumeration that exists. An old build's address is
    the version without dots, an undocumented convention; it is only applied
    to versions the notes name, and `probe` confirms each file exists.

    The feed gives a checksum for the current release only; `newest` is that
    release, so its row uses the stated address and checksum.
    """
    source = entry.get("source") or {}
    pattern = source.get("build_name") or ""
    if not pattern:
        return [], ""

    # A heading and the lines under it, until the next: that release's notes.
    seen = list(remembered or ())
    notes = {}
    current = ""
    for line in (notes_text or "").splitlines():
        found = re.match(r"^Version\s+([0-9][0-9.]*)\s*$", line)
        if found:
            current = found.group(1)
            if current not in seen:
                seen.append(current)
            notes.setdefault(current, [])
            continue
        if current and line.strip():
            notes[current].append(line.strip().lstrip("- ").strip())
    if not seen:
        return [], "No release notes came with this build, so its past builds are not listed."

    # Newest first. The part after the dot is read as a fraction, so 1.221
    # sits above 1.22, which sits above 1.19.
    def _order(version):
        head, _, tail = version.partition(".")
        try:
            return (int(head), float("0." + tail) if tail else 0.0)
        except ValueError:
            return (0, 0.0)

    seen.sort(key=_order, reverse=True)

    builds = []
    for version in seen[:FEED_HISTORY_LIMIT]:
        # The current release's address and checksum come from the feed.
        stated = newest if newest and newest.get("tag") == version else None
        url = (stated["url"] if stated
               else pattern.replace("{version}", version.replace(".", "")))
        # One request says both whether it is still published and its size.
        size = probe(url) if probe else 0
        if not size:
            continue
        builds.append({
            "tag": version,
            "name": url.rsplit("/", 1)[-1],
            "url": url,
            "size": size,
            "digest": stated["digest"] if stated else "",
            "published": "",
            "prerelease": False,
            # Capped; the first lines say what the release was for.
            "notes": _clip(" ".join(notes.get(version, ())[:6]), 600),
        })
    if not builds:
        return [], "None of the past builds named in the release notes are still published."
    return builds, ""


def read_build_notes(entry):
    """The release notes shipped with the installed build, or "".

    Shipped with the build, so no network is needed.
    """
    source = entry.get("source") or {}
    name = source.get("notes") or ""
    if not name or not emulator_catalog.is_safe_id(entry.get("id")):
        return ""
    path = os.path.join(emulators_dir(entry["id"], create=False), name)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(512 * 1024)
    except OSError:
        return ""


def build_size(url):
    """How big a past build is, or 0 if it is no longer published.

    Separate so `feed_history` can be tested with a fake probe. Zero means
    gone or unreadable, and either way the build is not offered.
    """
    return net.head_size(url)


def resolve_release_asset(repo, pattern, host="", failure=None):
    """Newest release asset matching `pattern`, from GitHub or a self-hosted forge.

    `host` empty means GitHub; otherwise a host running the same releases
    API. No token is sent: the plugin's own is scoped to this project.
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

#: A release tag. Permissive on shape, strict on characters, since it comes
#: from the frontend.
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def valid_tag(tag):
    return bool(_TAG_RE.match(tag or ""))


def resolve_release_list(repo, pattern, host="", limit=30):
    """Recent releases carrying an asset that matches, newest first.

    Returns (builds, error). Each build is {tag, name, url, size, published}.

    Releases with no matching asset, such as aarch64-only ones, are skipped.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo or ""):
        return [], "Not a valid repository name."
    if host and not _HOST_RE.match(host):
        return [], "Not a valid host name."

    api = SELF_HOSTED_RELEASES % (host, repo) if host else GITHUB_RELEASES % repo
    if not host:
        # GitHub's default of 30 can be two weeks for a project that tags
        # every build.
        api += "?per_page=100"
    label = "%s on %s" % (repo, host) if host else repo
    failure = {}
    payload = net.get_json(api, failure=failure)
    if not isinstance(payload, list):
        # Name the real failure; see `_resolve_asset`.
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
                "digest": asset.get("digest") or "",
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
    # The caller may want the details: a rate limit says when it lifts.
    failure = {} if failure is None else failure
    payload = net.get_json(api_url, failure=failure)
    if payload is None:
        # Name the real failure: a rate limit once read as the project having
        # moved. 451 (taken-down repositories) falls to the generic line.
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
                "digest": asset.get("digest") or "",
            },
            "",
        )

    return None, "No download in the latest release of %s matched what was expected." % label


#: How GitHub states an asset's checksum, e.g. "sha256:5c73...".
_DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$", re.IGNORECASE)

#: BigPEmu's feed states a 64-bit FNV-1a of each build and nothing else;
#: checked against a published value.
_FNV_RE = re.compile(r"^fnv1a64:([0-9a-f]{16})$", re.IGNORECASE)
_FNV_PRIME = 1099511628211
_FNV_OFFSET = 14695981039346656037
_FNV_MASK = (1 << 64) - 1


def _fnv1a64(path):
    """The 64-bit FNV-1a of a file, as lowercase hex. "" if it cannot be read."""
    value = _FNV_OFFSET
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                for byte in block:
                    value = ((value ^ byte) * _FNV_PRIME) & _FNV_MASK
    except OSError:
        return ""
    return "%016x" % value


def _digest_matches(path, digest):
    """Whether the file at `path` is what the release said it would be. (ok, error).

    Integrity, not authenticity: the checksum comes in the same reply as the
    URL. It catches a truncated or stale download. An asset with no digest
    passes, since many sources publish none.
    """
    weak = _FNV_RE.match((digest or "").strip())
    if weak:
        wanted = weak.group(1).lower()
        got = _fnv1a64(path)
        if not got:
            return False, "Could not read the download."
    else:
        stated = _DIGEST_RE.match((digest or "").strip())
        if not stated:
            return True, ""
        wanted = stated.group(1).lower()
        reader = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    reader.update(block)
        except OSError as error:
            return False, "Could not read the download: %s" % error
        got = reader.hexdigest()
    if got != wanted:
        appenv.logger.warning("Digest mismatch for %s: wanted %s, got %s",
                             path, wanted, got)
        return False, ("The download does not match the checksum the release "
                       "published, so it arrived damaged or altered. Nothing "
                       "was installed.")
    return True, ""


def install_appimage(entry, asset, on_progress=None):
    """Download an AppImage into its own folder under `~/deckyemu/emulators`.

    Returns (path, error). A folder per emulator, so a new build replaces the
    old cleanly.
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

    # Before unpacking, so a damaged archive is refused whole.
    whole, damaged = _digest_matches(path, asset.get("digest", ""))
    if not whole:
        try:
            os.remove(path)
        except OSError:
            pass
        return "", damaged

    # The program ships inside an archive, which is not the thing to run.
    source = entry.get("source") or {}
    extract = source.get("extract") or ""
    if extract and source.get("unpack"):
        # A tree rather than one file; `extract` names the one to run.
        member, failure = _unpack_release(path, target_dir, extract)
        try:
            os.remove(path)
        except OSError:
            pass
        if failure:
            return "", failure
        path = member
        asset = dict(asset, name=os.path.basename(member))
    elif extract:
        member, failure = _extract_member(path, target_dir, extract)
        try:
            os.remove(path)
        except OSError:
            pass
        if failure:
            return "", failure
        path = member
        asset = dict(asset, name=os.path.basename(member))

    try:
        os.chmod(path, 0o755)
    except OSError as error:
        # Fail here, where it can be explained; otherwise Steam shows the
        # game closing instantly.
        return "", "Downloaded but could not make it executable: %s" % error

    # Sweep the previous build, except where the folder is also the program's
    # data directory: then only the build the record names goes, and saves stay.
    if source.get("unpack"):
        # A tree: sweeping would delete the program's own data. The new
        # release is written over the top.
        pass
    elif entry.get("game_beside"):
        previous = (read_build_record(entry["id"]) or {}).get("asset") or ""
        if previous and previous != asset["name"]:
            try:
                os.remove(os.path.join(target_dir, previous))
            except OSError:
                pass
    else:
        _remove_others(target_dir, keep=asset["name"])

    # After the cleanup, or it is swept too. Written even with no tag, since
    # "build unknown" differs from "not installed". Known versions carry over,
    # so a rollback still offers the way forward.
    keep_versions = _merged(read_build_record(entry["id"]).get("versions"),
                            _versions_named(read_build_notes(entry)),
                            [asset.get("tag", "")])
    write_build_record(entry["id"], asset.get("tag", ""), asset["name"], keep_versions)

    # Patched copies derive from the new build. Not part of success: an
    # unpatchable build still runs, and `emu_patch.unapplied` reports it.
    emu_patch.refresh(entry, path, asset.get("tag", ""))

    appenv.logger.info("Installed %s to %s", entry["id"], path)
    return path, ""


def _remove_others(directory, keep):
    """Clear a folder of everything but `keep`, which may be one name or several."""
    keeping = {keep} if isinstance(keep, str) else set(keep)
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        # The record describes the kept build and is rewritten right after.
        if name in keeping or name == BUILD_RECORD:
            continue
        path = os.path.join(directory, name)
        try:
            # A patching tree left by a kill mid-way.
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as error:
            appenv.logger.warning("Could not remove old build %s: %s", name, error)


def tools_dir(*parts, create=True):
    """Where helper binaries live: `~/deckyemu/tools`.

    Separate from `emulators` so tools are never listed as emulators.
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


def _nothing_matched(pattern, names):
    """The error for an `extract` pattern that named no member of the archive.

    Lists what the archive holds, since patterns and releases drift, often
    only in letter case.
    """
    listed = ", ".join(sorted(names)[:8]) or "nothing"
    if len(names) > 8:
        listed += ", ..."
    return "Nothing in the download is named like %s. It holds: %s." % (pattern, listed)


def _replace(target):
    """Take a file out of the way so the new one can be written over it.

    An archive can ship read-only files, and `open(..., "wb")` cannot reopen
    one, so a second build failed over the first. Removed, not chmod-ed, so
    the new file inherits nothing.
    """
    try:
        os.remove(target)
    except FileNotFoundError:
        pass
    except OSError as error:
        appenv.logger.warning("Could not replace %s: %s", target, error)


def _safe_target(destination, name):
    """Where `name` lands under `destination`, or "" if it tries to leave it.

    Archives come off the network, so an absolute or `..` member is refused,
    and the resolved path is checked against the destination.
    """
    relative = os.path.normpath(name).replace("\\", "/")
    if relative.startswith("/") or relative.split("/")[0] == "..":
        return ""
    target = os.path.join(destination, *relative.split("/"))
    root = os.path.realpath(destination)
    if os.path.commonpath([root, os.path.realpath(os.path.dirname(target))]) != root:
        return ""
    return target


def _common_prefix(names):
    """The single folder every member sits in, or "".

    Stripped so a tarball's top folder does not nest inside ours. Only when
    every member shares it.
    """
    first = ""
    for name in names:
        head = name.replace("\\", "/").split("/")[0]
        if "/" not in name.replace("\\", "/"):
            return ""
        if first and head != first:
            return ""
        first = head
    return first


def _unpack_tarball(archive, destination, pattern):
    """`_unpack_release` for a .tar.gz. Same contract, same refusals.

    Only regular files come out, so links and devices are never written.
    `filter="data"` needs Python 3.12; the runtime was 3.11.
    """
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = ""
    seen = []
    try:
        with tarfile.open(archive, "r:*") as bundle:
            members = [m for m in bundle.getmembers() if m.isfile()]
            strip = _common_prefix([m.name for m in members])
            for member in members:
                name = member.name
                if strip:
                    name = name.replace("\\", "/")[len(strip) + 1:]
                    if not name:
                        continue
                target = _safe_target(destination, name)
                if not target:
                    return "", "The download holds a path that leaves its own folder."
                os.makedirs(os.path.dirname(target), exist_ok=True)
                _replace(target)
                source = bundle.extractfile(member)
                if source is None:
                    continue
                with source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                # The recorded mode carries the execute bit.
                if member.mode:
                    os.chmod(target, member.mode & 0o777)
                seen.append(os.path.basename(target))
                if matcher.match(os.path.basename(target)):
                    found = target
    except (OSError, tarfile.TarError, ValueError) as error:
        return "", "Could not unpack the download: %s" % error
    if not found:
        return "", _nothing_matched(pattern, seen)
    return found, ""


def _unpack_release(archive, destination, pattern):
    """Unpack a whole archive, and return the member `pattern` names. (path, error).

    Members keep their relative paths, so each is checked for escaping.
    """
    if tarfile.is_tarfile(archive):
        return _unpack_tarball(archive, destination, pattern)
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = ""
    seen = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = info.filename
                if info.is_dir() or not name:
                    continue
                relative = os.path.normpath(name).replace("\\", "/")
                if relative.startswith("/") or relative.split("/")[0] == "..":
                    return "", "The download holds a path that leaves its own folder."
                target = os.path.join(destination, *relative.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                # A read-only file from the last build cannot be written over.
                _replace(target)
                with bundle.open(info) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                # Keep the recorded mode.
                mode = info.external_attr >> 16
                if mode:
                    os.chmod(target, mode & 0o777)
                seen.append(os.path.basename(relative))
                if matcher.match(os.path.basename(relative)):
                    found = target
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return "", "Could not unpack the download: %s" % error
    if not found:
        return "", _nothing_matched(pattern, seen)
    return found, ""


def _extract_member(archive, destination, pattern):
    """Pull one file out of a downloaded zip by basename. Returns (path, error).

    Written by basename, never the archive's path. Exactly one must match;
    two means the pattern is ambiguous.
    """
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return "", "Bad extract pattern: %s" % error

    found = []
    seen = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = os.path.basename(info.filename)
                if info.is_dir() or not name:
                    continue
                seen.append(name)
                if not matcher.match(name):
                    continue
                found.append(info)
        if len(found) != 1:
            return "", (_nothing_matched(pattern, seen)
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

    Like `install_appimage`. `extract` names the member to keep from a zip;
    the zip is deleted so `installed_tool` cannot return it. A list of
    patterns keeps several, and the first names the binary.
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

    kept = []
    if extract:
        patterns = [extract] if isinstance(extract, str) else list(extract)
        for pattern in patterns:
            member, error = _extract_member(path, target_dir, pattern)
            if error:
                try:
                    os.remove(path)
                except OSError:
                    pass
                return "", error
            kept.append(member)
        try:
            os.remove(path)
        except OSError:
            pass
        path = kept[0]

    try:
        os.chmod(path, 0o755)
    except OSError as error:
        return "", "Downloaded but could not make it executable: %s" % error

    _remove_others(target_dir, keep=[os.path.basename(one) for one in kept]
                   or os.path.basename(path))
    appenv.logger.info("Installed tool %s to %s", name, path)
    return path, ""


def motion_server(entry):
    """The installed motion server for a catalog entry, or ''.

    Shared by the launcher writer and the fetcher so they agree. '' means
    the ordinary launcher, with only motion missing.
    """
    if not hardware.has_deck_sensors():
        # No sensors to serve.
        return ""
    server = ((entry or {}).get("motion") or {}).get("server") or {}
    name = server.get("name") or ""
    return installed_tool(name) if name else ""


#: When to ask GitHub about a tool again, by name. Emulators share a server
#: and the check runs on every status call, which once spent four requests of
#: the hourly budget in a second. In memory: a reload may retry.
_TOOL_RETRY_AFTER: dict = {}


def motion_configured(entry):
    """Whether the emulator itself is pointed at the motion server.

    `emu_config` won't overwrite a file the user owns, so a hand-configured
    controller silently gets no motion. True when there is nothing to check.
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
        # Not run yet, which is not misconfigured.
        return True


def motion_state(entry, now=None):
    """What the panel says about this emulator's motion server.

    A failed fetch used to reach only the log. `waiting` is seconds until the
    next attempt, so a rate limit reads as a wait, not a fault.
    """
    server = ((entry or {}).get("motion") or {}).get("server") or {}
    name = server.get("name") or ""
    # No sensors: no row at all.
    if not name or not hardware.has_deck_sensors():
        # Same keys whatever the answer.
        return {"declared": False, "ready": False, "configured": True, "waiting": 0}
    now = time.time() if now is None else now
    installed = bool(installed_tool(name))
    return {
        "declared": True,
        "ready": installed,
        # Only once the binary is here, so one fault is not reported as two.
        "configured": motion_configured(entry) if installed else True,
        "waiting": max(0, int(_TOOL_RETRY_AFTER.get(name, 0.0) - now)),
    }


def ensure_tool(spec, now=None):
    """Fetch one declared tool if it is not here yet. Returns (path, error).

    The feature that needs a tool fetches it; the Tools section only reports
    and restores. Called when the feature is turned on and at startup, for
    features enabled before the tool existed. Never fatal. A failure backs
    off briefly, a rate limit until it lifts.
    """
    spec = spec or {}
    name = spec.get("name") or ""
    if not name:
        return "", ""
    existing = installed_tool(name)
    if existing:
        return existing, ""

    now = time.time() if now is None else now
    until = _TOOL_RETRY_AFTER.get(name, 0.0)
    if now < until:
        return "", ""

    failure = {}
    asset, error = resolve_release_asset(spec["repo"], spec["asset"], failure=failure)
    if not asset:
        reset = net.rate_limit_reset(failure, now)
        _TOOL_RETRY_AFTER[name] = reset or (now + 300.0)
        return "", error or "No matching release asset."

    path, error = install_tool(name, asset, extract=spec.get("extract", ""))
    if error:
        _TOOL_RETRY_AFTER[name] = now + 300.0
    return path, error


def ensure_motion_server(entry, now=None):
    """Fetch this emulator's motion server if it is not here yet. (path, error).

    Not without Deck sensors (`hardware.has_deck_sensors`): it could never send
    a reading. Nothing failed, so no error.
    """
    if not hardware.has_deck_sensors():
        return "", ""
    return ensure_tool(((entry or {}).get("motion") or {}).get("server") or {}, now)


def ensure_hotkey_helper(entry, now=None):
    """Fetch the hotkey helper if this entry needs keys and it is not here yet.

    A launcher names the binary when written, so a late arrival needs the
    launcher rewritten. A port with no keys asks for nothing.
    """
    if not emulator_catalog.hotkeys.bindings_for(entry):
        return "", ""
    return ensure_tool(emulator_catalog.hotkeys.KEYBOARD_SERVER, now)


def ensure_cloud_tool(now=None):
    """Fetch rclone if cloud saves are on and it is not here. (path, error).

    Switching cloud saves on fetches it; the Tools row only reports.
    """
    return ensure_tool(emulator_catalog.cloud.RCLONE, now)


#: What was installed, beside the AppImage, so it survives a plugin reinstall.
BUILD_RECORD = ".build.json"


def build_record_path(entry_id):
    return os.path.join(emulators_dir(entry_id, create=False), BUILD_RECORD)


def read_build_record(entry_id):
    """{tag, asset} for an installed AppImage, or {} when it is not known.

    Empty is not an error: older installs have no record.
    """
    if not emulator_catalog.is_safe_id(entry_id):
        return {}
    try:
        with open(build_record_path(entry_id), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def write_build_record(entry_id, tag, asset_name, versions=()):
    """Record which release an AppImage came from. Best effort.

    `versions` are all releases seen, so a rollback still lists newer ones.
    """
    if not emulator_catalog.is_safe_id(entry_id):
        return
    kept = [version for version in versions if version]
    try:
        with open(build_record_path(entry_id), "w", encoding="utf-8") as handle:
            json.dump({"tag": tag or "", "asset": asset_name or "",
                       "versions": kept}, handle, indent=2)
    except OSError as error:
        # Not fatal: the build just reads as unknown.
        appenv.logger.warning("Could not record the build of %s: %s", entry_id, error)


#: The newest release of each AppImage emulator at the last check. In the
#: settings directory, unlike the build record: it is a disposable cache.
LATEST_TAGS = os.path.join(appenv.DATA_DIR, "latest-tags.json")


def read_latest_tags():
    """{entry_id: tag} from the last update check, or {}.

    No timestamp: installing the update rewrites the build record, which
    flips the comparison by itself.
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
        appenv.logger.warning("Could not record the latest tags: %s", error)


def github_latest_tag(repo):
    """The newest published tag for `repo`, or "". No API budget, no body.

    A renamed repository redirects and still answers.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo or ""):
        return ""
    landed = net.head_location(GITHUB_LATEST_PAGE % repo)
    found = _TAG_IN_URL.search(landed or "")
    return unquote(found.group(1)) if found else ""


def latest_tag(entry):
    """The newest published tag for one AppImage emulator, or ('', reason).

    One network call: never per row or tab open, which is why the answer is
    cached and asked for by a button.
    """
    source = entry.get("source") or {}
    if source.get("kind") == "url":
        asset, error = resolve_feed_build(source.get("feed", ""), source.get("select", ""))
        if not asset:
            return "", error or "Could not read the project's update feed."
        return asset.get("tag", ""), ""
    if source.get("kind") != "github":
        return "", ""
    repo, host = source.get("repo", ""), source.get("host", "")
    if not host:
        tag = github_latest_tag(repo)
        if tag:
            return tag, ""
        # Fall through to the API.
    asset, error = resolve_release_asset(repo, source.get("asset", ""), host)
    if not asset:
        return "", error or "Could not read the latest release."
    return asset.get("tag", ""), ""


def update_state(installed_tag, published_tag):
    """"available", "current", or "unknown" for one AppImage emulator.

    Unknown whenever either side is missing; it must not read as up to date.
    String equality, since tags come in shapes no one ordering fits.
    """
    if not installed_tag or not published_tag:
        return "unknown"
    return "current" if installed_tag == published_tag else "available"


def installed_appimage(entry_id):
    """The AppImage installed for `entry_id`, or ''."""
    if not emulator_catalog.is_safe_id(entry_id):
        return ""
    # Not created: asking must not leave empty folders.
    directory = emulators_dir(entry_id, create=False)
    # Saves kept by a removal may be files in here; never return one.
    saves = {os.path.normpath(one) for one in declared_saves(entry_id)}
    try:
        for name in sorted(os.listdir(directory)):
            # The build record sorts first.
            if name == BUILD_RECORD:
                continue
            path = os.path.join(directory, name)
            if os.path.normpath(path) in saves:
                continue
            if os.path.isfile(path):
                return path
    except OSError:
        pass
    return ""


def declared_saves(entry_id):
    """Absolute paths of what an entry calls its save data, as they exist now.

    Expanded through `savedata`'s patterns, so both mean the same files.
    """
    entry = emulator_catalog.find(entry_id)
    if not entry:
        return []
    home = sysenv.user_home()
    found = []
    for relative, _kind in emulator_catalog.schema.saves_of(entry):
        found.extend(savedata._matching(os.path.join(home, *relative.split("/"))))
    return found


def remove_appimage(entry_id, keep=()):
    """Delete the folder an AppImage emulator was installed into.

    `keep` are paths inside to leave behind: a portable port keeps its saves
    beside the binary, which a whole-folder delete would take.
    """
    if not emulator_catalog.is_safe_id(entry_id):
        return False, "Invalid emulator id."

    # create=False, or every removal "succeeds".
    directory = emulators_dir(entry_id, create=False)
    # Only ever under our own emulators folder.
    root = os.path.normpath(emulators_dir(create=False))
    if not os.path.normpath(directory).startswith(root + os.sep):
        return False, "Refusing to remove %s" % directory

    keeping = {os.path.normpath(one) for one in keep}
    try:
        if keeping:
            if not os.path.isdir(directory):
                return False, "Nothing was installed for that emulator."
            _prune(directory, keeping)
            # Nothing kept was in here, so the folder goes.
            if not os.listdir(directory):
                shutil.rmtree(directory)
        else:
            shutil.rmtree(directory)
    except FileNotFoundError:
        return False, "Nothing was installed for that emulator."
    except OSError as error:
        return False, "Could not remove %s: %s" % (directory, error)
    return True, ""


def _prune(folder, keeping):
    """Empty `folder` of everything that is not a kept save or holding one."""
    for name in sorted(os.listdir(folder)):
        child = os.path.join(folder, name)
        # The save itself, or something inside it: left exactly as it is.
        if any(child == one or child.startswith(one + os.sep) for one in keeping):
            continue
        # A folder on the way down to one: emptied of the rest, kept itself.
        if os.path.isdir(child) and any(
                one.startswith(child + os.sep) for one in keeping):
            _prune(child, keeping)
            continue
        if os.path.isdir(child) and not os.path.islink(child):
            shutil.rmtree(child)
        else:
            os.remove(child)


def remove_tool(name):
    """Delete an installed helper binary. Returns (removed, error).

    Only inside `tools_dir`; the name is checked so it cannot be a path.
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
    _TOOL_RETRY_AFTER.pop(name, None)
    appenv.logger.info("Removed tool %s", name)
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


def tools_report(installed_emulator_ids=(), features=()):
    """Every fetched helper, with whether it is here and whether it is wanted.

    A tool is `wanted` once an emulator needing it is installed, or for a
    plugin tool such as rclone, once its feature is on. Unwanted is not
    missing.
    """
    present = set(installed_emulator_ids or ())
    switched_on = set(features or ())
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
            wanted=(tool["feature"] in switched_on if tool.get("feature")
                    else any(entry_id in present for entry_id in entry_ids)),
            waiting=max(0, int(_TOOL_RETRY_AFTER.get(tool["name"], 0.0) - time.time())),
        ))
    return rows
