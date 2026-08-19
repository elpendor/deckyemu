"""Getting the user's own BIOS files and keys from the Deck into an emulator.

Transfer already solves the hard half: a file reaches `~/deckyemu/firmware` from
another device over a QR code or a six-digit code, with no cable and no Desktop
Mode. What was missing is the last step, because every emulator reads its
firmware from somewhere else, and leaving the files in a folder the emulator
never looks at is not an install.

**Matching is done on the filename**, which is what keeps this free of typing and
of file pickers: the user sends `scph39001.bin` and the panel already knows it is
a PS2 BIOS and that PCSX2 wants it. The one real trap is that a PS1 and a PS2
BIOS are both called `scph<digits>.bin` -- four digits for the PS1, five for the
PS2 -- so the two patterns differ only in that count. Get it wrong and a PS1 BIOS
lands in PCSX2, where it silently does nothing.

**Installing moves the file, and removing it deletes it.** Copying was tried
first and left the transfer folder holding a duplicate of every BIOS ever sent
-- a PS3 firmware PUP is a couple of hundred megabytes -- which then needed a
whole panel to explain which duplicates were safe to delete. One file in one
place is the simpler arrangement, and the cost is stated where it lands: the
confirm dialog says the file is gone and has to be sent again.

**Nothing is ever overwritten.** A file already present at the destination is
reported rather than replaced, because the user may have put a better dump there
by hand.

Requirements an emulator has to import itself -- RPCS3's PUP, a Switch firmware
archive -- are not copied anywhere, because the emulator unpacks them into a
layout of its own. Those carry one of two things instead of `dest`:

  `import`  the emulator can do it unattended, so this plugin runs it. RPCS3
            takes `--headless --installfw` and unpacks the PS3 firmware in about
            six seconds with no window and nothing to press.
  `manual`  it cannot, so the row says which one step is left. Still detected
            and still reported, because "you have the file, here is the step"
            is worth far more than silence.

An imported requirement reports as installed by looking at what the emulator
actually produced -- `dev_flash/vsh/etc/version.txt` for RPCS3 -- rather than by
remembering that a button was pressed.
"""

import json
import os
import posixpath
import re
import shutil
import zipfile

import decky

import emu_config
import emu_install
import net
import sysenv

# What this plugin moved where, so removing an install can tell its own work
# from a file the user put there by hand. Same reasoning as
# `emu_config.STATE_PATH`: without a record, the only way to undo something is
# to take away whatever is sitting at the destination, and a BIOS somebody
# placed themselves is exactly the wrong thing to move out from under them.
STATE_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "firmware_installed.json")


def _read_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except OSError as error:
        # The copy still happened; the only cost is that a later removal has to
        # say it cannot tell whose file it is.
        decky.logger.warning("Could not record what was installed: %s", error)


def _recorded(entry_id, requirement_name):
    return _read_state().get(entry_id, {}).get(requirement_name, [])

# The cap stops a stray ROM in the folder from being scanned as firmware. It was
# 64MB, written when everything here was a BIOS image or a key file -- and that
# made every console firmware invisible: a PS Vita PUP is 128MB and a PS3 one is
# around 200MB, so neither ever appeared as waiting and neither Install button
# could ever have been offered. Found by asking the backend why a row with a
# 128MB PUP beside it reported nothing ready.
#
# The number is now above the largest thing that legitimately belongs here
# rather than below the smallest. It is still a cap: nothing in this folder
# should be a disc image.
MAX_FIRMWARE_BYTES = 512 * 1024 * 1024


def available(directory=None):
    """Files sitting in the firmware folder, newest first."""
    directory = directory or emu_install.firmware_dir()
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        return found

    for name in sorted(names):
        path = os.path.join(directory, name)
        try:
            info = os.stat(path)
        except OSError:
            continue
        if not os.path.isfile(path) or info.st_size > MAX_FIRMWARE_BYTES:
            continue
        found.append({"name": name, "size": info.st_size, "modified": int(info.st_mtime)})

    found.sort(key=lambda item: item["modified"], reverse=True)
    return found


