"""Persistent settings and the registry of games this plugin has added to Steam."""

import json
import os
import stat
import threading

import decky

SETTINGS_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
LIBRARY_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "library.json")

DEFAULT_SETTINGS = {
    # SteamGridDB API key. Empty means "use libretro thumbnails only".
    "sgdb_api_key": "",
    # There was a "github_token" here, for the period when this repository was
    # private and the update check needed credentials to see its own releases.
    # It is gone rather than merely unused: a credential nothing reads is still
    # a credential sitting in a file. `forget_removed` clears it from installs
    # that stored one, and must keep doing so for as long as any device might
    # still be carrying it.
    # auto | libretro | sgdb
    "art_source": "auto",
    # RetroAchievements. Off until a login exists, because enabling it without
    # one only produces a "not logged in" notice at every launch.
    "cheevos_enable": False,
    # Hardcore disables save states, rewind, slowdown and cheats. RetroArch
    # defaults it on; this defaults it off, because switching achievements on
    # from here is not a request to lose save states.
    "cheevos_hardcore": False,
    "cheevos_username": "",
    # The Connect token from one login. Password-equivalent for achievements,
    # so it is stored like sgdb_api_key and never sent to the frontend.
    "cheevos_token": "",
    # How much of RetroArch's on-screen chatter to suppress when a game starts.
    # keep | startup | all
    "hide_osd": "startup",
    # Controller shortcut that opens RetroArch's menu. A key of
    # launchers.MENU_COMBOS; "off" leaves the user's own retroarch.cfg alone.
    # Defaulted on because RetroArch sets no combo of its own and the Deck never
    # sees the Guide button it would otherwise use. RetroArch cores only.
    "menu_combo": "start_select",
    # Group added games into a Steam collection so they are findable in Big
    # Picture rather than lost among every other non-Steam shortcut.
    "add_to_collection": True,
    "collection_name": "DeckyEmu",
    # When set, each system gets its own collection: "[DeckyEmu] Nintendo 64".
    #
    # On, because a shelf per console is what the library is *for* -- one
    # collection holding every system is the pile this was meant to replace, and
    # it only gets worse the more you add. `_pin_collection_layout` keeps an
    # install that already has games on whatever it was using, since changing
    # where games are filed under somebody is not a default's job.
    "collection_per_platform": True,
    # How a per-platform collection is named. `{name}` is the collection name
    # above, `{platform}` the system. A literal \n is turned into a newline,
    # though Steam most likely renders it as a space.
    "collection_template": "[{name}] {platform}",
    # short | full -- "SNES" rather than "Super Nintendo Entertainment System".
    "platform_names": "short",
    # Apply each custom emulator's fullscreen switch when launching.
    "emulator_fullscreen": True,
    # The one Steam shortcut used to open any emulator's own window.
    #
    # One rather than one per emulator, and hidden from the library. Several
    # emulators will only do certain jobs through their own UI -- installing PS3
    # firmware, importing Switch firmware -- and gamescope composites nothing
    # Steam did not launch, so a shortcut is the only door. It is also a door
    # used once and then never again, so N of them permanently in the library is
    # a poor trade for something nobody looks at twice. This one is repointed at
    # whichever emulator is being opened.
    "setup_app_id": 0,
    # Keep the transfer address the same between sessions, so a trusted device can
    # bookmark it and skip both the address and the code.
    #
    # Off by default, because it changes what the link *is*. Normally the port,
    # the token and the code are all minted per session, so nothing outlives the
    # transfer: a guest who scanned the QR once cannot come back. Remembering
    # turns the bookmarked URL into a standing credential that works whenever the
    # server is running, until it is reset. That is the right trade for your own
    # laptop and the wrong one for a house guest, so it is asked for rather than
    # assumed.
    "transfer_remember": False,
    # The port and token to reuse. Both are recorded from whatever the first
    # remembered session actually bound and minted, rather than hardcoded -- a
    # fixed port would be one more thing to collide with. Cleared by the reset,
    # which is what invalidates every bookmark at once.
    "transfer_port": 0,
    "transfer_token": "",
    # Which launchers.FORMAT_VERSION the scripts on disk were written in, so a
    # fix to how they are generated reaches games that already exist. Written by
    # startup rather than by anyone, and declared here because this dict is what
    # says which keys settings.json has -- one key that was written and read but
    # never listed is one the allowlist below would have dropped.
    "launcher_format": 0,
    # Remembered so the file picker reopens where the user left off.
    "last_rom_dir": "",
    # Remembered per-system so picking a core twice in a row is one tap.
    "last_core_by_ext": {},
}

