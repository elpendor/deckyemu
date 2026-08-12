"""Install libretro cores (and RetroArch itself) from inside the plugin.

Cores come from the same place RetroArch's own Core Downloader gets them: the
libretro buildbot's nightly directory. The stable directory only publishes a
single monolithic `RetroArch_cores.7z`, so nightly is the only practical source
for installing one core at a time.

The catalog comes from `info.zip`, which carries `supported_extensions` and
`database` for every core that exists -- not just installed ones. That is what
makes it possible to answer "which core would run this ROM?" before the user has
installed anything.
"""

import io
import json
import os
import re
import shutil
import time
import zipfile

import decky

import net

BUILDBOT = "https://buildbot.libretro.com"
CORE_BASE_URL = BUILDBOT + "/nightly/linux/x86_64/latest"
INFO_ZIP_URL = BUILDBOT + "/assets/frontend/info.zip"

FLATPAK_ID = "org.libretro.RetroArch"
FLATHUB_REPO = "https://flathub.org/repo/flathub.flatpakrepo"

_CACHE_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "installer")
_INFO_ZIP_PATH = os.path.join(_CACHE_DIR, "info.zip")
_AVAILABLE_PATH = os.path.join(_CACHE_DIR, "available.json")

_INFO_TTL = 7 * 24 * 60 * 60
_AVAILABLE_TTL = 24 * 60 * 60

# Roughly a third of what the buildbot publishes is not a game system: media
# players, image viewers, a ROM cleaner, tech demos. Two filters remove them.
#
# The functional one is that a core is only usable here if it declares a
# `database` (which is what artwork lookup keys on) and `supported_extensions`
# (which is what ROM matching keys on). That alone drops ffmpeg, mpv,
# imageviewer and romcleaner.
#
# The category deny-list then catches the leftovers that pass on a technicality.
# Note that "Game engine" cores are deliberately kept -- a Doom engine takes a
# .wad and has a real database, so it belongs in the list.
_SKIP_CORE_IDS = {"00_example"}
_EXCLUDED_CATEGORIES = {
    "Tech demo",
    "Test",
    "Utility",
    "Media player",
    "Video player",
    "Music player",
    "Images",
    "Streaming client",
}


def _fresh(path, ttl):
    try:
        return (time.time() - os.path.getmtime(path)) < ttl
    except OSError:
        return False


def _ensure_info_zip(force=False):
    """Local path to a reasonably fresh info.zip, or '' if unavailable."""
    if not force and os.path.isfile(_INFO_ZIP_PATH) and _fresh(_INFO_ZIP_PATH, _INFO_TTL):
        return _INFO_ZIP_PATH

    payload, _ = net.get_bytes(INFO_ZIP_URL, max_bytes=8 * 1024 * 1024)
    if not payload:
        # A stale copy beats no catalog at all.
        return _INFO_ZIP_PATH if os.path.isfile(_INFO_ZIP_PATH) else ""

    os.makedirs(_CACHE_DIR, exist_ok=True)
    tmp = _INFO_ZIP_PATH + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(payload)
    os.replace(tmp, _INFO_ZIP_PATH)
    return _INFO_ZIP_PATH


