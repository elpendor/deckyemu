"""One-click installs for the emulators RetroArch does not cover.

Registering a standalone emulator by hand means typing a name, browsing for a
binary, listing its file extensions and getting an argument string right -- four
chances to be wrong, three of them involving the on-screen keyboard. This package
exists so none of that is typed: pick Dolphin, and the flatpak is installed and
registered against Nintendo - GameCube with working arguments.

## Adding an emulator

One module per emulator, next to this file. To add one:

1. Copy the closest existing module -- `duckstation.py` is the small plain case,
   `rpcs3.py` the involved one -- and name it after the emulator.
2. Fill in `ENTRY`. Every field is described in `schema.py`; that file is the
   reference, not this docstring.
3. Add the module to `_MODULES` below.
4. Run `python scripts/tests/test_catalog.py`. It checks the entry against the
   schema and will name anything missing, misspelt or contradictory.

Nothing else in the plugin needs to learn about the new emulator. The install
flow, the ROM picker, collection grouping, the firmware panel and the reset tab
all read the catalog rather than a list of their own.

## Before the first deploy

Adding an emulator is cheap; *finding out what is wrong with it* is not, because
every answer costs a round trip through a Deck and a person. Each line below was
learned by spending one. Doing them in a single pass before deploying is the
difference between two cycles and twelve.

1. **Run it once with a real ROM path and read what it prints.** Not `--help`,
   which many emulators answer without touching their own data. Packaging faults
   surface here and nowhere else: Supermodel's flatpak ships `Games.xml` and its
   crosshair bitmaps where Supermodel does not look for them, so it detected no
   ROM at all and then aborted before its first frame. Both were one line of
   stderr apart.
2. **Find out which input backend it selected before trusting any button
   number.** Supermodel has two -- `sdl` reads raw joystick indices, `sdlgamepad`
   reads named buttons -- and the default is the raw one, where `BUTTON9` is
   whatever the device published ninth. On Steam's virtual pad that is the Steam
   button, which never reaches a game. The config, the emulator's own
   `-print-inputs` and the source all agreed the binding was right; all three
   were describing the backend that was not running.
3. **Launch it the way Steam does**, `steam "steam://rungameid/<id>"`, where the
   id is `(appid << 32) | 0x02000000`. An ssh launch reproduces neither Steam
   Input nor the on-screen keyboard, so it cannot show you either fault.
4. **Check `~/.steam/steam/logs/console_log.txt` for `steam://open/keyboard`.**
   Any SDL2 emulator that starts text input opens Steam's keyboard over the game
   -- see the `env` on this entry -- and the log records every time it happened,
   after the fact.
5. **A stdlib import no other module here already uses is a claim about the
   plugin sandbox.** It ships a trimmed Python; `xml.etree` is absent and its
   absence stops the whole backend from loading, while every test on a
   development machine passes. `tests/test_module_guard.py` holds the proven set.

And the one that is not about emulators at all: **before changing a value, find
everything that reads it.** A ROM set's name went to the wrong function, and
then correcting it broke the artwork search, because `matched_name` -- not
`title` -- is what SteamGridDB is scored against. Two round trips, one habit.

**Extensions are derived, not stored.** An entry declares `databases` -- the same
libretro system names a core declares -- and the extension list is the union of
`supported_extensions` across every core in `installer.core_catalog()` that
claims one of those databases. That is the keystone idea from `emulators.py`
doing one more job: `databases` already buys name cleanup, boxart and collection
grouping, and now it buys ROM matching too. It also means the list stays correct
as libretro adds formats, with nothing here to update.

`MANUAL_EXTENSIONS` is the floor under that, and every system an entry claims
needs a line in it -- see the comment there for the Deck that proved why.

**Launch arguments live here and only here.** `emulators.suggest_launch_options`,
which is what a hand-registered emulator gets, is derived from these entries
rather than kept as a second table. It was a second table until the two drifted:
the catalog installed RPCS3 with `--fullscreen` while the suggestion offered
`--no-gui` as the fullscreen switch, and four of the seven emulators in both
lists disagreed. The catalog is now the only source: a recipe is support for
the emulator it names, so it belongs to that emulator's entry or nowhere.

## Entries the user supplies

`CATALOG` is `BUNDLED` plus whatever `imported.py` loaded from disk, so an
emulator this project will not distribute can still behave like a catalogued
one. Those entries are checked far more strictly -- see FORBIDDEN_WHEN_IMPORTED
in schema.py -- because an entry is a list of actions the plugin performs rather
than data it reads, and a file from outside does not get to ask for the
destructive ones.

`CATALOG` is therefore rebuilt at runtime by `reload_imported`. Read it as
`emulator_catalog.CATALOG` every time; binding it to a name that outlives a call
freezes the bundled-only tuple.

**Still bundled, not fetched.** A catalog served from a URL would let entries
reach everyone without a release, and serving it is a commitment: a URL that
404s or goes stale breaks emulator installs for every user, where a bundled copy
simply cannot. Importing a file has the same reach for one user with none of
that exposure, which is why it is the shape this took.
"""