_lock = threading.Lock()


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    # 0600 before the rename, so the file is never readable at its real name
    # even briefly. settings.json holds the SteamGridDB key, the GitHub token
    # and the RetroAchievements Connect token, which is password-equivalent --
    # the same value launchers.write_override_config already restricts where it
    # writes it. Set unconditionally and on both files: a mode that depends on
    # what is being written is one that will be wrong the first time the
    # contents change, and library.json records where every ROM on the device
    # lives.
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as error:
        decky.logger.warning("Could not restrict %s: %s", path, error)
    os.replace(tmp, path)


def get_settings():
    with _lock:
        stored = _read_json(SETTINGS_PATH, {})
        merged = dict(DEFAULT_SETTINGS)
        if isinstance(stored, dict):
            merged.update(stored)
        return merged


def stored_keys():
    """Which settings were actually written, as opposed to merged in as defaults.

    A new setting needs to tell "this user has never seen it" apart from "this
    user chose what happens to be the default", which get_settings cannot show
    because it merges the two. That is what makes a one-time migration run once.
    """
    stored = _read_json(SETTINGS_PATH, {})
    return set(stored) if isinstance(stored, dict) else set()


#: Settings that existed once and no longer do. Cleared from the stored file on
#: startup rather than left to sit there, because the one that made this
#: necessary was a credential -- and because `get_settings` merges whatever is
#: stored over the defaults, so a key nothing declares any more is still handed
#: to every reader, including the frontend.
REMOVED_SETTINGS = ("github_token",)


def forget_removed():
    """Drop settings that no longer exist. Returns the names actually cleared."""
    with _lock:
        stored = _read_json(SETTINGS_PATH, {})
        if not isinstance(stored, dict):
            return []
        gone = [key for key in REMOVED_SETTINGS if key in stored]
        if not gone:
            return []
        for key in gone:
            del stored[key]
        _write_json(SETTINGS_PATH, stored)
        return gone


def known_only(patch):
    """`patch` reduced to the settings that exist. Returns (kept, dropped).

    Every method on the Plugin class is callable by anything running in Steam's
    JS context, so `set_settings` is reachable with any dict at all and merges
    whatever it is given. Nothing here is privileged, but a settings file that
    accumulates keys nobody reads is one nobody can reason about later.

    It catches the ordinary case as well: a misspelt key is not an error today,
    it is written and silently never read, which looks exactly like the setting
    not working.
    """
    kept, dropped = {}, []
    for key, value in (patch or {}).items():
        if key in DEFAULT_SETTINGS:
            kept[key] = value
        else:
            dropped.append(key)
    return kept, dropped


def set_settings(patch):
    with _lock:
        stored = _read_json(SETTINGS_PATH, {})
        if not isinstance(stored, dict):
            stored = {}
        stored.update(patch or {})
        _write_json(SETTINGS_PATH, stored)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(stored)
        return merged


def get_library():
    """Returns {str(app_id): entry} for everything this plugin has added."""
    data = _read_json(LIBRARY_PATH, {})
    return data if isinstance(data, dict) else {}


def remember_game(app_id, entry):
    with _lock:
        library = _read_json(LIBRARY_PATH, {})
        if not isinstance(library, dict):
            library = {}
        library[str(app_id)] = entry
        _write_json(LIBRARY_PATH, library)


def forget_game(app_id):
    with _lock:
        library = _read_json(LIBRARY_PATH, {})
        if not isinstance(library, dict):
            library = {}
        entry = library.pop(str(app_id), None)
        _write_json(LIBRARY_PATH, library)
        return entry


# Bulk forms of the three above. Each write rewrites the whole registry, so a
# caller looping over the single-game versions pays one full serialise per game
# -- and the startup backfill, adopting a previous install and recording
# collections all loop over the entire library. These do one read and one write
# however many games are involved, which also removes the window where a crash
# part-way through a loop leaves the file half updated.


def remember_games(entries):
    """Record several games at once. `entries` is {app_id: entry}."""
    if not entries:
        return 0
    with _lock:
        library = _read_json(LIBRARY_PATH, {})
        if not isinstance(library, dict):
            library = {}
        for app_id, entry in entries.items():
            library[str(app_id)] = entry
        _write_json(LIBRARY_PATH, library)
        return len(entries)


def forget_games(app_ids):
    """Drop several games at once. Returns {app_id: entry} for what was there."""
    with _lock:
        library = _read_json(LIBRARY_PATH, {})
        if not isinstance(library, dict):
            library = {}
        removed = {}
        for app_id in app_ids or []:
            entry = library.pop(str(app_id), None)
            if entry is not None:
                removed[str(app_id)] = entry
        if removed:
            _write_json(LIBRARY_PATH, library)
        return removed


def clear_library():
    """Forget every game. Returns what was there, since the caller still has to
    undo the Steam side and afterwards nothing remembers which apps those were."""
    with _lock:
        library = _read_json(LIBRARY_PATH, {})
        if not isinstance(library, dict):
            library = {}
        _write_json(LIBRARY_PATH, {})
        return library