def _parse_info_text(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        values[key.strip()] = raw.strip().strip('"')
    return values


_ZIP_NAME_RE = re.compile(r"([A-Za-z0-9_\-]+)_libretro\.so\.zip")


def _available_core_ids(force=False):
    """Core ids the buildbot currently publishes for linux/x86_64."""
    if not force and _fresh(_AVAILABLE_PATH, _AVAILABLE_TTL):
        try:
            with open(_AVAILABLE_PATH, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            if isinstance(cached, list) and cached:
                return set(cached)
        except (OSError, ValueError):
            pass

    payload, _ = net.get_bytes(CORE_BASE_URL + "/", max_bytes=8 * 1024 * 1024)
    if not payload:
        return set()

    listing = payload.decode("utf-8", errors="replace")
    ids = sorted(set(_ZIP_NAME_RE.findall(listing)))
    if ids:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        try:
            with open(_AVAILABLE_PATH, "w", encoding="utf-8") as handle:
                json.dump(ids, handle)
        except OSError:
            pass
    decky.logger.info("Buildbot publishes %d cores", len(ids))
    return set(ids)


# Building the catalog means unpacking and parsing every .info file in info.zip
# -- around 200 of them -- and three separate callers ask for it: the install
# panel, the "nothing here can run this ROM" suggestion in the add flow, and the
# system list in the emulator editor. The frontend already caches it across
# remounts; this is the same saving on the backend side.
_catalog_cache: dict = {"key": None, "catalog": []}


def clear_catalog_cache():
    _catalog_cache["key"] = None
    _catalog_cache["catalog"] = []
    _extension_cache["key"] = None
    _extension_cache["map"] = {}


def core_catalog(force=False):
    """Every installable core, with the metadata needed to match ROMs.

    Returns [{id, display_name, system_name, databases, extensions}] sorted by
    system then name.
    """
    info_zip = _ensure_info_zip(force)
    if not info_zip:
        return []

    available = _available_core_ids(force)

    # Keyed on exactly what the answer is derived from, so a refreshed info.zip
    # or a changed buildbot listing rebuilds it rather than serving a stale
    # catalog -- which would hide a core the user just made installable.
    try:
        key = (os.path.getmtime(info_zip), frozenset(available))
    except OSError:
        key = None
    if key is not None and _catalog_cache["key"] == key:
        # Copied because callers annotate what they get back -- list_installable
        # _cores writes an `installed` flag onto every entry -- and the cache
        # must not start carrying one caller's answer into the next.
        return [dict(entry) for entry in _catalog_cache["catalog"]]

    catalog = []
    try:
        with zipfile.ZipFile(info_zip) as archive:
            for entry in archive.namelist():
                if not entry.endswith("_libretro.info"):
                    continue
                core_id = entry[: -len("_libretro.info")]
                if core_id in _SKIP_CORE_IDS:
                    continue
                # Only offer what can actually be downloaded. If the listing
                # could not be fetched, offer everything rather than nothing.
                if available and core_id not in available:
                    continue

                info = _parse_info_text(
                    archive.read(entry).decode("utf-8", errors="replace")
                )
                databases = [
                    part.strip() for part in info.get("database", "").split("|") if part.strip()
                ]
                extensions = [
                    ext.strip().lower()
                    for ext in info.get("supported_extensions", "").split("|")
                    if ext.strip()
                ]

                # Not a game system -- see _EXCLUDED_CATEGORIES.
                if not databases or not extensions:
                    continue
                categories = {
                    part.strip() for part in info.get("categories", "").split("|") if part.strip()
                }
                if categories & _EXCLUDED_CATEGORIES:
                    continue

                catalog.append(
                    {
                        "id": core_id,
                        "display_name": info.get("display_name")
                        or info.get("corename")
                        or core_id,
                        # A few cores omit systemname; their database name is the
                        # next best label.
                        "system_name": info.get("systemname")
                        or (databases[0].split(" - ")[-1] if databases else "Other"),
                        "databases": databases,
                        "extensions": extensions,
                    }
                )
    except (OSError, zipfile.BadZipFile) as error:
        decky.logger.warning("Could not read core catalog: %s", error)
        return []

    catalog.sort(key=lambda core: (core["system_name"].lower(), core["display_name"].lower()))
    decky.logger.info("Core catalog: %d installable cores", len(catalog))

    if key is not None:
        _catalog_cache["key"] = key
        _catalog_cache["catalog"] = catalog
        return [dict(entry) for entry in catalog]
    return catalog


_extension_cache: dict = {"key": None, "map": {}}


def database_extensions(force=False):
    """{libretro database name: [extensions]}, from every core info.zip carries.

    Deliberately *not* built from `core_catalog`. That list is filtered to what
    the buildbot publishes for linux/x86_64, which is the right question for
    "what can I install" and the wrong one for "what formats does this system
    use". The Wii U and original Xbox cores are both in info.zip and both absent
    from the nightly listing, so a standalone emulator for either derived an
    empty extension list and would have matched no ROM at all.

    The category filter is kept: a core that declares a database while being a
    media player would otherwise widen a system's formats with its own.
    """
    info_zip = _ensure_info_zip(force)
    if not info_zip:
        return {}

    try:
        key = os.path.getmtime(info_zip)
    except OSError:
        key = None
    if key is not None and _extension_cache["key"] == key:
        return _extension_cache["map"]

    mapping = {}
    try:
        with zipfile.ZipFile(info_zip) as archive:
            for entry in archive.namelist():
                if not entry.endswith("_libretro.info"):
                    continue
                info = _parse_info_text(archive.read(entry).decode("utf-8", errors="replace"))
                categories = {
                    part.strip() for part in info.get("categories", "").split("|") if part.strip()
                }
                if categories & _EXCLUDED_CATEGORIES:
                    continue
                extensions = [
                    ext.strip().lower()
                    for ext in info.get("supported_extensions", "").split("|")
                    if ext.strip()
                ]
                if not extensions:
                    continue
                for database in info.get("database", "").split("|"):
                    database = database.strip()
                    if database:
                        mapping.setdefault(database, set()).update(extensions)
    except (OSError, zipfile.BadZipFile) as error:
        decky.logger.warning("Could not read extension map: %s", error)
        return {}

    mapping = {name: sorted(values) for name, values in mapping.items()}
    if key is not None:
        _extension_cache["key"] = key
        _extension_cache["map"] = mapping
    decky.logger.info("Extension map: %d libretro systems", len(mapping))
    return mapping


def target_core_dir(install):
    """Where to put newly downloaded cores.

    RetroArch's own downloader writes into the config directory's `cores` folder,
    which is user-writable even for the flatpak, so we match that.
    """
    return os.path.join(install["config_dir"], "cores")


def install_core(install, core_id, catalog_entry=None):
    """Download and install one core. Returns a result dict."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", core_id or ""):
        return {"ok": False, "error": "Invalid core id."}

    cores_dir = target_core_dir(install)
    try:
        os.makedirs(cores_dir, exist_ok=True)
    except OSError as error:
        return {"ok": False, "error": "Cannot create %s: %s" % (cores_dir, error)}

    if not os.access(cores_dir, os.W_OK):
        return {"ok": False, "error": "Core directory is not writable: %s" % cores_dir}

    url = "%s/%s_libretro.so.zip" % (CORE_BASE_URL, core_id)
    payload, _ = net.get_bytes(url, max_bytes=200 * 1024 * 1024)
    if not payload:
        return {"ok": False, "error": "Download failed for %s" % core_id}

    so_name = "%s_libretro.so" % core_id
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            member = next(
                (name for name in archive.namelist() if name.endswith(".so")), None
            )
            if not member:
                return {"ok": False, "error": "Archive for %s had no core in it." % core_id}
            data = archive.read(member)
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        return {"ok": False, "error": "Could not unpack %s: %s" % (core_id, error)}

    so_path = os.path.join(cores_dir, so_name)
    tmp_path = so_path + ".part"
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, so_path)
        os.chmod(so_path, 0o755)
    except OSError as error:
        return {"ok": False, "error": "Could not write core: %s" % error}

    # Drop the .info beside the .so. RetroArch keeps its own info directory
    # inside the flatpak (read-only from here), and this location is the first
    # place our core scanner looks, so newly installed cores still get proper
    # system names and artwork databases.
    info_written = _write_core_info(core_id, cores_dir)

    decky.logger.info("Installed core %s to %s (info=%s)", core_id, cores_dir, info_written)
    return {
        "ok": True,
        "core_id": core_id,
        "path": so_path,
        "info_written": info_written,
        "cores_dir": cores_dir,
    }


def _write_core_info(core_id, cores_dir):
    info_zip = _ensure_info_zip()
    if not info_zip:
        return False
    member = "%s_libretro.info" % core_id
    try:
        with zipfile.ZipFile(info_zip) as archive:
            if member not in archive.namelist():
                return False
            data = archive.read(member)
        with open(os.path.join(cores_dir, member), "wb") as handle:
            handle.write(data)
        return True
    except (OSError, zipfile.BadZipFile) as error:
        decky.logger.warning("Could not write info for %s: %s", core_id, error)
        return False


def uninstall_core(install, core_id):
    """Remove a core we could have installed. Refuses to touch anything else."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", core_id or ""):
        return {"ok": False, "error": "Invalid core id."}

    cores_dir = target_core_dir(install)
    removed = []
    for name in ("%s_libretro.so" % core_id, "%s_libretro.info" % core_id):
        path = os.path.join(cores_dir, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed.append(name)
            except OSError as error:
                return {"ok": False, "error": "Could not remove %s: %s" % (name, error)}

    if not removed:
        return {"ok": False, "error": "%s is not installed in %s" % (core_id, cores_dir)}
    return {"ok": True, "removed": removed}


def flatpak_binary():
    return shutil.which("flatpak") or ""


def retroarch_install_argv():
    """Commands to install the RetroArch flatpak for the current user.

    A user-scope install needs no root, which matters because the plugin runs as
    the desktop user.
    """
    flatpak = flatpak_binary()
    if not flatpak:
        return []
    return [
        [flatpak, "remote-add", "--if-not-exists", "--user", "flathub", FLATHUB_REPO],
        [flatpak, "install", "--user", "-y", "--noninteractive", "flathub", FLATPAK_ID],
    ]


def retroarch_uninstall_argv(delete_data=False):
    """The command that removes the user-scope RetroArch flatpak.

    Only ever `--user`. Removing a system install needs root, and removing a
    native package would mean unlocking SteamOS's read-only rootfs -- neither is
    something a plugin should attempt behind a button.

    `--delete-data` additionally removes `~/.var/app/org.libretro.RetroArch`,
    which is where RetroArch keeps its configuration, saves, save states, and
    every core downloaded into it. Off by default: uninstalling to reinstall is
    common, and silently destroying save files is not recoverable.
    """
    flatpak = flatpak_binary()
    if not flatpak:
        return []
    argv = [flatpak, "uninstall", "--user", "-y", "--noninteractive"]
    if delete_data:
        argv.append("--delete-data")
    argv.append(FLATPAK_ID)
    return argv