def under_home(relative):
    """`relative` resolved against the user's home, or '' if it escapes it.

    So a malformed catalog entry cannot name a path outside the user's own
    directory -- these are read from a table and then written to and deleted.
    """
    if not relative:
        return ""

    home = os.path.normpath(sysenv.user_home())
    # posixpath, because these are written as target-system paths and os.path
    # mangles them on Windows, where the tests run.
    target = os.path.normpath(os.path.join(home, *posixpath.normpath(relative).split("/")))
    if target != home and not target.startswith(home + os.sep):
        decky.logger.error("Refusing firmware path outside the home: %s", relative)
        return ""
    return target


def _destination(requirement):
    """Absolute path a requirement's files belong in, or ''."""
    return under_home(requirement.get("dest") or "")


def _size_of(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _dest_name(requirement, name):
    """What a file is called once it is in place, which is not always its name.

    RPCS3 reads a game licence only from a lowercase `.rap`, and says so in the
    one message nobody sees: it prints the instruction when the game fails to
    boot, long after the file was put somewhere that looked right. A `.RAP` sent
    from a phone that helpfully uppercased it would sit at the destination,
    report as installed, and decrypt nothing.
    """
    if not requirement.get("lower_ext"):
        return name
    stem, extension = os.path.splitext(name)
    return stem + extension.lower()


def _matching(requirement, files):
    pattern = requirement.get("match")
    if not pattern:
        return []
    try:
        matcher = re.compile(pattern)
    except re.error as error:
        decky.logger.warning("Bad firmware pattern %r: %s", pattern, error)
        return []

    # Size, where the filename cannot do the job. The Xbox pair is the case:
    # an MCPX boot ROM and an Xbox BIOS are both a .bin under whatever name the
    # dumper chose, and telling them apart by name is impossible -- but an MCPX
    # ROM is exactly 512 bytes and a BIOS is 256KB or more, so the file itself
    # says which it is. Applied only where a requirement asks for it, and only
    # against files whose size is known.
    sizes = requirement.get("sizes")
    return [
        item["name"]
        for item in files
        if matcher.match(item["name"])
        and (not sizes or item.get("size") in sizes)
    ]


# A stub is only ever a small text file the emulator wrote for the user to fill
# in. Reading more than this would mean a real dump is being scanned line by line
# for no reason.
MAX_STUB_BYTES = 64 * 1024


def _is_stub(path, stub):
    """Whether `path` is the empty file the emulator created, not a real dump.

    Some emulators create their own placeholder on first run. Cemu writes
    keys.txt with three comment lines and one example key the moment it starts,
    so the file exists before the user has supplied anything -- and without this
    the panel reports it as in place, offers no way to send a real one, and the
    game still will not decrypt.

    A stub declares which lines carry nothing (`empty`) and which the emulator
    wrote itself (`written`). Any other line means somebody put something real in
    there, and the file stops being ours to touch.
    """
    if not stub:
        return False
    try:
        if os.path.getsize(path) > MAX_STUB_BYTES:
            return False
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return False

    empty = re.compile(stub["empty"])
    written = [re.compile(pattern) for pattern in stub.get("written", ())]
    for line in lines:
        if empty.match(line):
            continue
        if any(pattern.match(line) for pattern in written):
            continue
        return False
    return True


def _filled(directory):
    """Whether a directory exists and has anything in it.

    Emptiness rather than absence is the test: the folder an emulator unpacks
    firmware into is usually created before any firmware arrives, so "it is
    there" answers nothing.
    """
    if not directory:
        return False
    try:
        return any(os.scandir(directory))
    except OSError:
        return False


def _installed_at(requirement, destination, recorded=()):
    """Files matching `requirement` that are sitting at the destination.

    Recorded names are included even when they do not match the pattern, so a
    pattern narrowed in a later version cannot orphan a file this plugin put
    there and can no longer see.
    """
    if not destination:
        return []
    try:
        present = os.listdir(destination)
    except OSError:
        return []
    # Sized, because a requirement that matches on size has to be able to
    # recognise its own installed file. Without this, `sizes` would make every
    # destination look empty and the row would offer to install forever.
    matched = set(
        _matching(
            requirement,
            [
                {"name": name, "size": _size_of(os.path.join(destination, name))}
                for name in present
            ],
        )
    )
    found = matched | (set(recorded) & set(present))
    stub = requirement.get("stub")
    if stub:
        # The emulator's own placeholder is not something the user supplied, so
        # it must not read as installed.
        found = {
            name for name in found
            if not _is_stub(os.path.join(destination, name), stub)
        }
    return sorted(found)


# The marker an emulator leaves behind is a text file it wrote itself; nothing
# here needs more than the first few lines of it.
MAX_MARKER_BYTES = 64 * 1024


def imported(spec, fallback=""):
    """What an `import` requirement has actually produced, as a label list.

    Empty when the emulator has not run it yet. The label is read out of the
    emulator's own output -- RPCS3 writes `release:04.9300:` into
    `dev_flash/vsh/etc/version.txt` -- so the row can say *which* firmware is
    installed rather than only that one is.

    `fallback` is what to say when there is nothing to read. Vita3K records no
    version anywhere, and its marker is `psp2bootconfig.skprx`, which is not a
    thing to show anybody -- the requirement's own name is.
    """
    marker = under_home(spec.get("installed") or "")
    if not marker or not os.path.isfile(marker):
        return []

    pattern = spec.get("label") or ""
    if pattern:
        try:
            if os.path.getsize(marker) <= MAX_MARKER_BYTES:
                with open(marker, "r", encoding="utf-8", errors="replace") as handle:
                    match = re.search(pattern, handle.read())
                if match:
                    return [match.group(1) if match.groups() else match.group(0)]
        except (OSError, re.error) as error:
            decky.logger.warning("Could not read %s: %s", marker, error)

    return [fallback or os.path.basename(marker)]


def find_requirement(entry, requirement_name):
    """One named requirement out of a catalog entry, or None.

    Not called `requirement`: `install` and `uninstall` both use that name for
    the dict itself, and a module-level function of the same name would make
    every one of those a local variable and the lookup an UnboundLocalError.
    """
    return next(
        (
            item
            for item in (entry.get("firmware") or [])
            if item.get("name") == requirement_name
        ),
        None,
    )


def matching(spec, files=None):
    """Filenames in the firmware folder that satisfy `spec`."""
    return _matching(spec, available() if files is None else files)


def status(entry, files=None):
    """What `entry` still needs, and what is already here for it.

    Returns a list of requirement dicts the UI can render without knowing any of
    the rules: each says whether files are waiting, whether they are already in
    place, and whether installing is something this plugin can do at all.
    """
    files = available() if files is None else files
    report = []

    for requirement in entry.get("firmware") or []:
        matched = _matching(requirement, files)
        importer = requirement.get("import")
        detect = requirement.get("detect")

        if detect and not importer:
            # A requirement the emulator installs through its own interface.
            # Nothing was copied, so there is no file of ours to look for --
            # only the folder it fills, and whether anything is in it. Ryujinx
            # writes 238 hash-named .nca directories there, so the count is the
            # answer and the names are not worth reading.
            destination = under_home(detect.get("path") or "")
            installed = [detect.get("label") or "installed"] if _filled(destination) else []
            foreign = []
        elif importer:
            # Nothing is copied and nothing is recorded: the emulator unpacked
            # the file into a layout of its own, so the only honest answer to
            # "is it installed" is whatever it left behind.
            destination = under_home(importer.get("installed") or "")
            installed = imported(importer, requirement.get("name", ""))
            foreign = []
        else:
            destination = _destination(requirement)

            # Read from the destination, not from what happens to be in the
            # transfer folder. Deriving it from the sent files meant a file
            # placed by hand was invisible, and -- worse -- deleting the sent
            # copy made an installed file stop reporting as installed.
            ours = set(_recorded(entry.get("id", ""), requirement.get("name", "")))
            installed = _installed_at(requirement, destination, ours)

            # Anything at the destination this plugin did not put there. Removal
            # is still offered -- otherwise a file installed before the record
            # existed could never be undone -- but the user is told first.
            foreign = [name for name in installed if name not in ours]

        report.append(
            {
                "name": requirement.get("name", ""),
                "note": requirement.get("note", ""),
                # What the match pattern will actually accept, in words. Without
                # it the naming rule is invisible: a PS2 BIOS under any other
                # name is simply never recognised, with nothing said about why.
                "expects": requirement.get("expects", ""),
                # Present when the emulator has to import the file itself.
                "manual": requirement.get("manual", ""),
                # Shown so a wrong path is visible rather than silent -- these
                # are flatpak data layouts and each wants confirming against a
                # real install.
                "dest": destination,
                "waiting": [name for name in matched if name not in installed],
                "installed": installed,
                "foreign": foreign,
                # An imported requirement is installable the moment its file is
                # here; there is no destination folder to have resolved first.
                "can_install": bool(importer)
                or bool(requirement.get("gui_install"))
                or (bool(destination) and not requirement.get("manual")),
                # Installing means opening the emulator's own window at it,
                # because the emulator offers no other way. The button is the
                # same; what happens behind it is not, so the UI has to know.
                "gui_install": bool(requirement.get("gui_install")),
                # What the user is about to be asked for, said before the
                # emulator opens rather than after it has.
                "prompt": (requirement.get("gui_install") or {}).get("prompt", ""),
                # A copy is undone by deleting the file that was copied.
                # Anything the emulator unpacked or installed for itself is
                # undone by deleting the tree it wrote, which is offered
                # wherever the catalog names that tree -- "delete several
                # thousand files somewhere under here" is not a promise worth
                # guessing at, but naming it is a one-line answer.
                #
                # Keyed on having somewhere to delete rather than on how the
                # thing arrived. Keying it on "was this a copy" was what left
                # RPCS3's firmware unremovable while a .rap next to it was not,
                # and Ryujinx's firmware unremovable because Ryujinx installs
                # its own.
                "can_remove": (
                    bool(requirement.get("removes")) and bool(installed)
                    if (importer or detect)
                    else bool(destination) and not requirement.get("manual")
                ),
                # Removal means deleting a directory rather than a file that
                # was copied here, which is a different promise and needs
                # different words in the dialog.
                "tree": bool(requirement.get("removes")),
                # Installed state read from a folder the emulator filled rather
                # than from files we put there, so `installed` holds a state
                # and not a list of names.
                "detected": bool(detect),
                # Told apart in the UI: an imported row says what the emulator
                # produced ("4.93"), not which file was copied.
                "imported": bool(importer),
                # The one kind of prerequisite this plugin may supply itself:
                # not a dump, so there is a button instead of a request.
                "can_fetch": bool(requirement.get("fetch")) and not installed,
                # Whether this one *could* be fetched, regardless of whether it
                # is installed right now. `can_fetch` answers "offer the button"
                # and so goes false the moment it is in place; the remove dialog
                # needs the other question -- whether putting it back is a press
                # or another trip to a PC.
                "fetchable": bool(requirement.get("fetch")),
                # Whether a game will boot without it. Only RPCS3's .rap row is
                # optional -- a licence belongs to one game rather than to the
                # emulator -- and the add flow must not warn "RPCS3 is missing
                # something" at every PS3 game because of it.
                "optional": bool(requirement.get("optional")),
                # Whether "not installed" is a fact or merely the absence of a
                # way to tell. A requirement the emulator installs itself, with
                # nowhere named to look, can only be reported as unknown --
                # and unknown must never be shown as missing. Ryujinx's
                # firmware was: it had no `detect`, so it read as absent
                # forever, and the add flow warned about it under a game that
                # had just launched perfectly well.
                "detectable": bool(
                    detect
                    or (importer and importer.get("installed"))
                    or (destination and not requirement.get("manual"))
                ),
            }
        )

    return report


def _newest(directory):
    """The most recent mtime at `directory`, itself and its immediate children.

    The directory's own stamp moves when entries are added or removed, which is
    what a firmware install does; the children are read too because an install
    that only overwrote what was already there would not move it. 238 entries
    is a few milliseconds and the answer has to be right, since a file gets
    deleted on the strength of it.
    """
    newest = 0.0
    try:
        newest = os.stat(directory).st_mtime
        with os.scandir(directory) as entries:
            for item in entries:
                try:
                    newest = max(newest, item.stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return 0.0
    return newest


def spent(entry, files=None):
    """Sent files the emulator has already taken in, and so no longer needs.

    Only for a requirement the emulator installs through its own window --
    Ryujinx's Switch firmware is the case. There is no return value from that
    install to act on: the emulator is opened as a Steam shortcut, asks the user
    to confirm, and this plugin never hears how it went. So the question is
    asked of the filesystem afterwards instead.

    **"Is anything installed" is not the question, and answering that one would
    delete somebody's firmware upgrade.** `detect` only says whether the folder
    has contents, so a device with 6.0 installed reports the same as one with
    nothing -- and a 7.0 zip sent to it would be thrown away before it was ever
    applied. The question is whether *this file* has been taken in, and the
    timestamps answer it: an install writes into the folder, so contents newer
    than the file mean the file went in, and contents older mean it is a newer
    dump still waiting its turn.

    A copied requirement is deliberately not swept. `install` copies rather than
    moves, because the folder the user sent to is the folder they resend from,
    and a second dump sitting there is a choice they made rather than litter.
    An imported one is already deleted at the point it succeeds, where the
    emulator's own output says so -- see `_import_firmware`.
    """
    files = available() if files is None else files
    directory = emu_install.firmware_dir()
    done = []

    for requirement in entry.get("firmware") or []:
        detect = requirement.get("detect")
        if not detect or requirement.get("import"):
            continue
        installed_at = _newest(under_home(detect.get("path") or ""))
        if not installed_at:
            continue
        for name in _matching(requirement, files):
            try:
                sent_at = os.path.getmtime(os.path.join(directory, name))
            except OSError:
                continue
            if installed_at >= sent_at:
                done.append(name)

    return done


def remove(names, directory=None):
    """Delete files from the firmware folder. Returns a result dict.

    Only ever a bare filename inside that one folder: the names arrive from the
    frontend, and this is a delete.
    """
    directory = directory or emu_install.firmware_dir()
    root = os.path.normpath(directory)

    removed = []
    missing = []
    for name in names or []:
        if not name or name != os.path.basename(name) or name in (".", ".."):
            return {"ok": False, "error": "Refusing to delete %r" % name}
        path = os.path.normpath(os.path.join(root, name))
        if os.path.dirname(path) != root:
            return {"ok": False, "error": "Refusing to delete %r" % name}
        if not os.path.isfile(path):
            missing.append(name)
            continue
        try:
            os.remove(path)
        except OSError as error:
            return {"ok": False, "error": "Could not delete %s: %s" % (name, error)}
        removed.append(name)

    decky.logger.info("Deleted %d file(s) from the firmware folder", len(removed))
    return {"ok": True, "removed": removed, "missing": missing}


def install(entry, requirement_name, files=None):
    """Copy everything matching one requirement into place.

    Returns a result dict. Copies rather than moves: the folder the user sent to
    is also the folder they can resend from, and a destination that turns out
    wrong should not have consumed the file.
    """
    files = available() if files is None else files

    requirement = find_requirement(entry, requirement_name)
    if requirement is None:
        return {"ok": False, "error": "That is not something %s asks for." % entry.get("name")}
    if requirement.get("manual"):
        return {"ok": False, "error": requirement["manual"]}
    if requirement.get("import"):
        # Handled by whoever can start the emulator; nothing here to copy.
        return {
            "ok": False,
            "error": "%s installs %s itself." % (entry.get("name"), requirement_name),
        }

    destination = _destination(requirement)
    if not destination:
        return {"ok": False, "error": "No install location is known for %s." % requirement_name}

    matched = _matching(requirement, files)
    if not matched:
        return {
            "ok": False,
            "error": "Nothing in the firmware folder looks like %s yet." % requirement_name,
        }

    try:
        os.makedirs(destination, exist_ok=True)
    except OSError as error:
        return {"ok": False, "error": "Cannot create %s: %s" % (destination, error)}

    source_dir = emu_install.firmware_dir()
    copied = []
    kept = []
    for name in matched:
        # Recorded and reported under the name it lands as, not the name it
        # arrived as, so a later removal can still find its own work.
        landed = _dest_name(requirement, name)
        target = os.path.join(destination, landed)
        # A placeholder the emulator wrote for the user to fill in is not
        # "already there" in any useful sense, and refusing to replace it would
        # mean the requirement could never be satisfied at all.
        if os.path.exists(target) and not _is_stub(target, requirement.get("stub")):
            # Never replace what is already there: the user may have put a
            # better dump in by hand, and a BIOS is not something to silently
            # swap under an emulator.
            kept.append(landed)
            continue
        if os.path.exists(target):
            try:
                os.remove(target)
            except OSError as error:
                return {"ok": False, "error": "Could not replace %s: %s" % (name, error)}
        try:
            # Moved, not copied. A copy leaves the transfer folder holding a
            # duplicate of every BIOS ever sent -- a PS3 firmware PUP is a
            # couple of hundred megabytes -- and needed a whole panel to
            # explain which duplicates were safe to delete. `uninstall` moves
            # the file back, so this stays as repeatable as copying was.
            # shutil.move rather than os.replace: the destination can be on a
            # different filesystem from the user's home.
            shutil.move(os.path.join(source_dir, name), target)
        except OSError as error:
            return {"ok": False, "error": "Could not move %s: %s" % (name, error)}
        copied.append(landed)

    if copied:
        # Recorded so `uninstall` can tell these from a file the user placed
        # themselves. Merged with whatever was recorded before, since a
        # multi-file BIOS can arrive a piece at a time.
        state = _read_state()
        for_entry = state.setdefault(entry["id"], {})
        previous = for_entry.get(requirement_name, [])
        for_entry[requirement_name] = sorted(set(previous) | set(copied))
        _write_state(state)

    configured, config_error = _configure(requirement, destination, copied or kept)

    decky.logger.info(
        "Installed %d firmware file(s) for %s into %s (%d already there)",
        len(copied), entry.get("id"), destination, len(kept),
    )
    return {
        "ok": True,
        "copied": copied,
        "kept": kept,
        "dest": destination,
        # Which setting now points at the file. Empty for the emulators that
        # look in a fixed folder, which is most of them.
        "configured": configured,
        "config_error": config_error,
    }


def _configure(requirement, destination, names):
    """Point a setting at the file that was just installed. Returns (key, error).

    Copying a file into place is not always enough. xemu reads its boot ROM,
    its BIOS and its disk image from three paths in `xemu.toml`, and an unset
    one means it will not start -- so "send the file" would otherwise still end
    at "now open xemu and browse to it three times", which is the Desktop Mode
    instruction this plugin exists to remove.

    Deliberately not fatal: the file is in place either way, and a settings file
    this could not write is worth reporting rather than pretending the whole
    install failed.
    """
    spec = requirement.get("configure")
    if not spec or not names:
        return "", ""

    path = under_home(spec["path"])
    if not path:
        return "", "Refusing to write outside the home."

    result = emu_config.apply_file(
        path,
        spec.get("format") or emu_config.TOML_KEYS,
        {spec["section"]: {spec["key"]: os.path.join(destination, names[0])}},
        spec.get("owner") or "firmware",
    )
    if not result.get("ok"):
        return "", result.get("error", "")
    return spec["key"] if result.get("applied") else "", ""


# A prerequisite this plugin is allowed to fetch is small and known: xemu's
# blank disk image is 68KB zipped. The cap is here so a redirect to something
# unexpected is refused rather than written into an emulator's data directory.
MAX_FETCH_BYTES = 64 * 1024 * 1024


def fetch(entry, requirement_name):
    """Download a prerequisite that is nobody's dump.

    The rule this bends is "firmware is never downloaded", and the rule's
    reason is what decides who is exempt. A PS2 BIOS or a set of Switch keys
    has to be copied off hardware you own; there is no lawful place to fetch
    one and offering to would be offering to do something else entirely.

    Neither of the cases here is that. xemu's hard disk image is an empty
    formatted disk published by xemu's own project. Sony's PUPs are published
    by Sony, at the addresses their own consoles update from, and every
    emulator's quickstart sends you to exactly those pages -- so "send it from
    another device" was asking the user to go and do by hand what this can do
    in one press, for no gain in anybody's rights.
    """
    requirement = find_requirement(entry, requirement_name)
    if requirement is None:
        return {"ok": False, "error": "That is not something %s asks for." % entry.get("name")}

    spec = requirement.get("fetch")
    if not spec:
        return {
            "ok": False,
            "error": "%s is your own file -- this plugin never downloads one."
            % requirement_name,
        }

    # A requirement that is copied somewhere is fetched straight there. One
    # that is not -- a PUP the emulator unpacks itself -- lands in the transfer
    # folder, which is where the same file would have arrived had it been sent
    # from another device. Everything downstream then treats the two identically:
    # the row reports it as waiting, and Install does the same work either way.
    destination = _destination(requirement) or emu_install.firmware_dir()

    url, name, error = _source(spec)
    if error:
        return {"ok": False, "error": error}

    try:
        os.makedirs(destination, exist_ok=True)
    except OSError as create_error:
        return {"ok": False, "error": "Cannot create %s: %s" % (destination, create_error)}

    if spec.get("extract"):
        archive = os.path.join(destination, ".deckyemu-fetch.zip")
        ok, error = net.download(url, archive, max_bytes=MAX_FETCH_BYTES)
        if not ok:
            _discard(archive)
            return {"ok": False, "error": error or "Download failed."}
        written, error = _extract(archive, destination, spec["extract"])
        _discard(archive)
        if error:
            return {"ok": False, "error": error}
    else:
        # Straight to its final name. A firmware image is one file and the
        # emulator is about to be pointed at it, so unpacking would only be a
        # step that could go wrong.
        target = os.path.join(destination, name)
        ok, error = net.download(url, target, max_bytes=MAX_FIRMWARE_FETCH_BYTES)
        if not ok:
            _discard(target)
            return {"ok": False, "error": error or "Download failed."}
        written = [name]

    configured, config_error = _configure(requirement, destination, written)
    decky.logger.info(
        "Fetched %s for %s into %s", ", ".join(written), entry.get("id"), destination
    )
    return {
        "ok": True,
        "copied": written,
        "kept": [],
        "dest": destination,
        "configured": configured,
        "config_error": config_error,
    }


# A console firmware image is a few hundred megabytes -- the PS3's is around
# 200MB -- where a helper archive is measured in kilobytes.
MAX_FIRMWARE_FETCH_BYTES = 1024 * 1024 * 1024


def _source(spec):
    """(url, filename, error) for whatever this requirement is fetched from.

    Three kinds, because the publishers differ in how permanent an address is.
    `github` resolves the newest release asset. `url` is a fixed address, right
    for a console whose firmware has stopped moving -- the Vita's ended at 3.74
    in 2022. `index` reads Sony's own update list and takes the address out of
    it, which is what the console itself does and what keeps the PS3 entry
    correct as Sony publish new versions.
    """
    kind = spec.get("kind")
    if kind == "github":
        asset, error = emu_install.resolve_github_asset(spec["repo"], spec["asset"])
        if error:
            return "", "", error
        return asset["url"], asset["name"], ""

    if kind == "url":
        return spec["url"], spec["name"], ""

    if kind == "index":
        payload, _kind = net.get_bytes(spec["index"])
        if payload is None:
            return "", "", "Could not reach %s." % spec["index"]
        text = payload.decode("utf-8", "replace")
        try:
            match = re.search(spec["find"], text)
        except re.error as error:
            return "", "", "Bad index pattern: %s" % error
        if not match:
            return "", "", "That update list no longer names a firmware image."
        return match.group(1), spec["name"], ""

    return "", "", "No download source is configured."


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _extract(archive, destination, pattern):
    """Pull matching members out of a zip. Returns (names written, error).

    Members are written by basename into one directory, so a crafted archive
    cannot place a file anywhere but where this intends -- the archive is
    fetched over the network, and `extractall` would honour a path inside it.
    """
    try:
        matcher = re.compile(pattern) if pattern else None
    except re.error as error:
        return [], "Bad extract pattern: %s" % error

    written = []
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                name = os.path.basename(info.filename)
                if info.is_dir() or not name:
                    continue
                if matcher and not matcher.match(name):
                    continue
                target = os.path.join(destination, name)
                with bundle.open(info) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                written.append(name)
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        return [], "Could not unpack the download: %s" % error

    if not written:
        return [], "The download did not contain what was expected."
    return written, ""


def _uninstall_tree(entry, requirement):
    """Delete the directories an emulator wrote a firmware into.

    There is no file to move back: the emulator was handed a .PUP, or sent to
    its own interface, and wrote some thousands of files out of it. What can be
    done is delete exactly what it wrote, which is only knowable because the
    catalog says so -- see the `removes` list on each requirement, each one
    taken from a directory listing before and after a real install rather than
    reasoned about.

    Guarded twice over. A path must be one the catalog named, and it must sit
    under the user's home: a typo in the catalog should fail to find anything,
    never delete from the root of the filesystem.
    """
    targets = requirement.get("removes") or []
    if not targets:
        # Only reachable by calling this directly; `uninstall` dispatches here
        # on `removes` being present. Kept so it stays true of the function
        # rather than of its one caller.
        return {"ok": False, "error": "It is not known what to take back out."}

    home = os.path.realpath(sysenv.user_home())
    removed = []
    freed = 0
    for relative in targets:
        path = os.path.realpath(under_home(relative))
        if not path.startswith(home + os.sep):
            decky.logger.warning("Refusing to remove %s: outside the home", path)
            continue
        if not os.path.isdir(path):
            continue
        try:
            freed += sysenv.directory_bytes(path)
            shutil.rmtree(path)
        except OSError as error:
            return {"ok": False, "error": "Could not remove %s: %s" % (relative, error)}
        removed.append(os.path.basename(path))

    if not removed:
        return {"ok": False, "error": "There was nothing left to remove."}

    decky.logger.info(
        "Removed %s for %s, freeing %d bytes", ", ".join(removed), entry.get("id"), freed
    )
    return {"ok": True, "removed": removed, "foreign": [], "freed": freed}


def uninstall(entry, requirement_name):
    """Remove a requirement's files from where the emulator reads them.

    This deletes. Installing moved the file rather than copying it, so there is
    no second copy anywhere and the file is gone -- supplying it again means
    sending it from another device again. The confirm dialog says so, because
    that is not what a trash button next to "In place" would otherwise imply.

    Files this plugin did not install are deleted too, because one that predates
    the record would otherwise be stuck forever, but they are counted separately
    so the UI can say so before anything happens.
    """
    requirement = find_requirement(entry, requirement_name)
    if requirement is None:
        return {"ok": False, "error": "That is not something %s asks for." % entry.get("name")}
    if requirement.get("removes"):
        return _uninstall_tree(entry, requirement)
    if requirement.get("import") or requirement.get("detect"):
        return {
            "ok": False,
            "error": "%s installed that itself, and it is not known what to "
            "take back out." % entry.get("name"),
        }

    destination = _destination(requirement)
    if not destination:
        return {"ok": False, "error": "No install location is known for %s." % requirement_name}

    ours = set(_recorded(entry["id"], requirement_name))
    # Candidates come from the destination itself, not from the transfer folder:
    # the copy that was sent may well have been deleted by now, and that must not
    # make the installed one unremovable.
    candidates = _installed_at(requirement, destination, ours)

    removed = []
    foreign = []
    for name in candidates:
        path = os.path.join(destination, name)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
        except OSError as error:
            return {"ok": False, "error": "Could not remove %s: %s" % (name, error)}
        (removed if name in ours else foreign).append(name)

    state = _read_state()
    if entry["id"] in state:
        state[entry["id"]].pop(requirement_name, None)
        if not state[entry["id"]]:
            del state[entry["id"]]
        _write_state(state)

    decky.logger.info(
        "Removed %d firmware file(s) for %s from %s (%d not installed by us)",
        len(removed), entry.get("id"), destination, len(foreign),
    )
    return {"ok": True, "removed": removed, "foreign": foreign, "dest": destination}
