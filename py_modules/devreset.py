"""Putting the Deck back to before this plugin touched it. Development only.

Every button here destroys something, which is the point: testing a first-run
path needs a first run, and by the second week of work no machine has one left.
The alternative is what was happening instead -- reinstalling emulators by hand
over ssh, remembering which of six json files records "already configured", and
discovering three tests later that one of them did not get cleared.

That last failure is the reason this module lists state files explicitly rather
than deleting a directory. `emulator_setup.json` records which config version
each emulator has had applied; leave it behind and a "clean" install skips
every setup block, silently, and the run you were about to trust is a lie.

None of this is reachable in a release. Two independent gates, both off unless
someone builds from source: the frontend tab is compiled out when the build
stamp is not "dev", and `available()` below refuses when CI's build.json is
present. CI asserts the first of those on every build.

Actions are deliberately separate and deliberately not one button. Sent dumps
cost a trip to another machine to replace, and emulator data holds save games;
those are worth their own press and their own sentence about what goes.
"""

import os
import shutil

import decky

import emu_install
import emulator_catalog
import emulators
import fileserver
import romshelf
import launchers
import sysenv


def available(plugin_root):
    """Whether the reset actions may run at all.

    Keyed on CI's build stamp rather than on a setting: a setting can be turned
    on by anyone reading the docs, and this deletes save data. `build.json` is
    written only by the release workflow, so its absence is what "somebody
    built this themselves" looks like.
    """
    return not os.path.isfile(os.path.join(plugin_root, "build.json"))


# ------------------------------------------------------------------ inventory


def _dir_report(path, label):
    """What is in a directory, without deciding anything about it."""
    if not path or not os.path.isdir(path):
        return None
    try:
        entries = os.listdir(path)
    except OSError:
        return None
    if not entries:
        return None
    return {
        "label": label,
        "path": path,
        "items": len(entries),
        "bytes": sysenv.directory_bytes(path),
    }


def _file_report(path, label):
    if not path or not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    return {"label": label, "path": path, "items": 1, "bytes": size}


def _emulator_data_dirs():
    """Where each installed emulator keeps everything it owns.

    A flatpak is easy and needs nothing declared: everything it can write is
    under its application id. An AppImage writes wherever it likes, and the
    catalog has to say so -- see `data` on those entries.

    Deriving the second case from the config file's directory was tried and was
    quietly wrong. RPCS3's catalog entry has no config path at all, so it
    contributed nothing and its 191MB of firmware and games would have survived
    a reset that said it deleted emulator data; Vita3K's config directory is
    24KB of yaml while its games and firmware are 215MB somewhere else. A reset
    that misses most of what it claims to remove is worse than no reset, since
    the next test run inherits state nobody believes is there.
    """
    home = sysenv.user_home()
    found = []
    for entry in emulator_catalog.CATALOG:
        source = entry["source"]
        if source["kind"] == "flatpak":
            relatives = [os.path.join(".var", "app", source["id"])]
        else:
            relatives = list(entry.get("data") or ())
        for relative in relatives:
            path = os.path.join(home, *relative.split("/"))
            if os.path.isdir(path):
                found.append((entry["name"], path))
    return found


# The plugin's own memory. Listed one by one on purpose -- see the note at the
# top of this file about the setup record.
def _state_files():
    settings = decky.DECKY_PLUGIN_SETTINGS_DIR
    return [
        (os.path.join(settings, "library.json"), "Games added to Steam (the plugin's record)"),
        (os.path.join(settings, "emulators.json"), "Registered emulators"),
        (os.path.join(settings, "emulator_setup.json"), "Which config version each emulator has"),
        (os.path.join(settings, "firmware_installed.json"), "What firmware this plugin installed"),
        (os.path.join(settings, "ps3_content_ids.json"), "Recorded PS3 content ids"),
        (os.path.join(settings, "settings.json"), "Plugin settings"),
    ]