import re

import platforms

from . import (
    azahar,
    cemu,
    dolphin,
    duckstation,
    pcsx2,
    ppsspp,
    rpcs3,
    ryujinx,
    shadps4,
    supermodel,
    vita3k,
    xemu,
    xenia,
)
from .schema import validate  # noqa: F401  -- re-exported for tests and callers

# The order emulators were added, which is the order `CATALOG` holds them in.
# Nothing depends on it -- `listing` sorts by name -- but keeping it stable keeps
# the diff for a new emulator to one line.
_MODULES = (
    dolphin,
    pcsx2,
    rpcs3,
    ryujinx,
    shadps4,
    cemu,
    ppsspp,
    duckstation,
    xemu,
    azahar,
    vita3k,
    xenia,
    supermodel,
)

#: The entries written in this package. Never changes at runtime.
BUNDLED = tuple(module.ENTRY for module in _MODULES)

#: Everything the plugin knows about, bundled plus imported.
#:
#: Rebuilt in place by `reload_imported`, so read it as `emulator_catalog.CATALOG`
#: and never bind it to a local name that outlives a call -- an import of the
#: form `from emulator_catalog import CATALOG` would freeze the bundled-only
#: tuple and quietly stop seeing anything the user added.
CATALOG = BUNDLED

#: Ids that are not in the catalog but are spoken for anyway.
#:
#: `retroarch` names RetroArch to the endpoints that change an installed flatpak's
#: build, which take a catalog id and are reused for it -- so a definition
#: claiming that id would be handed RetroArch's requests. Reserved rather than
#: worked around, because "an imported emulator called retroarch" is a confusing
#: thing to allow whatever the plumbing does with it.
RESERVED_IDS = frozenset({"retroarch"})

#: Why the last reload rejected the definitions it rejected, for the panel to
#: show. A file that fails to load has to say so somewhere the user looks; the
#: alternative is an emulator that simply never appears.
import_problems: list = []


def reload_imported():
    """Re-read the imported definitions and rebuild `CATALOG`. Returns them.

    Called at startup and after an import or removal. Bundled entries always win
    a clash of ids: an imported file cannot redefine an emulator this plugin
    ships, which would otherwise be a way to replace a trusted recipe with an
    untrusted one.
    """
    global CATALOG, import_problems

    from . import imported as _imported  # deferred: it imports decky

    known = [label for label, _full, _short in platforms.NO_LIBRETRO_PLATFORMS]
    entries, problems = _imported.load(known)

    taken = {entry["id"] for entry in BUNDLED} | RESERVED_IDS
    kept = []
    for entry in entries:
        if entry["id"] in taken:
            problems.append(
                "%s was not loaded: %r is already a built-in emulator."
                % (entry.get("source_file", entry["id"]), entry["id"])
            )
            continue
        kept.append(entry)

    CATALOG = BUNDLED + tuple(kept)
    import_problems = problems
    return kept



