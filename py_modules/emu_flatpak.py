"""Installing, updating, rolling back and pinning emulators from Flathub.

Always `--user`, which needs no password. flatpak tracks versions itself, so
everything here asks it rather than keeping state of its own.
"""

import os
import re
import shutil
import subprocess
import threading
import time

import appenv
import sysenv


FLATHUB_REPO = "https://flathub.org/repo/flathub.flatpakrepo"


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
