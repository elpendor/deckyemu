"""A Switch game's updates and DLC, kept by this plugin and handed to Ryujinx.

Ryujinx reads a game's updates and DLC from two files, `updates.json` and
`dlc.json`, in a folder per game under its config directory -- at every boot,
whatever started it. Its own "Autoadd DLC/Game Updates" folders cannot serve a
Steam shortcut: that scan runs only when Ryujinx's game list loads, and a launch
with a ROM path never loads the list. So the two files are written here,
whenever a game's list changes.

The packages live in `~/deckyemu/updates-dlc/<app id>/`, a folder per game the
way ROM hacks keep theirs, and never beside the ROM: a ROM may sit in a folder
this plugin does not own. Nothing is recorded next to them. Each is read again
when listed -- a few kilobytes of header -- so no record can disagree with the
folder.

**Entries this plugin did not write are kept.** An update added through
Ryujinx's own window stays; what is replaced is only what came from this game's
folder here, plus anything pointing at a file that no longer exists, which
Ryujinx itself drops the same way.
"""

import json
import os
import re
import shutil

import decky

import emulator_catalog
import emulators
import switch_content
import switch_nsz
import sysenv

#: NSPs, and NSZs, which Ryujinx cannot read and so are kept as the `.nsp`
#: they unpack into. An XCI update is not something anybody distributes.
SUFFIXES = (".nsp", ".nsz")

#: What a Switch game itself can arrive as, for finding its updates beside it.
GAME_SUFFIXES = (".nsp", ".xci", ".nsz")

_SAFE_APP = re.compile(r"^[0-9]{1,20}$")
_TITLE_ID = re.compile(r"^[0-9a-f]{16}$")


def store_dir(app_id, create=True):
    """Where this game's updates and DLC are kept, or "" for an unusable id."""
    if not _SAFE_APP.match(str(app_id or "")):
        return ""
    return sysenv.user_dir("updates-dlc", str(app_id), create=create)


def games_root_for(core_id):
    """Where a game's emulator reads updates and DLC, or "" when it has nowhere.

    Asked of the catalog rather than known here, so an emulator gains this by
    declaring `game_content` and nothing else has to learn about it.
    """
    if not emulators.is_emulator_id(core_id or ""):
        return ""
    entry = emulator_catalog.find(emulators.emulator_id(core_id)) or {}
    spec = entry.get("game_content") or {}
    if spec.get("format") != "ryujinx" or not spec.get("path"):
        return ""
    return os.path.join(sysenv.user_home(), spec["path"])


def _version_key(row):
    try:
        parts = tuple(int(part) for part in row["version"].split(".")) if row["version"] else ()
    except ValueError:
        parts = ()
    release = row.get("release")
    return (release if release is not None else -1, parts, row["file"])


def listing(app_id):
    """Every update and DLC kept for this game: the newest update first, then DLC."""
    directory = store_dir(app_id, create=False)
    if not directory or not os.path.isdir(directory):
        return []
    updates, dlcs = [], []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not name.lower().endswith(SUFFIXES) or not os.path.isfile(path):
            continue
        found = switch_content.inspect(path)
        row = dict(found, file=name, path=path)
        if found["kind"] == switch_content.UPDATE:
            updates.append(row)
        elif found["kind"] == switch_content.DLC:
            dlcs.append(row)
    updates.sort(key=_version_key, reverse=True)
    return updates + dlcs


def rows(app_id):
    """The listing as the editor shows it."""
    shown = []
    newest_update = True
    for row in listing(app_id):
        if row["kind"] == switch_content.UPDATE:
            label = "Update v%s" % row["version"] if row["version"] else "Update"
            # Ryujinx runs one update at a time. The others are kept, not used.
            used, newest_update = newest_update, False
        else:
            label, used = "DLC", True
        try:
            size = os.path.getsize(row["path"])
        except OSError:
            size = 0
        shown.append({"file": row["file"], "label": label, "kind": row["kind"],
                      "size": size, "used": used})
    return shown