# The floor under every catalog system: formats this plugin states outright,
# which derivation then widens. Keyed on the same string an entry puts in
# `databases` or `platform`.
#
# This used to hold only the five systems libretro has no core for, and deriving
# the rest was treated as reliable. It is not. A real Deck refused to register
# Cemu because its cached info.zip -- four days old, so still inside the TTL and
# never re-fetched -- had no "Nintendo - Wii U" database at all; libretro had
# added it days earlier. Nothing was broken, nothing was offline, and the answer
# still came back empty, leaving the user told to type extensions by hand. That
# is the one thing this catalog exists to avoid, so no entry may depend on the
# derived list to be usable at all.
#
# Every system an entry claims therefore needs a line here, which
# `extensions_for` tests. Keeping them is cheap: these are container formats and
# they do not move. Erring wide is deliberate -- extensions only decide which
# emulators are *offered* for a ROM, so a surplus one is a shrug while a missing
# one makes a ROM look unplayable.
#
# These are not the whole truth for every system: RPCS3 and Vita3K really run a
# directory (PS3_GAME/USRDIR/EBOOT.BIN, or an installed title), and the entry for
# each says so in `note`. What is listed is what the ROM picker can be pointed at
# and have something happen.
MANUAL_EXTENSIONS = {
    "Nintendo - GameCube": ["iso", "gcm", "gcz", "rvz", "ciso", "dol", "elf"],
    "Nintendo - Wii": ["iso", "wbfs", "rvz", "wad", "gcz", "ciso"],
    "Nintendo - Wii U": ["wud", "wux", "wua", "wuhb", "rpx", "elf", "iso"],
    "Nintendo - Switch": ["nsp", "xci", "nsz", "xcz"],
    "Nintendo - Nintendo 3DS": ["3ds", "cci", "cxi", "app", "3dsx", "elf", "axf"],
    "Sony - PlayStation": ["bin", "cue", "chd", "pbp", "img", "ecm", "iso", "m3u"],
    "Sony - PlayStation 2": ["iso", "chd", "cso", "zso", "bin", "cue", "gz", "mdf"],
    # `pkg` is not a thing RPCS3 can launch, and it is here anyway. A store PS3
    # game *is* a .pkg as far as the user is concerned, so it has to be pickable
    # in the ROM picker or the format has no way in at all. `probe_rom` spots it
    # and the add flow installs it first, arriving at the EBOOT.BIN underneath.
    "Sony - PlayStation 3": ["bin", "self", "elf", "pkg"],
    "Sony - PlayStation 4": ["bin", "elf"],
    "Sony - PlayStation Portable": ["iso", "cso", "chd", "pbp", "elf", "prx"],
    # `pkg`, and only `pkg`, for the same reason the PS3 line above carries it:
    # it is the one Vita format this plugin can do anything with. A `.vpk` or a
    # NoNpDrm `.zip` was listed here and matched Vita3K in the picker, which
    # produced a Steam shortcut that hands the emulator a path -- and that never
    # works, twice over. Vita3K's AppImage re-splits the path on spaces, and the
    # content has to be installed and decrypted before it can be started at all.
    # Those formats are recognised in `probe_rom` now and explained rather than
    # offered. See vita3k.py's own note.
    "Sony - PlayStation Vita": ["pkg"],
    # `zip`, alone, and the archive is the ROM rather than a wrapper round one.
    # A Model 3 ROM set is forty-odd chip dumps that mean nothing apart, and
    # Supermodel opens the zip and reads them out by name -- so there is no
    # inner extension to list, and unpacking one produces a folder no emulator
    # can do anything with. `ra_cores.is_romset` is the other half of this: it
    # keeps the file matched on `zip` rather than on whichever chip dump happens
    # to come first, and keeps the Unpack row out of the panel.
    "Sega - Model 3": ["zip"],
    "Microsoft - Xbox": ["iso", "xiso"],
    # Xenia dispatches on the file's magic bytes rather than its name --
    # `CreateDeviceForFile` switches on a signature, and XBE, EXE and Unknown
    # return a null device. So this list is what those signatures are called on
    # disk, not what Xenia parses.
    #
    # `zar` is Xenia's own zarchive: a compressed disc image it can both create
    # and boot, mounted through DiscZarchiveDevice. It is the only compressed
    # format that works -- `.zip`, `.7z`, `.rar`, `.tar` and `.gz` are refused
    # by name before anything is read.
    #
    # `stfs` is the LIVE/CON/PIRS container XBLA titles and DLC ship as, and it
    # is the odd one here: those files normally carry no extension at all, so
    # this is the name of the format rather than the name of anybody's file.
    # `xbox360_content.extension_from_header` supplies it from the first four
    # bytes when the filename has nothing to offer, which is what lets an XBLA
    # container be paired with Xenia at all.
    "Microsoft - Xbox 360": ["iso", "xex", "zar", "stfs"],
}

