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


def _emulator_data_dirs(entry_ids=None):
    """Where each installed emulator keeps everything it owns.

    `entry_ids` narrows it to those catalog ids, which is what the uninstall
    action needs: it deletes the data of the emulators it actually removed, and
    must leave alone the one it was refused -- a system-wide install belongs to
    root and is still there afterwards, so taking its saves would destroy data
    for an emulator the reset could not touch.

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
        if entry_ids is not None and entry["id"] not in entry_ids:
            continue
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
        # Which Steam collections this plugin made. Left behind, a reset would
        # go on claiming shelves for games it no longer has any record of --
        # and offering to delete them.
        (os.path.join(settings, "collections.json"), "Collections this plugin made"),
        (os.path.join(settings, "settings.json"), "Plugin settings"),
    ]


def _runtime_leftovers():
    """[(path, label, is_dir)] the plugin wrote into decky's runtime directory.

    `clear_state` used to name the launcher scripts and the artwork cache and
    stop there, which left two thirds of that directory standing after an action
    called "forget everything the plugin knows". Worse, what it left was the
    generated half: RetroArch override configs baked from settings that had just
    been deleted, and a pad profile written for them. A reinstall then read
    values nothing in the plugin remembered writing, which is the exact failure
    the state reset exists to rule out while testing.

    Derived from the modules that write them, not typed out again -- the list of
    override files has already grown once, and a copy here would have gone stale
    silently.
    """
    runtime = decky.DECKY_PLUGIN_RUNTIME_DIR
    items = [
        (launchers.LAUNCHER_DIR, "Launcher scripts", True),
        (os.path.join(runtime, "thumb_index"), "Cached artwork", True),
        # The pad profile RetroArch is pointed at for games launched from here.
        (launchers.AUTOCONFIG_DIR, "Controller profile", True),
        # The pad profile RetroArch is pointed at for games launched from here.

        # Short-named symlinks for emulators that re-split a path on its spaces.
        # Dangling once the ROMs they point at are gone, which is the same reset.
        (emulators.ARG_LINK_DIR, "Package links for launch arguments", True),
        # The libretro database and buildbot listing. A cache, so keeping it is
        # harmless in use and wrong here: a reset that leaves it means the next
        # run never exercises the first fetch, which is a thing worth testing.
        (os.path.join(runtime, "installer"), "Cached core catalog", True),
    ]
    # Every OSD mode's override file, plus the legacy one left for launchers
    # written before the split.
    for path in list(launchers.OVERRIDE_CONFIGS.values()) + [launchers.OVERRIDE_CONFIG]:
        items.append((path, "RetroArch override config", False))
    # An update downloaded and handed to decky. Named from the release asset, so
    # it is found rather than assumed.
    try:
        for name in sorted(os.listdir(runtime)):
            if name.lower().endswith(".zip"):
                items.append((os.path.join(runtime, name), "Staged update", False))
    except OSError:
        pass
    return items


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

    data = []
    for name, path in _emulator_data_dirs():
        found = _dir_report(path, "%s data (games, saves, firmware, config)" % name)
        if found:
            data.append(found)
    report["emulator_data"] = data

    # The emulators themselves carry no size -- uninstalling one costs a
    # download, not disk -- and the useful thing to show is which ones are about
    # to go. Their data is listed with them because the action deletes it too,
    # and that half is the irreversible half: a dialog that named four emulators
    # and no save directory would be the one place this destroys something
    # without saying so.
    report["emulators"] = [
        {"label": entry.get("name") or entry.get("id", ""), "path": entry.get("target", ""),
         "items": 1, "bytes": 0}
        for entry in emulators.list_emulators()
    ] + data

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
    # Same list the action deletes from, so the panel cannot promise less than
    # it takes. It said "Launcher scripts, Cached artwork" while removing those
    # two and nothing else -- honest at the time, and it stopped being honest
    # the moment anything else was added.
    for path, label, is_dir in _runtime_leftovers():
        found = _dir_report(path, label) if is_dir else _file_report(path, label)
        if found:
            state.append(found)
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
    if freed:
        decky.logger.info("Reset: emptied %s (%d bytes)", path, freed)
    return freed


def _remove(path):
    """Delete a directory outright. Returns bytes.

    Says what it deleted. Every one of these is somebody's install, ROM library
    or configuration, and the log is the only record afterwards -- a reset is
    the one action on this plugin whose effects are most easily mistaken for a
    bug days later. Removing RetroArch's directory here is what made a later
    "install this core" do nothing, and nothing in the log connected the two.
    """
    if not path or not os.path.isdir(path):
        return 0
    freed = sysenv.directory_bytes(path)
    try:
        shutil.rmtree(path)
    except OSError as error:
        decky.logger.warning("Could not delete %s: %s", path, error)
        return 0
    decky.logger.info("Reset: removed %s (%d bytes)", path, freed)
    return freed


def _remove_file(path):
    """Delete one generated file. Returns bytes. Named in the log, like _remove."""
    if not path or not os.path.isfile(path):
        return 0
    try:
        freed = os.path.getsize(path)
        os.remove(path)
    except OSError as error:
        decky.logger.warning("Could not delete %s: %s", path, error)
        return 0
    decky.logger.info("Reset: removed %s (%d bytes)", path, freed)
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


def clear_emulator_data(entry_ids=None):
    """Delete what the emulators themselves own. This includes save games.

    All of them by default; `entry_ids` restricts it to those catalog ids. The
    uninstall action passes a list because it must not touch what it could not
    remove -- see `_emulator_data_dirs`.
    """
    freed = 0
    for name, path in _emulator_data_dirs(entry_ids):
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

    Every file removed is named in the log, and that is not decoration. This
    deletes settings.json, and the next startup writes part of it back -- worth
    knowing before reading a log, because a setting that appears to have changed
    itself usually changed here. `_pin_collection_layout` was the worst of them:
    it found no stored `collection_per_platform` and a library full of games and
    pinned the layout to one shared collection, which is indistinguishable from
    the setting turning itself off. It decides from what the games are actually
    filed into now, so a reset no longer flips it. Chasing the original took a
    session, because the step that caused it removed the file with a bare
    os.remove and said nothing. A destructive action nobody can see afterwards
    is one nobody can reason about.
    """
    freed = 0
    cleared = []
    for path, label in _state_files():
        try:
            freed += os.path.getsize(path)
            os.remove(path)
        except OSError:
            continue
        cleared.append(label)
    if cleared:
        decky.logger.info("Reset: cleared %s", ", ".join(cleared))
    for path, _label, is_dir in _runtime_leftovers():
        freed += _remove(path) if is_dir else _remove_file(path)
    # Nothing to invalidate afterwards: every one of these files is read from
    # disk on each access rather than cached in the module. The one live copy
    # anywhere is the plugin's list of emulators, and its caller refreshes it.
    return freed