def check(path, base_id):
    """What `path` is, or why it cannot be installed for the game `base_id`.

    Returns `(found, error)`.
    """
    if not path or not os.path.isfile(path):
        return None, "That file is not there."
    if not path.lower().endswith(SUFFIXES):
        return None, "Only .nsp and .nsz files can be installed as an update or DLC."
    found = switch_content.inspect(path)
    if found["kind"] == switch_content.BASE:
        return None, "That is a game, not an update or DLC. Add it as a game instead."
    if found["kind"] not in (switch_content.UPDATE, switch_content.DLC):
        return None, ("Could not tell what that file is. It does not look like a "
                      "Switch update or DLC.")
    if found["kind"] == switch_content.DLC and not found["data_ncas"]:
        return None, "That DLC package has nothing in it to install."
    if found["base_id"] != base_id:
        what = "update" if found["kind"] == switch_content.UPDATE else "DLC"
        return None, "That %s is for a different game." % what
    return found, ""


def _free_name(directory, name):
    stem, suffix = os.path.splitext(name)
    candidate, count = name, 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = "%s (%d)%s" % (stem, count, suffix)
        count += 1
    return candidate


def add(app_id, path, base_id, inbox, progress=None):
    """Keep an update or DLC for this game. Returns `(row, error)`.

    Moved out of the transfer folder, the way a ROM is when its game is added:
    these run to gigabytes, and a second copy of each is too high a price for
    leaving the folder alone. From anywhere else it is copied, because a file
    somebody keeps in a place of their own is not this plugin's to move.
    """
    found, error = check(path, base_id)
    if error:
        return None, error
    directory = store_dir(app_id)
    if not directory:
        return None, "That game cannot hold updates or DLC."

    name = os.path.basename(path)
    from_inbox = bool(inbox) and (
        os.path.dirname(os.path.realpath(path)) == os.path.realpath(inbox))
    if name.lower().endswith(".nsz"):
        return _keep_unpacked(app_id, path, found, directory, from_inbox, progress)

    kept = os.path.join(directory, name)
    if os.path.isfile(kept) and os.path.getsize(kept) == os.path.getsize(path):
        # The same package sent a second time. The one already kept is it.
        if from_inbox:
            try:
                os.remove(path)
            except OSError as remove_error:
                decky.logger.warning("Could not clear %s from the inbox: %s",
                                     path, remove_error)
        return dict(found, file=name, path=kept), ""

    name = _free_name(directory, name)
    target = os.path.join(directory, name)
    try:
        if from_inbox:
            shutil.move(path, target)
        else:
            shutil.copyfile(path, target)
    except OSError as move_error:
        # Part of a package is not a package.
        try:
            os.remove(target)
        except OSError:
            pass
        return None, "Could not keep %s: %s" % (os.path.basename(path), move_error)

    decky.logger.info("Kept %s %s for app %s (%s)", found["kind"], name, app_id,
                      "moved" if from_inbox else "copied")
    return dict(found, file=name, path=target), ""


def _keep_unpacked(app_id, path, found, directory, from_inbox, progress):
    """`add` for an .nsz: unpacked straight into the folder it is kept in.

    What is kept is the `.nsp`, since nothing here reads the compressed one.
    Written where it stays rather than into the transfer folder and moved, which
    would write the same gigabytes a second time. From the transfer folder the
    `.nsz` goes afterwards, and may be used up on the way when that is the only
    way it fits; from anywhere else it is left exactly as it was.
    """
    name, size, error = switch_nsz.plan(path)
    if error:
        return None, error
    kept = os.path.join(directory, name)
    if not (os.path.isfile(kept) and os.path.getsize(kept) == size):
        name = _free_name(directory, name)
        _written, error = switch_nsz.into_folder(
            path, directory, progress, name=name, use_up=from_inbox)
        if error:
            return None, error
        kept = os.path.join(directory, name)
        decky.logger.info("Kept %s %s for app %s (unpacked from %s)", found["kind"], name,
                          app_id, os.path.basename(path))
    # Otherwise the same package, sent a second time and already kept.
    if from_inbox:
        try:
            os.remove(path)
        except OSError as remove_error:
            decky.logger.warning("Could not clear %s from the inbox: %s", path, remove_error)
    return dict(switch_content.inspect(kept), file=name, path=kept), ""