# The catalog.
#
# `args` and `fullscreen_args` are the fields that cannot be derived from
# anything -- the same reason `emulators.LAUNCH_HINTS` exists. `verified` says
# whether the recipe was confirmed against the emulator's own behaviour or is a
# best reading of its documentation; an unverified one is installed and
# registered exactly the same, but the UI says so, because several emulators
# ignore unknown arguments silently and a wrong guess is otherwise invisible.
#
# `firmware` names files the emulator needs and this plugin will never ship. They
# are the user's to supply, and the transfer flow is how they arrive without a
# cable or a Desktop Mode file manager.
#
# A requirement is either **placeable** or **manual**:
#
#   match  a regex against the *filename* of something in ~/deckyemu/firmware.
#          Matching on the name is what removes the file picker -- the user sends
#          the file and the panel already knows what it is.
#   dest   where the emulator reads it from, relative to the home directory.
#   manual what to tell the user instead, for requirements that are not a file
#          copy at all. RPCS3's PS3UPDAT.PUP and Vita3K's firmware are unpacked
#          and imported by the emulator itself, and xemu needs three files plus
#          config pointers and a formatted disk image nothing here can produce.
#          Claiming to install those would be worse than saying so plainly.
#
# The destinations are the flatpak/AppImage data layouts and each one needs
# confirming against a real install; `firmware_status` reports the path it would
# use so a wrong one is visible rather than silent.


def find(entry_id):
    for entry in CATALOG:
        if entry.get("id") == entry_id:
            return entry
    return None


def system_label(entry):
    """The libretro database name or platform label this entry runs."""
    databases = entry.get("databases") or []
    return databases[0] if databases else (entry.get("platform") or "")


def _system_keys(entry):
    """Every name this entry's extensions could be keyed under."""
    keys = list(entry.get("databases") or [])
    platform = entry.get("platform")
    if platform and platform not in keys:
        keys.append(platform)
    return keys


def extensions_for(entry, database_extensions):
    """File extensions for `entry`, derived from the libretro extension map.

    `database_extensions` is what `installer.database_extensions()` returns:
    {database name: [extensions]}. Passed in rather than imported so this stays
    pure and the caller decides when a network fetch is acceptable.

    Returns a sorted list, which may be empty when the map could not be read and
    the system has no manual entry -- the caller must treat that as a failure
    rather than registering an emulator that matches nothing.
    """
    found = set()
    for key in _system_keys(entry):
        found.update(
            extension.lower()
            for extension in (database_extensions or {}).get(key, ())
            if extension
        )
        found.update(MANUAL_EXTENSIONS.get(key, ()))
    return sorted(found)


def platform_labels(entry):
    """(platform, platform_full) for an entry, for collection naming.

    Only meaningful for the systems libretro has no database for; anything with a
    `databases` entry gets its label derived downstream exactly as a core does,
    and storing one here would be a second source for the same fact.
    """
    platform = entry.get("platform")
    if not platform:
        return "", ""
    for label, full, short in platforms.NO_LIBRETRO_PLATFORMS:
        if label == platform:
            return short, full
    return platforms.short_name(platform), platform


