"""Installing a catalog emulator, through whichever channel it publishes on.

Flatpak wherever Flathub carries the emulator (emu_flatpak.py). Release
AppImages are the fallback for emulators with no flatpak, since an AppImage is
a file this plugin then owns forever: found by emu_releases.py, unpacked by
emu_archives.py, and installed, recorded and removed here, along with the
helper tools some features fetch.
"""

import json
import os
import re
import shutil
import time
from urllib.parse import unquote

import appenv

import savedata
import sysenv

import emu_patch
import emulator_catalog
import hardware
import net
from emu_archives import (  # noqa: F401 -- re-exported; see emu_archives.py
    _common_prefix,
    _extract_member,
    _nothing_matched,
    _replace,
    _safe_target,
    _unpack_release,
    _unpack_tarball,
)
from emu_flatpak import (  # noqa: F401 -- re-exported; see emu_flatpak.py
    _APP_ID_RE,
    _clean_value,
    _COMMIT_RE,
    _DETAIL_KEYS,
    FLATHUB_REPO,
    flatpak_binary,
    flatpak_build_details,
    _flatpak_changed,
    flatpak_downgrade_argv,
    flatpak_files_dir,
    flatpak_held,
    flatpak_history,
    flatpak_hold,
    flatpak_hold_argv,
    flatpak_install_steps,
    flatpak_installed,
    flatpak_installed_commit,
    _flatpak_lines,
    flatpak_scope,
    flatpak_uninstall_argv,
    flatpak_update_argv,
    flatpak_updates,
    _NOTHING_INSTALLED,
    nothing_to_uninstall,
    _parse_commit,
    _parse_fields,
    _parse_history,
    _parse_ids,
    remove_flatpak_husk,
    seed_bundled_files,
    _UPDATES_CACHE,
    _UPDATES_LOCK,
    UPDATES_TTL,
    _valid_app_id,
    valid_commit,
)
from emu_releases import (  # noqa: F401 -- re-exported; see emu_releases.py
    build_size,
    _clip,
    _digest_matches,
    _DIGEST_RE,
    feed_history,
    FEED_HISTORY_LIMIT,
    _fnv1a64,
    _FNV_MASK,
    _FNV_OFFSET,
    _FNV_PRIME,
    _FNV_RE,
    GITHUB_API,
    GITHUB_LATEST_PAGE,
    GITHUB_RELEASES,
    _HOST_RE,
    MAX_FEED_BYTES,
    _merged,
    _resolve_asset,
    resolve_feed_build,
    resolve_github_asset,
    resolve_release_asset,
    resolve_release_list,
    SELF_HOSTED_API,
    SELF_HOSTED_RELEASES,
    _TAG_IN_URL,
    _TAG_RE,
    valid_tag,
    _versions_named,
)


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


# Parsers are kept apart from the commands so tests can feed them flatpak's real
# output.


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