def inventory():
    """What each action would delete, before anybody presses anything.

    Sizes rather than a warning, because a warning is easy to click past and
    "3.1 GB across 4 emulators" is not.
    """
    report = {}

    retroarch = []
    home = sysenv.user_home()
    for relative, label in (
        (".var/app/org.libretro.RetroArch", "RetroArch (flatpak data, cores and config)"),
        (".config/retroarch", "RetroArch config"),
    ):
        found = _dir_report(os.path.join(home, *relative.split("/")), label)
        if found:
            retroarch.append(found)
    report["retroarch"] = retroarch

    # Names only: what uninstalling costs is a download, not disk, and the
    # useful thing to show is which ones are about to go.
    report["emulators"] = [
        {"label": entry.get("name") or entry.get("id", ""), "path": entry.get("target", ""),
         "items": 1, "bytes": 0}
        for entry in emulators.list_emulators()
    ]

    data = []
    for name, path in _emulator_data_dirs():
        found = _dir_report(path, "%s data (games, saves, firmware, config)" % name)
        if found:
            data.append(found)
    report["emulator_data"] = data

    transfers = []
    for path, label in (
        # fileserver rather than emu_config: this is the folder uploads land in,
        # and emu_config's equivalent is private to it.
        (fileserver.default_dir(create=False), "Transfer folder (sent, not yet added)"),
        # Filed games, which is a different thing from the inbox and worth its
        # own line: these are the ROMs behind games already in the library, and
        # deleting them leaves shortcuts pointing at nothing.
        (romshelf.library_dir(), "ROMs filed under their system (added games)"),
        (emu_install.firmware_dir(), "Sent BIOS, keys and firmware"),
    ):
        found = _dir_report(path, label)
        if found:
            transfers.append(found)
    report["transfers"] = transfers

    downloads = []
    for path, label in (
        (sysenv.user_dir("emulators", create=False), "Downloaded emulator builds"),
        (sysenv.user_dir("tools", create=False), "Downloaded tools (the PS4 extractor)"),
        (sysenv.user_dir("packages", create=False), "Package links"),
        (sysenv.user_dir("games", create=False), "Unpacked PS4 games"),
    ):
        found = _dir_report(path, label)
        if found:
            downloads.append(found)
    report["downloads"] = downloads

    state = [found for found in
             (_file_report(path, label) for path, label in _state_files()) if found]
    launcher_dir = _dir_report(launchers.LAUNCHER_DIR, "Launcher scripts")
    if launcher_dir:
        state.append(launcher_dir)
    thumbs = _dir_report(
        os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "thumb_index"), "Cached artwork")
    if thumbs:
        state.append(thumbs)
    report["state"] = state

    return report


# -------------------------------------------------------------------- actions


def _wipe(path):
    """Delete a directory's contents, keeping the directory. Returns bytes."""
    if not path or not os.path.isdir(path):
        return 0
    freed = 0
    for name in os.listdir(path):
        target = os.path.join(path, name)
        try:
            size = (sysenv.directory_bytes(target) if os.path.isdir(target)
                    else os.path.getsize(target))
        except OSError:
            size = 0
        try:
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
        except OSError as error:
            decky.logger.warning("Could not delete %s: %s", target, error)
            continue
        freed += size
    return freed


def _remove(path):
    """Delete a directory outright. Returns bytes."""
    if not path or not os.path.isdir(path):
        return 0
    freed = sysenv.directory_bytes(path)
    try:
        shutil.rmtree(path)
    except OSError as error:
        decky.logger.warning("Could not delete %s: %s", path, error)
        return 0
    return freed


def clear_transfers():
    """Empty the folders ROMs live in. Sent dumps included -- see the note.

    Both the inbox and the filed library, because a reset that left the second
    behind would leave most of the disk in use and every added game still
    playable, which is not what the button says.
    """
    freed = _wipe(fileserver.default_dir(create=False))
    freed += _wipe(romshelf.library_dir())
    freed += _wipe(emu_install.firmware_dir())
    freed += _remove(sysenv.user_dir("packages", create=False))
    return freed


def clear_retroarch_data():
    """RetroArch's own directory, which a flatpak uninstall leaves behind.

    Cores, the system folder holding BIOS files, every config override and the
    playlists. Uninstalling without this leaves a reinstall arriving fully
    configured, which is the opposite of what a reset is for.
    """
    home = sysenv.user_home()
    freed = _remove(os.path.join(home, ".var", "app", "org.libretro.RetroArch"))
    freed += _remove(os.path.join(home, ".config", "retroarch"))
    return freed


def clear_downloads():
    freed = _remove(sysenv.user_dir("emulators", create=False))
    freed += _remove(sysenv.user_dir("tools", create=False))
    freed += _remove(sysenv.user_dir("games", create=False))
    return freed


def clear_emulator_data():
    """Delete what the emulators themselves own. This includes save games."""
    freed = 0
    for name, path in _emulator_data_dirs():
        gone = _remove(path)
        if gone:
            decky.logger.info("Cleared %s data (%d bytes)", name, gone)
        freed += gone
    return freed


def clear_state():
    """Forget everything the plugin remembers.

    The setup record is the one that matters and the one most easily missed: a
    fresh install that still believes every emulator is configured applies no
    setup block at all, and the bug you were testing for stays hidden.
    """
    freed = 0
    for path, _ in _state_files():
        try:
            freed += os.path.getsize(path)
            os.remove(path)
        except OSError:
            continue
    freed += _remove(launchers.LAUNCHER_DIR)
    freed += _remove(os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "thumb_index"))
    # Nothing to invalidate afterwards: every one of these files is read from
    # disk on each access rather than cached in the module. The one live copy
    # anywhere is the plugin's list of emulators, and its caller refreshes it.
    return freed