def to_emulator(entry, target, database_extensions):
    """Shape a catalog entry as the emulator dict `emulators.save` expects.

    `target` is the flatpak application id or the path the AppImage was written
    to, which is the one thing that is only known after installing.
    """
    short, full = platform_labels(entry)
    return {
        "id": entry["id"],
        "name": entry["name"],
        "kind": "flatpak" if entry["source"]["kind"] == "flatpak" else "path",
        "target": target,
        "args": entry.get("args") or "{rom}",
        # Recorded so a corrected recipe can reach an emulator already
        # installed. Launch arguments are written once at install time, and
        # PCSX2's needed fixing after the fact -- without this the only routes
        # were reinstalling the emulator or retyping the arguments by hand.
        "catalog_recipe": entry.get("recipe", 1),
        "catalog_args": entry.get("args") or "{rom}",
        "catalog_fullscreen_args": entry.get("fullscreen_args") or "",
        # Which binary inside the flatpak to run, when it is not the one the
        # manifest names, and anything its environment has to be told. Empty
        # for all but shadPS4 -- see `flatpak_prefix`.
        "command": entry.get("command", ""),
        "env": dict(entry.get("env") or {}),
        # A Steam Input layout the emulator depends on, not a preference:
        # Vita3K needs one that binds gyro or the Deck powers the sensor down.
        "layout": entry.get("layout", ""),
        # How to start a title this emulator has already installed, when a file
        # path will not do it. Vita3K only.
        "installed_args": entry.get("installed_args", ""),
        # Whether the emulator's own launcher re-splits its arguments, so file
        # paths have to reach it without spaces. Vita3K only.
        "splits_args": bool(entry.get("splits_args")),
        "extensions": extensions_for(entry, database_extensions),
        "databases": list(entry.get("databases") or []),
        "platform": short,
        "platform_full": full,
        "fullscreen_args": entry.get("fullscreen_args") or "",
    }


# AppImages land in a folder per emulator so a reinstall can clear out the
# previous build without a name-matching guess.
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def is_safe_id(entry_id):
    """Whether an id can be used as a directory name.

    Catalog ids are ours and all pass, but the id arrives from the frontend on
    every install call and ends up in a filesystem path.
    """
    return bool(_SAFE_ID_RE.match(entry_id or ""))


def listing(database_extensions, installed_ids=()):
    """The catalog as the UI wants it: labelled, with extensions resolved."""
    installed = set(installed_ids or ())
    entries = []
    for entry in CATALOG:
        short, full = platform_labels(entry)
        entries.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "summary": entry.get("summary", ""),
                "note": entry.get("note", ""),
                "kind": entry["source"]["kind"],
                "system": full or system_label(entry),
                "short": short or platforms.short_name(system_label(entry)),
                "extensions": extensions_for(entry, database_extensions),
                "verified": bool(entry.get("verified")),
                # Provenance, so the panel can say which recipes this project
                # stands behind. An imported entry is never "verified" -- nobody
                # here has run it -- and saying so is the honest half of letting
                # one be imported at all.
                "imported": bool(entry.get("imported")),
                "source_file": entry.get("source_file", ""),
                # Projected rather than passed through: the raw requirement
                # carries a match pattern and a destination path, neither of
                # which is the frontend's business.
                "firmware": [
                    {
                        "name": item.get("name", ""),
                        "note": item.get("note", ""),
                        "expects": item.get("expects", ""),
                    }
                    for item in (entry.get("firmware") or [])
                ],
                "installed": entry["id"] in installed,
            }
        )
    entries.sort(key=lambda item: item["name"].lower())
    return entries


def launch_hints():
    """(needle, args, fullscreen switch) for every recipe known, catalog first.

    The needle is matched as a substring against a flatpak id or a binary name.
    Only the catalog. There is no second table of recipes for emulators this
    project does not install: a launch recipe here is support for the emulator
    it names, and that is a decision to make per entry rather than a list to
    keep on the side.
    """
    hints = []
    for entry in CATALOG:
        needles = [entry["id"]] + list(entry.get("aliases") or ())
        flatpak = (entry.get("source") or {}).get("id")
        if flatpak:
            # Match the last component, `duckstation` out of
            # `org.duckstation.DuckStation`, so a path to the binary matches too.
            needles.append(flatpak.rsplit(".", 1)[-1])
        for needle in dict.fromkeys(name.lower() for name in needles if name):
            hints.append((needle, entry.get("args") or "{rom}",
                          entry.get("fullscreen_args") or ""))
    return tuple(hints)


def suggest_launch_options(target):
    """Likely {args, fullscreen_args} for `target`; empty strings when unknown.

    `target` is a flatpak application id or the path an AppImage was written to.
    Only ever a suggestion: several emulators ignore unknown arguments without
    complaint, which makes a wrong guess invisible, so the user can edit both.
    """
    haystack = (target or "").lower()
    for needle, args, fullscreen in launch_hints():
        if needle in haystack:
            return {"args": args, "fullscreen_args": fullscreen}
    return {"args": "", "fullscreen_args": ""}