def remove(app_id, stored):
    """Delete one kept package. Returns an error or ""."""
    directory = store_dir(app_id, create=False)
    name = os.path.basename(stored or "")
    if not directory or not name:
        return "That file is not one of this game's."
    try:
        os.remove(os.path.join(directory, name))
    except FileNotFoundError:
        pass
    except OSError as error:
        return "Could not delete %s: %s" % (name, error)
    return ""


def _inside(path, folder):
    if not folder:
        return False
    try:
        root = os.path.realpath(folder)
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:
        return False


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _write_json(path, value):
    temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return "Could not write %s: %s" % (os.path.basename(path), error)
    return ""


def sync(app_id, base_id, games_root):
    """Rewrite Ryujinx's `updates.json` and `dlc.json` for one game.

    Returns an error or "". The newest update kept here becomes the one Ryujinx
    runs -- installing one is asking for it -- and every DLC is on unless
    somebody switched it off in Ryujinx's own window, which is carried over.
    """
    if not games_root or not _TITLE_ID.match(base_id or ""):
        return "Could not tell which game to write updates for."
    ours = store_dir(app_id, create=False)
    kept = [row for row in listing(app_id) if row["base_id"] == base_id]
    updates = [row["path"] for row in kept if row["kind"] == switch_content.UPDATE]
    dlcs = [row for row in kept if row["kind"] == switch_content.DLC]

    folder = os.path.join(games_root, base_id)
    updates_path = os.path.join(folder, "updates.json")
    dlc_path = os.path.join(folder, "dlc.json")

    def theirs(path):
        return isinstance(path, str) and not _inside(path, ours) and os.path.isfile(path)

    existing = _read_json(updates_path, {})
    others = [path for path in existing.get("paths") or [] if theirs(path)]
    selected = existing.get("selected")
    if updates:
        selected = updates[0]
    elif not theirs(selected):
        selected = ""
    updates_body = {"selected": selected,
                    "paths": updates + [path for path in others if path not in updates]}

    previous = _read_json(dlc_path, [])
    enabled = {}
    for container in previous:
        if not isinstance(container, dict):
            continue
        for nca in container.get("dlc_nca_list") or []:
            if isinstance(nca, dict):
                enabled[(container.get("path"), nca.get("path"))] = nca.get("is_enabled", True)
    containers = [
        {
            "path": row["path"],
            "dlc_nca_list": [
                {"path": nca, "title_id": int(row["title_id"], 16),
                 "is_enabled": bool(enabled.get((row["path"], nca), True))}
                for nca in row["data_ncas"]
            ],
        }
        for row in dlcs
    ]
    containers += [one for one in previous
                   if isinstance(one, dict) and theirs(one.get("path"))]

    writes = [
        (updates_path, updates_body, bool(updates_body["paths"] or selected)),
        (dlc_path, containers, bool(containers)),
    ]
    writes = [(path, body) for path, body, wanted in writes
              if wanted or os.path.exists(path)]
    if not writes:
        return ""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        return "Could not reach Ryujinx's folder for this game: %s" % error
    for path, body in writes:
        problem = _write_json(path, body)
        if problem:
            return problem
    return ""


def footprint(app_id):
    """(bytes, count) kept for a game, for the dialog that removes it."""
    total, count = 0, 0
    for row in listing(app_id):
        try:
            total += os.path.getsize(row["path"])
        except OSError:
            continue
        count += 1
    return total, count


def forget(app_id, games_root):
    """Delete everything kept for a game being removed. Returns bytes freed.

    Ryujinx's files are rewritten afterwards, so they stop naming packages that
    are gone; entries it did not get from here are left as they were.
    """
    kept = listing(app_id)
    freed, _count = footprint(app_id)
    directory = store_dir(app_id, create=False)
    if directory and os.path.isdir(directory):
        shutil.rmtree(directory, ignore_errors=True)
    for base_id in {row["base_id"] for row in kept}:
        problem = sync(app_id, base_id, games_root) if games_root else ""
        if problem:
            decky.logger.warning("Could not tidy Ryujinx's list for %s: %s",
                                 base_id, problem)
    if kept:
        decky.logger.info("Deleted %d update(s) and DLC for app %s, freeing %d bytes",
                          len(kept), app_id, freed)
    return freed


#: Header reads remembered by path, size and modification time. The transfer
#: dialog asks every few seconds, about every `.nsp` waiting and every Switch
#: game in the library, and none of those files change between asks.
_INSPECTED: dict = {}
_INSPECTED_MAX = 256


def _inspect(path):
    try:
        info = os.stat(path)
    except OSError:
        return switch_content.inspect(path)
    key = (path, info.st_size, int(info.st_mtime))
    found = _INSPECTED.get(key)
    if found is None:
        if len(_INSPECTED) >= _INSPECTED_MAX:
            _INSPECTED.clear()
        found = _INSPECTED[key] = switch_content.inspect(path)
    return found


def owner(path, library):
    """Which added game an update or DLC belongs to, or None for anything else.

    `{kind, label, app_id, title, problem}`. `app_id` is 0 when no game in the
    library is the one this file is for, and `problem` then says so -- an update
    whose game has not been added has nowhere to go, and the panel says that
    rather than offering Install.

    What lets a file sent to the Deck offer **Install** without asking which
    game: an update or DLC names its game, unlike a ROM hack.
    """
    if not (path or "").lower().endswith(SUFFIXES):
        return None
    found = _inspect(path)
    if found["kind"] not in (switch_content.UPDATE, switch_content.DLC):
        return None
    if found["kind"] == switch_content.UPDATE:
        label = "Update v%s" % found["version"] if found["version"] else "Update"
    else:
        label = "DLC"

    games = sorted((library or {}).values(), key=lambda entry: entry.get("title", "").lower())
    for entry in games:
        if not entry.get("app_id") or not games_root_for(entry.get("core_id", "")):
            continue
        if _inspect(entry.get("rom_path", ""))["base_id"] == found["base_id"]:
            return {"kind": found["kind"], "label": label, "app_id": entry["app_id"],
                    "title": entry.get("title", ""), "problem": ""}
    return {
        "kind": found["kind"], "label": label, "app_id": 0, "title": "",
        "problem": "The game this is for has not been added yet. Add the game "
                   "first, then install this.",
    }


def waiting_for(rom_path):
    """Updates and DLC for this game sitting in the same folder, to install with it.

    `[{path, name, label}]`, newest update first. The same folder and nowhere
    else, which is how a game arrives with its updates: sent together, landing
    side by side in the transfer folder. Looking further would be deciding what
    somebody meant by files they keep elsewhere.
    """
    base_id = _inspect(rom_path or "")["base_id"] if rom_path else ""
    if not base_id or _inspect(rom_path)["kind"] != switch_content.BASE:
        return []
    folder = os.path.dirname(rom_path)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(folder, name)
        if not name.lower().endswith(SUFFIXES) or not os.path.isfile(path):
            continue
        one = _inspect(path)
        if one["kind"] not in (switch_content.UPDATE, switch_content.DLC):
            continue
        if one["base_id"] != base_id:
            continue
        if one["kind"] == switch_content.UPDATE:
            label = "Update v%s" % one["version"] if one["version"] else "Update"
        else:
            label = "DLC"
        found.append(dict(one, path=path, name=name, label=label, file=name))
    updates = sorted((row for row in found if row["kind"] == switch_content.UPDATE),
                     key=_version_key, reverse=True)
    dlcs = [row for row in found if row["kind"] == switch_content.DLC]
    return [{"path": row["path"], "name": row["name"], "label": row["label"]}
            for row in updates + dlcs]
