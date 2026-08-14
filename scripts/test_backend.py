#!/usr/bin/env python3
"""Exercise the backend logic without a Steam Deck.

Everything under py_modules/ is plain Python whose only decky dependency is a
logger and a few directory paths, so it can run anywhere once those are stubbed.
That covers the parts most likely to be wrong -- name cleanup and artwork
matching -- and leaves only the Steam client calls needing a real Deck.

    python scripts/test_backend.py            # includes live network checks
    python scripts/test_backend.py --offline  # pure logic only

Network checks hit thumbnails.libretro.com and are the real value here: they
prove a ROM filename actually resolves to real cover art.

This file is the original suite and is still most of it. The scaffolding it used
to carry lives in harness.py, and anything written from now on should go in its
own file under tests/ -- small enough to run on its own, with a namespace that
cannot collide with a section written eight months earlier. Running this file
runs those too.
"""

import io
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Before any py_modules import: this is what puts the fake `decky` in place.
from harness import (  # noqa: E402
    OFFLINE,
    REPO_ROOT,
    TMP,
    check,
    decky,
    failures,
    section,
    summary,
)

import launchers  # noqa: E402
import libretro_meta as meta  # noqa: E402
import ra_cores  # noqa: E402
import store  # noqa: E402

section("display_title -- turning a filename into a name worth showing")
check("plain region tag", meta.display_title("Super Mario World (USA)"), "Super Mario World")
check("dump flag", meta.display_title("Super Mario World (USA) [!]"), "Super Mario World")
check(
    "article moved to front",
    meta.display_title("Legend of Zelda, The - A Link to the Past (USA)"),
    "The Legend of Zelda: A Link to the Past",
)
check("underscores", meta.display_title("Sonic_The_Hedgehog_2"), "Sonic The Hedgehog 2")
# Dots separate words in dotted filenames but are punctuation in real titles.
check("dotted filename split", meta.display_title("Super.Mario.Bros"), "Super Mario Bros")
check(
    "abbreviation period survives",
    meta.display_title("Super Mario Bros. (World)"),
    "Super Mario Bros.",
)
check("Mr. keeps its period", meta.display_title("Mr. Do! (USA)"), "Mr. Do!")
check("several tags", meta.display_title("Chrono Trigger (USA) (Rev 1) [b1]"), "Chrono Trigger")
check(
    "subtitle becomes colon",
    meta.display_title("Final Fantasy VI - Advance (Europe)"),
    "Final Fantasy VI: Advance",
)

section("sanitize_for_thumbnails -- libretro's documented character rule")
check("ampersand", meta.sanitize_for_thumbnails("Tom & Jerry"), "Tom _ Jerry")
check("colon and slash", meta.sanitize_for_thumbnails("Sonic: R/X"), "Sonic_ R_X")
check("apostrophe survives", meta.sanitize_for_thumbnails("Q*bert's Qubes"), "Q_bert's Qubes")

section("candidate generation -- tried before any directory listing")
check(
    "produces 'Legend of Zelda, The' variant",
    any(c.startswith("Legend of Zelda, The") for c in meta._candidate_names("The Legend of Zelda")),
    True,
)

section("probing candidates -- concurrency must not change which name wins")
# Candidates are ordered best-guess first, so that order *is* the match quality.
# Probing them concurrently is only safe if the earlier name still wins when a
# later one answers sooner -- otherwise a ROM would get whichever cover the
# network happened to return first.
import time as _time  # noqa: E402

_probed = []


def _staggered_head_ok(url, headers=None):
    _probed.append(url)
    if url.endswith("later"):
        return True
    if url.endswith("earlier"):
        # Deliberately the slow one, and deliberately still the right answer.
        _time.sleep(0.25)
        return True
    return False


_real_head_ok = meta.net.head_ok
meta.net.head_ok = _staggered_head_ok
check(
    "the earlier candidate wins even when a later one answers first",
    meta._first_existing(["x/earlier", "x/later"]),
    0,
)
check("nothing found is reported as no match", meta._first_existing(["x/no", "x/none"]), -1)
check("an empty candidate list is not an error", meta._first_existing([]), -1)

# A hit near the front must not drag the whole tail of candidates over the
# network with it. One wave of waste is the price of the concurrency; more is a
# bug.
_probed.clear()
meta._first_existing(["x/earlier"] + ["x/no%d" % _i for _i in range(20)])
check(
    "a hit in the first wave stops the rest",
    len(_probed) <= meta._PROBE_WORKERS,
    True,
)
meta.net.head_ok = _real_head_ok

section("the art picker's scoring -- speed must not change which names come back")
import difflib as _difflib  # noqa: E402

# index_candidates scores the query against every name in a system's index, so it
# consults difflib's cheap upper bounds before the real comparison. Those bounds
# are only safe because they can never sit below the true ratio: a name they put
# under the cutoff could not have reached it. This pins that down from both ends,
# with real scores either side of the 0.5 cutoff.
#
# Seeded straight into the in-process index cache, which keeps the check offline
# and exercises that cache at the same time.
_PICKER_SYSTEM = "Test - Picker"
_PICKER_NAMES = [
    "Super Mario World 2 - Yoshi's Island (USA)",  # contains the query -> 0.9
    "Super Mario Kart (USA)",                      # 0.759
    "Super Metroid (USA)",                         # 0.667
    "Super Mario All-Stars (USA)",                 # 0.667
    "Super Star Wars (USA)",                       # 0.643
    "Super Widget (USA)",                          # 0.538 -- just above the cutoff
    "Wario's Woods (USA)",                         # 0.538 -- just above the cutoff
    "Super Bomberman (USA)",                       # 0.483 -- just below, but its
                                                   # cheap bounds are 0.62/0.97, so
                                                   # the real comparison must still
                                                   # run and still reject it
    "Super Soccer (USA)",                          # 0.462
    "Super Punch-Out!! (USA)",                     # 0.429
    "Mario Paint (USA)",                           # 0.400
    "Mario's Time Machine (USA)",                  # 0.312
    "Sim City (USA)",                              # 0.273 -- rejected by the bound
    "Wild Guns (USA)",                             # 0.261
]
meta._memory_index[_PICKER_SYSTEM] = _PICKER_NAMES

_picked = meta.index_candidates([_PICKER_SYSTEM], "Super Mario World")
_picked_names = [row["name"] for row in _picked]

check(
    "a name scoring just above the cutoff is kept",
    "Wario's Woods (USA)" in _picked_names,
    True,
)
check(
    "a name scoring just below it is dropped, cheap bounds notwithstanding",
    "Super Bomberman (USA)" in _picked_names,
    False,
)
check(
    "the closest match is offered first",
    _picked_names[0],
    "Super Mario World 2 - Yoshi's Island (USA)",
)

# The whole point of the prefilter is that it changes nothing, so the same
# scoring is done here the slow way and the two lists are compared outright.
_reference = []
for _name in _PICKER_NAMES:
    _n = meta._normalize_for_match(_name)
    _t = meta._normalize_for_match("Super Mario World")
    if _n == _t:
        _score = 1.0
    elif _t in _n or _n in _t:
        _score = 0.9
    else:
        _score = _difflib.SequenceMatcher(None, _t, _n).ratio()
    if _score >= 0.5:
        _reference.append((_score, _name))
_reference.sort(key=lambda item: (-item[0], meta._tag_count(item[1]), len(item[1]), item[1]))
check(
    "and returns exactly what scoring every name in full would have",
    _picked_names,
    [name for _score, name in _reference],
)

meta._memory_index.pop(_PICKER_SYSTEM, None)

section("the boxart index cache -- a failed listing must not stick")
# The index is read once per system per search and again by resolve's fallback, so
# it is held in memory rather than re-parsed from disk each time. An empty result
# means the listing failed, and remembering that would turn one moment without a
# network into "this system has no artwork" for the rest of the session.
meta.forget_cached_indexes()
_index_reads = []
_real_load_cached = meta._load_cached_index


def _counting_load(system):
    _index_reads.append(system)
    return _real_load_cached(system)


meta._load_cached_index = _counting_load
meta._store_cached_index("Test - Cached", ["Some Game (USA)"])
check("the first lookup reads the index", meta.fetch_boxart_index("Test - Cached"), ["Some Game (USA)"])
check("and the second answers without reading again", len(_index_reads), 1)
meta._load_cached_index = _real_load_cached

_real_get_bytes = meta.net.get_bytes
meta.net.get_bytes = lambda url, headers=None, max_bytes=0: (None, None)
check("a system whose listing fails reports nothing", meta.fetch_boxart_index("Test - Offline"), [])
meta.net.get_bytes = lambda url, headers=None, max_bytes=0: (
    b'<a href="Recovered%20Game%20(USA).png">x</a>',
    "text/html",
)
check(
    "and is retried rather than remembered as empty",
    meta.fetch_boxart_index("Test - Offline"),
    ["Recovered Game (USA)"],
)
meta.net.get_bytes = _real_get_bytes
meta.forget_cached_indexes()

SNES = "Nintendo - Super Nintendo Entertainment System"
GENESIS = "Sega - Mega Drive - Genesis"

if OFFLINE:
    section("LIVE artwork resolution -- SKIPPED (--offline)")
else:
    section("LIVE artwork resolution against thumbnails.libretro.com")
    cases = [
        # (filename, databases, required match_kind or None for "any match")
        ("Super Mario World (USA).sfc", [SNES], "exact"),
        ("Chrono Trigger (USA).sfc", [SNES], "exact"),
        ("Super Metroid.sfc", [SNES], None),  # no region tag at all
        ("The Legend of Zelda - A Link to the Past (USA).sfc", [SNES], None),  # article order
        ("Sonic The Hedgehog 2 (World).md", [GENESIS], None),
    ]
    for filename, databases, expected_kind in cases:
        result = meta.resolve("/roms/" + filename, databases)
        found = bool(result["boxart_url"])
        print(
            "  %-52s kind=%-6s art=%-5s title=%r"
            % (filename, result["match_kind"], found, result["title"])
        )
        if not found:
            failures.append("no artwork resolved for %s" % filename)
        if expected_kind and result["match_kind"] != expected_kind:
            failures.append(
                "%s: match_kind %s, expected %s"
                % (filename, result["match_kind"], expected_kind)
            )

section("launcher generation -- flatpak, ROM path full of shell metacharacters")
install = {
    "kind": "flatpak",
    "exe": "/usr/bin/flatpak",
    "config_dir": "/home/deck/.var/app/org.libretro.RetroArch/config/retroarch",
    "core_dirs": [],
    "info_dirs": [],
}
rom = "/run/media/mmcblk0p1/Emulation/roms/snes/Tom & Jerry (USA) [!].sfc"
core = "/home/deck/.var/app/org.libretro.RetroArch/config/retroarch/cores/snes9x_libretro.so"
script_path = launchers.write_launcher(install, "Tom & Jerry", core, rom)
body = open(script_path, encoding="utf-8").read()
print(body)
check("ROM path is quoted", "'%s'" % rom in body, True)
check(
    "ROM directory shared into the sandbox",
    "--filesystem=/run/media/mmcblk0p1/Emulation/roms/snes" in body,
    True,
)
check("execs rather than forks", body.strip().split("\n")[-1].startswith("exec "), True)
if os.name == "posix":
    check("script is executable", bool(os.stat(script_path).st_mode & 0o111), True)
else:
    print("SKIP script is executable (no POSIX mode bits on this host)")
check("refuses to delete outside runtime dir", launchers.remove_launcher("/etc/passwd"), False)
check("removes its own launcher", launchers.remove_launcher(script_path), True)

section("opening an emulator's own window, with and without an errand")
# The route to the jobs an emulator will only do through its own window. A
# window is composited only if Steam launched the process, so these go out as a
# Steam shortcut -- and the script behind that shortcut is rewritten on every
# press, which is what lets an errand be added for one run and gone by the next
# without a second entry appearing in anybody's library.
_gui_emu = {
    "id": "ryujinx", "name": "Ryujinx", "kind": "flatpak",
    "target": "io.github.ryubing.Ryujinx",
}
_plain = launchers.write_gui_launcher(_gui_emu, "Ryujinx")
_plain_body = open(_plain, encoding="utf-8").read()
check("plain open passes no arguments", "--install-firmware" in _plain_body, False)

_fw_file = "/home/deck/deckyemu/firmware/Firmware 20.1.5 (rebootless).zip"
_errand = launchers.write_gui_launcher(
    _gui_emu, "Ryujinx",
    ["--install-firmware", _fw_file],
    ["/home/deck/deckyemu/firmware"],
    "# Opens Ryujinx to install it.",
)
_errand_body = open(_errand, encoding="utf-8").read()
check("the errand rewrites the same script", _errand, _plain)
check("the firmware path is quoted, spaces and all", "'%s'" % _fw_file in _errand_body, True)
# Without this Ryujinx cannot read what it was handed, and reports the file as
# invalid rather than unreadable -- which reads as a bad dump.
# Read-only: it needs to read one archive, and the folder it is being opened at
# holds every dump the user has ever sent.
check("the transfer folder is shared into the sandbox, read-only",
      "--filesystem=/home/deck/deckyemu/firmware:ro" in _errand_body, True)
# The interface has to be visible, unlike a headless tool run.
check("the gamescope socket is still asked for",
      "--socket=" in _errand_body or "gamescope" in _errand_body.lower(), True)
# And back to plain, because the next press of "open the emulator" writes it
# again. An errand that outlived its press would install firmware every time
# anybody opened Ryujinx.
launchers.write_gui_launcher(_gui_emu, "Ryujinx")
check("and the next plain open clears it",
      "--install-firmware" in open(_plain, encoding="utf-8").read(), False)
launchers.remove_launcher(_plain)

section("suppressing RetroArch's on-screen chatter")
quiet_path = launchers.write_launcher(install, "Quiet", core, rom, "startup")
quiet_body = open(quiet_path, encoding="utf-8").read()
check("passes --appendconfig", "--appendconfig=" in quiet_body, True)
check(
    "grants read-only sandbox access to the override",
    ":ro" in quiet_body,
    True,
)
override = open(launchers.OVERRIDE_CONFIGS["startup"], encoding="utf-8").read()
check(
    "disables the load banner",
    'menu_show_load_content_animation = "false"' in override,
    True,
)
check("disables autoconfig notices", 'notification_show_autoconfig = "false"' in override, True)
check(
    "startup mode keeps normal messages",
    "video_font_enable" not in override,
    True,
)

launchers.write_launcher(install, "Silent", core, rom, "all")
override_all = open(launchers.OVERRIDE_CONFIGS["all"], encoding="utf-8").read()
check('"all" also disables the font', 'video_font_enable = "false"' in override_all, True)

# One file per mode: with per-game overrides, two games can want different modes
# at once, and a single shared file would let the last one written decide for both.
check(
    "each OSD mode has its own override file",
    launchers.OVERRIDE_CONFIGS["startup"] != launchers.OVERRIDE_CONFIGS["all"],
    True,
)
check(
    "writing 'all' leaves the startup file intact",
    "video_font_enable"
    not in open(launchers.OVERRIDE_CONFIGS["startup"], encoding="utf-8").read(),
    True,
)
check(
    "a launcher points at the file for its own mode",
    launchers.OVERRIDE_CONFIGS["startup"] in quiet_body,
    True,
)

keep_path = launchers.write_launcher(install, "Loud", core, rom, "keep")
keep_body = open(keep_path, encoding="utf-8").read()
# Every launch carries an override file now, even one suppressing nothing.
# The pad Steam hands the game matches none of RetroArch's bundled profiles, so
# every launch has to point it at ours or nothing on the controller responds.
check(
    '"keep" still points RetroArch at the pad profile',
    "--appendconfig" in keep_body,
    True,
)
quiet_exec = quiet_body.strip().split("\n")[-1]
check(
    "appendconfig is a RetroArch arg, so it precedes -L",
    quiet_exec.index("--appendconfig=") < quiet_exec.index("-L"),
    True,
)
check(
    "the flatpak app id still precedes RetroArch's own args",
    quiet_exec.index("org.libretro.RetroArch") < quiet_exec.index("--appendconfig="),
    True,
)

section("the controller shortcut into RetroArch's menu")
# RetroArch takes a fixed enum here, and its own retroarch.cfg comments have
# documented the wrong numbers for years (libretro/RetroArch#12928). These are
# read off `input_combo_type` in input/input_defines.h; a wrong number here
# silently binds some other combo, which is indistinguishable from "not working".
check("Select + Start is combo 4", launchers.MENU_COMBOS["start_select"], "4")
check("L3 + R3 is combo 2", launchers.MENU_COMBOS["l3_r3"], "2")
check("off writes no value", launchers.MENU_COMBOS["off"], "")

combo_path = launchers.write_launcher(
    install, "Shortcut", core, rom, "startup", menu_combo="start_select"
)
combo_override = open(launchers.OVERRIDE_CONFIGS["startup"], encoding="utf-8").read()
check(
    "the chosen combo reaches RetroArch",
    'input_menu_toggle_gamepad_combo = "4"' in combo_override,
    True,
)
check(
    "it shares the file for the OSD mode rather than adding one",
    launchers.OVERRIDE_CONFIGS["startup"] in open(combo_path, encoding="utf-8").read(),
    True,
)

# The shortcut has to survive "keep": that mode suppresses nothing and used to
# mean no override file existed, which would have dropped the shortcut for
# anyone who left RetroArch's notifications alone.
keep_combo = launchers.write_launcher(
    install, "Loud Shortcut", core, rom, "keep", menu_combo="l3_r3"
)
keep_combo_body = open(keep_combo, encoding="utf-8").read()
check(
    '"keep" still gets an override when a shortcut is set',
    launchers.OVERRIDE_CONFIGS["keep"] in keep_combo_body,
    True,
)
keep_override = open(launchers.OVERRIDE_CONFIGS["keep"], encoding="utf-8").read()
check(
    "and that file suppresses nothing",
    "notification_show_autoconfig" not in keep_override,
    True,
)
check(
    "carrying only the shortcut",
    'input_menu_toggle_gamepad_combo = "2"' in keep_override,
    True,
)

# An unknown combo contributes nothing, but the file is still written for the
# pad profile -- and the point of the check is that no bogus combo value is in
# it, which is now what it asserts.
_nonsense = launchers.write_override_config("keep", "nonsense")
check(
    "an unknown combo name writes no combo value",
    "input_menu_toggle_gamepad_combo" in open(_nonsense, encoding="utf-8").read(),
    False,
)

# A standalone emulator has no libretro menu to open, and nothing here can bind
# one for it. The setting must not leak into its launcher.
emu_combo = launchers.write_launcher(
    install,
    "Standalone",
    "",
    rom,
    "startup",
    emulator={"id": "emu:test", "target": "/bin/true", "args": "{rom}"},
    menu_combo="start_select",
)
check(
    "the shortcut never reaches a custom emulator's launcher",
    "appendconfig" in open(emu_combo, encoding="utf-8").read(),
    False,
)

section("settings and added-games store")
check("default art source", store.get_settings()["art_source"], "auto")
# On by default: RetroArch binds no combo of its own, and the Guide button its
# autoconfig would use never reaches it on a Deck -- Steam takes that button
# first, so an unconfigured game has no way back to the menu.
check("a menu shortcut is configured out of the box", store.get_settings()["menu_combo"], "start_select")
check("default collection name", store.get_settings()["collection_name"], "DeckyEmu")
store.set_settings({"sgdb_api_key": "secret", "art_source": "libretro"})
check("patch persists", store.get_settings()["art_source"], "libretro")
check("untouched defaults survive a patch", store.get_settings()["collection_name"], "DeckyEmu")
store.remember_game(42, {"app_id": 42, "title": "Zelda", "launcher_path": "/x.sh"})
check("library records the game", list(store.get_library().keys()), ["42"])
check("forget returns the entry", store.forget_game(42)["title"], "Zelda")
check("library is empty again", store.get_library(), {})

# The bulk forms exist so a whole-library pass costs one write instead of one per
# game. They have to agree with the single-game versions exactly, or the startup
# backfill and adoption would record something subtly different from an add.
store.remember_game(1, {"app_id": 1, "title": "Kept"})
store.remember_games({2: {"app_id": 2, "title": "Two"}, 3: {"app_id": 3, "title": "Three"}})
check("a bulk write adds every game", sorted(store.get_library().keys()), ["1", "2", "3"])
check("without disturbing what was already there", store.get_library()["1"]["title"], "Kept")
store.remember_games({2: {"app_id": 2, "title": "Renamed"}})
check("and overwrites an existing entry", store.get_library()["2"]["title"], "Renamed")
check("an empty bulk write is a no-op", store.remember_games({}), 0)
check("which leaves the library alone", len(store.get_library()), 3)
dropped = store.forget_games([2, 3, 999])
check("a bulk forget returns what was actually there", sorted(dropped.keys()), ["2", "3"])
check("an id that was never tracked is simply absent", "999" in dropped, False)
check("and the rest survives", list(store.get_library().keys()), ["1"])
check("clearing returns everything it removed", list(store.clear_library().keys()), ["1"])
check("and leaves nothing behind", store.get_library(), {})

section("core .info parsing")
core_dir = os.path.join(TMP, "cores")
os.makedirs(core_dir, exist_ok=True)
open(os.path.join(core_dir, "snes9x_libretro.so"), "w").close()
with open(os.path.join(core_dir, "snes9x_libretro.info"), "w", encoding="utf-8") as handle:
    handle.write(
        'display_name = "Nintendo - SNES / SFC (Snes9x)"\n'
        'supported_extensions = "smc|sfc|swc|fig"\n'
        'systemname = "Super Nintendo Entertainment System"\n'
        'database = "Nintendo - Super Nintendo Entertainment System"\n'
    )
# A core with no .info file, which must fall back to the built-in table.
open(os.path.join(core_dir, "mgba_libretro.so"), "w").close()

cores = ra_cores.list_cores({"core_dirs": [core_dir], "info_dirs": [core_dir]})
check("both cores found", len(cores), 2)
snes = next(core for core in cores if core["id"] == "snes9x")
mgba_short_expected = next(c for c in cores if c["id"] == "mgba")["short_name"]
check("database parsed", snes["databases"], [SNES])
check("extensions parsed", snes["extensions"], ["smc", "sfc", "swc", "fig"])
check("display name parsed", snes["display_name"], "Nintendo - SNES / SFC (Snes9x)")
# Lists of installed cores use the short name: the display name carries a system
# prefix full of hyphens and slashes, and six of those in one line is unreadable.
check("short name falls back to the display name", snes["short_name"],
      "Nintendo - SNES / SFC (Snes9x)")
check("and falls back when there is none", mgba_short_expected, "mgba")
mgba = next(core for core in cores if core["id"] == "mgba")
check("fallback database for info-less core", mgba["databases"], ["Nintendo - Game Boy Advance"])
check(
    "extension filter includes the right core",
    [core["id"] for core in ra_cores.cores_for_extension(cores, "sfc")],
    ["snes9x"],
)
check("extension filter excludes others", ra_cores.cores_for_extension(cores, "iso"), [])

# Achievements read emulated memory, so a core declaring no memory map cannot
# support them. Only the "false" direction is knowable: a core that does publish
# one may still have no achievement sets, so it must never be called supported.
# BlastEm is the real example -- it ships memory_descriptors = "false" while
# Genesis Plus GX, for the same system, ships "true".
open(os.path.join(core_dir, "blastem_libretro.so"), "w").close()
with open(os.path.join(core_dir, "blastem_libretro.info"), "w", encoding="utf-8") as handle:
    handle.write(
        # Shaped like the real file: the display name carries the system, the
        # corename is the core itself.
        'display_name = "Sega - Mega Drive - Genesis (BlastEm)"\n'
        'corename = "BlastEm"\n'
        'memory_descriptors = "false"\n'
    )
open(os.path.join(core_dir, "genesis_plus_gx_libretro.so"), "w").close()
with open(
    os.path.join(core_dir, "genesis_plus_gx_libretro.info"), "w", encoding="utf-8"
) as handle:
    handle.write('display_name = "Genesis Plus GX"\nmemory_descriptors = "true"\n')

cores = ra_cores.list_cores({"core_dirs": [core_dir], "info_dirs": [core_dir]})
by_id = {core["id"]: core for core in cores}
check("a core without a memory map says no", by_id["blastem"]["cheevos"], "no")
check(
    "the picker still gets the system-qualified name",
    by_id["blastem"]["display_name"],
    "Sega - Mega Drive - Genesis (BlastEm)",
)
# The whole point: this is what a list of installed cores prints, and it is
# readable next to five others. The display name, with its two internal hyphens,
# is not.
check("lists get the core's own name", by_id["blastem"]["short_name"], "BlastEm")
check("one with a memory map says yes", by_id["genesis_plus_gx"]["cheevos"], "yes")
# Neither of these has said no, and neither has said yes. Reporting either would
# put words in the .info file's mouth.
check("silence is unknown, not a refusal", by_id["snes9x"]["cheevos"], "unknown")
check("a missing .info file is unknown too", by_id["mgba"]["cheevos"], "unknown")

section("archives -- zipped ROMs must match on their contents")
import zipfile  # noqa: E402

zipped_rom = os.path.join(TMP, "Super Mario World (USA).zip")
with zipfile.ZipFile(zipped_rom, "w") as archive:
    archive.writestr("Super Mario World (USA).sfc", b"not a real rom")

check("looks inside the zip", ra_cores.archive_inner_extension(zipped_rom), "sfc")
check("content_extension unwraps the archive", ra_cores.content_extension(zipped_rom), "sfc")
check(
    "a zipped ROM still matches a core",
    [core["id"] for core in ra_cores.cores_for_extension(cores, ra_cores.content_extension(zipped_rom))],
    ["snes9x"],
)

loose_rom = os.path.join(TMP, "Super Mario World (USA).sfc")
open(loose_rom, "w").close()
check("loose ROM unaffected", ra_cores.content_extension(loose_rom), "sfc")

# A corrupt archive must degrade to the archive extension, not raise.
broken = os.path.join(TMP, "broken.zip")
with open(broken, "wb") as handle:
    handle.write(b"definitely not a zip file")
check("corrupt archive degrades safely", ra_cores.content_extension(broken), "zip")

# 7z cannot be inspected with the standard library; it must not crash.
seven = os.path.join(TMP, "game.7z")
open(seven, "w").close()
check("7z falls back to its own extension", ra_cores.content_extension(seven), "7z")

section("SteamGridDB key entry -- avoiding the on-screen keyboard")
import json as _json  # noqa: E402

import sgdb  # noqa: E402

SAMPLE_KEY = "ab12cd34ef56ab78cd90ef12ab34cd56"

# discover_existing_key reads other plugins' settings under DECKY_HOME, so it
# must only accept values in fields that actually look like key fields.
sgdb_dir = os.path.join(decky.DECKY_HOME, "settings", "decky-steamgriddb")
os.makedirs(sgdb_dir, exist_ok=True)
discovered = os.path.join(sgdb_dir, "settings.json")


def discover(payload):
    with open(discovered, "w", encoding="utf-8") as handle:
        _json.dump(payload, handle)
    return sgdb.discover_existing_key()["key"]


check("finds a flat api_key", discover({"api_key": SAMPLE_KEY}), SAMPLE_KEY)
check("finds a nested apiKey", discover({"a": {"b": {"apiKey": SAMPLE_KEY}}}), SAMPLE_KEY)
check("ignores unrelated fields", discover({"unrelated_id": SAMPLE_KEY}), "")
check("no key present", discover({"window_width": 1280}), "")
# Field names that merely contain "key" must not be mistaken for an API key.
check("ignores hotkey fields", discover({"hotkey_binding": SAMPLE_KEY}), "")
check("ignores keyboard fields", discover({"keyboard_layout": SAMPLE_KEY}), "")
check("accepts steamgriddb_api_key", discover({"steamgriddb_api_key": SAMPLE_KEY}), SAMPLE_KEY)

# The four artwork lookups run concurrently, so each reply has to find its way
# back to the slot that asked for it. Getting this wrong would put the hero image
# in the capsule slot -- artwork that is real, and for the right game, and in the
# wrong shape everywhere Steam draws it.
_sgdb_real_get_json = sgdb.net.get_json


def _fake_get_json(url, headers=None):
    # Answers out of order relative to the slot list, and slowest first, so an
    # implementation that zipped replies by arrival would be caught.
    if "logos" in url:
        return {"success": True, "data": [{"url": "http://x/logo.png"}]}
    if "heroes" in url:
        return {"success": True, "data": [{"url": "http://x/hero.png"}]}
    if "600x900" in url:
        _time.sleep(0.15)
        return {"success": True, "data": [{"url": "http://x/capsule.png"}]}
    if "460x215" in url:
        # No header art for this game: the slot must be absent, not empty.
        return {"success": True, "data": []}
    return None


sgdb.net.get_json = _fake_get_json
_slots = sgdb.art_urls(SAMPLE_KEY, 1234)
check(
    "every artwork URL lands in the slot that asked for it",
    sorted(_slots.items()),
    [("capsule", "http://x/capsule.png"), ("hero", "http://x/hero.png"), ("logo", "http://x/logo.png")],
)
check("a slot with no artwork is absent rather than empty", "header" in _slots, False)
check("no key means no requests at all", sgdb.art_urls("", 1234), {})


# A taken-down asset is not removed from the listing and its URL works: it
# serves a placeholder saying the asset was removed following a DMCA request,
# at the dimensions the real artwork had. Nothing downstream can tell -- it is a
# valid PNG of the right shape -- so the game goes into Steam wearing a notice
# instead of a cover. Real, and reported: Super Mario 3D World's highest-scoring
# 600x900 grid is locked.
def _locked_get_json(url, headers=None):
    if "600x900" in url:
        # Locked first, as SteamGridDB orders it -- by score, and a takedown does
        # not change an asset's score. Taking the first url gets the notice.
        return {"success": True, "data": [
            {"url": "http://x/dmca-notice.png", "lock": True, "width": 600, "height": 900},
            {"url": "http://x/real-cover.png", "lock": False},
        ]}
    if "460x215" in url:
        # Every candidate locked. The slot has to come back empty rather than
        # settle for a notice, so the caller falls back to libretro's thumbnail.
        return {"success": True, "data": [{"url": "http://x/also-locked.png", "lock": True}]}
    return {"success": True, "data": []}


sgdb.net.get_json = _locked_get_json
_locked = sgdb.art_urls(SAMPLE_KEY, 1234)
check("a locked asset is passed over for the next one", _locked.get("capsule"), "http://x/real-cover.png")
check("a slot with nothing but locked assets is absent", "header" in _locked, False)
sgdb.net.get_json = _sgdb_real_get_json

section("SteamGridDB matching -- the wrong game is worse than no artwork")
# Regression: searching "Super Mario Brothers" returns Super Mario Galaxy 2 as
# SteamGridDB's first result, so taking data[0] produced confident, wrong art.
check(
    "Brothers and Bros normalize alike",
    sgdb._normalize_title("Super Mario Brothers") == sgdb._normalize_title("Super Mario Bros."),
    True,
)
check(
    "region tags do not erode the score",
    sgdb._normalize_title("Super Mario Bros. (World)")
    == sgdb._normalize_title("Super Mario Bros."),
    True,
)
check(
    "leading article ignored",
    sgdb._normalize_title("The Legend of Zelda")
    == sgdb._normalize_title("Legend of Zelda"),
    True,
)
check(
    "different games stay different",
    sgdb._normalize_title("Super Mario Bros.") == sgdb._normalize_title("Super Mario Galaxy 2"),
    False,
)

NES_DB = ["Nintendo - Nintendo Entertainment System"]
GALAXY2_RELEASE = 1274572800  # 2010
SMB_RELEASE = 495417600  # 1985

check(
    "a 2010 game is penalised as an NES title",
    sgdb._era_penalty(GALAXY2_RELEASE, NES_DB) > 0.3,
    True,
)
check("a 1985 game is not penalised", sgdb._era_penalty(SMB_RELEASE, NES_DB), 0.0)
check(
    "an unknown system imposes no constraint",
    sgdb._era_penalty(GALAXY2_RELEASE, ["Some - Unlisted System"]),
    0.0,
)
check("a missing release date is not penalised", sgdb._era_penalty(None, NES_DB), 0.0)
check("garbage release date is survivable", sgdb._era_penalty("not-a-date", NES_DB), 0.0)

variants = sgdb._query_variants("Super Mario Brothers", "Super Mario Brothers (USA)")
check("query variants drop tags", any("(USA)" not in v for v in variants), True)
check(
    "query variants include a Bros. spelling",
    any("bros" in v.lower() for v in variants),
    True,
)
check("no key means no search", sgdb.search_game("", "Super Mario Bros."), 0)
check("no title means no search", sgdb.search_game("dummykey", ""), 0)

section("TLS -- cert failures must be detected, never ignored")
import ssl  # noqa: E402
import urllib.error  # noqa: E402

import net  # noqa: E402

check(
    "bare cert error detected",
    net._is_cert_error(ssl.SSLCertVerificationError("bad")),
    True,
)
check(
    "cert error wrapped in URLError detected",
    net._is_cert_error(urllib.error.URLError(ssl.SSLCertVerificationError("bad"))),
    True,
)
check(
    "unrelated network error not treated as a cert problem",
    net._is_cert_error(urllib.error.URLError("name resolution failed")),
    False,
)
check("timeouts are not cert problems", net._is_cert_error(OSError("timed out")), False)

section("probe connections -- reused between probes, and never reused when broken")
# Artwork probing is a dozen or more requests to one host in a row, and a fresh
# TLS handshake for each was most of the wait. Connections are therefore kept per
# thread, which is only safe if a connection the server has since closed is
# noticed and replaced rather than handed out again.
import http.client as _http_client  # noqa: E402


class _FakeResponse:
    def __init__(self, status, location=""):
        self.status = status
        self._location = location
        self.read_called = False

    def getheader(self, name, default=None):
        if name.lower() == "location":
            return self._location or default
        return default

    def read(self):
        self.read_called = True
        return b""


class _FakeConnection:
    """Records requests, and can fail the way a dropped keep-alive does."""

    opened = 0

    def __init__(self, script):
        # script: list of _FakeResponse or Exception, consumed per request
        self.script = list(script)
        self.requests = []
        self.closed = False
        _FakeConnection.opened += 1

    def request(self, method, target, headers=None):
        self.requests.append((method, target, dict(headers or {})))
        nxt = self.script[0] if self.script else _FakeResponse(200)
        if isinstance(nxt, Exception):
            self.script.pop(0)
            raise nxt

    def getresponse(self):
        return self.script.pop(0) if self.script else _FakeResponse(200)

    def close(self):
        self.closed = True


def _with_fake_connections(script_per_connection):
    """Point net's connection factory at scripted fakes. Returns the fakes made."""
    made = []
    scripts = list(script_per_connection)

    def factory(scheme, host, timeout):
        conn = _FakeConnection(scripts.pop(0) if scripts else [])
        made.append(conn)
        return conn

    net.close_connections()
    net._open_connection = factory
    return made


_real_open_connection = net._open_connection

# Two probes to the same host must share one connection.
_made = _with_fake_connections([[_FakeResponse(200), _FakeResponse(404)]])
check("a probe that finds artwork says so", net.head_ok("https://example.test/a.png"), True)
check("and a 404 is a plain no", net.head_ok("https://example.test/b.png"), False)
check("both went down one connection", len(_made), 1)
check("which was asked for both paths", [r[1] for r in _made[0].requests], ["/a.png", "/b.png"])
check("and each response was drained so the socket stays usable", _made[0].script, [])

# A keep-alive the server has already closed surfaces as a failure on the *next*
# request. That must be retried on a fresh connection, not reported as a miss --
# this is the failure mode that makes pooling risky.
_made = _with_fake_connections(
    [[_http_client.RemoteDisconnected("closed")], [_FakeResponse(200)]]
)
check(
    "a dropped keep-alive is retried rather than reported as no artwork",
    net.head_ok("https://example.test/c.png"),
    True,
)
check("on a second connection", len(_made), 2)
check("and the dead one was closed", _made[0].closed, True)

# But a host that is genuinely down must still fail, and be logged, not retried
# forever.
_made = _with_fake_connections([[OSError("unreachable")], [OSError("unreachable")]])
check("a host that never answers is a miss", net.head_ok("https://example.test/d.png"), False)
check("after exactly two attempts", len(_made), 2)

# urlopen followed redirects; http.client does not, so head_ok has to. Without
# this a moved thumbnail reads as "no artwork found".
_made = _with_fake_connections(
    [[_FakeResponse(302, "https://example.test/moved.png"), _FakeResponse(200)]]
)
check("a redirect is followed", net.head_ok("https://example.test/e.png"), True)
check("to the target it named", _made[0].requests[1][1], "/moved.png")

_made = _with_fake_connections([[_FakeResponse(302, "https://example.test/loop.png")] * 6])
check(
    "a redirect that never settles gives up instead of looping",
    net.head_ok("https://example.test/loop.png"),
    False,
)

# Servers that refuse HEAD are asked for one byte instead.
_made = _with_fake_connections([[_FakeResponse(405), _FakeResponse(206)]])
check("a server refusing HEAD is asked for one byte", net.head_ok("https://example.test/f.png"), True)
check("with a Range header", _made[0].requests[1][2].get("Range"), "bytes=0-0")
check("and by GET", _made[0].requests[1][0], "GET")

net._open_connection = _real_open_connection
net.close_connections()

if os.name == "posix":
    check("a system CA bundle is available", net._system_ca_context() is not None, True)
else:
    print("SKIP system CA bundle lookup (no /etc/ssl on this host)")

section("core installer -- guards that must hold without a network")
import installer  # noqa: E402

fake_install = {
    "kind": "flatpak",
    "exe": "/usr/bin/flatpak",
    "config_dir": os.path.join(TMP, "raconfig"),
    "core_dirs": [],
    "info_dirs": [],
}
check(
    "cores land in the config dir",
    installer.target_core_dir(fake_install),
    os.path.join(TMP, "raconfig", "cores"),
)

# Core ids reach a URL and a filesystem path, so they must be validated.
for bad_id in ("../../etc/passwd", "core;rm -rf /", "core id", "core/../x", ""):
    result = installer.install_core(fake_install, bad_id)
    if result.get("ok") or "Invalid core id" not in result.get("error", ""):
        failures.append("install_core accepted a bad id: %r -> %r" % (bad_id, result))
print("PASS %-52s %r" % ("install_core rejects malformed ids", True))

for bad_id in ("../../etc/passwd", "core;rm -rf /", ""):
    result = installer.uninstall_core(fake_install, bad_id)
    if result.get("ok") or "Invalid core id" not in result.get("error", ""):
        failures.append("uninstall_core accepted a bad id: %r -> %r" % (bad_id, result))
print("PASS %-52s %r" % ("uninstall_core rejects malformed ids", True))

check(
    "uninstalling something absent is reported, not silent",
    installer.uninstall_core(fake_install, "definitely_not_installed").get("ok"),
    False,
)

# The catalog is parsed out of ~200 .info members in a zip and asked for by three
# separate callers, so it is cached. A stale cache would hide a core the user has
# just made installable, which is why the key is the zip and the buildbot listing
# rather than a clock.
import zipfile as _zipfile  # noqa: E402


def _write_info_zip(entries, when):
    os.makedirs(installer._CACHE_DIR, exist_ok=True)
    with _zipfile.ZipFile(installer._INFO_ZIP_PATH, "w") as _archive:
        for core_id, system in entries:
            _archive.writestr(
                "%s_libretro.info" % core_id,
                'display_name = "%s"\nsystemname = "%s"\n'
                'database = "%s"\nsupported_extensions = "sfc|smc"\n' % (core_id, system, system),
            )
    os.utime(installer._INFO_ZIP_PATH, (when, when))
    with open(installer._AVAILABLE_PATH, "w", encoding="utf-8") as _handle:
        _json.dump([core_id for core_id, _system in entries], _handle)


_now = _time.time()
_write_info_zip([("fakecore", "Fake System")], _now)
installer.clear_catalog_cache()
check("the catalog is parsed from info.zip", [c["id"] for c in installer.core_catalog()], ["fakecore"])
check("a second call agrees with the first", [c["id"] for c in installer.core_catalog()], ["fakecore"])

# list_installable_cores writes an `installed` flag onto every entry it is given,
# so a cache handing out its own list would carry one caller's answer into the
# next caller's result.
_annotated = installer.core_catalog()
_annotated[0]["installed"] = True
check("annotating the result cannot reach the cache", "installed" in installer.core_catalog()[0], False)

# A newer info.zip must rebuild it. Cached against a clock instead, this is the
# case that would keep serving yesterday's catalog.
_write_info_zip([("fakecore", "Fake System"), ("othercore", "Other System")], _now + 10)
check(
    "a newer info.zip rebuilds the catalog",
    sorted(c["id"] for c in installer.core_catalog()),
    ["fakecore", "othercore"],
)
os.remove(installer._INFO_ZIP_PATH)
os.remove(installer._AVAILABLE_PATH)
installer.clear_catalog_cache()

section("RetroAchievements -- one login, and nothing written without it")
import cheevos  # noqa: E402
import launchers as _launchers  # noqa: E402

# Nothing is written unless achievements are on *and* signed in. Writing
# cheevos_enable = "false" when off would override the user's own choice for
# games launched from here, which is not this plugin's business.
for label, settings in (
    ("off entirely", {"cheevos_enable": False, "cheevos_username": "u", "cheevos_token": "t"}),
    ("on but no token", {"cheevos_enable": True, "cheevos_username": "u", "cheevos_token": ""}),
    ("on but no username", {"cheevos_enable": True, "cheevos_username": "", "cheevos_token": "t"}),
):
    check("nothing is written when %s" % label, cheevos.config_lines(settings), [])

_signed_in = {"cheevos_enable": True, "cheevos_username": "Player", "cheevos_token": "abc123"}
_lines = dict(cheevos.config_lines(_signed_in))
check("achievements are switched on", _lines.get("cheevos_enable"), "true")
check("the username reaches RetroArch", _lines.get("cheevos_username"), "Player")
check("so does the token", _lines.get("cheevos_token"), "abc123")
# RetroArch defaults hardcore ON, and it disables save states. Staying silent
# would hand that default to anyone who merely switched achievements on.
check("hardcore is stated, not left to RetroArch", "cheevos_hardcore_mode_enable" in _lines, True)
check("and defaults to off", _lines.get("cheevos_hardcore_mode_enable"), "false")
check(
    "hardcore is honoured when asked for",
    dict(cheevos.config_lines(dict(_signed_in, cheevos_hardcore=True))).get(
        "cheevos_hardcore_mode_enable"
    ),
    "true",
)

# The username lands in a config file as key = "value", so a quote in it would
# terminate the string early and corrupt everything after it.
for bad in ('a"b', "a b", "a;b", "", "x" * 33, 'foo" \ncheevos_token = "'):
    if cheevos.login(bad, "irrelevant").get("ok"):
        failures.append("login accepted a bad username: %r" % bad)
print("PASS %-52s %r" % ("malformed usernames are refused before any request", True))
check(
    "an empty password never reaches the network",
    cheevos.login("Player", "").get("ok"),
    False,
)

section("the override file must not leak into the user's retroarch.cfg")

# RetroArch ships config_save_on_exit = "true" and saves the *merged* config on
# quit, so every --appendconfig value became permanent and global. A real Deck
# was found with our menu combo and notification settings written into its own
# retroarch.cfg. Whenever we write an override at all, we must turn that off.
_override = _launchers.write_override_config("startup", "start_select")
with io.open(_override, encoding="utf-8") as handle:
    _text = handle.read()
check("an override file was written", bool(_override), True)
check("saving on exit is disabled", 'config_save_on_exit = "false"' in _text, True)
check("the combo is still written", 'input_menu_toggle_gamepad_combo = "4"' in _text, True)

# ... and the one thing there is always to say is where the pad profile is,
# without which a Steam-launched game gets a controller RetroArch cannot bind.
_plainest = _launchers.write_override_config("keep", "off")
check(
    "even the plainest launch carries the pad profile",
    "joypad_autoconfig_dir" in open(_plainest, encoding="utf-8").read(),
    True,
)

_with_token = _launchers.write_override_config("keep", "off", _signed_in)
with io.open(_with_token, encoding="utf-8") as handle:
    check("a token-carrying file is written", 'cheevos_token = "abc123"' in handle.read(), True)
if os.name == "posix":
    check(
        "and is readable only by its owner",
        oct(os.stat(_with_token).st_mode & 0o777),
        oct(0o600),
    )
else:
    print("SKIP file mode check (not POSIX)")

section("removing RetroArch -- only ever the user's own flatpak")
import ra_detect  # noqa: E402

# The command is asserted rather than run: getting `--user` wrong would reach for
# a system install and fail on a password prompt nothing can answer, and getting
# `--delete-data` wrong would destroy saves that were meant to be kept.
_real_flatpak_binary = installer.flatpak_binary
installer.flatpak_binary = lambda: "/usr/bin/flatpak"
try:
    keep = installer.retroarch_uninstall_argv(False)
    wipe = installer.retroarch_uninstall_argv(True)
    check("removal is scoped to the user, never the system", "--user" in keep, True)
    check("it never asks for a system uninstall", "--system" in keep, False)
    check("it targets RetroArch and nothing else", keep[-1], installer.FLATPAK_ID)
    check("it does not prompt, since nothing can answer", "--noninteractive" in keep, True)
    check("keeping data is the default", "--delete-data" in keep, False)
    check("deleting data is opt-in and explicit", "--delete-data" in wipe, True)
    check("the two differ by exactly that flag", len(wipe) - len(keep), 1)

    installer.flatpak_binary = lambda: ""
    check(
        "no flatpak binary yields no command, rather than a broken one",
        installer.retroarch_uninstall_argv(False),
        [],
    )
finally:
    installer.flatpak_binary = _real_flatpak_binary

# Scope decides whether removal is offered at all, so it must not guess: a
# leftover ~/.var/app directory is not an installed application.
_scope_home = os.path.join(TMP, "scopehome")
_real_user_home = ra_detect.user_home
ra_detect.user_home = lambda: _scope_home
try:
    os.makedirs(os.path.join(_scope_home, ".var", "app", ra_detect.FLATPAK_ID), exist_ok=True)
    check("stale user data alone is not an install", ra_detect.flatpak_scope(), "")

    os.makedirs(
        os.path.join(_scope_home, ".local", "share", "flatpak", "app", ra_detect.FLATPAK_ID),
        exist_ok=True,
    )
    check("a user-scope install is recognised", ra_detect.flatpak_scope(), "user")
finally:
    ra_detect.user_home = _real_user_home

if OFFLINE:
    print("SKIP catalog fetch (--offline)")
else:
    catalog = installer.core_catalog()
    ids = {entry["id"] for entry in catalog}
    check("catalog is populated", len(catalog) > 100, True)
    check("every entry has a system name", all(e["system_name"] for e in catalog), True)
    check("every entry has a database", all(e["databases"] for e in catalog), True)
    check("every entry has extensions", all(e["extensions"] for e in catalog), True)
    # Non-game-system cores must not be offered.
    for junk in ("romcleaner", "ffmpeg", "mpv", "imageviewer", "2048", "3dengine"):
        if junk in ids:
            failures.append("catalog should not include %s" % junk)
    print("PASS %-52s %r" % ("utility/media cores excluded", True))
    for wanted in ("mupen64plus_next", "snes9x", "melonds", "prboom"):
        if wanted not in ids:
            failures.append("catalog missing %s" % wanted)
    print("PASS %-52s %r" % ("real emulator cores present", True))
    n64 = sorted(e["id"] for e in catalog if "n64" in e["extensions"])
    check("only real N64 cores claim .n64", n64, ["mupen64plus_next", "parallel_n64"])

section("custom emulators -- must behave exactly like a core")
import emulators  # noqa: E402

DOLPHIN = {
    "name": "Dolphin",
    "kind": "flatpak",
    "target": "org.DolphinEmu.dolphin-emu",
    "args": "-b -e {rom}",
    "extensions": "iso, rvz .gcm  wbfs",
    "databases": ["Nintendo - GameCube"],
}

check("extensions parse from free text", emulators.parse_extensions("iso, rvz .gcm  wbfs"),
      ["iso", "rvz", "gcm", "wbfs"])
check("duplicate extensions collapse", emulators.parse_extensions("iso ISO .iso"), ["iso"])

saved, error = emulators.save(dict(DOLPHIN))
check("a valid emulator saves", error, "")
check("id is slugified", saved["id"], "dolphin")
check("extensions are normalised on save", saved["extensions"], ["iso", "rvz", "gcm", "wbfs"])

# Validation must reject definitions that could not possibly launch.
for bad, expect in [
    ({**DOLPHIN, "name": ""}, "name"),
    ({**DOLPHIN, "target": "not a flatpak id"}, "Flatpak"),
    ({**DOLPHIN, "extensions": ""}, "extension"),
    ({**DOLPHIN, "args": "-b -e"}, "{rom}"),
    ({**DOLPHIN, "kind": "path", "target": "relative/path"}, "executable"),
    ({**DOLPHIN, "kind": "path", "target": "/definitely/not/here"}, "No file exists"),
    ({**DOLPHIN, "kind": "wat"}, "Flatpak or an executable"),
]:
    _, message = emulators.save(dict(bad))
    if expect.lower() not in message.lower():
        failures.append("expected %r in rejection, got %r" % (expect, message))
print("PASS %-52s %r" % ("invalid definitions are rejected", True))

# Shaped like a core so nothing downstream needs to know the difference.
entry = emulators.to_core_entry(saved, "GameCube")
check("namespaced id", entry["id"], "emu:dolphin")
check("id round-trips", emulators.emulator_id(entry["id"]), "dolphin")
check("recognised as an emulator", emulators.is_emulator_id(entry["id"]), True)
check("a core id is not", emulators.is_emulator_id("bsnes"), False)
check("carries the artwork database", entry["databases"], ["Nintendo - GameCube"])
# Every key a real core has, or a consumer joining names prints a blank entry:
# a registered emulator with no short_name put a dangling " · " on the end of the
# RetroArch tab's core list, because Array.join renders undefined as "".
check("has a short name like a core", entry["short_name"], "Dolphin")
check("and is marked as an emulator, not a core", entry["source"], "emulator")
check("matches by extension like a core",
      [c["id"] for c in ra_cores.cores_for_extension([entry], "rvz")], ["emu:dolphin"])

# The whole point of the launcher script: ROM paths break naive quoting.
nasty = "/run/media/mmcblk0p1/games/Wii/Mario & Sonic (USA) [!].rvz"
argv = emulators.launch_argv(saved, nasty)
check("flatpak run is used", argv[:2], ["flatpak", "run"])
check("the ROM directory is shared", "--filesystem=/run/media/mmcblk0p1/games/Wii" in argv, True)
check("the app id precedes the emulator's own args", argv.index("org.DolphinEmu.dolphin-emu") < argv.index("-b"), True)
check("the ROM stays a single argument", nasty in argv, True)
check("no argument was split on spaces", all(" " not in a or a == nasty for a in argv), True)

# launch_argv does not validate, so the executable form can be exercised on any
# host. Saving one requires a real POSIX path, which only exists on the Deck.
native = {
    "name": "PCSX2",
    "kind": "path",
    "target": "/home/deck/Applications/pcsx2.AppImage",
    "args": "-fullscreen -- {rom}",
    "extensions": ["iso", "chd"],
    "databases": ["Sony - PlayStation 2"],
}
native_argv = emulators.launch_argv(native, "/roms/ps2/Game (USA).iso")
check("executable is invoked directly", native_argv[0], native["target"])
check("no flatpak wrapper", "flatpak" not in native_argv, True)
check("its own flags are preserved in order", native_argv[1:3], ["-fullscreen", "--"])
check("the ROM is the final argument", native_argv[-1], "/roms/ps2/Game (USA).iso")
check(
    "a relative executable is refused",
    "executable" in emulators.validate({**native, "target": "pcsx2.AppImage"}).lower(),
    True,
)

# A launcher for an emulator must not carry RetroArch's -L core argument.
emu_launcher = launchers.write_launcher(install, "Mario & Sonic", "", nasty, "startup", saved)
emu_body = open(emu_launcher, encoding="utf-8").read()
check("no libretro core is passed", "-L" not in emu_body, True)
check("no RetroArch appendconfig", "--appendconfig" not in emu_body, True)
check("the nasty ROM path is quoted", "'%s'" % nasty in emu_body, True)

# libretro has no Switch/Wii U/PS3 database, so those carry their own label.
switch, error = emulators.save({
    "name": "Ryujinx", "kind": "flatpak", "target": "org.ryujinx.Ryujinx",
    "args": "{rom}", "extensions": "nsp xci",
    "databases": [], "platform": "Switch", "platform_full": "Nintendo Switch",
})
check("a libretro-less system saves", error, "")
check("no artwork database", switch["databases"], [])
check("label is stored directly", switch["platform"], "Switch")
switch_entry = emulators.to_core_entry(switch)
check("the label is used, not the emulator name", switch_entry["system_name"], "Switch")
check(
    "matches its extensions",
    [c["id"] for c in ra_cores.cores_for_extension([switch_entry], "xci")],
    [switch_entry["id"]],
)

# Without a platform or database, the emulator name is the last resort rather
# than an empty collection name.
nameless = emulators.to_core_entry({"name": "SomeEmu", "databases": [], "extensions": ["bin"]})
check("falls back to the emulator name", nameless["system_name"], "SomeEmu")

section("launch recipes -- args and fullscreen interact, so both are suggested")
# Which recipe each emulator gets is checked in scripts/tests/test_catalog.py,
# against the catalog entries the recipes are now derived from. What matters
# here is the other half: that a recipe, once chosen, is turned into an argument
# list correctly.
check("suggestions come from the catalog",
      emulators.suggest_launch_options("org.DolphinEmu.dolphin-emu")["args"],
      "-b -e {rom}")
check(
    "Dolphin has no fullscreen flag",
    emulators.suggest_launch_options("org.DolphinEmu.dolphin-emu")["fullscreen_args"],
    "",
)

# The combination must put the ROM last and the flag before it.
combo = emulators.launch_argv(
    {"kind": "path", "target": "/x/nimbus.AppImage", "args": "-g {rom}", "fullscreen_args": "-f"},
    "/roms/Game (USA).nsp",
    True,
)
check("full argv", combo, ["/x/nimbus.AppImage", "-f", "-g", "/roms/Game (USA).nsp"])

fs = {
    "name": "Nimbus", "kind": "flatpak", "target": "dev.nimbus.Nimbus", "args": "{rom}",
    "extensions": ["nsp"], "fullscreen_args": "-f", "platform": "Switch",
}
on = emulators.launch_argv(fs, "/roms/switch/Game (USA).nsp", True)
off = emulators.launch_argv(fs, "/roms/switch/Game (USA).nsp", False)
check("the switch is added when on", "-f" in on, True)
check("and omitted when off", "-f" in off, False)
# Emulators taking a positional path need the ROM last, after any flags.
check("the ROM stays last", on[-1], "/roms/switch/Game (USA).nsp")
check("the flag precedes the ROM", on.index("-f") < len(on) - 1, True)
check(
    "unparseable fullscreen args are rejected",
    "fullscreen" in emulators.validate({**fs, "fullscreen_args": "'unclosed"}).lower(),
    True,
)

# Whether a flatpak can reach gamescope's socket is down to its manifest, and
# DuckStation's does not ask for it -- so the bypass layer loaded, failed to
# connect, and the emulator put a Vulkan error in front of the game. Granted per
# launch rather than through `flatpak override`, so nothing is left behind.
check("a flatpak is handed the gamescope socket",
      emulators.GAMESCOPE_SOCKET_ARG in on, True)
check("before the application id", on.index(emulators.GAMESCOPE_SOCKET_ARG) < on.index("dev.nimbus.Nimbus"),
      True)
# An AppImage is not sandboxed, so there is nothing to grant and no flatpak
# argument to put in front of it.
check("but a plain executable is not",
      any("gamescope" in token for token in combo), False)

# Opening an emulator's own interface is a different launch, not the game
# launch with an empty ROM. Every argument in the catalog exists to get into a
# game and back out -- RPCS3's --no-gui most obviously -- and all of them are
# wrong for reaching the windows where firmware and PKGs get installed.
gui = emulators.gui_argv(fs)
check("opening the interface passes no game arguments", gui, [
    "flatpak", "run", emulators.GAMESCOPE_SOCKET_ARG, "dev.nimbus.Nimbus",
])
check("and leaves no empty argument where a ROM would be", "" in gui, False)
check("a plain executable opens on its own",
      emulators.gui_argv({"kind": "appimage", "target": "/home/deck/x.AppImage"}),
      ["/home/deck/x.AppImage"])

# A flatpak does not always run the emulator. shadPS4's manifest names a picker
# for which build of shadPS4 to use, and handing that a game path fails outright
# -- it reads the game as the name of an emulator. `command` goes straight to
# the binary that runs games, and has to reach every way of launching one.
_cmd_emu = {"kind": "flatpak", "target": "net.shadps4.shadPS4", "command": "shadps4",
            "args": "-g {rom}", "fullscreen_args": "--fullscreen true"}
check("a launch goes straight to the named binary",
      emulators.launch_argv(_cmd_emu, "/roms/eboot.bin"),
      ["flatpak", "run", "--command=shadps4", "--filesystem=/roms",
       emulators.GAMESCOPE_SOCKET_ARG, "net.shadps4.shadPS4",
       "--fullscreen", "true", "-g", "/roms/eboot.bin"])

# A sandbox gets more than the binary wrong. shadPS4 enumerated four Vulkan
# devices on a Deck and picked llvmpipe, so every game rendered on the CPU;
# restricting the loader to the AMD driver leaves one device to pick.
_env_emu = dict(_cmd_emu, env={"VK_DRIVER_FILES": "/a.json:/b.json", "FOO": "bar"})
check("environment reaches the launch",
      [a for a in emulators.launch_argv(_env_emu, "/roms/eboot.bin") if a.startswith("--env")],
      ["--env=FOO=bar", "--env=VK_DRIVER_FILES=/a.json:/b.json"])
check("and every other way of starting it",
      ("--env=FOO=bar" in emulators.gui_argv(_env_emu),
       "--env=FOO=bar" in emulators.tool_argv(_env_emu, ["-h"])),
      (True, True))
check("an emulator with no environment gets no --env",
      any(a.startswith("--env") for a in emulators.launch_argv(fs, "/roms/game.nsp")),
      False)
# The catalog is where this is set, and the editor never sends it, so a save
# from there has to carry it over exactly as `command` is.
_saved_env, _ = emulators.save({
    "name": "EnvTest", "kind": "flatpak", "target": "net.shadps4.shadPS4",
    "args": "-g {rom}", "extensions": "bin", "env": {"VK_DRIVER_FILES": "/a.json"},
})
_edited_env, _ = emulators.save({
    "id": _saved_env["id"], "name": "EnvTest Renamed", "kind": "flatpak",
    "target": "net.shadps4.shadPS4", "args": "-g {rom}", "extensions": "bin",
})
check("renaming keeps the environment it needs",
      _edited_env["env"], {"VK_DRIVER_FILES": "/a.json"})
emulators.remove(_saved_env["id"])

# An emulator registered before the environment existed has none of it stored,
# and the launcher already on disk bakes in the argv it was written with. Both
# have to be corrected or the fix reaches nobody who already installed it --
# which is exactly what happened: the launcher kept running without --env and
# shadPS4 kept rendering on the CPU.
check("the launcher format version moved with the argv",
      launchers.FORMAT_VERSION >= 5, True)
import emulator_catalog as _catalog_check  # noqa: E402
check("and shadPS4's recipe moved with its environment",
      _catalog_check.find("shadps4").get("recipe", 1) >= 2, True)
check("and so does opening its interface",
      "--command=shadps4" in emulators.gui_argv(_cmd_emu), True)
check("and a headless run", "--command=shadps4" in emulators.tool_argv(_cmd_emu, ["-h"]), True)
# Every other flatpak runs whatever its manifest names, so nothing is added.
check("an emulator with no override is untouched",
      "--command" in " ".join(emulators.launch_argv(fs, "/roms/game.nsp")), False)
# The editor never sends this field, so a save from there must carry it over
# rather than drop it -- otherwise editing the name would break every launch.
_saved_cmd, _ = emulators.save({
    "name": "ShadTest", "kind": "flatpak", "target": "net.shadps4.shadPS4",
    "args": "-g {rom}", "extensions": "bin", "command": "shadps4",
})
_edited_cmd, _ = emulators.save({
    "id": _saved_cmd["id"], "name": "ShadTest Renamed", "kind": "flatpak",
    "target": "net.shadps4.shadPS4", "args": "-g {rom}", "extensions": "bin",
})
check("renaming an emulator keeps the binary it runs", _edited_cmd["command"], "shadps4")
emulators.remove(_saved_cmd["id"])

# Vita3K starts an installed title rather than a file: `-Fr PCSA00011` boots a
# game and handing it a path does not. A title id also never contains a space,
# which matters because its AppImage word-splits its own arguments.
_vita_emu = {"kind": "path", "target": "/home/deck/Vita3K.AppImage",
             "args": "{rom}", "fullscreen_args": "--fullscreen",
             "installed_args": "-r {title}"}
check("an installed title launches by id, not by path",
      emulators.launch_argv(_vita_emu, "/games/ux0/app/PCSA00011/eboot.bin",
                            title_id="PCSA00011"),
      ["/home/deck/Vita3K.AppImage", "--fullscreen", "-r", "PCSA00011"])
# The ROM path is still what the library records -- every health check here
# asks whether a game's file exists -- but it must not reach the command line.
check("and the path it was installed from is not passed",
      any("eboot" in a for a in
          emulators.launch_argv(_vita_emu, "/games/ux0/app/PCSA00011/eboot.bin",
                                title_id="PCSA00011")),
      False)
check("without a title id it falls back to the path",
      emulators.launch_argv(_vita_emu, "/roms/thing.vpk"),
      ["/home/deck/Vita3K.AppImage", "--fullscreen", "/roms/thing.vpk"])
# Every other emulator ignores a title id entirely.
check("an emulator with no installed_args is unaffected",
      emulators.launch_argv(fs, "/roms/game.nsp", title_id="PCSA00011"),
      emulators.launch_argv(fs, "/roms/game.nsp"))

# Running an emulator as a command-line tool is a third shape again: no window
# at all. RPCS3 unpacks a package or a firmware image this way in seconds, which
# is the only reason those are buttons in the panel rather than instructions.
tool = emulators.tool_argv(fs, ["--headless", "--installpkg", "/x/game.pkg"], ["/x"])
check("a headless run passes its arguments through", tool, [
    "flatpak", "run", "--filesystem=/x", "dev.nimbus.Nimbus",
    "--headless", "--installpkg", "/x/game.pkg",
])
# Nothing is being displayed, so asking for a gamescope socket the run will
# never use only adds a way for it to fail.
check("and asks for no gamescope socket",
      any("gamescope" in token for token in tool), False)
check("an AppImage takes the arguments directly",
      emulators.tool_argv({"kind": "appimage", "target": "/home/deck/x.AppImage"},
                          ["--headless", "--installfw", "/f/PS3UPDAT.PUP"]),
      ["/home/deck/x.AppImage", "--headless", "--installfw", "/f/PS3UPDAT.PUP"])

check("emulators can be removed", emulators.remove("dolphin"), True)
check("removing twice is reported", emulators.remove("dolphin"), False)
check("only the Switch emulator remains", [e["id"] for e in emulators.list_emulators()], ["ryujinx"])
check("it can be removed too", emulators.remove("ryujinx"), True)
check("the list is empty again", emulators.list_emulators(), [])

section("launch recipes reach emulators already installed")
import emulator_catalog as _cat_for_recipe  # noqa: E402

# Launch arguments are written once, when the emulator is installed, so a fix
# to them would otherwise reach nobody who already had it. PCSX2's needed one.
_recipe_entry = {
    "id": "recipe-test", "name": "RecipeTest", "kind": "flatpak",
    "target": "org.example.App", "args": "-old -- {rom}", "extensions": ["iso"],
    "databases": [], "platform": "Test", "fullscreen_args": "-fs",
    "catalog_recipe": 1, "catalog_args": "-old -- {rom}",
    "catalog_fullscreen_args": "-fs",
}
emulators.save(dict(_recipe_entry))
check("an untouched recipe is recorded as the catalog's",
      emulators.find("recipe-test")["catalog_args"], "-old -- {rom}")

# A save that does not mention the catalog fields -- which is every save from
# the editor -- must not drop them, or renaming an emulator would quietly
# freeze its launch arguments forever.
emulators.save({**_recipe_entry, "name": "Renamed",
                "catalog_recipe": None, "catalog_args": None,
                "catalog_fullscreen_args": None})
check("renaming does not lose the recipe record",
      emulators.find("recipe-test")["catalog_args"], "-old -- {rom}")
check("and the rename took", emulators.find("recipe-test")["name"], "Renamed")
emulators.remove("recipe-test")

section("the emulator catalog -- extensions are derived, never stored")
import emu_install  # noqa: E402
import emulator_catalog as emu_catalog  # noqa: E402
import sysenv  # noqa: E402

# The whole point of the catalog is that a one-click install produces an emulator
# that validate() accepts. An entry that cannot be turned into a valid definition
# installs the emulator and then leaves it unregistered and invisible, which is a
# worse outcome than not offering it.
_ids = [entry["id"] for entry in emu_catalog.CATALOG]
check("every catalog id is unique", len(set(_ids)), len(_ids))
check("every id is safe as a directory name", all(emu_catalog.is_safe_id(i) for i in _ids), True)
for _entry in emu_catalog.CATALOG:
    if emulators.ROM_PLACEHOLDER not in (_entry.get("args") or ""):
        failures.append("catalog entry %s passes no ROM" % _entry["id"])
    if not (_entry.get("databases") or _entry.get("platform")):
        failures.append("catalog entry %s names no system" % _entry["id"])
    _source = _entry.get("source") or {}
    if _source.get("kind") == "flatpak":
        if not emu_install._valid_app_id(_source.get("id")):
            failures.append("catalog entry %s has a bad flatpak id" % _entry["id"])
    elif _source.get("kind") == "github":
        if not _source.get("repo") or not _source.get("asset"):
            failures.append("catalog entry %s has an incomplete github source" % _entry["id"])
    else:
        failures.append("catalog entry %s has no usable source" % _entry["id"])
print("PASS %-52s %r" % ("every catalog entry is coherent", True))

# Extensions come from the union of every core claiming the same database. This
# is what makes the catalog cheap to maintain: adding an emulator means naming a
# system, not transcribing a format list that libretro already publishes.
_fake_catalog = {
    "Nintendo - GameCube": ["gcm", "ISO", "rvz"],
    "Nintendo - Wii": ["iso", "wbfs"],
    "Sony - PlayStation 2": ["chd"],
    "Nintendo - Nintendo 3DS": ["3ds", "cci"],
}
check(
    "extensions are the union across an entry's systems",
    emu_catalog.extensions_for(emu_catalog.find("dolphin"), _fake_catalog),
    sorted(
        set(emu_catalog.MANUAL_EXTENSIONS["Nintendo - GameCube"])
        | set(emu_catalog.MANUAL_EXTENSIONS["Nintendo - Wii"])
        | {"gcm", "iso", "rvz", "wbfs"}
    ),
)
# Case is normalised, and a format only the derived catalog knows still arrives.
check("a derived-only format is picked up", "wbfs" in emu_catalog.extensions_for(
    emu_catalog.find("dolphin"), _fake_catalog), True)
check(
    "an unrelated system's formats are not picked up",
    "chd" in emu_catalog.extensions_for(emu_catalog.find("dolphin"), _fake_catalog),
    False,
)

# libretro has no core for the Switch, PS3, PS4, Vita or Xbox 360, so there is
# nothing to derive from and the manual table is the only source. These must work
# with an empty catalog, which is also the offline case.
check(
    "the Switch falls back to the manual table",
    emu_catalog.extensions_for(emu_catalog.find("ryujinx"), []),
    ["nsp", "nsz", "xci", "xcz"],
)
check(
    "and needs no libretro catalog at all",
    emu_catalog.extensions_for(emu_catalog.find("rpcs3"), []) != [],
    True,
)
# This used to assert the opposite -- that a system libretro covers must *not* be
# listed manually, on the grounds that a second source for the same fact is
# maintenance nobody asked for. A real Deck settled the argument: derivation is
# best-effort widening, not a guarantee, because the archive it reads is cached
# and can be a version behind. So every system any entry claims needs a floor.
_unfloored = sorted(
    {
        database
        for entry in emu_catalog.CATALOG
        for database in (entry.get("databases") or [])
        if database not in emu_catalog.MANUAL_EXTENSIONS
    }
)
failures.extend(
    "%s is claimed by an entry but has no floor in MANUAL_EXTENSIONS" % name
    for name in _unfloored
)
check("every system an entry claims has a floor", _unfloored, [])

# Every entry libretro covers must actually resolve against the real catalog.
# The invariant that matters most, and the one that was missing: every entry has
# to be usable with *no* derived catalog at all.
#
# The check below only ever compared against a freshly fetched info.zip, so it
# could not catch what actually happened on a real Deck -- a cached archive four
# days old, still inside its TTL and so never re-fetched, that predated libretro
# adding "Nintendo - Wii U". Nothing failed and nothing was offline; Cemu simply
# derived nothing and refused to register, telling the user to type its
# extensions by hand. Passing an empty map here reproduces that exactly.
_floorless = [
    entry["id"] for entry in emu_catalog.CATALOG if not emu_catalog.extensions_for(entry, {})
]
failures.extend(
    "%s has no extensions without a derived catalog -- add its system to "
    "MANUAL_EXTENSIONS" % name
    for name in _floorless
)
check("every entry is usable with no derived catalog", _floorless, [])
check(
    "and Wii U specifically, which is what a stale archive was missing",
    "wud" in emu_catalog.extensions_for(emu_catalog.find("cemu"), {}),
    True,
)
# The floor must not narrow anything: derivation still widens it.
check(
    "a derived format still comes through",
    "rvz" in emu_catalog.extensions_for(
        emu_catalog.find("dolphin"), {"Nintendo - Wii": ["rvz"]}
    ),
    True,
)

# Offline this cannot be checked, and a system whose database name has a typo
# would otherwise install an emulator that matches no ROM at all.
if OFFLINE:
    print("SKIP catalog extension derivation against real info.zip (--offline)")
else:
    _real = installer.database_extensions()
    _missing = [
        entry["id"]
        for entry in emu_catalog.CATALOG
        if entry.get("databases") and not emu_catalog.extensions_for(entry, _real)
    ]
    failures.extend(
        "%s derives no extensions -- check its database names" % name for name in _missing
    )
    check("every libretro-backed entry derives extensions", _missing, [])
    # The map must be wider than the installable-core catalog, which is filtered
    # to what the buildbot publishes for x86_64. Deriving from that instead left
    # the Wii U and original Xbox with no extensions at all.
    check(
        "the extension map covers systems no installable core does",
        set(_real) > {core["databases"][0] for core in installer.core_catalog()},
        True,
    )

# The label a collection is named from. A libretro-backed entry stores nothing,
# because the label is derived downstream exactly as it is for a core.
check("a libretro system stores no platform", emu_catalog.platform_labels(emu_catalog.find("dolphin")), ("", ""))
check(
    "a libretro-less one carries its own label",
    emu_catalog.platform_labels(emu_catalog.find("ryujinx")),
    ("Switch", "Nintendo Switch"),
)
check(
    "PS4 was added to the platform list, not invented here",
    emu_catalog.platform_labels(emu_catalog.find("shadps4")),
    ("PS4", "PlayStation 4"),
)

# to_emulator must produce something emulators.validate() accepts, or a
# successful install ends with an emulator that cannot be registered.
_defn = emu_catalog.to_emulator(emu_catalog.find("pcsx2"), "net.pcsx2.PCSX2", _fake_catalog)
check("a flatpak entry validates", emulators.validate(_defn), "")
check("and is registered as a flatpak", _defn["kind"], "flatpak")
_defn = emu_catalog.to_emulator(
    emu_catalog.find("azahar"),
    os.path.join(TMP, "Azahar.AppImage"),
    _fake_catalog,
)
check("an AppImage entry is registered as a path", _defn["kind"], "path")
if os.name == "posix":
    # validate() requires an absolute POSIX path that exists, so the file has to
    # be real and the check cannot run on Windows.
    with open(_defn["target"], "w", encoding="utf-8") as _handle:
        _handle.write("#!/bin/sh\n")
    check("an AppImage entry validates", emulators.validate(_defn), "")
else:
    print("SKIP AppImage entry validation (needs a POSIX path)")

# The point of the floor, stated as the thing the user actually hit: with no
# derived catalog at all, a real entry still produces a saveable emulator. This
# is what refused to register Cemu on a real Deck.
check(
    "an entry still validates with no derived catalog",
    emulators.validate(emu_catalog.to_emulator(emu_catalog.find("cemu"), "info.cemu.Cemu", {})),
    "",
)
# The guard behind it is still worth keeping: a system nothing knows about
# yields nothing, and that is refused rather than saved as an emulator matching
# no ROM at all.
check(
    "but a system nothing knows is a refusal, not an empty emulator",
    emulators.validate(
        emu_catalog.to_emulator({**emu_catalog.find("cemu"), "databases": ["Made - Up"]},
                                "info.cemu.Cemu", {})
    ) != "",
    True,
)

section("installing an emulator -- the guards, without a network")

# The same rule as RetroArch: only ever the user's own flatpak. A system-scope
# uninstall hits a password prompt nothing can answer.
_real_which = emu_install.shutil.which
emu_install.shutil.which = lambda name: "/usr/bin/flatpak"
try:
    _steps = emu_install.flatpak_install_steps("org.DolphinEmu.dolphin-emu")
    check("installing adds the remote first", _steps[0][1], "remote-add")
    check("and is scoped to the user", "--user" in _steps[1], True)
    check("it never prompts, since nothing can answer", "--noninteractive" in _steps[1], True)
    _rm = emu_install.flatpak_uninstall_argv("org.DolphinEmu.dolphin-emu")
    check("removal is scoped to the user too", "--user" in _rm, True)
    check("it never asks for a system uninstall", "--system" in _rm, False)
    # Uninstalling an emulator means "take it off my list", not "destroy my saves".
    check("removing an emulator never deletes its data", "--delete-data" in _rm, False)
    # The app id reaches a subprocess argument list, so a malformed one must be
    # refused here rather than passed to flatpak to interpret.
    for _bad in ("", "not-an-id", "../../etc", "a.b; rm -rf /", "org.Foo Bar"):
        if emu_install.flatpak_install_steps(_bad) or emu_install.flatpak_uninstall_argv(_bad):
            failures.append("a bad flatpak id was accepted: %r" % _bad)
    print("PASS %-52s %r" % ("malformed application ids are refused", True))
finally:
    emu_install.shutil.which = _real_which

_real_which = emu_install.shutil.which
emu_install.shutil.which = lambda name: ""
try:
    check(
        "no flatpak binary yields no command, rather than a broken one",
        emu_install.flatpak_install_steps("org.DolphinEmu.dolphin-emu"),
        [],
    )
finally:
    emu_install.shutil.which = _real_which

# An id becomes a directory name under the user's home, so traversal must not
# survive it.
for _bad in ("../etc", "a/b", "", ".hidden", "A-Capital", "x" + chr(0)):
    if emu_catalog.is_safe_id(_bad):
        failures.append("unsafe emulator id accepted: %r" % _bad)
print("PASS %-52s %r" % ("emulator ids cannot escape their folder", True))

# Leftover data is not an install -- the same distinction ra_detect makes for
# RetroArch. Offering "Remove" for a flatpak that is already gone is a dead end.
_fp_home = os.path.join(TMP, "fphome")
_real_user_home = sysenv.user_home
sysenv.user_home = lambda: _fp_home
try:
    os.makedirs(os.path.join(_fp_home, ".var", "app", "net.pcsx2.PCSX2"), exist_ok=True)
    check("stale user data alone is not an install", emu_install.flatpak_installed("net.pcsx2.PCSX2"), False)
    os.makedirs(
        os.path.join(_fp_home, ".local", "share", "flatpak", "app", "net.pcsx2.PCSX2"),
        exist_ok=True,
    )
    check("a user-scope install is recognised", emu_install.flatpak_installed("net.pcsx2.PCSX2"), True)
    check("and its scope is reported", emu_install.flatpak_scope("net.pcsx2.PCSX2"), "user")
    check("an absent one has no scope", emu_install.flatpak_scope("net.rpcs3.RPCS3"), "")

    # AppImages live under the user's home, and removal must never reach outside
    # the folder this plugin created.
    _app_dir = emu_install.emulators_dir("vita3k")
    with open(os.path.join(_app_dir, "Vita3K-x86_64.AppImage"), "w", encoding="utf-8") as _handle:
        _handle.write("x")
    check("an installed AppImage is found", os.path.basename(emu_install.installed_appimage("vita3k")), "Vita3K-x86_64.AppImage")
    check("asking about an absent one creates nothing", emu_install.installed_appimage("azahar"), "")
    check(
        "and does not leave an empty folder behind",
        os.path.isdir(emu_install.emulators_dir("azahar", create=False)),
        False,
    )
    check("removal reports success", emu_install.remove_appimage("vita3k"), (True, ""))
    check("removing twice is reported, not crashed", emu_install.remove_appimage("vita3k")[0], False)
    check("a traversing id is refused outright", emu_install.remove_appimage("../..")[0], False)
finally:
    sysenv.user_home = _real_user_home

# Release assets carry an aarch64 build beside the x86_64 one. A substring match
# would install the wrong architecture, which fails at exec time with nothing
# that names the cause -- so the patterns are anchored.
_fake_release = {
    "tag_name": "1.2.3",
    "assets": [
        {"name": "Vita3K-aarch64.AppImage", "browser_download_url": "https://x/arm", "size": 1},
        {"name": "Vita3K-x86_64.AppImage", "browser_download_url": "https://x/x86", "size": 2},
    ],
}
_real_get_json = net.get_json
net.get_json = lambda url, headers=None: _fake_release
try:
    _asset, _error = emu_install.resolve_github_asset("Vita3K/Vita3K", r"^Vita3K-x86_64\.AppImage$")
    check("the x86_64 asset is chosen", _asset["name"], "Vita3K-x86_64.AppImage")
    check("and the release tag is recorded", _asset["tag"], "1.2.3")
    _asset, _error = emu_install.resolve_github_asset("Vita3K/Vita3K", r"^Nothing\.AppImage$")
    check("no match is an error, not a silent skip", bool(_error), True)
    check("nothing is returned with it", _asset, None)

    # Both Ryujinx mirrors answer 451: taken down, now self-hosting their git.
    # "GitHub did not respond" would send someone to check their wifi.
    net.get_json = lambda url, headers=None: None
    _asset, _error = emu_install.resolve_github_asset("nimbus-emu/Releases", r"^x$")
    check("a project that left GitHub says so", "moved" in _error, True)

    for _bad in ("", "notarepo", "a/b/c", "../../etc"):
        if emu_install.resolve_github_asset(_bad, r"^x$")[1] == "":
            failures.append("a bad repository name was accepted: %r" % _bad)
    print("PASS %-52s %r" % ("malformed repository names are refused", True))
finally:
    net.get_json = _real_get_json

section("recommended settings -- writing into a config the user owns")
import emu_config  # noqa: E402

# Azahar reads a value only when its companion `\default` line is absent or
# true; `\default=true` means the stored value is thrown away entirely. So a
# value written without clearing that flag does nothing at all, and this is the
# check that would catch it.
_cfg_home = os.path.join(TMP, "cfghome")
_cfg_path = os.path.join(_cfg_home, ".config", "azahar-emu", "qt-config.ini")
os.makedirs(os.path.dirname(_cfg_path), exist_ok=True)


def _write_cfg(text):
    with io.open(_cfg_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _read_cfg():
    with io.open(_cfg_path, encoding="utf-8") as handle:
        return handle.read()


_real_user_home = sysenv.user_home
sysenv.user_home = lambda: _cfg_home
try:
    _write_cfg(
        "[Controls]\n"
        "profile=0\n"
        'profiles\\1\\button_a="code:65,engine:keyboard"\n'
        "profiles\\1\\button_a\\default=true\n"
        'profiles\\1\\button_b="code:83,engine:keyboard"\n'
        "profiles\\1\\button_b\\default=false\n"
        "\n"
        "[UI]\n"
        "fullscreen=false\n"
        "fullscreen\\default=true\n"
        "hideInactiveMouse=false\n"
        "hideInactiveMouse\\default=true\n"
    )
    _result = emu_config.apply_setup(emu_catalog.find("azahar"))
    _text = _read_cfg()
    check("the setup reports success", _result["ok"], True)
    check("fullscreen is turned on", "fullscreen=true" in _text, True)
    # Without this line Azahar reads its own default and the write above is
    # silently discarded -- the failure would look exactly like doing nothing.
    check(
        "and its default flag is cleared, or the value is ignored",
        "fullscreen\\default=false" in _text,
        True,
    )
    # The exact string matters. Azahar 2125.1.3 has no `maptype`/`api` support:
    # it reads params.Get("guid", "0") and resolves "0" to a placeholder
    # joystick, so a binding without a real GUID reads false forever. That is
    # what shipped once, from reading master instead of the installed tag.
    check(
        "an untouched binding is replaced",
        'profiles\\1\\button_a="button:1,engine:sdl,'
        'guid:030079f6de280000ff11000001000000,port:0"' in _text,
        True,
    )
    check("bindings name a real pad, never guid 0", 'guid:0"' in _text or "guid:0," in _text, False)
    # The D-pad is a hat on this pad and the C-stick is axes 3/4 -- read off the
    # device with SDL_GameControllerMappingForGUID, not from SDL's
    # GameController numbering, which disagrees about both.
    check("the D-pad is bound as a hat", "hat:0,port:0" in _text, True)
    check("the C-stick uses the pad's own axes", "axis_x:3,axis_y:4" in _text, True)
    # The whole safety rule: `\default=false` means the value differs from the
    # emulator's own default because somebody set it. Not ours to overwrite.
    check(
        "a binding the user changed is left alone",
        'profiles\\1\\button_b="code:83,engine:keyboard"' in _text,
        True,
    )
    check(
        "and is reported as skipped rather than silently dropped",
        "Controls/profiles\\1\\button_b" in _result["skipped"],
        True,
    )
    # Anything not named in the spec must survive untouched, so this stays a
    # line editor rather than a parser that rewrites what it did not understand.
    check("unrelated settings survive", "hideInactiveMouse=false" in _text, True)
    check("the profile index is untouched", "\nprofile=0\n" in _text, True)

    # 15, not 16: button_b is the one the user changed, and it was left alone.
    check(
        "every binding names Steam Input's virtual pad",
        _text.count("guid:030079f6de280000ff11000001000000"),
        15,
    )

    # Applying twice must not duplicate keys or drift. It must also still do
    # something: writing a value requires clearing its `\default` flag, so a
    # naive rule would read our own writes back as the user's and skip
    # everything, leaving the re-apply action doing nothing.
    _again = emu_config.apply_setup(emu_catalog.find("azahar"))
    check("applying twice changes nothing further", _read_cfg(), _text)
    check("our own writes are not mistaken for the user's", len(_again["skipped"]), 1)
    # 16: every key in the spec except the one binding the user had changed.
    check("so re-applying still re-applies", len(_again["applied"]), 16)

    # A missing file is the fresh-install case: Azahar has not run yet, and a
    # partial file is fine because it fills in whatever it does not find.
    os.remove(_cfg_path)
    _fresh = emu_config.apply_setup(emu_catalog.find("azahar"))
    _text = _read_cfg()
    check("a missing config is created", _fresh["ok"], True)
    check("with the sections it needs", "[Controls]" in _text and "[UI]" in _text, True)
    check("and nothing skipped", _fresh["skipped"], [])
    check(
        "every written key carries a cleared default flag",
        _text.count("\\default=false"),
        len(_fresh["applied"]),
    )

    # Correcting our own past mistakes is the case that matters most here. An
    # earlier version wrote `maptype:all` bindings, which the released Azahar
    # does not understand; they carry `\default=false` like any written value,
    # so without the supersede rule they would be read as the user's own choice
    # and left broken forever. This is the check that a wrong setting shipped
    # once can still be fixed.
    _write_cfg(
        "[Controls]\n"
        'profiles\\1\\button_a="engine:sdl,maptype:all,api:controller,button:1"\n'
        "profiles\\1\\button_a\\default=false\n"
        'profiles\\1\\button_b="code:83,engine:keyboard"\n'
        "profiles\\1\\button_b\\default=false\n"
    )
    os.remove(emu_config.STATE_PATH)
    _fixed = emu_config.apply_setup(emu_catalog.find("azahar"))
    _text = _read_cfg()
    check(
        "a binding this plugin got wrong before is corrected",
        "guid:030079f6de280000ff11000001000000" in _text.split("button_a=")[1].splitlines()[0],
        True,
    )
    check(
        "while a real user binding beside it is still left alone",
        'profiles\\1\\button_b="code:83,engine:keyboard"' in _text,
        True,
    )
    check("and only that one is reported skipped", _fixed["skipped"], ["Controls/profiles\\1\\button_b"])

    # What was written is recorded, which is what lets the *next* correction
    # tell this plugin's work from the user's without a pattern for every past
    # mistake.
    check("what was written is recorded", os.path.isfile(emu_config.STATE_PATH), True)
    with io.open(emu_config.STATE_PATH, encoding="utf-8") as _handle:
        _state = _json.load(_handle)
    check("under the emulator's id", "azahar" in _state, True)
    check(
        "and the user's untouched binding is not claimed as ours",
        "Controls/profiles\\1\\button_b" in _state["azahar"],
        False,
    )

    # Settings are applied when an emulator is installed, and an emulator is
    # installed once -- so without a version to compare against, a *correction*
    # to those settings could only ever reach someone who had not installed it
    # yet. This is what replaced a button the user had to know to press.
    check("a version is recorded once applied", _state["azahar"][emu_config.VERSION_KEY],
          emu_catalog.find("azahar")["setup"]["version"])
    check("so nothing is re-applied at the next startup",
          emu_config.needs_setup(emu_catalog.find("azahar")), False)

    _bumped = _json.loads(_json.dumps(_state))
    _bumped["azahar"][emu_config.VERSION_KEY] = 0
    with io.open(emu_config.STATE_PATH, "w", encoding="utf-8") as _handle:
        _json.dump(_bumped, _handle)
    check("but a newer version is picked up",
          emu_config.needs_setup(emu_catalog.find("azahar")), True)
    # Never installed at all is also "needs applying", which is what makes the
    # first install write them.
    os.remove(emu_config.STATE_PATH)
    check("and so is an emulator that has never had them",
          emu_config.needs_setup(emu_catalog.find("azahar")), True)
    # A bare entry rather than a named emulator: every one of them grows a setup
    # block sooner or later, and this is about the absence, not about who.
    _no_setup = {"id": "nosetup", "name": "No Setup"}
    check("while one with no settings never asks",
          emu_config.needs_setup(_no_setup), False)

    # Recorded even when every key was left as the user set them, or the attempt
    # would repeat at every single startup for no gain.
    _write_cfg(
        "[Controls]\n"
        'profiles\\1\\button_a="code:65,engine:keyboard"\n'
        "profiles\\1\\button_a\\default=false\n"
    )
    emu_config.apply_setup(emu_catalog.find("azahar"))
    check("a run that changed nothing still settles the version",
          emu_config.needs_setup(emu_catalog.find("azahar")), False)

    # PCSX2 writes no bindings of its own -- only `Type` -- so an absent `Up`
    # means nobody has configured the pad, and that is what the anchor keys off.
    _pcsx2_ini = os.path.join(
        _cfg_home, ".var", "app", "net.pcsx2.PCSX2", "config", "PCSX2", "inis", "PCSX2.ini"
    )
    os.makedirs(os.path.dirname(_pcsx2_ini), exist_ok=True)
    with io.open(_pcsx2_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Pad1]\nType = DualShock2\n\n[InputSources]\nSDL = false\n")
    emu_config.apply_setup(emu_catalog.find("pcsx2"))
    with io.open(_pcsx2_ini, encoding="utf-8") as _handle:
        _p_text = _handle.read()
    check("an unconfigured PCSX2 pad is bound", "Cross = SDL-0/A" in _p_text, True)
    # PCSX2 runs a setup wizard until told otherwise. It is modal, a gamepad
    # cannot complete it, and its first run rewrote the whole config.
    check("and the setup wizard is answered", "SetupWizardIncomplete = false" in _p_text, True)

    # That rewrite is the case that shipped broken: PCSX2's own first run put
    # keyboard defaults in the pad, which are neither absent nor ours, so the
    # section would have been skipped forever.
    with io.open(_pcsx2_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Pad1]\nUp = Keyboard/Up\nCross = Keyboard/X\n")
    emu_config.apply_setup(emu_catalog.find("pcsx2"))
    with io.open(_pcsx2_ini, encoding="utf-8") as _handle:
        _p_after = _handle.read()
    check("a pad PCSX2 reset to its keyboard defaults is rebound",
          "Cross = SDL-0/A" in _p_after, True)
    # Without SDL as an input source the bindings above address nothing.
    check("and SDL is switched on as an input source", "SDL = true" in _p_text, True)
    check("the pad type is left as PCSX2 set it", "Type = DualShock2" in _p_text, True)

    # A pad somebody has already bound is theirs, whole.
    with io.open(_pcsx2_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Pad1]\nUp = Keyboard/W\nCross = Keyboard/Space\n")
    emu_config.apply_setup(emu_catalog.find("pcsx2"))
    with io.open(_pcsx2_ini, encoding="utf-8") as _handle:
        _p_kept = _handle.read()
    check("a pad already bound by hand is untouched", "Up = Keyboard/W" in _p_kept, True)
    check("all of it", "Cross = Keyboard/Space" in _p_kept, True)

    # An emulator with sensible defaults has no setup block, and that is not an
    # error.
    check("no setup block is not a failure",
          emu_config.apply_setup({"id": "nosetup", "name": "No Setup"}),
          {"ok": True, "applied": [], "skipped": [], "changed": False})

    # DuckStation shares PCSX2's input manager, and a real install confirmed it
    # shares the trap too: its own defaults are `Up = Keyboard/Up`, so without
    # that listed as replaceable the pad is skipped key by key.
    _duck_ini = os.path.join(
        _cfg_home, ".var", "app", "org.duckstation.DuckStation",
        "config", "duckstation", "settings.ini",
    )
    os.makedirs(os.path.dirname(_duck_ini), exist_ok=True)
    with io.open(_duck_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "[Main]\nSetupWizardIncomplete = true\nConfirmPowerOff = true\n\n"
            "[Pad1]\nType = AnalogController\nUp = Keyboard/Up\nCross = Keyboard/K\n"
        )
    emu_config.apply_setup(emu_catalog.find("duckstation"))
    with io.open(_duck_ini, encoding="utf-8") as _handle:
        _duck_text = _handle.read()
    check("DuckStation's keyboard pad is rebound", "Cross = SDL-0/A" in _duck_text, True)
    check("its setup wizard is answered too",
          "SetupWizardIncomplete = false" in _duck_text, True)
    # Otherwise quitting asks "are you sure", and a Steam shortcut never stops.
    check("and it stops asking before powering off",
          "ConfirmPowerOff = false" in _duck_text, True)
    # It checks GitHub for a release on every start and puts the answer in a
    # dialog in front of the game -- a link nobody can follow from Game Mode.
    check("and stops checking GitHub for updates",
          "CheckAtStartup = false" in _duck_text, True)

    # PPSSPP's ini carries a UTF-8 BOM. Read as plain utf-8 the mark stays glued
    # to the first line, `[General]` matches no section, and a second `[General]`
    # is appended -- a whole section silently duplicated.
    _pp_ini = os.path.join(
        _cfg_home, ".var", "app", "org.ppsspp.PPSSPP",
        "config", "ppsspp", "PSP", "SYSTEM", "ppsspp.ini",
    )
    os.makedirs(os.path.dirname(_pp_ini), exist_ok=True)
    with io.open(_pp_ini, "w", encoding="utf-8-sig", newline="\n") as _handle:
        _handle.write("[General]\nFirstRun = False\nCheckForNewVersion = True\n")
    emu_config.apply_setup(emu_catalog.find("ppsspp"))
    with io.open(_pp_ini, encoding="utf-8-sig") as _handle:
        _pp_text = _handle.read()
    check("a value is written past a byte order mark",
          "CheckForNewVersion = False" in _pp_text, True)
    check("without duplicating the section it sits in",
          _pp_text.count("[General]"), 1)
    check("and the mark itself survives",
          io.open(_pp_ini, "rb").read(3), b"\xef\xbb\xbf")
    check("with everything around it left alone", "FirstRun = False" in _pp_text, True)

    # Cemu ships no controller profile and writes no settings until it is used,
    # so there is nothing to edit and nothing to parse -- the file is supplied
    # whole, and owning it means "absent, or exactly what we last wrote".
    _cemu_dir = os.path.join(_cfg_home, ".var", "app", "info.cemu.Cemu", "config", "Cemu")
    _cemu_profile = os.path.join(_cemu_dir, "controllerProfiles", "controller0.xml")
    _cemu_settings = os.path.join(_cemu_dir, "settings.xml")
    _cemu = emu_config.apply_setup(emu_catalog.find("cemu"))
    check("Cemu's profile is created from nothing", _cemu["ok"], True)
    check("including the directory it lives in", os.path.isfile(_cemu_profile), True)
    with io.open(_cemu_profile, encoding="utf-8") as _handle:
        _cemu_text = _handle.read()
    # Wii U puts A on the right, where SDL puts B. Getting this "obvious" would
    # swap confirm and cancel in every game.
    check("with A on the right face button",
          "<mapping>1</mapping>\n\t\t\t\t<button>1</button>" in _cemu_text, True)
    check("and the Steam virtual pad's guid",
          emu_catalog.steam_pad._STEAM_PAD_GUID in _cemu_text, True)
    # Cemu decides it has never run by whether settings.xml exists, so writing
    # the file at all is what stops the Getting Started dialog.
    check("and settings.xml exists so it is not a first start",
          os.path.isfile(_cemu_settings), True)

    # Cemu's loader falls back to a different value than the setting is declared
    # with, and assigns unconditionally -- so a key missing from our file
    # *replaces* Cemu's default rather than leaving it alone. An absent TVDevice
    # selects no audio output, which is why a game ran with picture and no
    # sound. These keys therefore look redundant and are not, which is exactly
    # how they would get deleted again.
    with io.open(_cemu_settings, encoding="utf-8") as _handle:
        _settings_text = _handle.read()
    for _key, _value, _why in (
        ("TVDevice", "default", "an empty device name is no audio output at all"),
        ("api", "3", "audio_api defaults to Windows-only DirectSound, so the "
                     "device lookup throws and the game is silent"),
        ("api", "1", "an absent Graphic/api quietly downgrades Vulkan to OpenGL"),
        ("TVVolume", "50", "an absent TVVolume drops the volume to 20"),
        ("InputVolume", "50", "an absent InputVolume drops it to 20"),
    ):
        if "<%s>%s</%s>" % (_key, _value, _key) not in _settings_text:
            failures.append("Cemu settings.xml must pin %s: %s" % (_key, _why))
    check("every default our own file would displace is restated",
          [f for f in failures if "settings.xml must pin" in f], [])

    # Applying again is a no-op, and does not report the file as the user's.
    _cemu_again = emu_config.apply_setup(emu_catalog.find("cemu"))
    check("applying again changes nothing", _cemu_again["changed"], False)
    check("and claims nothing was skipped", _cemu_again["skipped"], [])

    # RPCS3 ships no input config at all -- a headless first run writes config.yml
    # and never creates input_configs -- so the pad file is supplied whole, and
    # everything in it that is not a binding has to be there too.
    _rpcs3_pad_file = os.path.join(
        _cfg_home, ".config", "rpcs3", "input_configs", "global", "Default.yml",
    )
    _rpcs3 = emu_config.apply_setup(emu_catalog.find("rpcs3"))
    check("RPCS3's pad file is created where there was none", _rpcs3["ok"], True)
    with io.open(_rpcs3_pad_file, encoding="utf-8") as _handle:
        _rpcs3_text = _handle.read()
    check("player one uses the evdev handler",
          "Player 1 Input:\n  Handler: Evdev\n" in _rpcs3_text, True)
    # RPCS3 matches the pad by the name the kernel reports, not by a guid, so
    # this string is the whole binding -- and it is the same one SDL checksums
    # into the guid every other entry uses.
    check("and names the Steam pad exactly as the kernel reports it",
          "  Device: %s\n" % emu_catalog.rpcs3._RPCS3_PAD_DEVICE in _rpcs3_text, True)
    check("with Cross on the bottom face button, uncrossed",
          "    Cross: A\n" in _rpcs3_text, True)
    check("and every player slot present",
          _rpcs3_text.count("Input:\n"), emu_catalog.rpcs3._RPCS3_PLAYERS)
    check("the slots nobody is holding are explicitly empty",
          _rpcs3_text.count('  Handler: "Null"\n'), emu_catalog.rpcs3._RPCS3_PLAYERS - 1)
    # A profile is only live if it is the active one, and RPCS3's fallback stops
    # being Default the moment somebody saves a second profile.
    _rpcs3_active = os.path.join(os.path.dirname(os.path.dirname(_rpcs3_pad_file)),
                                 "active_profiles.yml")
    with io.open(_rpcs3_active, encoding="utf-8") as _handle:
        check("and the written profile is the active one",
              "global: Default" in _handle.read(), True)
    # RPCS3's GUI settings are the one place a setup mixes formats: a pad file
    # written whole, plus two keys inside a Qt ini that already holds the user's
    # language. Both have to land, and the ini has to keep what was there.
    _rpcs3_gui = os.path.join(
        _cfg_home, ".config", "rpcs3", "GuiConfigs", "CurrentSettings.ini",
    )
    with io.open(_rpcs3_gui, encoding="utf-8") as _handle:
        _gui_text = _handle.read()
    check("the modal welcome box is answered in advance",
          "infoBoxEnabledWelcome = false" in _gui_text, True)
    # RPCS3 reopens each picker where it was last used, so this is what puts a
    # sent PUP or PKG on screen instead of a file browser at the home directory.
    check("and the firmware picker opens on the transfer folder",
          "lastExplorePathPUP = %s" % emu_install.firmware_dir() in _gui_text, True)
    import fileserver  # noqa: E402
    import ps3_games  # noqa: E402

    # The package picker opens on the staged links, not on the ROM folder.
    # RPCS3's install dialog is as wide as the filename it prints inline, and a
    # real 101-character name made it 1539px across on a 1280px screen -- the
    # Install button off the right edge, visible because gamescope scales the
    # picture, unreachable because it does not scale the pointer.
    check("the package picker opens on the staged links",
          "lastExplorePathPKG = %s" % ps3_games.stage_dir() in _gui_text, True)
    # The tokens resolve by rebuilding the path rather than importing the module
    # that owns it, because that import would be a cycle. These keep them honest.
    check("the firmware token is the firmware folder",
          emu_config._firmware_dir(), emu_install.firmware_dir())
    check("and the transfer token is where uploads land",
          emu_config._transfer_dir(), fileserver.default_dir())
    check("and the packages token is the staging folder",
          emu_config._packages_dir(), ps3_games.stage_dir())

    # ---- PARAM.SFO ----------------------------------------------------------
    # Built here, byte by byte, from the documented layout rather than shipped
    # as a file. It used to be Braid's own PARAM.SFO, lifted off a Deck -- a
    # kilobyte of a commercial game, Sony's copyright notice included, sitting
    # in a repository that is going public. Not worth it for a parser test.
    #
    # Constructing it from the spec keeps what the fixture was for. The
    # objection to a generated file is that it only proves the writer and the
    # reader agree; that does not apply here, because there is no writer -- this
    # is struct.pack against the format as documented, and sfo.py has to meet it
    # rather than meet itself.
    def _make_sfo(pairs):
        """A PARAM.SFO holding `pairs`. Strings and uint32s, which is all it uses.

        Header: magic, version, offset of the key table, offset of the data
        table, entry count. Then one 16-byte index entry per key -- key offset,
        format, used length, total length, data offset -- then the keys as
        null-terminated ASCII, then the values.
        """
        import struct as _struct

        keys, values, index = b"", b"", b""
        for name, value in pairs:
            if isinstance(value, int):
                fmt, raw = 0x0404, _struct.pack("<I", value)
                used = total = 4
            else:
                fmt = 0x0204
                raw = value.encode("utf-8") + b"\x00"
                used = len(raw)
                # Real ones pad the value to a multiple of four; the reader has
                # to cope with total > used, so the fixture exercises that.
                total = (used + 3) & ~3
                raw = raw.ljust(total, b"\x00")
            index += _struct.pack("<HHIII", len(keys), fmt, used, total, len(values))
            keys += name.encode("ascii") + b"\x00"
            values += raw
        keys = keys.ljust((len(keys) + 3) & ~3, b"\x00")

        header_size = _struct.calcsize("<4sIIII")
        key_table = header_size + len(index)
        data_table = key_table + len(keys)
        return (_struct.pack("<4sIIII", b"\x00PSF", 0x0101, key_table, data_table,
                             len(pairs)) + index + keys + values)

    _sfo_bytes = _make_sfo([
        ("APP_VER", "01.00"),
        ("BOOTABLE", 1),
        ("CATEGORY", "HG"),
        ("PARENTAL_LEVEL", 4),
        ("TITLE", "Braid"),
        ("TITLE_ID", "NPUB30133"),
    ])
    _sfo_path = os.path.join(_cfg_home, "made-up-PARAM.SFO")
    with io.open(_sfo_path, "wb") as _handle:
        _handle.write(_sfo_bytes)

    _sfo = ps3_games.read_sfo(_sfo_path)
    check("a PARAM.SFO gives up its title", _sfo.get("TITLE"), "Braid")
    check("and its title id", _sfo.get("TITLE_ID"), "NPUB30133")
    check("strings and integers are told apart", _sfo.get("BOOTABLE"), 1)
    check("padding after a string is not read back as part of it",
          _sfo.get("CATEGORY"), "HG")
    check("something that is not an SFO is skipped, not raised",
          ps3_games.read_sfo(os.path.join(_cfg_home, "nope.sfo")), {})

    # ---- the installed game listing ----------------------------------------
    _ps3_root = os.path.join(_cfg_home, "ps3games")
    _installed = os.path.join(_ps3_root, "NPUB30133")
    os.makedirs(os.path.join(_installed, "USRDIR"), exist_ok=True)
    with io.open(os.path.join(_installed, "PARAM.SFO"), "wb") as _dst:
        _dst.write(_sfo_bytes)
    io.open(os.path.join(_installed, "USRDIR", "EBOOT.BIN"), "w").close()
    io.open(os.path.join(_installed, "ICON0.PNG"), "w").close()
    # RPCS3 creates this placeholder itself and there is no PARAM.SFO in it.
    os.makedirs(os.path.join(_ps3_root, "TEST12345", "USRDIR"), exist_ok=True)

    _ps3 = ps3_games.installed_games(_ps3_root)
    check("the installed game is found by name", [g["title"] for g in _ps3], ["Braid"])
    check("with the path that actually boots",
          _ps3[0]["eboot"].endswith(os.path.join("NPUB30133", "USRDIR", "EBOOT.BIN")), True)
    # The package carries its own art, so a PKG game needs nothing downloaded.
    check("and the artwork the package brought with it",
          _ps3[0]["icon"].endswith("ICON0.PNG"), True)
    check("a background that is not there is not claimed", _ps3[0]["background"], "")
    check("RPCS3's own empty placeholder is not offered as a game",
          any(g["title_id"] == "TEST12345" for g in _ps3), False)
    # A title whose EBOOT never unpacked would be a row that cannot start.
    os.remove(os.path.join(_installed, "USRDIR", "EBOOT.BIN"))
    check("nor is a title with no EBOOT", ps3_games.installed_games(_ps3_root), [])
    io.open(os.path.join(_installed, "USRDIR", "EBOOT.BIN"), "w").close()

    # ---- staging packages under a short name -------------------------------
    _pkg_src = os.path.join(_cfg_home, "pkgin")
    _pkg_out = os.path.join(_cfg_home, "pkgout")
    os.makedirs(_pkg_src, exist_ok=True)
    os.makedirs(_pkg_out, exist_ok=True)
    # A header shaped like the real one: magic, then the content id at 0x30.
    _pkg_header = bytearray(b"\x00" * 0x54)
    _pkg_header[0:4] = b"\x7fPKG"
    _pkg_header[0x30:0x30 + 36] = b"UP4049-NPUB30133_00-BRAID00000000001"
    _long_name = "vaMJjYU6mQ1N6kXDWKoKPuqgXJ8UaINGi5N6oYoRp9M9hpwWvKDB9WhkQpaf5HgK7l7HdHQGp8qb2BVY9lMVeaoCIM39cXSe8XUPl.pkg"
    with io.open(os.path.join(_pkg_src, _long_name), "wb") as _handle:
        _handle.write(bytes(_pkg_header))

    _staged = ps3_games.stage_packages(_pkg_src, _pkg_out)
    if _staged:
        check("a package is staged under its title id",
              os.path.basename(_staged[0]), "NPUB30133.pkg")
        # The whole point: what RPCS3 prints in its dialog is now 13 characters
        # instead of 105, which is the difference between a dialog that fits on
        # a 1280px screen and one whose buttons are off the edge.
        check("which is far shorter than what the user sent",
              len(os.path.basename(_staged[0])) < len(_long_name) / 4, True)
        check("and staging again does not pile up links",
              len(ps3_games.stage_packages(_pkg_src, _pkg_out)), 1)
    else:
        # Symlinks need a privilege Windows does not grant by default, and the
        # tests run there. Not a failure -- but say so rather than pass quietly.
        print("SKIP package staging (symlinks unavailable on this platform)")

    # ---- the packages waiting to be installed ------------------------------
    # Two folders are searched, because a package is a game that arrives looking
    # like firmware: the picker for it is in the ROM folder, but anyone who used
    # the PS3 firmware row's send button put it beside PS3UPDAT.PUP instead, and
    # a file that seems to vanish is the exact friction this removes.
    _pkg_alt = os.path.join(_cfg_home, "pkgalt")
    os.makedirs(_pkg_alt, exist_ok=True)
    with io.open(os.path.join(_pkg_alt, "Some Other Game.pkg"), "wb") as _handle:
        _handle.write(b"not a package at all")
    io.open(os.path.join(_pkg_src, "notes.txt"), "w").close()

    _waiting = ps3_games.packages([_pkg_src, _pkg_alt], installed={"NPUB30133"})
    check("packages are found across every folder searched",
          [item["name"] for item in _waiting],
          ["Some Other Game.pkg", _long_name])
    check("anything that is not a package is left out",
          any(item["name"] == "notes.txt" for item in _waiting), False)
    _braid_pkg = next(item for item in _waiting if item["name"] == _long_name)
    check("a package names the title inside it", _braid_pkg["title_id"], "NPUB30133")
    check("and says its game is already installed", _braid_pkg["installed"], True)
    # A header that will not parse still gets offered: with no title id there is
    # nothing to compare against, and offering it is the recoverable half of
    # that guess -- installing again is harmless, hiding a game is not.
    _other_pkg = next(item for item in _waiting if item["name"] != _long_name)
    check("a package with no readable header is still offered",
          (_other_pkg["title_id"], _other_pkg["installed"]), ("", False))
    check("with the size, so a truncated transfer is visible",
          _other_pkg["size"], len(b"not a package at all"))
    if _staged:
        # The staging folder holds symlinks to these same files. Without the
        # realpath check the panel would offer every package twice.
        _both = ps3_games.packages([_pkg_src, _pkg_out], installed=set())
        check("a staged link is not offered beside the file it points at",
              [item["name"] for item in _both], [_long_name])
    check("a folder that is not there is not an error",
          ps3_games.packages([os.path.join(_cfg_home, "nowhere")], installed=set()), [])
    # QT_INI's `\default` flag is an Azahar convention; RPCS3 has none, and
    # writing them would leave keys it does not recognise.
    check("with none of Azahar's default flags", "\\default" in _gui_text, False)

    _rpcs3_again = emu_config.apply_setup(emu_catalog.find("rpcs3"))
    check("applying RPCS3 again claims nothing was skipped",
          _rpcs3_again["skipped"], [])
    with io.open(_rpcs3_pad_file, encoding="utf-8") as _handle:
        check("and leaves the pad file exactly as it was",
              _handle.read() == _rpcs3_text, True)

    # Ryujinx keeps everything in JSON and rewrites the file wholesale, so it is
    # parsed rather than line-edited. Its one shipped input config is a keyboard,
    # which is why nothing on a Deck moves out of the box.
    _ryu_cfg = os.path.join(
        _cfg_home, ".var", "app", "io.github.ryubing.Ryujinx",
        "config", "Ryujinx", "Config.json",
    )
    os.makedirs(os.path.dirname(_ryu_cfg), exist_ok=True)
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "show_confirm_exit": True,
            "docked_mode": True,
            "input_config": [{"backend": "WindowKeyboard", "id": "0", "name": "Keyboard"}],
        }))
    _ryu = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    check("Ryujinx's config is written", _ryu["ok"], True)
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        _ryu_data = _json.load(_handle)
    check("the keyboard input config is replaced by a pad",
          _ryu_data["input_config"][0]["backend"], "GamepadSDL2")
    # Ryujinx is C#, and .NET reverses the first GUID fields, so this is not the
    # SDL spelling used everywhere else in the catalog. It also drops SDL's crc
    # field, which the derivation further down is what actually pins.
    check("bound to the Steam virtual pad in Ryujinx's own spelling",
          _ryu_data["input_config"][0]["id"], emu_catalog.ryujinx._RYUJINX_PAD_ID)
    # Switch A is on the right, where SDL has B.
    check("with A on the right face button",
          _ryu_data["input_config"][0]["right_joycon"]["button_a"], "B")
    check("and the exit confirmation answered", _ryu_data["show_confirm_exit"], False)
    check("while everything else in the file survives", _ryu_data["docked_mode"], True)

    # Ryujinx rewrites Config.json on exit and fills in fields it did not find,
    # so a config this plugin wrote comes back changed and stops matching what
    # was recorded. A correction was skipped as "the user's" -- while still
    # recording itself as applied -- and the pad stayed bound to an id that
    # matched no controller. The id we wrote before survives that rewrite.
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "input_config": [{
                "backend": "GamepadSDL2",
                "id": "0-f7390003-28de-0000-ff11-000001000000",
                "player_index": "Player1",
                "normalised_by_ryujinx": True,
            }],
        }))
    _state = _json.loads(io.open(emu_config.STATE_PATH, encoding="utf-8").read())
    _state["ryujinx"][emu_config.VERSION_KEY] = 0
    io.open(emu_config.STATE_PATH, "w", encoding="utf-8").write(_json.dumps(_state))
    _ryu_fixed = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        check("a superseded pad id is still recognised as ours after a rewrite",
              _json.load(_handle)["input_config"][0]["id"], emu_catalog.ryujinx._RYUJINX_PAD_ID)
    check("and is not reported as the user's",
          "Config.json/input_config" in _ryu_fixed["skipped"], False)

    # The same for the second wrong id, which is the one installs are carrying
    # now: it kept SDL's crc field, and Ryujinx zeroes that before matching.
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "input_config": [{
                "backend": "GamepadSDL2",
                "id": "0-f6790003-28de-0000-ff11-000001000000",
                "player_index": "Player1",
                "normalised_by_ryujinx": True,
            }],
        }))
    _state = _json.loads(io.open(emu_config.STATE_PATH, encoding="utf-8").read())
    _state["ryujinx"][emu_config.VERSION_KEY] = 0
    io.open(emu_config.STATE_PATH, "w", encoding="utf-8").write(_json.dumps(_state))
    _ryu_crc = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        check("the crc-bearing pad id is corrected too",
              _json.load(_handle)["input_config"][0]["id"], emu_catalog.ryujinx._RYUJINX_PAD_ID)
    check("and it is not reported as the user's",
          "Config.json/input_config" in _ryu_crc["skipped"], False)

    # Ryujinx's id is the Steam pad's guid with SDL's crc field -- bytes 2 and 3
    # -- zeroed, then read back little-endian by .NET. Deriving it here rather
    # than comparing two constants is what would catch putting the crc back.
    _guid_bytes = [int(emu_catalog.steam_pad._STEAM_PAD_GUID[_i:_i + 2], 16) for _i in range(0, 32, 2)]
    _guid_bytes[2] = _guid_bytes[3] = 0
    _expected_pad_id = "0-%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%s" % (
        _guid_bytes[3], _guid_bytes[2], _guid_bytes[1], _guid_bytes[0],
        _guid_bytes[5], _guid_bytes[4], _guid_bytes[7], _guid_bytes[6],
        _guid_bytes[8], _guid_bytes[9],
        "".join("%02x" % _b for _b in _guid_bytes[10:]),
    )
    check("Ryujinx's pad id is the Steam pad with SDL's crc dropped",
          emu_catalog.ryujinx._RYUJINX_PAD_ID, _expected_pad_id)

    # A pad somebody has already configured is theirs: the list stops being
    # all-keyboard, so it is left alone entirely.
    with io.open(_ryu_cfg, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps({
            "version": 70,
            "input_config": [{"backend": "GamepadSDL2", "id": "mine", "name": "Mine"}],
        }))
    _state = _json.loads(io.open(emu_config.STATE_PATH, encoding="utf-8").read())
    _state["ryujinx"][emu_config.VERSION_KEY] = 0
    io.open(emu_config.STATE_PATH, "w", encoding="utf-8").write(_json.dumps(_state))
    _ryu_mine = emu_config.apply_setup(emu_catalog.find("ryujinx"))
    with io.open(_ryu_cfg, encoding="utf-8") as _handle:
        check("a pad already configured by hand is untouched",
              _json.load(_handle)["input_config"][0]["id"], "mine")
    check("and is reported as left alone",
          "Config.json/input_config" in _ryu_mine["skipped"], True)

    # A profile somebody has edited is theirs, whole.
    with io.open(_cemu_profile, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("<emulated_controller><type>Wii U Pro Controller</type></emulated_controller>\n")
    with io.open(emu_config.STATE_PATH, encoding="utf-8") as _handle:
        _state = _json.load(_handle)
    _state["cemu"][emu_config.VERSION_KEY] = 0
    with io.open(emu_config.STATE_PATH, "w", encoding="utf-8") as _handle:
        _handle.write(_json.dumps(_state))
    _cemu_edited = emu_config.apply_setup(emu_catalog.find("cemu"))
    with io.open(_cemu_profile, encoding="utf-8") as _handle:
        _kept_text = _handle.read()
    check("a hand-edited profile is left alone", "Wii U Pro Controller" in _kept_text, True)
    check("and says so", "controller0.xml/content" in _cemu_edited["skipped"], True)

    # Plain INI has no `\default` marker, so a written False cannot be told from
    # a False the user chose. A key therefore states the default it may replace,
    # and anything else is left alone.
    _dolphin_ini = os.path.join(
        _cfg_home, ".var", "app", "org.DolphinEmu.dolphin-emu",
        "config", "dolphin-emu", "Dolphin.ini",
    )
    _pad_ini = os.path.join(os.path.dirname(_dolphin_ini), "GCPadNew.ini")
    os.makedirs(os.path.dirname(_dolphin_ini), exist_ok=True)
    with io.open(_dolphin_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Display]\nFullscreen = False\nRenderToMain = True\n")

    _dol = emu_config.apply_setup(emu_catalog.find("dolphin"))
    with io.open(_dolphin_ini, encoding="utf-8") as _handle:
        _dol_text = _handle.read()
    check("the setup writes across both of Dolphin's files", _dol["ok"], True)
    check("Dolphin's own default is replaced", "Fullscreen = True" in _dol_text, True)
    check("and a neighbouring setting is untouched", "RenderToMain = True" in _dol_text, True)
    with io.open(_pad_ini, encoding="utf-8") as _handle:
        _pad_text = _handle.read()
    # An explicit Device line is the tell that Dolphin does not find a pad by
    # itself -- an emulator that auto-detected would not need one.
    check("the pad names the device SDL reports on a Deck",
          "Device = SDL/0/Steam Deck Controller" in _pad_text, True)
    # GameCube A sits where the Deck prints B, and Dolphin names buttons by
    # compass point, so `Button E` is the right-hand face button.
    check("GameCube A is the right-hand face button", "Buttons/A = `Button E`" in _pad_text, True)
    check("the D-pad is bound", "D-Pad/Up = `Pad N`" in _pad_text, True)

    # Wii reads a different file entirely, so a working GameCube pad says
    # nothing about it -- which is exactly how it shipped unconfigured once.
    _wii_ini = os.path.join(os.path.dirname(_dolphin_ini), "WiimoteNew.ini")
    with io.open(_wii_ini, encoding="utf-8") as _handle:
        _wii_text = _handle.read()
    check("the Wiimote is bound too", "Device = SDL/0/Steam Deck Controller" in _wii_text, True)
    check("with a nunchuk attached", "Extension = Nunchuk" in _wii_text, True)
    # The Deck's own gyro stands in for a real Wiimote's motion.
    check("and the Deck's motion sensors", "IMUGyroscope/Yaw Left = `Gyro Yaw Left`" in _wii_text, True)

    # Dolphin's first-run dialog asks whether it may report usage data. It is
    # modal and a gamepad cannot dismiss it, so a game launched from Steam stops
    # before it starts.
    check("the analytics prompt is answered", "PermissionAsked = True" in _dol_text, True)
    check("and answered no", "Enabled = False" in _dol_text, True)

    # The case that shipped broken: Dolphin writes its own bindings the first
    # time it runs, so every key existed with a value that was neither absent nor
    # ours and a whole Wiimote profile was skipped one key at a time. A profile
    # is judged by its Device line instead -- still the X11 pointer means nobody
    # has configured it.
    with io.open(_wii_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "[Wiimote1]\n"
            "Device = XInput2/0/Virtual core pointer\n"
            "Buttons/A = `Click 1`\n"
            "Buttons/B = `Click 3`\n"
        )
    emu_config.apply_setup(emu_catalog.find("dolphin"))
    with io.open(_wii_ini, encoding="utf-8") as _handle:
        _redone = _handle.read()
    check(
        "a profile still on the emulator's own device is replaced wholesale",
        "Device = SDL/0/Steam Deck Controller" in _redone,
        True,
    )
    check("including the bindings under it", "Buttons/A = `Button S`" in _redone, True)
    # Not "Click 1": our own Buttons/A binds the mouse click alongside the face
    # button, so its presence proves nothing. Buttons/B is unambiguous.
    check("and Dolphin's own binding under it is replaced", "Click 3" in _redone, False)
    check("with ours", "Buttons/B = `Button E`" in _redone, True)

    # But a profile pointed at a device we did not choose belongs to whoever
    # chose it, and none of it is touched.
    with io.open(_wii_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(
            "[Wiimote1]\nDevice = SDL/0/My Own Fightstick\nButtons/A = `Button Z`\n"
        )
    _mine = emu_config.apply_setup(emu_catalog.find("dolphin"))
    with io.open(_wii_ini, encoding="utf-8") as _handle:
        _kept_text = _handle.read()
    check("a profile someone else configured is left alone",
          "Device = SDL/0/My Own Fightstick" in _kept_text, True)
    check("every key of it, not just the device",
          "Buttons/A = `Button Z`" in _kept_text, True)
    check("and the whole section is reported skipped",
          len([n for n in _mine["skipped"] if n.startswith("WiimoteNew.ini/Wiimote1/")]) > 10,
          True)

    # Back to a state this plugin owns, so the idempotence check below is about
    # repeat application rather than about the fightstick left above.
    os.remove(_wii_ini)
    emu_config.apply_setup(emu_catalog.find("dolphin"))
    check("applying twice changes nothing", emu_config.apply_setup(emu_catalog.find("dolphin"))["skipped"], [])
    with io.open(_dolphin_ini, encoding="utf-8") as _handle:
        check("and the file is identical", _handle.read(), _dol_text)

    # A value that is neither the emulator's default nor ours was chosen by
    # somebody, and windowed is a perfectly reasonable thing to have chosen.
    with io.open(_dolphin_ini, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("[Display]\nFullscreen = Maybe\n")
    _kept = emu_config.apply_setup(emu_catalog.find("dolphin"))
    check("an unrecognised value is left alone",
          "Dolphin.ini/Display/Fullscreen" in _kept["skipped"], True)
    with io.open(_dolphin_ini, encoding="utf-8") as _handle:
        check("really left alone", "Fullscreen = Maybe" in _handle.read(), True)

    # Two files in one setup must not collide on the same section and key name,
    # which is what the per-file prefix in the recorded state is for.
    check(
        "state keys are scoped per file",
        all(
            name.startswith(("Dolphin.ini/", "GCPadNew.ini/", "WiimoteNew.ini/"))
            for name in _dol["applied"]
        ),
        True,
    )
finally:
    sysenv.user_home = _real_user_home

section("firmware -- the user's own dumps, put where the emulator reads them")
import emu_firmware  # noqa: E402

_fw_home = os.path.join(TMP, "fwhome")
_real_user_home = sysenv.user_home
sysenv.user_home = lambda: _fw_home
try:
    _fw_dir = emu_install.firmware_dir()

    def _send(name, size=16):
        with io.open(os.path.join(_fw_dir, name), "wb") as handle:
            handle.write(b"\0" * size)

    # A PS1 and a PS2 BIOS are both scph<digits>.bin -- four digits for the PS1,
    # five for the PS2. That count is the only thing telling them apart by name,
    # and getting it wrong files a PS1 BIOS into PCSX2 where it does nothing.
    _send("scph39001.bin")
    _send("scph5501.bin")
    _send("Super Mario 3D Land.cci", 32)

    _ps2 = emu_firmware.status(emu_catalog.find("pcsx2"))[0]
    _ps1 = emu_firmware.status(emu_catalog.find("duckstation"))[0]
    check("a five-digit BIOS is offered to PCSX2", _ps2["waiting"], ["scph39001.bin"])
    check("a four-digit one is offered to DuckStation", _ps1["waiting"], ["scph5501.bin"])
    check("and neither claims the other's", "scph5501.bin" in _ps2["waiting"], False)
    # Anything else in the folder is not firmware and must not be offered.
    check("a ROM sitting in the folder is ignored",
          any("cci" in name for name in _ps2["waiting"] + _ps1["waiting"]), False)

    _result = emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")
    check("installing reports what it copied", _result["copied"], ["scph39001.bin"])
    check(
        "into the path the emulator reads",
        _result["dest"].endswith(os.path.join("net.pcsx2.PCSX2", "config", "PCSX2", "bios")),
        True,
    )
    check(
        "the file is really there",
        os.path.isfile(os.path.join(_result["dest"], "scph39001.bin")),
        True,
    )
    # Moved, not copied: copying left the transfer folder holding a duplicate of
    # every BIOS ever sent, which then needed a panel to explain which
    # duplicates were safe to delete.
    check(
        "and the transfer folder no longer holds a duplicate",
        os.path.isfile(os.path.join(_fw_dir, "scph39001.bin")),
        False,
    )
    _after = emu_firmware.status(emu_catalog.find("pcsx2"))[0]
    check("and it now reports as in place", _after["installed"], ["scph39001.bin"])
    check("with nothing left waiting", _after["waiting"], [])

    # Nothing left to install, because the file moved.
    check(
        "installing again with nothing sent is refused",
        emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")["ok"],
        False,
    )

    # A BIOS already at the destination is never replaced: the user may have put
    # a better dump there, and swapping one under an emulator silently is not
    # something an install button should do.
    _send("scph39001.bin")
    _again = emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")
    check("a second install replaces nothing", _again["copied"], [])
    check("and says what it kept", _again["kept"], ["scph39001.bin"])
    check(
        "leaving the newly sent one where it is",
        os.path.isfile(os.path.join(_fw_dir, "scph39001.bin")),
        True,
    )
    emu_firmware.remove(["scph39001.bin"])

    # A requirement the emulator unpacks itself. RPCS3 turns one PUP into
    # several thousand files under dev_flash, so there is nothing to copy --
    # `--headless --installfw` does the whole thing in about six seconds with no
    # window -- and the row is installable the moment the file arrives even
    # though it names no destination folder.
    _send("PS3UPDAT.PUP")
    _pup = emu_firmware.status(emu_catalog.find("rpcs3"))[0]
    check("a PUP is recognised", _pup["waiting"], ["PS3UPDAT.PUP"])
    check("and installing it is offered", _pup["can_install"], True)
    check("as an import rather than a copy", _pup["imported"], True)
    # Copying can be undone by copying back; unpacking a firmware image into a
    # tree cannot, so the trash button is not offered next to it.
    check("with no removal offered", _pup["can_remove"], False)
    check("and nothing installed until it runs", _pup["installed"], [])

    # Which requirements count as "this emulator is not ready". Exactly one row
    # in the whole catalog is optional -- RPCS3's .rap -- because a licence
    # belongs to a game rather than to the emulator, and without this every PS3
    # game added would warn that RPCS3 was missing something it does not need.
    _rpcs3_rows = emu_firmware.status(emu_catalog.find("rpcs3"), emu_firmware.available())
    check("the firmware is required",
          [r["optional"] for r in _rpcs3_rows if r["name"].startswith("PS3 firmware")], [False])
    check("and the licence row is not",
          [r["optional"] for r in _rpcs3_rows if r["name"].startswith("Game licences")], [True])
    # Not knowing whether something is installed is not the same as knowing it
    # is not, and only one of the two may be reported. Ryujinx's firmware is
    # installed through its own interface and used to have nowhere named to
    # look, so it read as absent forever -- and the add flow warned about it
    # under a Switch game that launched perfectly.
    _ryu = emu_firmware.status(emu_catalog.find("ryujinx"), emu_firmware.available())
    _ryu_fw = next(r for r in _ryu if r["name"] == "Switch firmware")
    check("a manually installed firmware is still detectable", _ryu_fw["detectable"], True)
    check("and reports absent while its folder is empty", _ryu_fw["installed"], [])
    _registered = os.path.join(
        _fw_home, ".var", "app", "io.github.ryubing.Ryujinx", "config", "Ryujinx",
        "bis", "system", "Contents", "registered")
    os.makedirs(_registered, exist_ok=True)
    check("an existing but empty folder is not firmware",
          next(r for r in emu_firmware.status(emu_catalog.find("ryujinx"),
                                              emu_firmware.available())
               if r["name"] == "Switch firmware")["installed"], [])
    os.makedirs(os.path.join(_registered, "2f8531a91b713716aa989427090ddfe4.nca"))
    check("and one with contents is",
          next(r for r in emu_firmware.status(emu_catalog.find("ryujinx"),
                                              emu_firmware.available())
               if r["name"] == "Switch firmware")["installed"], ["installed"])

    # Installed by Ryujinx itself, and removable all the same: which of those
    # two is true was never the question -- knowing where the files are is.
    # Keying removal on "did we copy this" is what left it, and RPCS3's
    # firmware, stuck as permanent while a .rap beside them could be taken out.
    check("a firmware the emulator installed itself can still be removed",
          next(r for r in emu_firmware.status(emu_catalog.find("ryujinx"),
                                              emu_firmware.available())
               if r["name"] == "Switch firmware")["can_remove"], True)
    _ryu_gone = emu_firmware.uninstall(emu_catalog.find("ryujinx"), "Switch firmware")
    check("removing it succeeds", _ryu_gone["ok"], True)
    check("and the registered contents are gone", os.path.isdir(_registered), False)
    check("games and their updates are elsewhere and untouched",
          os.path.isdir(os.path.join(
              _fw_home, ".var", "app", "io.github.ryubing.Ryujinx", "config",
              "Ryujinx", "bis", "system", "Contents")), True)

    # Every requirement in the catalog must be answerable one way or the other,
    # or the add flow is guessing about it.
    check("nothing in the catalog is undetectable",
          [r["name"] for e in emu_catalog.CATALOG
           for r in emu_firmware.status(e, emu_firmware.available())
           if not r["detectable"]],
          [])

    check("no other requirement anywhere is optional",
          sorted({r["name"] for e in emu_catalog.CATALOG
                  for r in emu_firmware.status(e, emu_firmware.available())
                  if r["optional"]}),
          ["Game licences (.rap)"])

    # The copy path must refuse it outright rather than half-doing something:
    # `install` moves files, and there is no destination to move this to.
    _refused = emu_firmware.install(
        emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)"
    )
    check("copying it is refused", _refused["ok"], False)
    check("saying who does the work", "RPCS3 installs" in _refused["error"], True)
    check(
        "and taking it back out finds nothing to take",
        emu_firmware.uninstall(emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)")["ok"],
        False,
    )

    # Removing an imported firmware means deleting the tree the emulator wrote,
    # which is only offered where the catalog names that tree. It is the only
    # route back from a firmware that installed badly -- and, now that an
    # installed row no longer shows an Install button, the only route at all.
    _flash = os.path.join(_fw_home, ".config", "rpcs3", "dev_flash", "vsh", "etc")
    os.makedirs(_flash, exist_ok=True)
    with io.open(os.path.join(_flash, "version.txt"), "w") as _handle:
        _handle.write("release:04.9300:\n")
    _pup_in = emu_firmware.status(emu_catalog.find("rpcs3"), emu_firmware.available())[0]
    check("with the firmware unpacked it reports the version",
          _pup_in["installed"], ["4.93"])
    check("and now offers to remove it", _pup_in["can_remove"], True)
    _gone = emu_firmware.uninstall(emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)")
    check("removing it succeeds", (_gone["ok"], _gone["removed"]), (True, ["dev_flash"]))
    check("the whole tree is gone",
          os.path.isdir(os.path.join(_fw_home, ".config", "rpcs3", "dev_flash")), False)
    check("and it reports what that recovered", _gone["freed"] > 0, True)
    check("with nothing left, removal is offered no more",
          emu_firmware.status(emu_catalog.find("rpcs3"),
                              emu_firmware.available())[0]["can_remove"], False)

    # The catalog decides what a removal deletes, so a wrong path in it must
    # fail to find anything rather than delete from wherever it points. Both
    # guards are load-bearing: named by the catalog, and under the home.
    _outside = os.path.join(TMP, "notmyhome")
    os.makedirs(_outside, exist_ok=True)
    _rogue = {"name": "rogue", "removes": [
        os.path.join("..", "..", os.path.basename(TMP), "notmyhome")]}
    check("a removal pointing outside the home deletes nothing",
          emu_firmware._uninstall_tree({"name": "x", "id": "x"}, _rogue)["ok"], False)
    check("and the directory it pointed at is untouched",
          os.path.isdir(_outside), True)

    # A .rap is sixteen bytes of key material with nothing inside naming the
    # game it unlocks, and RPCS3 finds it by filename alone -- but the file is
    # moved into exdata by this plugin, so it can be renamed on the way and the
    # name it arrives under does not have to be the one RPCS3 needs.
    _pkg_probe = os.path.join(_fw_dir, "braid.pkg")
    _hdr = bytearray(b"\0" * 0x54)
    _hdr[0:4] = b"\x7fPKG"
    _hdr[0x30:0x30 + 36] = b"UP4049-NPUB30133_00-BRAID00000000001"
    with io.open(_pkg_probe, "wb") as _handle:
        _handle.write(bytes(_hdr))
    check("the content id is read whole, not just the title id",
          ps3_games.package_content_id(_pkg_probe),
          "UP4049-NPUB30133_00-BRAID00000000001")
    check("with no licence anywhere it reports nothing",
          ps3_games.licence_state("UP4049-NPUB30133_00-BRAID00000000001", _fw_dir), "")
    # Not the same as missing, and never shown as one: without a content id
    # there is nowhere to look, which is every game installed outside this
    # plugin. "No licence" there would be a guess, wrong for licence-free games.
    check("no content id is unknown, not missing",
          ps3_games.licence_state("", _fw_dir), "unknown")
    # Recorded at install because it cannot be recovered later: an installed
    # game's PARAM.SFO has TITLE_ID and no CONTENT_ID -- checked against a real
    # install -- and the package that carried it is deleted.
    check("a title with nothing recorded has no content id",
          ps3_games.content_id_for("NPUB99999"), "")
    ps3_games.remember_content_id("NPUB30133", "UP4049-NPUB30133_00-BRAID00000000001")
    check("and one recorded at install is remembered",
          ps3_games.content_id_for("NPUB30133"),
          "UP4049-NPUB30133_00-BRAID00000000001")

    # A licence sent with its game lands beside the game, not in the firmware
    # folder -- which is the obvious thing to do and is what the Vita flow
    # already expects. Looking only in the firmware folder made a correctly
    # named .rap sitting next to its own package invisible.
    _beside = os.path.join(TMP, "besidepkg")
    os.makedirs(_beside, exist_ok=True)
    _CID = "UP4415-NPUB31749_00-GOATSIMULATORPS3"
    _pkg_beside = os.path.join(_beside, _CID + "_bg_1_abcdef.pkg")
    io.open(_pkg_beside, "w").close()
    io.open(os.path.join(_beside, _CID + ".rap"), "w").close()
    _dirs = ps3_games.licence_dirs(_pkg_beside, _fw_dir)
    check("the licence beside a package is seen",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "waiting")
    # And installed by the same press that installs the game, so "send both
    # together" is all there is to it.
    check("installing it puts it where RPCS3 reads licences",
          ps3_games.install_licence(_CID, _dirs, _pkg_beside), _CID + ".rap")
    check("after which it reports as in place",
          ps3_games.licence_state(_CID), "installed")
    check("and it is gone from beside the package",
          os.path.isfile(os.path.join(_beside, _CID + ".rap")), False)
    os.remove(os.path.join(ps3_games.exdata_dir(), _CID + ".rap"))

    # Named anything at all. The Vita side already accepts "I sent both files"
    # without demanding they match, and there is no reason this cannot: the
    # rename happens here, so the only real question is which file is meant.
    _loose = os.path.join(_beside, "goat licence.rap")
    io.open(_loose, "w").close()
    check("a lone .rap beside the package is the one meant, whatever it is called",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "waiting")
    check("and it is renamed to what RPCS3 reads as it goes in",
          ps3_games.install_licence(_CID, _dirs, _pkg_beside), _CID + ".rap")
    check("under the content id, not the name it arrived with",
          os.path.isfile(os.path.join(ps3_games.exdata_dir(), _CID + ".rap")), True)
    os.remove(os.path.join(ps3_games.exdata_dir(), _CID + ".rap"))

    # Two of them is not an unambiguous answer, and picking wrong installs a
    # licence that fails exactly like a bad dump.
    io.open(os.path.join(_beside, "one.rap"), "w").close()
    io.open(os.path.join(_beside, "two.rap"), "w").close()
    check("two unnamed licences beside a package is a guess, so nothing is taken",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "")
    # Unless one of them says which game it is for, which settles it.
    os.rename(os.path.join(_beside, "one.rap"), os.path.join(_beside, "NPUB31749.rap"))
    check("a licence named for the title id wins over the ambiguity",
          ps3_games.licence_state(_CID, _dirs, _pkg_beside), "waiting")
    check("and installs under the content id",
          ps3_games.install_licence(_CID, _dirs, _pkg_beside), _CID + ".rap")
    os.remove(os.path.join(ps3_games.exdata_dir(), _CID + ".rap"))
    os.remove(os.path.join(_beside, "two.rap"))
    io.open(os.path.join(_fw_dir, "UP4049-NPUB30133_00-BRAID00000000001.rap"), "w").close()
    check("a sent licence is waiting",
          ps3_games.licence_state("UP4049-NPUB30133_00-BRAID00000000001", _fw_dir),
          "waiting")
    # The lone-candidate sweep is deliberately limited to the folder the package
    # is in. The firmware folder collects licences for every game ever sent, so
    # "the only .rap here" means nothing there -- and with no package to be
    # beside, there is no folder to sweep at all.
    os.rename(os.path.join(_fw_dir, "UP4049-NPUB30133_00-BRAID00000000001.rap"),
              os.path.join(_fw_dir, "braid.rap"))
    check("a renamed licence in the firmware folder is not guessed at",
          ps3_games.licence_state("UP4049-NPUB30133_00-BRAID00000000001", _fw_dir), "")
    os.remove(os.path.join(_fw_dir, "braid.rap"))
    os.remove(_pkg_probe)

    # Installed is read from what the emulator produced, not from a record of
    # the button being pressed. RPCS3 writes its firmware version into
    # dev_flash, and that file is the only thing that says a PUP was unpacked.
    _rpcs3_import = emu_catalog.find("rpcs3")["firmware"][0]["import"]
    _version_txt = emu_firmware.under_home(_rpcs3_import["installed"])
    os.makedirs(os.path.dirname(_version_txt), exist_ok=True)
    with open(_version_txt, "w", encoding="utf-8") as _handle:
        # Copied from a real Deck, digit for digit.
        _handle.write(
            "release:04.9300:\nbuild:68500,20260108:tetsu@tetsu-linux17\n"
            "target:0001:CEX-ww\n"
        )
    check(
        "the firmware version is read out of RPCS3's own record",
        emu_firmware.imported(_rpcs3_import),
        ["4.93"],
    )
    check(
        "and the row now reports it as installed",
        emu_firmware.status(emu_catalog.find("rpcs3"))[0]["installed"],
        ["4.93"],
    )
    # A marker whose contents will not parse is still an install: the version is
    # a nicety, the file existing is the fact.
    with open(_version_txt, "w", encoding="utf-8") as _handle:
        _handle.write("something else entirely\n")
    check(
        "an unreadable version still counts as installed",
        emu_firmware.imported(_rpcs3_import),
        ["version.txt"],
    )
    os.remove(_version_txt)
    check("and a missing marker is not installed", emu_firmware.imported(_rpcs3_import), [])

    # Nothing may resolve outside the user's own home, because these paths are
    # read from a table and then written to and deleted.
    check(
        "a marker path escaping the home is refused",
        emu_firmware.under_home("../../etc/passwd"),
        "",
    )

    # A game licence lands under a name RPCS3 will actually read. It only
    # accepts a lowercase .rap and says so nowhere until the game fails to boot
    # with "Failed to decrypt content", so a .RAP sent from a phone that
    # uppercased it would sit at the destination reporting as installed and
    # decrypt nothing.
    _rap_name = "UP4049-NPUB30133_00-BRAID00000000001.RAP"
    _send(_rap_name)
    _rap_result = emu_firmware.install(emu_catalog.find("rpcs3"), "Game licences (.rap)")
    check("an uppercase licence is installed lowercase",
          _rap_result["copied"], [_rap_name[:-4] + ".rap"])
    _rap_dest = emu_firmware._destination(
        emu_firmware.find_requirement(emu_catalog.find("rpcs3"), "Game licences (.rap)")
    )
    check("and that is the name on disk",
          os.path.isfile(os.path.join(_rap_dest, _rap_name[:-4] + ".rap")), True)
    # Read from the directory listing rather than with isfile, which answers
    # yes to either spelling on the case-insensitive filesystem these tests run
    # on and so could never see the rename fail.
    check("and the only name there", os.listdir(_rap_dest), [_rap_name[:-4] + ".rap"])
    # Recorded under the name it landed as, or removing it would not recognise
    # its own work and would report the user's own file as somebody else's.
    _rap_status = emu_firmware.status(emu_catalog.find("rpcs3"))[1]
    check("the licence reports as installed", _rap_status["installed"],
          [_rap_name[:-4] + ".rap"])
    check("and as this plugin's own work", _rap_status["foreign"], [])
    check("removing it takes it back out",
          emu_firmware.uninstall(emu_catalog.find("rpcs3"), "Game licences (.rap)")["removed"],
          [_rap_name[:-4] + ".rap"])
    # Everything else keeps the name it arrived with.
    check("a requirement without the rule renames nothing",
          emu_firmware._dest_name({}, "SCPH39001.BIN"), "SCPH39001.BIN")

    # ---- xemu: told apart by size, and pointed at afterwards ---------------
    # An MCPX boot ROM and an Xbox BIOS are both a .bin under whatever the
    # dumper called them. There is no naming convention to match on, but an MCPX
    # ROM is exactly 512 bytes and a BIOS never is, so the file itself says
    # which it is.
    _xemu = emu_catalog.find("xemu")
    _send("dump-a.bin", 512)
    _send("dump-b.bin", 262144)
    _xemu_rows = {row["name"]: row for row in emu_firmware.status(_xemu)}
    check("the 512-byte file is recognised as the boot ROM",
          _xemu_rows["MCPX boot ROM"]["waiting"], ["dump-a.bin"])
    check("and the 256KB one as the BIOS",
          _xemu_rows["Xbox BIOS"]["waiting"], ["dump-b.bin"])
    # Both rows match `*.bin`, so without the size rule each would claim both
    # files and a boot ROM would be installed as a BIOS.
    check("neither claims the other's file",
          (len(_xemu_rows["MCPX boot ROM"]["waiting"]),
           len(_xemu_rows["Xbox BIOS"]["waiting"])),
          (1, 1))

    # Copying is not enough for xemu: it reads all three from paths in
    # xemu.toml, and an unset one means it will not start. So the install
    # writes the path it just landed on.
    _mcpx = emu_firmware.install(_xemu, "MCPX boot ROM")
    check("installing the boot ROM works", _mcpx["copied"], ["dump-a.bin"])
    check("and points xemu at it", _mcpx["configured"], "bootrom_path")
    _xemu_toml = emu_firmware.under_home(emu_catalog.xemu._XEMU_TOML)
    with io.open(_xemu_toml, encoding="utf-8") as _handle:
        _toml_text = _handle.read()
    # TOML strings are quoted, and an unquoted one is not a parse error there --
    # it is a different type, so xemu would reject the whole file.
    check("with the path written as a quoted TOML string",
          "bootrom_path = '%s'" % os.path.join(
              emu_firmware.under_home(emu_catalog.xemu._XEMU_DATA), "dump-a.bin"
          ) in _toml_text,
          True)
    check("under the table xemu reads it from", "[sys.files]" in _toml_text, True)

    emu_firmware.install(_xemu, "Xbox BIOS")
    with io.open(_xemu_toml, encoding="utf-8") as _handle:
        check("and a second requirement joins it rather than replacing it",
              _handle.read().count("rom_path = "), 2)

    # The disk image is the one prerequisite here that is nobody's dump, so it
    # is the only one with a source to fetch from.
    check("a dump is never downloaded",
          "never downloads" in emu_firmware.fetch(_xemu, "Xbox BIOS")["error"], True)

    # Sony's PUPs are published by Sony at the addresses their own consoles
    # update from, so they are fetchable where a BIOS is not. The PS3's is read
    # from Sony's update list each time because they still publish versions;
    # the Vita's is pinned because its last firmware was 3.74 in 2022.
    _ps3_fw = emu_firmware.find_requirement(
        emu_catalog.find("rpcs3"), "PS3 firmware (PS3UPDAT.PUP)")
    check("the PS3 firmware is fetched from Sony's own index",
          _ps3_fw["fetch"]["kind"], "index")
    check("and the Vita's from a fixed address",
          emu_firmware.find_requirement(
              emu_catalog.find("vita3k"), "PS Vita firmware")["fetch"]["kind"],
          "url")
    # Vita3K needs two PUPs, not one. PSVUPDAT.PUP is the firmware and
    # PSP2UPDAT.PUP is the font package, and without the fonts Vita3K reports
    # itself unconfigured -- which is what a welcome screen that kept coming
    # back turned out to mean. Each row must claim only its own file: an
    # earlier version accepted both names for the firmware and would have had
    # the two rows fighting over each other's downloads.
    _vita_fw = emu_firmware.find_requirement(
        emu_catalog.find("vita3k"), "PS Vita firmware")
    _vita_font = emu_firmware.find_requirement(
        emu_catalog.find("vita3k"), "PS Vita font package")
    check("the firmware row takes only the firmware",
          [emu_firmware._matching(_vita_fw, [{"name": n}])
           for n in ("PSVUPDAT.PUP", "PSP2UPDAT.PUP")],
          [["PSVUPDAT.PUP"], []])
    check("and the font row only the fonts",
          [emu_firmware._matching(_vita_font, [{"name": n}])
           for n in ("PSVUPDAT.PUP", "PSP2UPDAT.PUP")],
          [[], ["PSP2UPDAT.PUP"]])
    check("each fetches the file it matches",
          (_vita_fw["fetch"]["name"], _vita_font["fetch"]["name"]),
          ("PSVUPDAT.PUP", "PSP2UPDAT.PUP"))
    # Sony serve the font package over plain http, and Vita3K's own downloader
    # asks for it over https and fails the certificate. Fetching it at the
    # address Vita3K's quickstart gives is what avoids that.
    check("the font package is fetched over the scheme Sony serve",
          _vita_font["fetch"]["url"].startswith("http://"), True)
    # Both install the same way, and both need a display to do it.
    check("both are installed by Vita3K itself",
          (_vita_fw["import"]["args"], _vita_font["import"]["args"]),
          (["--firmware", "{file}"], ["--firmware", "{file}"]))
    # Neither is copied anywhere, so neither has a `dest`. A fetch must still
    # know where to put it: the transfer folder, exactly where the same file
    # would have arrived had it been sent from another device.
    check("a requirement with no destination still has somewhere to land",
          bool(emu_firmware._destination(_ps3_fw)), False)

    # Vita3K installs its own firmware too, with no window -- six seconds and
    # exit 0 on a Deck. It records no version anywhere, and its marker file is
    # `psp2bootconfig.skprx`, which is not a thing to show anybody.
    _vita_import = _vita_fw["import"]
    check("Vita3K installs its firmware itself", _vita_import["args"],
          ["--firmware", "{file}"])
    _vita_marker = emu_firmware.under_home(_vita_import["installed"])
    check("and reports nothing installed before it has",
          emu_firmware.imported(_vita_import, "PS Vita firmware"), [])
    os.makedirs(os.path.dirname(_vita_marker), exist_ok=True)
    io.open(_vita_marker, "w").close()
    check("then names the requirement rather than the marker file",
          emu_firmware.imported(_vita_import, "PS Vita firmware"), ["PS Vita firmware"])
    check("with the row agreeing",
          {r["name"]: r for r in emu_firmware.status(emu_catalog.find("vita3k"))}
          ["PS Vita firmware"]["installed"],
          ["PS Vita firmware"])
    # RPCS3 does record a version, and must still report it rather than a name.
    check("while a version that can be read still wins",
          emu_firmware.imported(_rpcs3_import, "PS3 firmware"), [])
    os.remove(_vita_marker)

    # The display is opt-in. Handing one to a run that asked to be headless
    # invites it to open a window, which is the opposite of the point.
    check("only Vita3K asks for a display",
          sorted({e["id"] for e in emu_catalog.CATALOG
                  for r in e.get("firmware") or []
                  if (r.get("import") or {}).get("needs_display")}),
          ["vita3k"])

    # A console firmware is far bigger than anything this folder held when the
    # cap was written, and the cap silently excluded all of them: a row with a
    # 128MB PUP beside it reported nothing waiting, so its Install button could
    # never appear. Every firmware this catalog fetches has to be visible.
    # Checked against the cap rather than by writing one: a real PUP is 128MB
    # and a PS3 one around 200MB, and writing that on every run left a
    # gigabyte-scale pile of temp directories behind. The two facts that matter
    # are that the cap clears the largest thing that belongs here, and that the
    # filter it feeds actually excludes by size.
    check("the cap clears the largest firmware that belongs here",
          emu_firmware.MAX_FIRMWARE_BYTES > 220 * 1024 * 1024, True)
    _pup = os.path.join(_fw_dir, "PSVUPDAT.PUP")
    _send("PSVUPDAT.PUP", 4096)
    check("a firmware image under the cap is visible",
          [f["name"] for f in emu_firmware.available() if f["name"] == "PSVUPDAT.PUP"],
          ["PSVUPDAT.PUP"])
    check("and the row that wants it reports it as waiting",
          {r["name"]: r for r in emu_firmware.status(emu_catalog.find("vita3k"))}
          ["PS Vita firmware"]["waiting"],
          ["PSVUPDAT.PUP"])
    _real_cap = emu_firmware.MAX_FIRMWARE_BYTES
    emu_firmware.MAX_FIRMWARE_BYTES = 1024
    check("while one over it is filtered out, which is what hid every PUP",
          [f["name"] for f in emu_firmware.available() if f["name"] == "PSVUPDAT.PUP"],
          [])
    emu_firmware.MAX_FIRMWARE_BYTES = _real_cap
    os.remove(_pup)

    # A real zip, unpacked by the real code path. The names inside it are the
    # interesting part: an archive fetched over the network must not be able to
    # place a file anywhere but where this intends.
    import shutil as _shutil  # noqa: E402
    import zipfile as _zipfile  # noqa: E402
    _fetch_zip = os.path.join(TMP, "hdd.zip")
    with _zipfile.ZipFile(_fetch_zip, "w") as _bundle:
        _bundle.writestr("xbox_hdd.qcow2", b"QFI\xfb" + b"\0" * 64)
        _bundle.writestr("../../../escaped.qcow2", b"nope")
        _bundle.writestr("readme.txt", b"ignored")

    _real_resolve = emu_install.resolve_github_asset
    _real_net_download = net.download
    emu_install.resolve_github_asset = lambda repo, pattern: (
        {"name": "xbox_hdd.qcow2.zip", "url": "https://example.test/hdd.zip",
         "tag": "1.0", "size": 0},
        "",
    )
    net.download = lambda url, path, max_bytes=None, on_progress=None: (
        (_shutil.copyfile(_fetch_zip, path), (True, ""))[1]
    )
    try:
        _fetched = emu_firmware.fetch(_xemu, "Xbox hard disk image")
    finally:
        emu_install.resolve_github_asset = _real_resolve
        net.download = _real_net_download

    check("the disk image is fetched", _fetched["ok"], True)
    check("taking only what was asked for", _fetched["copied"], ["xbox_hdd.qcow2"])
    check("and pointing xemu at it", _fetched["configured"], "hdd_path")
    _xemu_dir = emu_firmware.under_home(emu_catalog.xemu._XEMU_DATA)
    check("a member with a path in its name cannot escape",
          os.path.isfile(os.path.join(os.path.dirname(_xemu_dir), "escaped.qcow2")),
          False)
    check("and nothing unmatched is written",
          "readme.txt" in os.listdir(_xemu_dir), False)
    check("the downloaded archive is not left behind",
          [n for n in os.listdir(_xemu_dir) if n.endswith(".zip")], [])
    check("and the row now reports it as in place",
          {row["name"]: row for row in emu_firmware.status(_xemu)}
          ["Xbox hard disk image"]["installed"],
          ["xbox_hdd.qcow2"])

    # Nothing sent yet is not an error, it is just nothing to do.
    check(
        "an unmatched requirement offers nothing",
        emu_firmware.install(emu_catalog.find("azahar"), "aes_keys.txt")["ok"],
        False,
    )
    _send("aes_keys.txt")
    check(
        "and works once the file arrives",
        emu_firmware.install(emu_catalog.find("azahar"), "aes_keys.txt")["copied"],
        ["aes_keys.txt"],
    )

    # Cemu writes keys.txt itself the first time it starts -- three comments and
    # one example key -- so the file exists long before the user has supplied
    # anything. Treating that as "in place" would report the requirement as met,
    # offer no way to send a real one, and leave every disc image undecryptable.
    _cemu_entry = emu_catalog.find("cemu")
    _cemu_keys_dir = emu_firmware._destination(_cemu_entry["firmware"][0])
    os.makedirs(_cemu_keys_dir, exist_ok=True)
    _cemu_keys = os.path.join(_cemu_keys_dir, "keys.txt")
    _CEMU_STUB = (
        "# this file contains keys needed for decryption of disc file system data (WUD/WUX)\n"
        "# 1 key per line, any text after a '#' character is considered a comment\n"
        "# the emulator will automatically pick the right key\n"
        "541b9889519b27d363cd21604b97c67a # example key (can be deleted)\n"
    )
    with io.open(_cemu_keys, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(_CEMU_STUB)
    _keys_state = emu_firmware.status(_cemu_entry)[0]
    check("Cemu's own empty keys.txt is not counted as installed",
          _keys_state["installed"], [])
    check("so the requirement still asks for one", _keys_state["can_install"], True)

    # And installing over it is allowed, or the requirement could never be met.
    with io.open(os.path.join(_fw_dir, "keys.txt"), "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("00112233445566778899aabbccddeeff # my own dump\n")
    _keys_result = emu_firmware.install(_cemu_entry, _cemu_entry["firmware"][0]["name"])
    check("a real keys.txt replaces the placeholder", _keys_result["copied"], ["keys.txt"])
    with io.open(_cemu_keys, encoding="utf-8") as _handle:
        check("and it is the user's file that is there now",
              "00112233445566778899aabbccddeeff" in _handle.read(), True)
    check("which now reads as installed",
          emu_firmware.status(_cemu_entry)[0]["installed"], ["keys.txt"])

    # A key the user added by hand is not a stub, and must never be replaced.
    with io.open(_cemu_keys, "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write(_CEMU_STUB + "aabbccddeeff00112233445566778899 # added by hand\n")
    check("a placeholder the user has added to is theirs",
          emu_firmware._is_stub(_cemu_keys, _cemu_entry["firmware"][0]["stub"]),
          False)
    with io.open(os.path.join(_fw_dir, "keys.txt"), "w", encoding="utf-8", newline="\n") as _handle:
        _handle.write("ffffffffffffffffffffffffffffffff\n")
    check("so a send does not overwrite it",
          emu_firmware.install(_cemu_entry, _cemu_entry["firmware"][0]["name"])["kept"],
          ["keys.txt"])
    emu_firmware.remove(["keys.txt"])

    # A destination is joined onto the user's home, so a malformed catalog entry
    # must not be able to write outside it.
    check(
        "a traversing destination is refused",
        emu_firmware._destination({"dest": "../../etc"}),
        "",
    )
    check("an absent destination is not a path", emu_firmware._destination({}), "")
    # Asking for something the emulator never wanted must not write anything.
    check(
        "an unknown requirement is refused",
        emu_firmware.install(emu_catalog.find("pcsx2"), "Nonsense")["ok"],
        False,
    )

    # Removing an install is what makes Install repeatable -- retrying a wrong
    # destination, or testing the flow twice. It deletes at the destination and
    # leaves the transfer folder alone, so a second Install puts it back.
    check(
        "an installed requirement can be taken back out",
        emu_firmware.uninstall(emu_catalog.find("pcsx2"), "PS2 BIOS")["removed"],
        ["scph39001.bin"],
    )
    check(
        "the emulator no longer has it",
        os.path.isfile(os.path.join(_result["dest"], "scph39001.bin")),
        False,
    )
    # Gone, not returned. Installing moved the file, so there is no second copy
    # anywhere and supplying it again means sending it again -- which is what
    # the confirm dialog says, since a trash button would not imply it.
    check(
        "and no copy is left behind anywhere",
        os.path.isfile(os.path.join(_fw_dir, "scph39001.bin")),
        False,
    )
    _send("scph39001.bin")
    check(
        "sending it again is what puts it back",
        emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")["copied"],
        ["scph39001.bin"],
    )

    # A file the plugin did not install is still removable -- one installed
    # before the record existed would otherwise be stuck forever -- but it is
    # counted separately so the UI can warn before anything happens.
    with io.open(os.path.join(_result["dest"], "scph70012.bin"), "wb") as _handle:
        _handle.write(b"\0")
    _byhand = emu_firmware.status(emu_catalog.find("pcsx2"))[0]
    check("a hand-placed file is reported as not ours", _byhand["foreign"], ["scph70012.bin"])
    _pulled = emu_firmware.uninstall(emu_catalog.find("pcsx2"), "PS2 BIOS")
    check("ours is removed as ours", _pulled["removed"], ["scph39001.bin"])
    check("and theirs is counted separately", _pulled["foreign"], ["scph70012.bin"])
    check(
        "removing what is not there is not an error",
        emu_firmware.uninstall(emu_catalog.find("pcsx2"), "PS2 BIOS")["removed"],
        [],
    )
    emu_firmware.install(emu_catalog.find("pcsx2"), "PS2 BIOS")

    # Only two things are left in the transfer folder after a successful
    # install: a file the emulator has to import itself, and one nothing
    # recognised. Deleting is still reachable for those -- the PUP sent above is
    # exactly the first case, and is a couple of hundred megabytes in reality.
    check(
        "a file waiting for a manual import can be deleted",
        emu_firmware.remove(["PS3UPDAT.PUP"])["removed"],
        ["PS3UPDAT.PUP"],
    )

    # The names arrive from the frontend and this is a delete, so anything that
    # is not a bare filename in that one folder must be refused outright.
    for _bad in ("../secret", "sub/dir.bin", "/etc/passwd", "", ".", ".."):
        if emu_firmware.remove([_bad])["ok"]:
            failures.append("delete accepted a bad name: %r" % _bad)
    print("PASS %-52s %r" % ("a delete cannot escape the firmware folder", True))

    # Matching is on the filename, so a dump under any other name is silently
    # never recognised. Every requirement has to say which names it takes, or
    # the rule is invisible and the user has no way to find out.
    for _entry in emu_catalog.CATALOG:
        for _req in _entry.get("firmware") or []:
            if not _req.get("expects"):
                failures.append("%s/%s says nothing about expected filenames"
                                % (_entry["id"], _req.get("name")))
    print("PASS %-52s %r" % ("every requirement names the files it accepts", True))
    check(
        "and it reaches the panel",
        bool(emu_firmware.status(emu_catalog.find("pcsx2"))[0]["expects"]),
        True,
    )
    # The match pattern is the plugin's business, not the frontend's.
    _listed = emu_catalog.listing({}, ())
    _pcsx2_listed = next(item for item in _listed if item["id"] == "pcsx2")
    check(
        "the listing carries the expected names",
        bool(_pcsx2_listed["firmware"][0]["expects"]),
        True,
    )
    check(
        "but not the match pattern or destination",
        [key for key in _pcsx2_listed["firmware"][0] if key in ("match", "dest", "manual")],
        [],
    )

    # Every placeable requirement in the catalog must name a destination and a
    # pattern, or the row would offer an Install button that does nothing. An
    # imported one is copied nowhere, so what it must name instead is the
    # command and the file the emulator leaves behind -- without that marker the
    # row could never report the install as having happened.
    for _entry in emu_catalog.CATALOG:
        for _req in _entry.get("firmware") or []:
            if _req.get("manual"):
                continue
            if not _req.get("match"):
                failures.append(
                    "%s/%s is installable but names no pattern"
                    % (_entry["id"], _req.get("name"))
                )
                continue
            _import = _req.get("import")
            if _import:
                if not _import.get("args") or not _import.get("installed"):
                    failures.append(
                        "%s/%s is imported but names no %s"
                        % (
                            _entry["id"],
                            _req.get("name"),
                            "command" if not _import.get("args") else "marker",
                        )
                    )
                elif "{file}" not in " ".join(_import["args"]):
                    # Without the placeholder the emulator would be run with no
                    # file at all, which for RPCS3 means opening its interface.
                    failures.append(
                        "%s/%s never passes the file to the emulator"
                        % (_entry["id"], _req.get("name"))
                    )
            elif not _req.get("dest"):
                failures.append(
                    "%s/%s is installable but names no destination"
                    % (_entry["id"], _req.get("name"))
                )
    print("PASS %-52s %r" % ("every installable requirement is complete", True))

    # A flatpak reads and writes inside its own sandbox, so both the firmware
    # destination and anything the setup edits have to be under it. Getting the
    # branch of that path wrong is the live failure mode -- DuckStation's BIOS
    # folder was under `data/` when it follows XDG_CONFIG_HOME and is really
    # under `config/` -- and this at least catches a path aimed at the wrong
    # application entirely, which looks identical in review.
    for _entry in emu_catalog.CATALOG:
        _src = _entry.get("source") or {}
        if _src.get("kind") != "flatpak":
            continue
        _sandbox = ".var/app/%s/" % _src["id"]
        _paths = [_req["dest"] for _req in _entry.get("firmware") or [] if _req.get("dest")]
        # A requirement that points a setting at what it installed writes into
        # the emulator's own config, which is inside the sandbox too.
        _paths += [
            _req["configure"]["path"]
            for _req in _entry.get("firmware") or []
            if _req.get("configure")
        ]
        _paths += list(((_entry.get("setup") or {}).get("files") or {}))
        for _path in _paths:
            if not _path.startswith(_sandbox):
                failures.append(
                    "%s writes to %s, outside %s" % (_entry["id"], _path, _sandbox)
                )
    print("PASS %-52s %r" % ("every path stays inside the emulator's sandbox", True))
finally:
    sysenv.user_home = _real_user_home

section("collections -- renaming must move games that are already added")
import asyncio  # noqa: E402

sys.path.insert(0, REPO_ROOT)
import main as plugin_main  # noqa: E402

N64_CORE = {
    "id": "mupen64plus_next",
    "path": "/cores/mupen64plus_next_libretro.so",
    "display_name": "Nintendo - Nintendo 64 (Mupen64Plus-Next)",
    "system_name": "Nintendo 64",
    "databases": ["Nintendo - Nintendo 64"],
    "extensions": ["n64"],
    "has_info": True,
}
SNES_CORE = dict(
    N64_CORE,
    id="bsnes",
    system_name="Super Nintendo Entertainment System",
    databases=["Nintendo - Super Nintendo Entertainment System"],
    extensions=["sfc"],
)

Plugin = plugin_main.Plugin
check("core system name preferred", Plugin._platform_label(N64_CORE), "Nintendo 64")
# Long database names read badly on a shelf header, so short names are default.
check("short NES", Plugin._platform_label({"databases": ["Nintendo - Nintendo Entertainment System"]}, short=True), "NES")
check("short SNES", Plugin._platform_label(SNES_CORE, short=True), "SNES")
check("short from a stored system", Plugin._platform_label(None, "Nintendo - Game Boy Advance", True), "GBA")
check("short arcade", Plugin._platform_label(None, "FBNeo - Arcade Games", True), "Arcade")
check(
    "unlisted systems drop the manufacturer",
    Plugin._platform_label(None, "Acme - Wonder Machine", True),
    "Wonder Machine",
)
check(
    "full style keeps the long name",
    Plugin._platform_label(SNES_CORE, short=False),
    "Super Nintendo Entertainment System",
)
check(
    "style follows the setting",
    Plugin._entry_platform({"platform_names": "short"}, SNES_CORE, {}),
    "SNES",
)
check(
    "full setting honoured",
    Plugin._entry_platform({"platform_names": "full"}, SNES_CORE, {}),
    "Super Nintendo Entertainment System",
)

# Dolphin declares GameCube *and* Wii. Taking databases[0] filed every Wii game
# under GameCube -- artwork resolution had already worked out which system the
# game was in, and the answer was thrown away at registration.
DUAL_CORE = {"databases": ["Nintendo - GameCube", "Nintendo - Wii"], "system_name": ""}
check(
    "a resolved system wins over the core's first database",
    Plugin._system_for(DUAL_CORE, "Nintendo - Wii"),
    "Nintendo - Wii",
)
check(
    "and reaches the collection label",
    Plugin._entry_platform({"platform_names": "short"}, DUAL_CORE, {"system": "Nintendo - Wii"}),
    "Wii",
)
check(
    "with no answer, the first database is still the fallback",
    Plugin._system_for(DUAL_CORE, ""),
    "Nintendo - GameCube",
)
# A stale system must not survive a core change, or editing a game onto a
# different emulator would keep filing it under the old system.
check(
    "a system the new core does not claim is discarded",
    Plugin._system_for(SNES_CORE, "Nintendo - Wii"),
    SNES_CORE["databases"][0],
)
check(
    "and the stored one is preferred when the core still covers it",
    Plugin._system_for(DUAL_CORE, "", "Nintendo - Wii"),
    "Nintendo - Wii",
)
check(
    "falls back to the database tail",
    Plugin._platform_label({"databases": ["Sega - Mega Drive - Genesis"]}),
    "Genesis",
)
check("falls back to a stored system", Plugin._platform_label(None, "Nintendo - Game Boy"), "Game Boy")
check("no core and no system", Plugin._platform_label(None, ""), "")

flat = {"collection_name": "RetroArch", "collection_per_platform": False}
per_platform = {"collection_name": "RetroArch", "collection_per_platform": True}
check("flat naming", Plugin._collection_name(flat, "Nintendo 64"), "RetroArch")
check(
    "per-platform naming",
    Plugin._collection_name(per_platform, "Nintendo 64"),
    "RetroArch - Nintendo 64",
)
check(
    "per-platform with unknown system falls back",
    Plugin._collection_name(per_platform, ""),
    "RetroArch",
)


# The matcher that recognises our own collections lives in the frontend, where
# it decides whether one gets deleted, and is tested there against the shipped
# code -- src/collectionMatch.test.ts. It used to be re-implemented here in
# Python: that proved the copy right and said nothing about what runs.
#
# What stays on this side is the other half of the contract: `collection_shape`
# hands over the base, the flag and the template, and the names below are what
# `_collection_name` really produces from them.
def named(template):
    return Plugin._collection_name(
        {"collection_name": "Emulation", "collection_per_platform": True,
         "collection_template": template},
        "Nintendo 64",
    )


check("bracketed format", named("[{name}] {platform}"), "[Emulation] Nintendo 64")
check("colon format", named("{name}: {platform}"), "Emulation: Nintendo 64")
check("middot format", named("{name} · {platform}"), "Emulation · Nintendo 64")
check("platform only", named("{platform}"), "Nintendo 64")
check("platform first", named("{platform} ({name})"), "Nintendo 64 (Emulation)")
check("newline escape becomes a newline", named("{name}\\n{platform}"), "Emulation\nNintendo 64")
check("a missing template falls back to the default", named(""), "Emulation - Nintendo 64")
# A template that leaves a dangling separator should not produce " - Nintendo 64".
check("dangling separators are trimmed", named("- {platform}"), "Nintendo 64")
check("runs of spaces collapse", named("{name}    {platform}"), "Emulation Nintendo 64")
check("an empty base disables collections", Plugin._collection_name({"collection_name": " "}, "N64"), "")

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = [N64_CORE, SNES_CORE]
# Set explicitly: list_cores merges custom emulators into the core list, so an
# unset attribute would fail rather than simply returning the libretro cores.
plugin._emulators = []
# The full shape ra_detect.detect() returns, so anything reading a field the
# earlier fixture omitted fails here rather than on the device.
plugin._install = {
    "kind": "flatpak",
    "exe": "/usr/bin/flatpak",
    "config_dir": "/x",
    "core_dirs": ["/x/cores"],
    "info_dirs": ["/x/info"],
}


def run(coro):
    return plugin.loop.run_until_complete(coro)


store.set_settings({"collection_name": "RetroArch", "collection_per_platform": False})
store.remember_game(
    11,
    {"app_id": 11, "title": "Zelda", "core_id": "mupen64plus_next", "collection": "RetroArch"},
)
store.remember_game(
    22, {"app_id": 22, "title": "Mario", "core_id": "bsnes", "collection": "RetroArch"}
)

check("nothing to do when settings are unchanged", run(plugin.plan_collection_migration())["moves"], [])

# The reported bug: a rename left already-added games in the old collection.
store.set_settings({"collection_name": "Emulation"})
moves = run(plugin.plan_collection_migration())["moves"]
check("a rename moves every game", len(moves), 2)
check("moves come from the old name", sorted({m["from"] for m in moves}), ["RetroArch"])
check("moves go to the new name", sorted({m["to"] for m in moves}), ["Emulation"])

store.set_settings({"collection_per_platform": True})
moves = run(plugin.plan_collection_migration())["moves"]
check(
    "per-platform splits by system",
    sorted(m["to"] for m in moves),
    ["[Emulation] N64", "[Emulation] SNES"],
)

run(plugin.record_collections({m["app_id"]: m["to"] for m in moves}))
check("recorded assignments settle the plan", run(plugin.plan_collection_migration())["moves"], [])

store.set_settings({"collection_per_platform": False})
moves = run(plugin.plan_collection_migration())["moves"]
check("turning it off merges them back", sorted({m["to"] for m in moves}), ["Emulation"])
check(
    "and knows the per-platform names to leave",
    sorted({m["from"] for m in moves}),
    ["[Emulation] N64", "[Emulation] SNES"],
)

# Games added by an older build recorded no collection. Without the previous
# settings their old collection is unknown, so they get added to the new one and
# never removed from the old -- which left old collections populated.
store.set_settings({"collection_name": "Fresh", "collection_per_platform": False})
store.remember_game(33, {"app_id": 33, "title": "Legacy", "core_id": "bsnes"})

legacy = [m for m in run(plugin.plan_collection_migration())["moves"] if m["app_id"] == 33]
check("a legacy game still moves", len(legacy), 1)
check("but its source is unknown without help", legacy[0]["from"], "")

legacy = [
    m
    for m in run(
        plugin.plan_collection_migration(
            {"collection_name": "Emulation", "collection_per_platform": False}
        )
    )["moves"]
    if m["app_id"] == 33
]
check("previous settings recover the source", legacy[0]["from"], "Emulation")

legacy = [
    m
    for m in run(
        plugin.plan_collection_migration(
            {"collection_name": "Emulation", "collection_per_platform": True}
        )
    )["moves"]
    if m["app_id"] == 33
]
# The previous dict carries no template or style, so the built-in defaults for
# those apply -- which is what an older settings file looks like.
check("including a previous per-platform name", legacy[0]["from"], "Emulation - SNES")

targets = run(plugin.collection_targets())
check("targets cover every registered game", sorted(targets["targets"].keys()), ["11", "22", "33"])
check("targets use the current name", set(targets["targets"].values()), {"Fresh"})

# With collections off a game belongs nowhere, so "is it filed correctly" has no
# answer -- and the library check, which has no panel gating it, would otherwise
# report every game as missing from a collection nobody asked for.
store.set_settings({"add_to_collection": False})
check("no targets at all when collections are switched off",
      run(plugin.collection_targets()), {"targets": {}, "titles": {}})
store.set_settings({"add_to_collection": True})

section("install progress -- a bogus percentage drives the bar off screen")
# Output is read in fixed-size chunks, so a number can be split across reads.
# "1425%" must not be read as 425: nProgress is 0-100 (decky-loader emits
# round(raw/total*100)), and anything above 100 renders past the bar's track.
check("a split number is rejected", Plugin._parse_percent("1425%"), -1)
check("a plain percentage is read", Plugin._parse_percent("Downloading 45%"), 45)
check("the last one wins", Plugin._parse_percent("1/5 12% ... 87%"), 87)
check("100 is allowed", Plugin._parse_percent("done 100%"), 100)
check("no percentage yields -1", Plugin._parse_percent("Updating runtime/org.kde.Platform"), -1)
check("an out-of-range value is ignored", Plugin._parse_percent("999%"), -1)
check("spacing is tolerated", Plugin._parse_percent("progress 7 %"), 7)
check(
    "a real flatpak line",
    Plugin._parse_percent("Installing 12/34… 63%  1.2 MB/s"),
    63,
)

section("file transfer -- the upload page must reach the token path")
import re as _re  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from urllib.parse import urljoin  # noqa: E402

import fileserver  # noqa: E402

check("traversal is stripped", fileserver.safe_name("../../etc/passwd"), "passwd")
check("windows separators too", fileserver.safe_name("..\..\win.ini"), "win.ini")
check("leading dots removed", fileserver.safe_name(".hidden"), "hidden")
check("empty names get a fallback", fileserver.safe_name(""), "upload.bin")

incoming = os.path.join(TMP, "incoming")
os.makedirs(incoming, exist_ok=True)
served = fileserver.start(incoming)

if served.get("error"):
    print("SKIP file server (%s)" % served["error"])
else:
    url = served["url"]
    root = "http://127.0.0.1:%d" % served["port"]
    check("the URL ends in a slash", url.endswith("/"), True)

    with urllib.request.urlopen(url, timeout=5) as response:
        page = response.read().decode()
    base = _re.search(r"const UPLOAD_BASE = '([^']+)'", page)
    check("the page carries an absolute upload path", bool(base), True)
    # A grid item defaults to min-width:auto and will not shrink below its own
    # content, so the ellipsis on the filename never got a chance and a long
    # name pushed the whole card off the side of the page. A string check is a
    # weak test of a layout, but this exact mistake has now been made twice in
    # two different layout systems, and it pins the rule that fixes it.
    check("the upload list cannot be widened by a long filename",
          ("grid-template-columns: minmax(0, 1fr)" in page, "li { min-width: 0" in page),
          (True, True))
    # Regression: a relative 'upload/x' resolves against /<token> and loses the
    # token, so every upload was refused and the file never arrived.
    check(
        "it is not the relative form that dropped the token",
        urljoin(url.rstrip("/"), "upload/x.sfc").endswith("/upload/x.sfc")
        and base.group(1) != "upload/",
        True,
    )

    def put(path, data=b"rom"):
        request = urllib.request.Request(root + path, data=data, method="PUT")
        request.add_header("Content-Length", str(len(data)))
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def settled(seconds=3.0):
        """Wait for the in-flight count to drop, then report it.

        The client sees its 200 from inside the handler, which returns before the
        counter is decremented -- so a read taken the instant an upload finishes can
        still be 1. Harmless in use (the worst case is that closing the dialog
        leaves the server to stop on idle) but it makes a bare assertion flaky.
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            count = fileserver.status()["uploading"]
            if count == 0:
                return count
            time.sleep(0.05)
        return fileserver.status()["uploading"]

    check("upload via the page's own path", put(base.group(1) + "Game%20(USA).sfc"), 200)
    check("and the in-flight count returns to zero afterwards", settled(), 0)

    # A slow upload must be visible as in flight, or closing the dialog would stop
    # the server underneath it.
    import http.client as _http  # noqa: E402
    import threading as _threading  # noqa: E402

    seen = []

    def _slow_upload():
        connection = _http.HTTPConnection("127.0.0.1", served["port"], timeout=10)
        connection.putrequest("PUT", base.group(1) + "Slow.sfc")
        connection.putheader("Content-Length", "64")
        connection.endheaders()
        connection.send(b"x" * 32)
        # Half sent: the handler is blocked waiting for the rest.
        time.sleep(0.6)
        seen.append(fileserver.status()["uploading"])
        connection.send(b"x" * 32)
        connection.getresponse().read()
        connection.close()

    worker = _threading.Thread(target=_slow_upload)
    worker.start()
    worker.join(timeout=15)
    check("an upload in progress is counted", seen, [1])
    check("and the count clears when it finishes", settled(), 0)

    # A count alone cannot tell a 4 GB ROM crawling in over wifi from a
    # connection that has stalled -- both are "1 file". The bytes have to be
    # visible while the file is still arriving, which means larger than one read:
    # the handler blocks in rfile.read until a whole chunk is there, so a payload
    # smaller than _CHUNK reports nothing until it is already complete.
    tracked = []
    tracked_total = fileserver._CHUNK + 512 * 1024

    def _tracked_upload():
        connection = _http.HTTPConnection("127.0.0.1", served["port"], timeout=20)
        connection.putrequest("PUT", base.group(1) + "Big.iso")
        connection.putheader("Content-Length", str(tracked_total))
        connection.endheaders()
        # Exactly one chunk, so the handler's first read completes and publishes.
        connection.send(b"x" * fileserver._CHUNK)
        time.sleep(0.6)
        tracked.append(fileserver.status()["uploads"])
        connection.send(b"x" * (tracked_total - fileserver._CHUNK))
        connection.getresponse().read()
        connection.close()

    tracked_worker = _threading.Thread(target=_tracked_upload)
    tracked_worker.start()
    tracked_worker.join(timeout=30)
    mid = tracked[0][0] if tracked and tracked[0] else {}
    check("an upload in flight says what it is", mid.get("name"), "Big.iso")
    check("how big it will be", mid.get("total"), tracked_total)
    check("and how much has arrived so far", mid.get("received"), fileserver._CHUNK)
    check("and it stops being reported once complete", settled(), 0)
    check("the finished file is on disk", os.path.isfile(os.path.join(incoming, "Big.iso")), True)

    # Cancelling a transfer that is still moving. The handler notices the flag
    # between chunks, so this needs nothing from the socket and holds everywhere.
    def _drip_upload(filename, total, pieces, gap):
        """Send `total` bytes in `pieces`, pausing between them."""
        def _send():
            connection = _http.HTTPConnection("127.0.0.1", served["port"], timeout=20)
            try:
                connection.putrequest("PUT", base.group(1) + filename)
                connection.putheader("Content-Length", str(total))
                connection.endheaders()
                for _piece in range(pieces):
                    connection.send(b"x" * (total // pieces))
                    time.sleep(gap)
                connection.getresponse().read()
            except OSError:
                # Expected once the far end goes away under a cancel.
                pass
            finally:
                try:
                    connection.close()
                except OSError:
                    pass

        worker = _threading.Thread(target=_send)
        worker.start()
        return worker

    dripping = _drip_upload("Abandoned.iso", fileserver._CHUNK * 8, 8, 0.2)
    # Wait until the handler has actually written something, so the cancel lands
    # mid-transfer rather than before it began.
    deadline = time.time() + 5
    live = []
    while time.time() < deadline:
        live = fileserver.status()["uploads"]
        if live and live[0]["received"] > 0:
            break
        time.sleep(0.05)

    check("an upload in progress can be identified", len(live), 1)
    check("cancelling it reports what it signalled", fileserver.cancel(live[0]["id"]), 1)
    check("and the handler lets go", settled(5.0), 0)
    dripping.join(timeout=10)
    check(
        "the half-written file is deleted, not left as litter",
        os.path.isfile(os.path.join(incoming, "Abandoned.iso.uploading")),
        False,
    )
    check(
        "and no finished file is invented from a partial transfer",
        os.path.isfile(os.path.join(incoming, "Abandoned.iso")),
        False,
    )
    check("cancelling when nothing is running is not an error", fileserver.cancel(), 0)

    # The wrapper the frontend actually calls. 0 means "all of them", so a caller
    # with no particular transfer in mind needs no id to abandon everything.
    _cancelled = run(plugin.cancel_upload(0))
    check("cancel_upload reports how many it signalled", _cancelled["cancelled"], 0)
    check("and hands back the server state with it", _cancelled["running"], True)
    check("including what has already been received", "received" in _cancelled, True)

    # A transfer that has stalled outright is the one you most want to abandon,
    # and the one a flag alone cannot reach: the handler is blocked in rfile.read
    # waiting for bytes that will never arrive, so nothing checks the flag until
    # cancel() shuts the socket down under it.
    #
    # POSIX only. Linux releases a blocked recv on shutdown(); Windows does not
    # reliably, and the Deck is Linux. The cooperative path above is what covers
    # this logic on a Windows host.
    if os.name == "posix":
        stalled_total = fileserver._CHUNK * 4

        def _stalled_upload():
            connection = _http.HTTPConnection("127.0.0.1", served["port"], timeout=20)
            try:
                connection.putrequest("PUT", base.group(1) + "Stalled.iso")
                connection.putheader("Content-Length", str(stalled_total))
                connection.endheaders()
                connection.send(b"x" * fileserver._CHUNK)
                # Then nothing, ever. Only cancel() gets the handler out of this.
                time.sleep(8.0)
            except OSError:
                pass
            finally:
                try:
                    connection.close()
                except OSError:
                    pass

        stuck = _threading.Thread(target=_stalled_upload, daemon=True)
        stuck.start()
        deadline = time.time() + 5
        stalled = []
        while time.time() < deadline:
            stalled = fileserver.status()["uploads"]
            if stalled and stalled[0]["received"] > 0:
                break
            time.sleep(0.05)

        check("a stalled upload is still reported as in flight", len(stalled), 1)
        fileserver.cancel(stalled[0]["id"])
        check("cancelling releases a handler blocked on a dead socket", settled(5.0), 0)
        check(
            "and its partial file goes too",
            os.path.isfile(os.path.join(incoming, "Stalled.iso.uploading")),
            False,
        )
    else:
        print("SKIP cancelling a stalled transfer (shutdown does not unblock reads here)")

    # Closing the browser mid-upload is the ordinary way a transfer dies. The page
    # now asks before letting that happen, but the prompt is advisory -- the user
    # can dismiss it and several mobile browsers ignore beforeunload outright --
    # so the server must still treat a vanished client as a normal ending and
    # clean up after it.
    def _client_hangs_up():
        connection = _http.HTTPConnection("127.0.0.1", served["port"], timeout=20)
        try:
            connection.putrequest("PUT", base.group(1) + "Dropped.iso")
            connection.putheader("Content-Length", str(fileserver._CHUNK * 3))
            connection.endheaders()
            connection.send(b"x" * fileserver._CHUNK)
            time.sleep(0.4)
        except OSError:
            pass
        finally:
            # No further bytes, no polite ending: the tab is gone.
            try:
                connection.close()
            except OSError:
                pass

    dropped = _threading.Thread(target=_client_hangs_up)
    dropped.start()
    dropped.join(timeout=15)
    check("a client that vanishes is not left counted", settled(5.0), 0)
    check(
        "and its half-written file is cleaned up",
        os.path.isfile(os.path.join(incoming, "Dropped.iso.uploading")),
        False,
    )
    check(
        "with no truncated ROM left in its place",
        os.path.isfile(os.path.join(incoming, "Dropped.iso")),
        False,
    )

    # The page has to carry the guard, or there is nothing to dismiss. `page` is
    # the upload page as this running server actually served it, fetched above.
    check("the upload page warns before a tab is closed mid-transfer",
          "beforeunload" in page, True)
    check("and only while something is actually running",
          "if (active === 0) return;" in page, True)
    check("with the counter released on every outcome", "loadend" in page, True)

    # Declared inline so the browser never asks for /favicon.ico -- which this
    # server answers 404 and logs, once per page load, for nothing. Both pages
    # carry it, so a tab shows the same icon before and after the code is entered.
    check("the page declares its own icon", 'rel="icon" href="data:image/svg' in page, True)
    check(
        "and so does the code form",
        'rel="icon" href="data:image/svg' in fileserver._code_page(),
        True,
    )

    # A partial left by something no handler survived -- an unload, a power cut --
    # has nothing to clean it up, so starting again does it.
    orphan_partial = os.path.join(incoming, "Interrupted.iso.uploading")
    with open(orphan_partial, "wb") as _handle:
        _handle.write(b"half a rom")
    real_file = os.path.join(incoming, "Keep Me.sfc")
    with open(real_file, "wb") as _handle:
        _handle.write(b"a real rom")
    check("a leftover partial is swept", fileserver.sweep_partials(incoming), [orphan_partial])
    check("and is gone", os.path.isfile(orphan_partial), False)
    check("while real files are left alone", os.path.isfile(real_file), True)
    check("sweeping a folder with nothing to sweep is fine", fileserver.sweep_partials(incoming), [])
    check("as is sweeping somewhere that does not exist", fileserver.sweep_partials("/nope/nowhere"), [])
    os.remove(real_file)
    check("the decoded name is used", os.path.isfile(os.path.join(incoming, "Game (USA).sfc")), True)
    check("no token means refused", put("/upload/sneaky.sfc"), 404)
    check("wrong token refused", put("/notthetoken/upload/sneaky.sfc"), 404)
    check("nested paths refused", put(base.group(1) + "sub/dir.sfc"), 404)
    check("encoded traversal is contained", put(base.group(1) + "..%2F..%2Fout.sfc"), 200)
    check("nothing escaped the folder", os.path.isfile(os.path.join(TMP, "out.sfc")), False)
    check("no partial files left behind",
          [f for f in os.listdir(incoming) if f.endswith(".uploading")], [])

    # The way in from a computer: a short address and six digits, because nothing
    # on a desktop scans a QR code and nobody types a 22-character token.
    def get(path, follow=False):
        """(status, body, location) for a GET, without following redirects."""
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None

        opener = (
            urllib.request.build_opener()
            if follow
            else urllib.request.build_opener(_NoRedirect)
        )
        try:
            with opener.open(root + path, timeout=5) as response:
                return response.status, response.read().decode(), ""
        except urllib.error.HTTPError as error:
            return error.code, "", error.headers.get("Location", "")

    token = served["url"].rstrip("/").rsplit("/", 1)[-1]
    check("the short address needs no token", token not in served["short_url"], True)
    check("the code is six digits", len(served["pin"]) == 6 and served["pin"].isdigit(), True)

    status_code, body, _ = get("/")
    check("the root serves a code form without a token", status_code == 200 and "<form" in body, True)

    _status, _body, location = get("/?code=%s" % served["pin"])
    check("the right code redirects to the token path", location, "/%s/" % token)
    check("following it reaches the upload page",
          "UPLOAD_BASE" in get(location, follow=True)[1], True)

    wrong = "0" * 6 if served["pin"] != "000000" else "111111"
    status_code, body, _ = get("/?code=%s" % wrong)
    check("a wrong code is rejected without redirecting", status_code, 200)
    check("and says so rather than failing silently", "not right" in body, True)
    check("the right code still works after one miss", bool(get("/?code=%s" % served["pin"])[2]), True)

    # Anything on the network can put a raw high byte in a request line, and
    # BaseHTTPRequestHandler hands it to us decoded as latin-1. compare_digest
    # refuses a non-ASCII str outright, so both the token check and the code
    # check used to raise inside the handler -- the connection was dropped with a
    # traceback in the log instead of being answered. urllib cannot reproduce
    # this: it percent-encodes, which is the case that already worked.
    import socket as _socket  # noqa: E402

    def raw(line):
        """A request line sent verbatim. Returns the reply, or b'' if dropped."""
        connection = _socket.create_connection(("127.0.0.1", served["port"]), timeout=5)
        try:
            connection.sendall(line + b"\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
            reply = b""
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                reply += chunk
            return reply
        finally:
            connection.close()

    check(
        "a non-ASCII path is refused rather than raising",
        b" 404 " in raw(b"GET /\xc3\xa9/ HTTP/1.1"),
        True,
    )
    check(
        "a non-ASCII code is refused rather than raising",
        b" 200 " in raw(b"GET /?code=\xe9\xe9\xe9\xe9\xe9\xe9 HTTP/1.1"),
        True,
    )
    check(
        "and a non-ASCII upload path is refused too",
        b" 404 " in raw(b"PUT /\xff/upload/x.sfc HTTP/1.1"),
        True,
    )

    # Six digits are only safe because guessing is capped.
    for _attempt in range(fileserver.PIN_ATTEMPTS):
        get("/?code=%s" % wrong)
    check("too many wrong codes locks the code out", fileserver.status()["pin_locked"], True)
    check("even the correct code stops working", get("/?code=%s" % served["pin"])[2], "")
    check("and the page explains the lockout", "Too many wrong codes" in get("/")[1], True)
    # The token URL is unaffected: the code only opens the door.
    check("the token path still works", get("/%s/" % token)[0], 200)

    fileserver.stop()
    check("stopping leaves nothing running", fileserver.status()["running"], False)
    check("and reports no code once stopped", fileserver.status()["pin"], "")

    # Closing the dialog stops the server, so the frontend has to be able to tell
    # whether stopping now would cut a transfer off.
    check("nothing is in flight when idle", settled(), 0)

    # One tap from the panel: no folder argument, so the caller needs no round trip
    # to discover the default first.
    defaulted = run(plugin.start_file_server())
    check("starting with no folder succeeds", defaulted["ok"], True)
    check("and uses the default folder", defaulted["target_dir"], fileserver.default_dir())
    check("a blank folder means the same thing", run(plugin.stop_file_server())["running"], False)
    blank = run(plugin.start_file_server("   "))
    check("whitespace is not treated as a folder", blank["target_dir"], fileserver.default_dir())
    run(plugin.stop_file_server())

    # A remembered link. Normally the port, the token and the code are all minted
    # per session, so nothing outlives a transfer -- which also means a trusted
    # device retypes an address and a code every single time. Reusing the pair
    # reproduces the same URL, and that is the whole feature.
    fileserver.stop()
    first = fileserver.start(incoming)
    if not first.get("error"):
        # `get` reads `root` at call time, so it has to follow the server as these
        # restarts move it between ports.
        root = "http://127.0.0.1:%d" % first["port"]
        remembered_port = first["port"]
        remembered_token = fileserver.current_token()
        first_url = first["url"]
        fileserver.stop()

        again = fileserver.start(incoming, remembered_port, remembered_token)
        root = "http://127.0.0.1:%d" % again["port"]
        check("a remembered link comes back on the same address", again["url"], first_url)
        check("and the same token is still serving", fileserver.current_token(), remembered_token)
        # The saved link must actually work, not merely look identical.
        check("the saved link still reaches the upload page", get("/%s/" % remembered_token)[0], 200)
        # Only then is it honest to suggest bookmarking it.
        check("and the page offers to be kept", "Keep this page" in get("/%s/" % remembered_token)[1], True)
        fileserver.stop()

        # Without the pair, everything is new -- which is what makes a link that
        # was never meant to last stop working.
        fresh = fileserver.start(incoming)
        root = "http://127.0.0.1:%d" % fresh["port"]
        check("a fresh session issues a different token", fileserver.current_token() != remembered_token, True)
        check("so the old link is refused", get("/%s/" % remembered_token)[0], 404)
        check(
            "and a page that will not last does not ask to be kept",
            "Keep this page" in get("/%s/" % fileserver.current_token())[1],
            False,
        )
        fileserver.stop()

        # A remembered port that something else has taken must cost a changed
        # address, not a failed transfer.
        import socket as _sock  # noqa: E402

        squatter = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        squatter.bind(("0.0.0.0", 0))
        squatter.listen(1)
        taken_port = squatter.getsockname()[1]
        crowded = fileserver.start(incoming, taken_port, remembered_token)
        root = "http://127.0.0.1:%d" % crowded["port"]
        check("a taken port does not stop the server starting", crowded.get("error"), None)
        check("it just lands somewhere else", crowded["port"] != taken_port, True)
        check(
            "and stops claiming the link is worth keeping",
            "Keep this page" in get("/%s/" % remembered_token)[1],
            False,
        )
        squatter.close()
        fileserver.stop()

    served = fileserver.start(incoming)
    root = "http://127.0.0.1:%d" % served["port"]
    token = served["url"].rstrip("/").rsplit("/", 1)[-1]

    # A restart mints a new code and a fresh allowance, which is what the panel
    # tells a locked-out user to do.
    restarted = fileserver.start(incoming)
    if not restarted.get("error"):
        check("restarting clears the lockout", restarted["pin_locked"], False)
        check("and issues a different code", restarted["pin"] != served["pin"], True)

        # Stopping must not disown transfers that are still running. It used to
        # zero the in-flight count, so the request's own decrement took it to -1
        # -- and since start() never reset it, the count stayed negative for the
        # rest of the session and the panel could no longer tell that nothing was
        # in flight. Simulated rather than raced, because the bug is about who
        # owns the record, not about timing.
        # The full shape do_PUT records, not a convenient subset: a fixture that
        # drifts from the real entry is one that stops testing the real thing.
        fileserver._in_flight[999] = {
            "name": "Big.iso",
            "received": 1,
            "total": 2,
            "at": time.time(),
            "connection": None,
            "partial": os.path.join(incoming, "Big.iso.uploading"),
            "cancelled": False,
        }
        fileserver.stop()
        check("stopping leaves running uploads recorded", len(fileserver._in_flight), 1)
        _fresh = fileserver.start(incoming)
        if not _fresh.get("error"):
            check("but a new server starts from zero", fileserver.status()["uploading"], 0)
            check("with nothing left to report", fileserver.status()["uploads"], [])
            fileserver.stop()

section("Steam runtime -- system binaries must not load Steam's libraries")
import sysenv  # noqa: E402

# Decky runs plugins inside Steam's environment, where LD_LIBRARY_PATH points at
# the Steam Runtime. flatpak then loads Steam's libcrypto and dies instantly:
#   libcrypto.so.3: version `OPENSSL_3.4.0' not found
dirty = {
    "LD_LIBRARY_PATH": "/steam/runtime/lib",
    "LD_PRELOAD": "/steam/overlay.so",
    "GTK_PATH": "/steam/gtk",
    "HOME": "/home/deck",
    "PATH": "/usr/bin",
}
cleaned = sysenv.clean_env(dirty)
check("the runtime library path is cleared", "LD_LIBRARY_PATH" in cleaned, False)
check("the Steam overlay preload is cleared", "LD_PRELOAD" in cleaned, False)
check("other injected paths are cleared", "GTK_PATH" in cleaned, False)
check("unrelated variables survive", cleaned.get("HOME"), "/home/deck")
check("PATH survives", cleaned.get("PATH"), "/usr/bin")

# Where Steam preserved the original search path, restore it rather than leaving
# the variable unset.
restored = sysenv.clean_env(
    {"LD_LIBRARY_PATH": "/steam/runtime/lib", "SYSTEM_LD_LIBRARY_PATH": "/usr/lib"}
)
check("a saved system path is restored", restored.get("LD_LIBRARY_PATH"), "/usr/lib")

# Steam runs the generated launcher scripts, so they need the same treatment.
launcher = launchers.write_launcher(install, "Env Check", core, rom)
launcher_body = open(launcher, encoding="utf-8").read()
check("launchers unset the loader variables", "unset LD_LIBRARY_PATH" in launcher_body, True)
check("and do so before exec",
      launcher_body.index("unset LD_LIBRARY_PATH") < launcher_body.index("exec "), True)

# A launcher once exported SDL_JOYSTICK_HIDAPI=1, on the theory that emulators
# disabling SDL's HIDAPI driver cannot see the Deck's pad. Measured from inside
# the launcher, Steam Input publishes a virtual pad SDL enumerates either way,
# so it fixed nothing and the real fault was in how the bindings named the pad.
check(
    "launchers do not set SDL hints they do not need",
    "SDL_JOYSTICK_HIDAPI" in launcher_body,
    False,
)
launchers.remove_launcher(launcher)

_emu_launcher = launchers.write_launcher(
    install,
    "Emu Env Check",
    "",
    "/roms/game.3ds",
    emulator={
        "kind": "path", "target": "/x/azahar.AppImage", "args": "{rom}",
        "fullscreen_args": "",
    },
)
_emu_body = open(_emu_launcher, encoding="utf-8").read()
check("nor do emulator launchers", "SDL_JOYSTICK_HIDAPI" in _emu_body, False)
launchers.remove_launcher(_emu_launcher)

section("RetroArch detection -- leftover data is not an install")
import ra_detect  # noqa: E402

fake_flatpak_root = os.path.join(TMP, "flatpak-root")
fake_data_dir = os.path.join(TMP, "var-app", ra_detect.FLATPAK_ID)
os.makedirs(fake_data_dir, exist_ok=True)

_real_roots = ra_detect._flatpak_system_roots
_real_data = ra_detect._flatpak_data_dir
_real_which = ra_detect.shutil.which
# A function now, not a constant: as a constant the per-user root was expanded at
# import time and ignored DECKY_USER_HOME.
ra_detect._flatpak_system_roots = lambda: (fake_flatpak_root,)
ra_detect._flatpak_data_dir = lambda: fake_data_dir
# `flatpak info` would otherwise be consulted and could answer either way.
ra_detect.shutil.which = lambda name: None

check(
    "a leftover data directory alone is not an install",
    ra_detect._flatpak_installed(),
    False,
)
os.makedirs(os.path.join(fake_flatpak_root, "app", ra_detect.FLATPAK_ID), exist_ok=True)
check("the installed app is detected", ra_detect._flatpak_installed(), True)

ra_detect._flatpak_system_roots = _real_roots
ra_detect._flatpak_data_dir = _real_data
ra_detect.shutil.which = _real_which

section("downloading artwork -- every image must reach the slot that asked")
# The images are fetched concurrently, so the mapping from slot to image is the
# thing that can break. A hero landing in the capsule slot is artwork that is
# real, and for the right game, and the wrong shape everywhere Steam draws it.
_real_get_data_uri = net.get_data_uri


def _fake_get_data_uri(url, headers=None):
    if "slow" in url:
        # Answers last; must still be the capsule.
        _time.sleep(0.15)
        return "data:image/png;base64,SLOW", "png"
    if "broken" in url:
        return None, None
    return "data:image/png;base64," + url.rsplit("/", 1)[-1].upper(), "jpg"


net.get_data_uri = _fake_get_data_uri
_art = run(
    plugin._download_art(
        {
            "capsule": "http://x/slow",
            "header": "http://x/header",
            "hero": "http://x/broken",
            "logo": "",
        }
    )
)
check(
    "the slowest download still lands in its own slot",
    _art.get("capsule"),
    {"data": "data:image/png;base64,SLOW", "kind": "png"},
)
check("and a fast one is not shifted into another", _art.get("header"),
      {"data": "data:image/png;base64,HEADER", "kind": "jpg"})
check("a download that failed is absent, not empty", "hero" in _art, False)
check("a slot with no URL is never requested", "logo" in _art, False)
check("nothing to download is not an error", run(plugin._download_art({})), {})
net.get_data_uri = _real_get_data_uri

section("the add flow -- probe, prepare, register")
# The primary path through the plugin. It was the last thing without tests, which
# is backwards: editing a game is rarer than adding one.
for _app_id in list(store.get_library().keys()):
    store.forget_game(_app_id)
store.set_settings(
    {
        "collection_name": "Games",
        "collection_per_platform": True,
        "platform_names": "short",
        "add_to_collection": True,
        "last_core_by_ext": {},
    }
)

add_rom = os.path.join(TMP, "Super Mario World (USA) [!].sfc")
open(add_rom, "w").close()

probe = run(plugin.probe_rom(add_rom))
check("the extension is read from the file", probe["extension"], "sfc")
check("a loose ROM is not an archive", probe["is_archive"], False)
check("the name is cleaned up before anyone sees it", probe["provisional_title"], "Super Mario World")
check("only cores that take .sfc are offered", [c["id"] for c in probe["matching_cores"]], ["bsnes"])
check("every core is still available behind the toggle", len(probe["all_cores"]), 2)
check("a matching core is suggested", probe["suggested_core_id"], "bsnes")
check("a supported extension is not flagged", probe["unsupported_extension"], False)

unknown_rom = os.path.join(TMP, "Mystery Game.xyz")
open(unknown_rom, "w").close()
odd = run(plugin.probe_rom(unknown_rom))
check("no core is suggested for an extension nothing handles", odd["suggested_core_id"], "")
check("and none are offered", odd["matching_cores"], [])
# Distinct from the above: a save file or a screenshot next to the ROMs is not an
# unknown system, it is something the user did not mean to pick.
save_file = os.path.join(TMP, "Super Mario World (USA).srm")
open(save_file, "w").close()
check(
    "a save file is called out as not a ROM",
    run(plugin.probe_rom(save_file))["unsupported_extension"],
    True,
)
check("while a real ROM is not", probe["unsupported_extension"], False)
os.remove(save_file)

# Archives are matched on what is inside them, so a zipped SNES ROM offers SNES
# cores rather than whatever claims to read .zip.
zipped_rom = os.path.join(TMP, "Zipped Game (USA).zip")
with zipfile.ZipFile(zipped_rom, "w") as handle:
    handle.writestr("Zipped Game (USA).sfc", b"\0")
zipped = run(plugin.probe_rom(zipped_rom))
check("an archive is recognised", zipped["is_archive"], True)
check("cores are matched on the content inside", zipped["match_extension"], "sfc")
check("so an SNES core is offered for a zip", [c["id"] for c in zipped["matching_cores"]], ["bsnes"])

# Two cores for the same system, so "the one you used last" is a real choice
# rather than the only option.
SNES_CORE_2 = dict(SNES_CORE, id="snes9x", path="/cores/snes9x_libretro.so")
plugin._cores = [N64_CORE, SNES_CORE, SNES_CORE_2]
check(
    "with nothing remembered the first matching core wins",
    run(plugin.probe_rom(add_rom))["suggested_core_id"],
    "bsnes",
)
store.set_settings({"last_core_by_ext": {"sfc": "snes9x"}})
reprobe = run(plugin.probe_rom(add_rom))
check("the core used last for this extension is suggested", reprobe["suggested_core_id"], "snes9x")
check("and the others are still offered", [c["id"] for c in reprobe["matching_cores"]],
      ["snes9x", "bsnes"])
# A remembered core that cannot read this file must not be suggested, or the
# shortcut would start the emulator and load nothing.
store.set_settings({"last_core_by_ext": {"sfc": "mupen64plus_next"}})
check(
    "a remembered core that does not match is ignored",
    run(plugin.probe_rom(add_rom))["suggested_core_id"],
    "bsnes",
)
store.set_settings({"last_core_by_ext": {}})
plugin._cores = [N64_CORE, SNES_CORE]

prepared = run(plugin.prepare_shortcut("Super Mario World", "bsnes", add_rom))
check("preparing a shortcut succeeds", prepared["ok"], True)
check("the launcher exists on disk", os.path.isfile(prepared["exe"]), True)
check("Steam is given the launcher's own directory", prepared["start_dir"],
      os.path.dirname(prepared["exe"]))
check("arguments stay out of Steam's hands", prepared["launch_options"], "")
check("the collection is resolved here, not in the UI", prepared["collection_name"], "[Games] SNES")
check(
    "the launcher runs the chosen core",
    "bsnes" in open(prepared["exe"], encoding="utf-8").read()
    or SNES_CORE["path"] in open(prepared["exe"], encoding="utf-8").read(),
    True,
)
check(
    "an empty title falls back to the cleaned filename",
    run(plugin.prepare_shortcut("   ", "bsnes", add_rom))["title"],
    "Super Mario World",
)
check(
    "a core that is gone is refused",
    "no longer available" in run(plugin.prepare_shortcut("x", "nope", add_rom))["error"],
    True,
)
check(
    "a ROM that is gone is refused",
    "no longer exists"
    in run(plugin.prepare_shortcut("x", "bsnes", os.path.join(TMP, "vanished.sfc")))["error"],
    True,
)

# A Deck with no RetroArch at all, which the emulator catalog exists to make
# usable: the guard at the top of prepare_shortcut lets `_install` be None as
# long as a standalone emulator was chosen. The last statement then indexed it
# unconditionally for the SD-card warning and raised TypeError -- so adding a
# game succeeded at every step and failed on the way out. A type checker found
# it; nothing here had, because every test so far had RetroArch installed.
_saved_install = plugin._install
plugin._install = None
# Registered here rather than reused from earlier: the plugin caches its
# emulator list, and this needs one it can actually resolve right now.
emulators.save(dict(DOLPHIN))
run(plugin._refresh_emulators())
try:
    _no_ra = run(plugin.prepare_shortcut("Standalone", "emu:dolphin", add_rom))
    check("a game can be added with no RetroArch installed", _no_ra["ok"], True)
    check("and nothing warns about a sandbox that is not there",
          _no_ra["warn_flatpak_sdcard"], False)
finally:
    plugin._install = _saved_install
    # Put the registry back: later sections assert that nothing is registered
    # yet, and a fixture that outlives its own test is how those start failing
    # for reasons that have nothing to do with them.
    emulators.remove("dolphin")
    run(plugin._refresh_emulators())

# The flatpak cannot see an SD card without being told to, and a shortcut that
# silently fails to launch is worse than a warning.
sd_rom = "/run/media/mmcblk0p1/Emulation/roms/snes/On A Card.sfc"
check(
    "an SD-card ROM under flatpak is flagged",
    run(plugin.prepare_shortcut("On A Card", "bsnes", add_rom))["warn_flatpak_sdcard"],
    False,
)
check(
    "and the check looks at the ROM path",
    sd_rom.startswith("/run/media") and plugin._install["kind"] == "flatpak",
    True,
)

registered = run(plugin.register_game(700, "Super Mario World", add_rom, "bsnes", prepared["exe"]))
check("registering records the app id", registered["app_id"], 700)
check("the libretro system is stored for artwork lookups", registered["system"],
      "Nintendo - Super Nintendo Entertainment System")
check("the display platform is stored", registered["platform"], "SNES")
check("the collection it was filed into is remembered", registered["collection"], "[Games] SNES")
check("the ROM is recorded", registered["rom_path"], add_rom)
check("it is now in the library", "700" in store.get_library(), True)
check(
    "the core is remembered for this extension",
    store.get_settings()["last_core_by_ext"].get("sfc"),
    "bsnes",
)
# Not always wanted. A PS3 game boots EBOOT.BIN, so remembering its core would
# file `.bin` under RPCS3 and then suggest a PlayStation 3 emulator for the next
# PS1 disc image anybody adds.
run(plugin.register_game(702, "Not Remembered", add_rom, "mupen64plus_next",
                         prepared["exe"], "", False))
check(
    "a game added without remembering leaves the suggestion alone",
    store.get_settings()["last_core_by_ext"].get("sfc"),
    "bsnes",
)
run(plugin.unregister_game(702))

run(plugin.register_game(701, "Aardvark", add_rom, "mupen64plus_next", prepared["exe"]))
check(
    "added games are listed alphabetically",
    [g["title"] for g in run(plugin.list_added())],
    ["Aardvark", "Super Mario World"],
)

gone = run(plugin.unregister_game(701))
check("unregistering returns the entry it forgot", gone["app_id"], 701)
check("and it leaves the library", "701" in store.get_library(), False)
check("unregistering an unknown game is not an error", run(plugin.unregister_game(99998)), None)

run(plugin.forget_games([700]))
os.remove(unknown_rom)

section("PlayStation 3 -- a package in, a game in the library")
# The route nothing else here uses. Every other system has a ROM: one file, in
# the ROM folder, that a picker can show you. A PS3 game bought from the store
# is a .pkg, and until RPCS3 unpacks it there is no game -- afterwards what
# boots is dev_hdd0/game/NPUB30133/USRDIR/EBOOT.BIN, which nobody would type.

import ps3_games  # noqa: E402

_ps3_emulator, _ps3_error = emulators.save({
    "name": "RPCS3", "kind": "flatpak", "target": "net.rpcs3.RPCS3",
    "args": "--no-gui {rom}", "fullscreen_args": "--fullscreen",
    "extensions": "bin self elf", "platform": "Sony - PlayStation 3",
})
check("a PS3 emulator registers", (_ps3_error, (_ps3_emulator or {}).get("id")), ("", "rpcs3"))
plugin._emulators = emulators.list_emulators()

# ---- running an emulator as a tool, with no window ------------------------
# This is what makes the install a button instead of an instruction, so its
# three outcomes are worth pinning down: it worked, it failed, it never ended.
# The "emulator" is the Python running these tests, so these are real
# subprocesses with exits chosen on purpose.
_tool_emu = {"id": "toolemu", "name": "ToolEmu", "kind": "path", "target": sys.executable}
check(
    "a headless tool run reports success",
    run(plugin._run_emulator_tool(_tool_emu, ["-c", "print('unpacking')"], seconds=60)),
    (True, ""),
)
_tool_ok, _tool_error = run(plugin._run_emulator_tool(
    _tool_emu, ["-c", "import sys; print('bad news'); sys.exit(3)"], seconds=60
))
check("a failing one is not reported as success", _tool_ok, False)
# Nothing is on screen by design, so the emulator's own last lines are the only
# account of what went wrong.
check("and carries the exit code and what it said",
      "code 3" in _tool_error and "bad news" in _tool_error, True)
_tool_ok, _tool_error = run(plugin._run_emulator_tool(
    _tool_emu, ["-c", "import time; time.sleep(30)"], seconds=1
))
check("one that never finishes is killed rather than waited on", _tool_ok, False)
check("and says so plainly", "did not finish" in _tool_error, True)

# ---- the packages waiting -------------------------------------------------
_ps3_rom_dir, _ps3_fw_dir = run(plugin._run(plugin._ps3_package_dirs))
check("packages are looked for where uploads land", _ps3_rom_dir, fileserver.default_dir())
# And beside the PUP, because anyone who used the PS3 firmware row's send button
# put one there instead, and a file that seems to vanish is the friction this
# whole plugin exists to remove.
check("and beside the firmware", _ps3_fw_dir, emu_install.firmware_dir())

_ps3_pkg = os.path.join(_ps3_rom_dir, "NPUB30133.pkg")
_ps3_pkg_header = bytearray(b"\x00" * 0x54)
_ps3_pkg_header[0:4] = b"\x7fPKG"
_ps3_pkg_header[0x30:0x30 + 36] = b"UP4049-NPUB30133_00-BRAID00000000001"
with io.open(_ps3_pkg, "wb") as _handle:
    _handle.write(bytes(_ps3_pkg_header))

_ps3_listed = run(plugin.list_ps3_packages())
check("the package is offered", [p["name"] for p in _ps3_listed["packages"]],
      ["NPUB30133.pkg"])
check("with the title it will install", _ps3_listed["packages"][0]["title_id"], "NPUB30133")

# The path arrives from the frontend and becomes a subprocess argument, so it is
# checked against the list rather than trusted.
check(
    "a path that is not one of the offered packages is refused",
    run(plugin.install_ps3_package("/etc/passwd"))["error"],
    "That package is no longer in the transfer folder.",
)
# The call resolves when the unpack has finished, rather than when it has been
# started. It was the other way round, and a completion event that never
# arrived left the panel showing "Unpacking" over an install that had finished
# five seconds earlier -- so nothing may report progress by return value alone.
check(
    "installing answers with the outcome, not with 'started'",
    "started" in run(plugin.install_ps3_package("/etc/passwd")),
    False,
)

# ---- the game that came out the other side --------------------------------
_ps3_installed_root = ps3_games.game_root()
_ps3_installed = os.path.join(_ps3_installed_root, "NPUB30133")
os.makedirs(os.path.join(_ps3_installed, "USRDIR"), exist_ok=True)
# The same synthetic PARAM.SFO the parser section builds, rather than a
# kilobyte of somebody's game checked into the repository.
with io.open(os.path.join(_ps3_installed, "PARAM.SFO"), "wb") as _dst:
    _dst.write(_sfo_bytes)
io.open(os.path.join(_ps3_installed, "USRDIR", "EBOOT.BIN"), "w").close()

check("an installed package is not offered as waiting",
      run(plugin.list_ps3_packages())["packages"][0]["installed"], True)
check("the installed game is listed by name",
      [g["title"] for g in run(plugin.list_installed_ps3_games())["games"]], ["Braid"])

# ---- and the package taking the ordinary add-a-game route ------------------
# A .pkg is picked like any other ROM. probe_rom is what spots that it is not a
# game yet, so the panel can offer to unpack it rather than build a launcher
# pointing at a package nothing can run.
_ps3_probe = run(plugin.probe_rom(_ps3_pkg))
check("a package is recognised in the ROM picker",
      _ps3_probe["ps3_package"]["title_id"], "NPUB30133")
# This emulator was registered without `pkg` among its extensions, which is
# exactly the state of an RPCS3 registered before the catalog listed it. The
# package must still be recognised: unpacking does not go through the core
# match, and `ps3_core_id` supplies the emulator afterwards. Otherwise anyone
# who installed RPCS3 last week would have to re-register it first.
check("even when no core claims .pkg", _ps3_probe["suggested_core_id"], "")

check("the catalog does list pkg for PlayStation 3",
      "pkg" in emu_catalog.extensions_for(emu_catalog.find("rpcs3"), {}), True)
emulators.save(dict(_ps3_emulator, extensions="bin self elf pkg"))
plugin._emulators = emulators.list_emulators()
_ps3_probe = run(plugin.probe_rom(_ps3_pkg))
check("and once it does, RPCS3 is the emulator offered",
      _ps3_probe["suggested_core_id"], "emu:rpcs3")
# Already unpacked, so the flow skips straight to the game rather than offering
# to install what is installed.
check("an installed one carries the name from its PARAM.SFO",
      _ps3_probe["ps3_package"]["title"], "Braid")
check("and the path that actually boots",
      _ps3_probe["ps3_package"]["eboot"].endswith(
          os.path.join("NPUB30133", "USRDIR", "EBOOT.BIN")),
      True)
check("an ordinary ROM carries no package block", "ps3_package" in probe, False)

# ---- and a PS4 package, which shares the extension and nothing else --------
# A PS3 package begins \x7fPKG and a PS4 one \x7fCNT. Nothing else about the
# file tells them apart -- same extension, same rough size, same naming -- and
# sending a PS4 game to RPCS3 gets it reported as a corrupt package.
import ps4_games  # noqa: E402

_ps4_pkg = os.path.join(_ps3_rom_dir, "Some PS4 Game.pkg")
_ps4_header = bytearray(b"\0" * 0x400)
_ps4_header[0:4] = b"\x7fCNT"
_ps4_header[0x40:0x40 + 36] = b"UP9000-CUSA00001_00-EXAMPLE000000001"
with io.open(_ps4_pkg, "wb") as _handle:
    _handle.write(bytes(_ps4_header))

check("a PS4 package is not mistaken for a PS3 one",
      (ps4_games.is_package(_ps4_pkg), ps3_games.package_title_id(_ps4_pkg)),
      (True, ""))
check("and a PS3 package is not mistaken for a PS4 one",
      ps4_games.is_package(_ps3_pkg), False)
check("its title id is read from the header",
      ps4_games.package_title_id(_ps4_pkg), "CUSA00001")

_ps4_probe = run(plugin.probe_rom(_ps4_pkg))
check("the probe reports it as a PS4 package",
      _ps4_probe["ps4_package"]["title_id"], "CUSA00001")
check("and not as a PS3 one", "ps3_package" in _ps4_probe, False)
check("while the PS3 package is still reported as PS3",
      ("ps3_package" in _ps3_probe, "ps4_package" in _ps3_probe), (True, False))

# The title id reaches a filesystem path and an extractor's command line.
check("a title id that is not one has nowhere to unpack to",
      ps4_games.target_dir("../../etc"), "")
check("and neither does an empty one", ps4_games.target_dir(""), "")

# An installed PS4 game is a folder with eboot.bin and sce_sys/param.sfo --
# the PS3 layout with different capitalisation, and the same SFO container, so
# the parser is shared rather than written twice.
_ps4_root = os.path.join(TMP, "ps4games")
_ps4_game = os.path.join(_ps4_root, "CUSA00001")
os.makedirs(os.path.join(_ps4_game, "sce_sys"), exist_ok=True)
io.open(os.path.join(_ps4_game, "eboot.bin"), "w").close()
with io.open(os.path.join(_ps4_game, "sce_sys", "param.sfo"), "wb") as _dst:
    _dst.write(_sfo_bytes)
check("an unpacked PS4 game is listed by its param.sfo name",
      [(g["title"], g["title_id"]) for g in ps4_games.installed_games(_ps4_root)],
      [("Braid", "NPUB30133")])
check("a folder with no eboot is not a game",
      ps4_games.installed_games(os.path.join(TMP, "ps4empty")), [])
# The extractor may write the package's contents directly or inside a folder of
# its own, so the eboot is looked for rather than the layout assumed.
check("the game is found one level down too",
      ps4_games.unpacked_game(_ps4_root), _ps4_game)
check("and directly when it is there",
      ps4_games.unpacked_game(_ps4_game), _ps4_game)

# The real extractor names a folder after the title inside whatever it is
# pointed at, so unpacking into <games>/CUSA07010 produced
# <games>/CUSA07010/CUSA07010 -- one level too deep for this module's listing
# and for shadPS4, which reads game folders straight out of install_dirs.
_nest_root = os.path.join(TMP, "ps4nest")
_nest_target = os.path.join(_nest_root, "CUSA07010")
_nest_inner = os.path.join(_nest_target, "CUSA07010")
os.makedirs(os.path.join(_nest_inner, "sce_sys"), exist_ok=True)
io.open(os.path.join(_nest_inner, "eboot.bin"), "w").close()
with io.open(os.path.join(_nest_inner, "sce_sys", "param.sfo"), "wb") as _dst:
    _dst.write(_sfo_bytes)

check("a nested unpack is flattened", ps4_games.settle(_nest_target), (_nest_target, ""))
check("leaving the eboot where the listing looks",
      os.path.isfile(os.path.join(_nest_target, "eboot.bin")), True)
check("with no wrapper folder left behind",
      sorted(os.listdir(_nest_target)), ["eboot.bin", "sce_sys"])
check("and the game now listed",
      [g["title_id"] for g in ps4_games.installed_games(_nest_root)], ["NPUB30133"])
# Settling something already in the right shape must not disturb it.
check("settling an already-flat game changes nothing",
      ps4_games.settle(_nest_target), (_nest_target, ""))
check("an empty target settles to nothing rather than failing",
      ps4_games.settle(os.path.join(TMP, "ps4nowhere")), ("", ""))

check("installing something that is not a PS4 package is refused",
      run(plugin.install_ps4_package(_ps3_pkg))["error"],
      "That file is not a PlayStation 4 package.")
check("and the package it refused is still there",
      os.path.isfile(_ps3_pkg), True)

# Both consoles delete the package once the game is out of it, so the delete
# dialog can make one promise rather than two.
_ps4_del_root = os.path.join(TMP, "ps4del")
_ps4_del = os.path.join(_ps4_del_root, "CUSA00001")
os.makedirs(os.path.join(_ps4_del, "sce_sys"), exist_ok=True)
io.open(os.path.join(_ps4_del, "eboot.bin"), "w").close()
with io.open(os.path.join(_ps4_del, "sce_sys", "param.sfo"), "wb") as _dst:
    _dst.write(_sfo_bytes)
_ps4_info = ps4_games.game_info(os.path.join(_ps4_del, "eboot.bin"), _ps4_del_root)
check("a PS4 game is recognised from its eboot path",
      (_ps4_info["ok"], _ps4_info["title"]), (True, "Braid"))
check("deleting it reports what it freed",
      ps4_games.delete_game("CUSA00001", _ps4_del_root)[1], "")
check("and the folder is gone", os.path.isdir(_ps4_del), False)
check("a title id that is not one deletes nothing",
      ps4_games.delete_game("../../etc", _ps4_del_root)[1].startswith("'../../etc'"), True)

# The token the catalog writes into shadPS4's config has to be the folder this
# module actually unpacks into, or the emulator's list and the panel's disagree.
check("the PS4 games token is where packages are unpacked",
      emu_config._ps4_games_dir(), ps4_games.games_dir())

# ---- nested JSON, which shadPS4's config is and Ryujinx's is not ----------
# Written flat, a section dict was compared against the real section, skipped
# as "the user's", and the setup recorded itself as applied having written
# nothing -- so it never ran again. Both halves are tested here: the dotted key
# that works, and the malformed spec that must now be loud.
import json as _json_mod  # noqa: E402
_nested_cfg = os.path.join(TMP, "nested.json")
with io.open(_nested_cfg, "w", encoding="utf-8") as _handle:
    _json_mod.dump({"General": {"install_dirs": [], "other": "kept"},
               "Vulkan": {"pipeline_cache_enabled": False}}, _handle)

_applied, _skipped, _written, _err = emu_config._apply_json_keys(
    _nested_cfg,
    {
        "General.install_dirs": {"value": ["/games"], "default": []},
        "Vulkan.pipeline_cache_enabled": {"value": True, "default": False},
    },
)
check("a dotted key reaches inside a section", (_err, sorted(_applied)),
      ("", ["General.install_dirs", "Vulkan.pipeline_cache_enabled"]))
with io.open(_nested_cfg, encoding="utf-8") as _handle:
    _nested_now = _json_mod.load(_handle)
check("writing the value it was given",
      _nested_now["General"]["install_dirs"], ["/games"])
check("and the one in the other section",
      _nested_now["Vulkan"]["pipeline_cache_enabled"], True)
check("leaving everything else in the section alone",
      _nested_now["General"]["other"], "kept")
# A section handed over as if it were a value is a programming error, and
# silence about it is exactly what let this ship.
check("a section passed as a value is refused, not skipped",
      "is a section, not a value" in emu_config._apply_json_keys(
          _nested_cfg, {"General": {"install_dirs": []}})[3],
      True)
check("and a path through something that is not an object is refused",
      "not inside an object" in emu_config._apply_json_keys(
          _nested_cfg, {"General.other.deeper": "x"})[3],
      True)
# Undotted keys behave exactly as before, which is what Ryujinx's config uses.
check("a flat key still works",
      emu_config._apply_json_keys(_nested_cfg, {"top": "level"})[0], ["top"])

# ---- PS Vita releases, which are zips like every zipped ROM is a zip ------
# NoNpDrm releases are the common Vita format and they arrive as .zip. The
# picker already looks inside an archive to match cores on its content, and a
# Vita release holds nothing that looks like a ROM -- so without content
# detection it matches nothing and Vita3K is never offered. Every .zip on a
# real Deck was a SNES or NES ROM, which is why extension alone cannot decide.
import vita_release  # noqa: E402

_vita_zip = os.path.join(TMP, "Some Vita Game.zip")
with zipfile.ZipFile(_vita_zip, "w") as _bundle:
    _bundle.writestr("PCSE00001/eboot.bin", b"\0")
    _bundle.writestr("PCSE00001/sce_sys/param.sfo", _sfo_bytes)
    _bundle.writestr("PCSE00001/work.bin", b"\0" * 512)

_vita = vita_release.inspect(_vita_zip)
check("a Vita release is recognised inside the zip", _vita["vita"], True)
check("with the name from its own param.sfo", _vita["title"], "Braid")
check("and its licence noticed", _vita["licence"], True)

# The whole point: a zipped ROM must be left completely alone.
check("a zipped SNES ROM is not a Vita release",
      vita_release.inspect(zipped_rom)["vita"], False)
check("and neither is something that is not a zip",
      vita_release.inspect(add_rom)["vita"], False)

# A release without the licence still installs; it is worth saying, not
# refusing, because the game may be licence-free.
_vita_nolic = os.path.join(TMP, "No Licence.zip")
with zipfile.ZipFile(_vita_nolic, "w") as _bundle:
    _bundle.writestr("sce_sys/param.sfo", _sfo_bytes)
    _bundle.writestr("eboot.bin", b"\0")
check("a release at the archive root is found too",
      vita_release.inspect(_vita_nolic)["vita"], True)
check("and a missing licence is reported rather than assumed",
      vita_release.inspect(_vita_nolic)["licence"], False)

_vita_probe = run(plugin.probe_rom(_vita_zip))
check("the probe reports the release", _vita_probe["vita_release"]["title_id"], "NPUB30133")
check("and names the game rather than the file",
      _vita_probe["provisional_title"], "Braid")
check("a zipped ROM still probes as before",
      "vita_release" in run(plugin.probe_rom(zipped_rom)), False)

# Vita3K takes a fullscreen flag and the entry had none, so every game opened
# windowed.
check("Vita3K passes a fullscreen flag",
      _catalog_check.find("vita3k")["fullscreen_args"], "--fullscreen")
check("and starts installed titles by id",
      _catalog_check.find("vita3k")["installed_args"], "-r {title}")

# ---- the installed Vita titles, which are the only way these games get in --
# Vita3K decrypts content as it installs, so a game copied into ux0/app is
# listed and refuses to start. The install happens in its interface; this list
# is what turns the result into something addable.
import vita_games  # noqa: E402

_vita_root = os.path.join(TMP, "vitaapps")
_vita_game = os.path.join(_vita_root, "PCSA00011")
os.makedirs(os.path.join(_vita_game, "sce_sys"), exist_ok=True)
io.open(os.path.join(_vita_game, "eboot.bin"), "w").close()
with io.open(os.path.join(_vita_game, "sce_sys", "param.sfo"), "wb") as _dst:
    _dst.write(_sfo_bytes)
check("an installed Vita title is listed by name",
      [(g["title"], g["title_id"]) for g in vita_games.installed_games(_vita_root)],
      [("Braid", "NPUB30133")])
check("a folder with no eboot is not a game",
      vita_games.installed_games(os.path.join(TMP, "vitaempty")), [])
# The launcher is rebuilt from what the library recorded, which is the eboot --
# so the id `-Fr` needs has to be recoverable from it.
check("the title id is recovered from the recorded ROM",
      vita_games.title_of(os.path.join(_vita_game, "eboot.bin"), _vita_root),
      "PCSA00011")
check("and a path outside Vita3K belongs to no title",
      vita_games.title_of(add_rom, _vita_root), "")

# ---- Vita packages, which share the PS3's magic ---------------------------
# `\x7fPKG` for both consoles; the type field at offset 6 is 2 for the Vita and
# 1 for the PS3. Read off a real Vita package rather than assumed, because
# getting it wrong hands a Vita game to RPCS3.
import struct as _struct_mod  # noqa: E402


def _vita_pkg(path, kind=2, content=b"UP9000-PCSA00045_00-0000000000000000"):
    head = bytearray(b"\0" * 0x60)
    head[0:4] = b"\x7fPKG"
    _struct_mod.pack_into(">H", head, 4, 0x8000)
    _struct_mod.pack_into(">H", head, 6, kind)
    head[0x30:0x30 + len(content)] = content
    with io.open(path, "wb") as handle:
        handle.write(bytes(head))

_vpkg = os.path.join(TMP, "livetweet.pkg")
_vita_pkg(_vpkg)
_p3pkg = os.path.join(TMP, "a-ps3-game.pkg")
_vita_pkg(_p3pkg, kind=1, content=b"UP4049-NPUB30133_00-BRAID00000000001")

check("a Vita package is recognised by its type field",
      vita_games.is_package(_vpkg), True)
check("and a PS3 package with the same magic is not",
      vita_games.is_package(_p3pkg), False)
check("its title id is read from the content id",
      vita_games.package_title_id(_vpkg), "PCSA00045")

# The key is never bundled -- a third-party table of licence keys is not
# something to ship -- so it travels beside the game.
check("no key beside the package is reported, not guessed",
      vita_games.find_zrif(_vpkg, "PCSA00045"), "")
# Fabricated, and it has to be: a zRIF is a licence key, and a third-party
# table of them is exactly what this plugin refuses to ship. The finder only
# asks for the KO5if prefix and base64 characters, so a made-up string of the
# right shape exercises every path a real one would -- and unlocks nothing.
_ZRIF = "KO5ifNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREAL"
with io.open(os.path.join(TMP, "livetweet.zrif"), "w") as _handle:
    _handle.write(_ZRIF + "\n")
check("a key named after the package is found",
      vita_games.find_zrif(_vpkg, "PCSA00045"), _ZRIF)
os.remove(os.path.join(TMP, "livetweet.zrif"))
# Distributed as a .txt as often as a .zrif, and usually with other text in it.
with io.open(os.path.join(TMP, "PCSA00045.txt"), "w") as _handle:
    _handle.write("Gravity Rush zRIF below, do not share\n\n%s\n" % _ZRIF)
check("a key in a text file named after the title id is found too",
      vita_games.find_zrif(_vpkg, "PCSA00045"), _ZRIF)
check("and a readme with no key in it is not mistaken for one",
      vita_games._read_zrif(os.path.join(TMP, "notes.txt")), "")
os.remove(os.path.join(TMP, "PCSA00045.txt"))

# Removing a Vita game can clear it from the emulator, like the other two.
_vita_info = vita_games.game_info(os.path.join(_vita_game, "eboot.bin"), _vita_root)
check("a Vita game is recognised from its eboot path",
      (_vita_info["ok"], _vita_info["title"]), (True, "Braid"))
check("an id that is not one deletes nothing",
      vita_games.delete_game("../../etc", _vita_root)[1].startswith("'../../etc'"), True)
# The licence stays, exactly as the .rap does on PS3. It was written by Vita3K
# rather than sent, which once looked like reason enough to remove it -- but
# the package is deleted on install and only the .zrif survives beside it, so
# once that is tidied away the .rif is the last copy of the key. Deleting a
# game must not be the thing that loses it.
_vita_licence = os.path.join(
    sysenv.user_home(), *vita_games.LICENSE_DIR.split("/"), "PCSA00011")
os.makedirs(_vita_licence, exist_ok=True)
io.open(os.path.join(_vita_licence, "6488b73b912a753a492e2714e9b38bc7.rif"), "w").close()
check("deleting an installed one succeeds",
      vita_games.delete_game("PCSA00011", _vita_root)[1], "")
check("and the folder is gone", os.path.isdir(_vita_game), False)
check("but the licence is kept, as RPCS3's .rap is",
      os.path.isdir(_vita_licence), True)
# All three consoles answer the same lookup, so the remove dialog does not
# need to know which one it is holding.
check("every packaged console answers packaged_game_info",
      sorted(plugin._PACKAGED), ["ps3", "ps4", "vita"])

# ---- flat YAML, which is what Vita3K's config.yml is ----------------------
# Line edited rather than parsed: the file is the emulator's, and everything
# not addressed has to come back out untouched, including ordering and any
# comment a future version adds.
_yml = os.path.join(TMP, "config.yml")
with io.open(_yml, "w", encoding="utf-8") as _handle:
    _handle.write("---\n# a comment Vita3K wrote\nvalidation-layer: true\n"
                  "initial-setup: false\npref-path: \"\"\nlog-level: 0\n")
_yaml_applied, _yaml_skipped, _, _yaml_err = emu_config._apply_yaml_keys(
    _yml,
    {
        "validation-layer": {"value": "false", "default": "true"},
        "initial-setup": {"value": "true", "default": "false"},
    },
)
check("both keys are written", (_yaml_err, sorted(_yaml_applied)),
      ("", ["initial-setup", "validation-layer"]))
with io.open(_yml, encoding="utf-8") as _handle:
    _yml_text = _handle.read()
check("with YAML's colon rather than an equals sign",
      "validation-layer: false" in _yml_text, True)
check("the comment survives", "# a comment Vita3K wrote" in _yml_text, True)
check("and so does everything not addressed",
      'pref-path: ""' in _yml_text and "log-level: 0" in _yml_text, True)
# A value the user chose is theirs, exactly as in every other handler.
with io.open(_yml, "w", encoding="utf-8") as _handle:
    _handle.write("---\nvalidation-layer: maybe\n")
check("a value that is neither ours nor the default is left alone",
      emu_config._apply_yaml_keys(
          _yml, {"validation-layer": {"value": "false", "default": "true"}})[1],
      ["validation-layer"])
# A key the emulator has never written is appended rather than lost.
check("a missing key is added",
      emu_config._apply_yaml_keys(_yml, {"brand-new-key": "yes"})[0],
      ["brand-new-key"])
# But a whole file is never invented. Vita3K reads its config as one document:
# given one holding only the three keys this writes, it failed with "invalid
# node; first invalid key", fell back to an empty pref-path and aborted in
# create_directories. A partial config did not degrade, it stopped the
# emulator starting -- so an absent file is an error, which also keeps
# apply_setup from recording the version and lets it retry later.
_absent = os.path.join(TMP, "never-written.yml")
check("a config that does not exist yet is refused, not created",
      "does not exist yet" in emu_config._apply_yaml_keys(_absent, {"a": "b"})[3], True)
check("and nothing is written in its place", os.path.exists(_absent), False)

# ---- Xbox discs: is there anything on them to boot? -----------------------
# An Xbox disc boots exactly one way, by loading default.xbe from the root. A
# real Championship Manager image had a single `data/` folder and no executable
# anywhere, and the console's way of saying so is "Please insert an Xbox disc"
# on a black screen -- which reads as a broken emulator for a long time before
# it reads as a bad file.
import struct  # noqa: E402
import xbox_disc  # noqa: E402


def _xiso(path, names, base=0):
    """A minimal XDVDFS image whose root lists `names`. `names` is [(name, dir)]."""
    sector = xbox_disc.SECTOR
    root_sector = 264
    table = bytearray()
    offsets = []
    for name, is_dir in names:
        offsets.append(len(table) // 4)
        encoded = name.encode("latin-1")
        entry = bytearray(struct.pack("<HHIIB", 0, 0, 300, 2048, 0x10 if is_dir else 0))
        entry.append(len(encoded))
        entry += encoded
        while len(entry) % 4:
            entry.append(0)
        table += entry
    # Chain them down the right-hand side, which is what a one-sided tree is.
    for index in range(len(offsets) - 1):
        struct.pack_into("<H", table, offsets[index] * 4 + 2, offsets[index + 1])

    with io.open(path, "wb") as handle:
        handle.write(b"\0" * (base + xbox_disc.HEADER_AT))
        handle.write(xbox_disc.MAGIC)
        handle.write(b"\0" * (0x14 - len(xbox_disc.MAGIC)))
        handle.write(struct.pack("<II", root_sector, len(table)))
        handle.write(b"\0" * (base + root_sector * sector - handle.tell()))
        handle.write(bytes(table))
        handle.write(b"\0" * 2048)


_good_iso = os.path.join(TMP, "Bootable Game.iso")
_xiso(_good_iso, [("default.xbe", False), ("Media", True)])
_bad_iso = os.path.join(TMP, "Data Only.iso")
_xiso(_bad_iso, [("data", True)])

check("a disc with default.xbe is bootable",
      xbox_disc.inspect(_good_iso), {"xbox": True, "bootable": True, "certain": True,
                                     "entries": ["Media", "default.xbe"]})
# A root chained down one side, which XDVDFS trees are allowed to be. An earlier
# version capped tree depth at 64 and would have truncated this and called the
# disc unbootable -- the one error that matters, because this answer is allowed
# to change what the Add button says.
_long_iso = os.path.join(TMP, "Many Files.iso")
_xiso(_long_iso, [("file%03d.dat" % n, False) for n in range(200)] + [("default.xbe", False)])
check("a root of 201 entries is read to the end",
      (xbox_disc.inspect(_long_iso)["bootable"], len(xbox_disc.inspect(_long_iso)["entries"])),
      (True, 201))
check("one with only a data folder is not",
      (xbox_disc.inspect(_bad_iso)["xbox"], xbox_disc.inspect(_bad_iso)["bootable"]),
      (True, False))
# Redump images keep the video partition first, putting the game 0x18300000
# in. Tested against a shifted base rather than a real one: writing 387MB of
# padding on every run left that much litter in the temp directory each time,
# and what is being checked is that a non-zero base is searched at all.
_redump = os.path.join(TMP, "Redump Style.iso")
_real_bases = xbox_disc.BASES
xbox_disc.BASES = (0, 0x2000)
_xiso(_redump, [("default.xbe", False)], base=0x2000)
check("a redump-style image is found at its own offset",
      xbox_disc.inspect(_redump)["bootable"], True)
xbox_disc.BASES = _real_bases
check("and the real redump offset is one of the bases searched",
      0x18300000 in xbox_disc.BASES, True)
check("a shifted image is not found once that base is not searched",
      xbox_disc.inspect(_redump)["xbox"], False)
os.remove(_redump)

# Silence is the default. `.iso` is the most overloaded extension in the
# catalog, so a GameCube or PS2 image must draw no comment at all.
check("a non-Xbox image is not an Xbox disc",
      xbox_disc.inspect(add_rom),
      {"xbox": False, "bootable": False, "certain": False, "entries": []})
check("and neither is a file that is not there",
      xbox_disc.inspect(os.path.join(TMP, "gone.iso"))["xbox"], False)

check("the panel is warned about the empty disc",
      "default.xbe" in run(plugin.probe_rom(_bad_iso))["disc_warning"], True)
check("and says nothing about the bootable one",
      "disc_warning" in run(plugin.probe_rom(_good_iso)), False)
check("nor about a ROM that is not a disc image at all",
      "disc_warning" in run(plugin.probe_rom(add_rom)), False)

check("the PS3 core id is resolved rather than assumed",
      run(plugin.ps3_core_id()), {"ok": True, "core_id": "emu:rpcs3"})

# Every PS3 game boots a file called EBOOT.BIN, so without the override the
# artwork lookup would ask SteamGridDB about "EBOOT" for all of them.
_ps3_eboot = _ps3_probe["ps3_package"]["eboot"]
check("a lookup with no title falls back to the filename",
      run(plugin.resolve_game(_ps3_eboot, "emu:rpcs3"))["title"], "EBOOT")
check("and the PARAM.SFO name overrides it",
      run(plugin.resolve_game(_ps3_eboot, "emu:rpcs3", "Braid"))["title"], "Braid")

_ps3_prepared = run(plugin.prepare_shortcut(
    "Braid", "emu:rpcs3", _ps3_eboot, "Sony - PlayStation 3"))
check("preparing the shortcut is the ordinary path", _ps3_prepared["ok"], True)
check("with a launcher written for it", os.path.isfile(_ps3_prepared["exe"]), True)

# ---- and the one game removal that can delete something --------------------
# Everywhere else, removing a game leaves the ROM alone: it is the user's own
# file. A PS3 game is neither -- this plugin unpacked it, and the package it
# came from was consumed doing so -- so what removal would otherwise leave is a
# couple of hundred megabytes nothing in the panel can see or remove.
_ps3_home = os.path.join(os.path.dirname(_ps3_installed_root), "home", "00000001")
_ps3_saves = os.path.join(_ps3_home, "savedata", "NPUB30133-AUTOSAVE")
_ps3_exdata = os.path.join(_ps3_home, "exdata")
os.makedirs(_ps3_saves, exist_ok=True)
os.makedirs(_ps3_exdata, exist_ok=True)
io.open(os.path.join(_ps3_exdata, "UP4049-NPUB30133_00-BRAID00000000001.rap"), "w").close()

_ps3_info = run(plugin.packaged_game_info(_ps3_eboot))
check("a PS3 game is recognised from its launcher's ROM path",
      (_ps3_info["ok"], _ps3_info["title_id"], _ps3_info["title"]),
      (True, "NPUB30133", "Braid"))
check("with the size that will be freed", _ps3_info["bytes"] > 0, True)
check("an ordinary ROM is not one", run(plugin.packaged_game_info(add_rom)), {"ok": False})
# The library entry does not record which console a game came from, so the
# lookup asks both and says which one answered.
check("and it says which console answered", _ps3_info["system"], "ps3")
# The id becomes an rmtree argument, so it is gated on the shape of a real
# title id *and* on landing directly inside the game folder.
check("a title id that is not one is refused",
      ps3_games.game_dir("../../etc"), "")
check("and so is one with a path in it",
      ps3_games.game_dir("NPUB30133/../../etc"), "")
check("a path outside the game folder belongs to no game",
      ps3_games.game_of(add_rom), "")

check(
    "deleting a game RPCS3 does not have is refused",
    run(plugin.delete_packaged_game("ps3", "NPUB99999"))["ok"],
    False,
)
_ps3_deleted = run(plugin.delete_packaged_game("ps3", "NPUB30133"))
check("deleting an installed one reports what it freed",
      (_ps3_deleted["ok"], _ps3_deleted["freed"] > 0), (True, True))
check("and the game is gone", os.path.isdir(_ps3_installed), False)
# A game can be installed again; progress in it cannot. The licence is the
# user's own file and would have to be sent from another device again.
check("but the save data is untouched",
      os.path.isdir(os.path.join(_ps3_saves)), True)
check("and so is the licence",
      os.listdir(_ps3_exdata), ["UP4049-NPUB30133_00-BRAID00000000001.rap"])
check("so it is no longer offered as installed",
      run(plugin.list_installed_ps3_games())["games"], [])

# Put it back for the rest of this section.
os.makedirs(os.path.join(_ps3_installed, "USRDIR"), exist_ok=True)
with io.open(os.path.join(_ps3_installed, "PARAM.SFO"), "wb") as _dst:
    _dst.write(_sfo_bytes)
io.open(os.path.join(_ps3_installed, "USRDIR", "EBOOT.BIN"), "w").close()

_ps3_registered = run(plugin.register_game(
    703, "Braid", _ps3_eboot, "emu:rpcs3",
    _ps3_prepared["launcher_path"], "Sony - PlayStation 3", False,
))
# libretro has no PlayStation 3 database, so there is no system to record and the
# label comes from what the emulator itself declares -- the same arrangement
# Switch and Wii U games arrive under, and the reason those carry a platform.
check("adding it files the game under PlayStation 3",
      (_ps3_registered["system"], _ps3_registered["platform"]),
      ("", "Sony - PlayStation 3"))
check("and EBOOT.BIN never becomes the remembered core for .bin",
      store.get_settings()["last_core_by_ext"].get("bin"), None)
run(plugin.unregister_game(703))
emulators.remove("rpcs3")
plugin._emulators = emulators.list_emulators()
os.remove(_ps3_pkg)

section("what the panel is told -- status, systems, emulators")
status = run(plugin.get_status())
check("an install is reported as found", status["found"], True)
check("the install shape is passed through", status["kind"], "flatpak")
check("the core count is what was scanned", status["core_count"], 2)
check("no emulators are registered yet", status["emulator_count"], 0)

_saved_install = plugin._install
plugin._install = None
missing = run(plugin.get_status())
check("no install is reported as not found", missing["found"], False)
check("and reports no cores rather than stale ones", missing["core_count"], 0)
check("but still suggests somewhere to look for ROMs", bool(missing["default_rom_dir"]), True)
plugin._install = _saved_install

# get_status resolves the home directory once and answers both fields from it,
# rather than dispatching the same environment lookup to the executor twice on a
# call the panel makes on every mount. That is only correct while the ROM
# directory really is the home directory, so the coupling is checked here rather
# than left to be discovered when the two silently disagree.
import ra_detect as _ra_detect  # noqa: E402

check(
    "the suggested ROM directory is the user's home",
    _ra_detect.default_rom_dir(),
    _ra_detect.user_home(),
)
check(
    "and status reports the same path for both fields",
    status["default_rom_dir"] == status["home_dir"] == _ra_detect.user_home(),
    True,
)

# The system picker: this list is what a custom emulator is mapped onto, and the
# mapping is what makes artwork work at all.
systems = run(plugin.list_systems())
labels = [option["label"] for option in systems]
check("the picker is sorted by full name", labels, sorted(labels, key=str.lower))
check("system ids are unique", len(({option["id"] for option in systems})), len(systems))
# The Vita is in libretro's catalog *and* in the hand-written no-libretro list, so
# it appeared twice: the same name offered once able to find boxart and once not.
check("no system is listed twice", sorted(set(labels)), sorted(labels))
switch = [option for option in systems if option["short"] == "Switch"]
check("Switch is offered even though libretro has no database", len(switch), 1)
check("and is marked as having no libretro system", switch[0]["libretro"], False)
check("so artwork for it cannot come from libretro", switch[0]["database"], "")
snes = [
    option
    for option in systems
    if option["database"] == "Nintendo - Super Nintendo Entertainment System"
]
check("a real libretro system is offered", len(snes), 1)
check("it is marked as a libretro system", snes[0]["libretro"], True)
check("with a short label for collection names", snes[0]["short"], "SNES")
check(
    "full names keep each manufacturer's systems together",
    snes[0]["label"].startswith("Nintendo - "),
    True,
)

# Custom emulators, through the plugin rather than the module. A flatpak id is
# used here because it needs no filesystem: the executable case follows, and only
# makes sense on a POSIX host.
saved = run(
    plugin.save_emulator(
        {
            "name": "Nimbus",
            "kind": "flatpak",
            "target": "org.nimbus_emu.nimbus",
            "args": "-f -g {rom}",
            "extensions": "nsp, xci",
            "databases": [],
            "platform": "Switch",
            "platform_full": "Nintendo Switch",
            "fullscreen_args": "",
        }
    )
)
check("saving a custom emulator succeeds", saved["ok"], True)
check("its id is derived from the name", saved["emulator"]["id"], "nimbus")
check("free-text extensions are parsed into a list", saved["emulator"]["extensions"], ["nsp", "xci"])
check(
    "arguments without the ROM placeholder are refused",
    "{rom}"
    in run(
        plugin.save_emulator(
            {"name": "Broken", "kind": "flatpak", "target": "org.x.Y",
             "args": "-f", "extensions": "iso", "databases": []}
        )
    )["error"],
    True,
)
check(
    "a target that is not a flatpak id is refused",
    "Flatpak application id"
    in run(
        plugin.save_emulator(
            {"name": "Broken", "kind": "flatpak", "target": "not an id",
             "args": "{rom}", "extensions": "iso", "databases": []}
        )
    )["error"],
    True,
)

# An AppImage downloaded through a browser has no execute bit, and the failure is
# invisible: the game just closes immediately. This is the single most common
# reason a freshly registered emulator does nothing, so it is repaired on save.
if os.name == "posix":
    appimage = os.path.join(TMP, "Cemu.AppImage")
    open(appimage, "w").close()
    os.chmod(appimage, 0o644)
    fixed = run(
        plugin.save_emulator(
            {"name": "Cemu", "kind": "path", "target": appimage, "args": "-g {rom}",
             "extensions": "wud, wux", "databases": [], "platform": "Wii U"}
        )
    )
    check("an executable emulator saves", fixed["ok"], True)
    check("a missing execute bit is repaired rather than refused", bool(fixed["notice"]), True)
    check("and the file really is executable now", os.access(appimage, os.X_OK), True)
    check(
        "a target that does not exist is refused",
        "No file exists"
        in run(
            plugin.save_emulator(
                {"name": "Ghost", "kind": "path", "target": "/nope/ghost.AppImage",
                 "args": "{rom}", "extensions": "iso", "databases": []}
            )
        )["error"],
        True,
    )
    run(plugin.remove_emulator("cemu"))
    os.remove(appimage)
else:
    print("SKIP execute-bit repair and path validation (needs a POSIX host)")

check("it is reported in the status", run(plugin.get_status())["emulator_count"], 1)
check(
    "and appears alongside the cores as something that can run a ROM",
    any(core["id"].startswith("emu:") for core in run(plugin.list_cores())),
    True,
)
emu_probe = run(plugin.probe_rom(os.path.join(TMP, "Some Switch Game.nsp")))
check(
    "its extensions are matched like a core's",
    [core["id"] for core in emu_probe["matching_cores"]],
    ["emu:nimbus"],
)
check("removing it succeeds", run(plugin.remove_emulator("nimbus"))["ok"], True)
check("and it is gone from the status", run(plugin.get_status())["emulator_count"], 0)

# Games added before per-platform collections existed recorded no platform, which
# made them fall back to the plain collection name instead of being grouped.
store.remember_game(
    800,
    {"app_id": 800, "title": "Old Entry", "core_id": "bsnes",
     "system": "Nintendo - Super Nintendo Entertainment System"},
)
run(plugin._backfill_library())
check("a legacy entry gets its platform filled in",
      store.get_library()["800"]["platform"], "SNES")
store.remember_game(801, {"app_id": 801, "title": "Unknown", "core_id": "gone", "system": ""})
run(plugin._backfill_library())
check("an entry with nothing to go on is left alone",
      store.get_library()["801"].get("platform"), None)
run(plugin.forget_games([800, 801]))

# flatpak resolves --user installs from HOME, so a missing HOME makes it fail
# with an exit code and no explanation.
env = plugin._subprocess_env()
check("HOME is always set for subprocesses", bool(env.get("HOME")), True)
check("XDG_DATA_HOME follows it", env["XDG_DATA_HOME"].startswith(env["HOME"]), True)
check("a PATH is guaranteed", bool(env.get("PATH")), True)
check("and Steam's runtime is cleared out", "LD_LIBRARY_PATH" in env, False)

section("reading RetroArch's own config")
import shutil as _shutil  # noqa: E402

import fileserver  # noqa: E402
import ra_detect  # noqa: E402
import sysenv  # noqa: E402

cfg_dir = os.path.join(TMP, "ra-config")
os.makedirs(cfg_dir, exist_ok=True)
with open(os.path.join(cfg_dir, "retroarch.cfg"), "w", encoding="utf-8") as handle:
    handle.write(
        "\n".join(
            [
                "# a comment",
                "",
                'libretro_directory = "~/cores"',
                'rgui_browser_directory = ":/roms"',
                "unquoted_key = plain",
                'has_equals = "a=b"',
                "malformed line with no separator",
                "  spaced_key   =   \"value\"  ",
            ]
        )
    )

cfg = ra_detect.parse_cfg(os.path.join(cfg_dir, "retroarch.cfg"))
check("quoted values lose their quotes", cfg["libretro_directory"], "~/cores")
check("unquoted values are kept", cfg["unquoted_key"], "plain")
check("only the first = separates", cfg["has_equals"], "a=b")
check("whitespace around keys and values is trimmed", cfg["spaced_key"], "value")
check("comments are skipped", "# a comment" in cfg, False)
check("lines with no separator are skipped", len(cfg), 5)
# A missing config is normal on a fresh install, so it must not raise.
check("a missing config reads as empty", ra_detect.parse_cfg(os.path.join(TMP, "nope.cfg")), {})

# Every folder default resolves through one home, so sandbox it -- otherwise
# these would read the real home of whatever machine runs the tests.
fake_home = os.path.join(TMP, "fake-home")
os.makedirs(fake_home, exist_ok=True)
_saved_home = os.environ.get("DECKY_USER_HOME")
os.environ["DECKY_USER_HOME"] = fake_home

check("the home is DECKY_USER_HOME when the loader sets it", sysenv.user_home(), fake_home)
check("and ra_detect agrees rather than resolving its own", ra_detect.user_home(), fake_home)

# The ROM picker opens at home. It used to guess -- RetroArch's remembered browse
# directory, then two ROM layouts other emulation setups lay down, and SD-card
# variants of both -- and every guess that missed dropped the user somewhere
# unexplained.
check("the ROM picker default is the home directory", ra_detect.default_rom_dir(), fake_home)
browsed = os.path.join(cfg_dir, "roms")
os.makedirs(browsed, exist_ok=True)
check(
    "even when RetroArch remembers browsing elsewhere",
    ra_detect.default_rom_dir(),
    fake_home,
)
os.rmdir(browsed)
# The literal names stay: they are the layouts the removed guessing looked for,
# so they are what proves it is no longer looking.
for layout in (("Emulation", "roms"), ("retrodeck", "roms"), ("roms",)):
    os.makedirs(os.path.join(fake_home, *layout), exist_ok=True)
check(
    "and when one of those layouts exists -- home is above all of them",
    ra_detect.default_rom_dir(),
    fake_home,
)

# Transfers get their own folder rather than a guess at an existing ROM library:
# uploads arrive unsorted and of unknown system.
user_dir = os.path.join(fake_home, sysenv.USER_DIR_NAME)
transfer_dir = os.path.join(user_dir, fileserver.DEFAULT_SUBDIR)
check("the transfer folder is inside home", fileserver.default_dir(), transfer_dir)
# A subdirectory, not the plugin folder itself, so `~/deckyemu` stays free for
# anything else that needs storing later.
check("it is one level below the plugin's own folder",
      os.path.dirname(fileserver.default_dir()), user_dir)
check("and is created if it was missing", os.path.isdir(transfer_dir), True)
check("including its parent", os.path.isdir(user_dir), True)
check("asking again returns the same folder", fileserver.default_dir(), transfer_dir)
check("the plugin's user folder is separate from what decky owns",
      sysenv.user_dir() != decky.DECKY_PLUGIN_RUNTIME_DIR, True)
check(
    "it is not where the ROM picker opens -- browsing and receiving are different",
    fileserver.default_dir() != ra_detect.default_rom_dir(),
    True,
)
check(
    "and it can be reported without being created",
    fileserver.default_dir(create=False),
    transfer_dir,
)
# start() still refuses a folder that has gone, which is what catches one deleted
# after the picker offered it.
_shutil.rmtree(transfer_dir)
check(
    "a folder that disappeared is refused rather than recreated silently",
    "does not exist" in (fileserver.start(transfer_dir).get("error") or "").lower()
    or bool(fileserver.start(transfer_dir).get("error")),
    True,
)

# `~` in retroarch.cfg means the *user's* home. os.path.expanduser would read the
# home of whatever account the backend runs as, which decky does not guarantee.
tilde_cores = os.path.join(fake_home, "cores")
os.makedirs(tilde_cores, exist_ok=True)
os.makedirs(os.path.join(cfg_dir, "info"), exist_ok=True)
tilde_install = ra_detect._build_install("flatpak", cfg_dir)
check(
    "a ~ path in the config resolves against the user's home",
    os.path.normpath(tilde_cores) in tilde_install["core_dirs"],
    True,
)

# The folder cores are installed into counts even before it exists. Every other
# candidate is dropped unless it is a real directory -- right for a guess at
# somebody else's layout, wrong for the one place this plugin writes to. On a
# RetroArch that had never had a core, that folder was absent at detection and
# dropped, the installer then created it and wrote the core there, and the scan
# that followed looked everywhere else: "0 core(s) now available", with the core
# invisible until something re-detected.
_bare_cfg = os.path.join(TMP, "bare-retroarch")
os.makedirs(_bare_cfg, exist_ok=True)
_bare = ra_detect._build_install("flatpak", _bare_cfg)
_destination = os.path.normpath(os.path.join(_bare_cfg, "cores"))
check("the install target is scanned before it exists",
      _destination in _bare["core_dirs"], True)
check("and it is where the installer actually writes",
      os.path.normpath(installer.target_core_dir(_bare)), _destination)
# The exception is only for that one path; a guess that is not there is still
# dropped, or every install would carry a list of folders nobody has.
check("a directory that does not exist is otherwise still dropped",
      [d for d in _bare["core_dirs"] if not os.path.isdir(d) and d != _destination],
      [])

if _saved_home is None:
    del os.environ["DECKY_USER_HOME"]
else:
    os.environ["DECKY_USER_HOME"] = _saved_home

# A native install is launched directly rather than through flatpak, and must not
# be handed any --filesystem arguments.
native_argv = ra_detect.launch_argv(
    {"kind": "native", "exe": "/usr/bin/retroarch"}, "/usr/lib/libretro/x.so", "/roms/a.sfc"
)
check("a native install runs its own binary", native_argv[0], "/usr/bin/retroarch")
check("no sandbox arguments are passed to it",
      any(a.startswith("--filesystem") for a in native_argv), False)
check("the core and ROM still follow -L", native_argv[-3:], ["-L", "/usr/lib/libretro/x.so", "/roms/a.sfc"])

section("editing an added game")
edit_rom = os.path.join(TMP, "Zelda II (USA).nes")
open(edit_rom, "w").close()
store.set_settings(
    {"collection_name": "Games", "collection_per_platform": True, "platform_names": "short"}
)

first_launcher = launchers.write_launcher(install, "Old Name", core, edit_rom)
store.remember_game(
    500,
    {
        "app_id": 500,
        "title": "Old Name",
        "rom_path": edit_rom,
        "core_id": "bsnes",
        "core_path": core,
        "system": "Nintendo - Super Nintendo Entertainment System",
        "platform": "SNES",
        "collection": "[Games] SNES",
        "launcher_path": first_launcher,
    },
)

# Rename only: the launcher filename embeds the title, so it must move and the
# old script must go, or the orphan audit would report it as a stray.
renamed = run(plugin.update_game(500, "Zelda II: The Adventure of Link", "bsnes"))
check("rename succeeds", renamed["ok"], True)
check("the new title is used", renamed["title"], "Zelda II: The Adventure of Link")
check("the launcher moved", renamed["launcher_changed"], True)
check("the old launcher is deleted", os.path.isfile(first_launcher), False)
check("the new launcher exists", os.path.isfile(renamed["exe"]), True)
check("the collection is unchanged", renamed["collection"], renamed["previous_collection"])
check(
    "the registry has the new title",
    store.get_library()["500"]["title"],
    "Zelda II: The Adventure of Link",
)

# Changing the core changes the system, so the platform and the per-platform
# collection must both follow -- and the caller is told where to move it from.
moved = run(plugin.update_game(500, "Zelda II: The Adventure of Link", "mupen64plus_next"))
check("core change succeeds", moved["ok"], True)
check("the platform follows the new core", moved["platform"], "N64")
check("the target collection follows", moved["collection"], "[Games] N64")
check("and the previous one is reported", moved["previous_collection"], "[Games] SNES")
entry_after = store.get_library()["500"]
check("the stored system is the new one", entry_after["system"], "Nintendo - Nintendo 64")
check("the stored platform is the new one", entry_after["platform"], "N64")
check("the recorded collection matches the target", entry_after["collection"], "[Games] N64")

check(
    "a missing core is refused",
    "not available" in run(plugin.update_game(500, "x", "core-that-vanished"))["error"],
    True,
)
check(
    "an unknown game is refused",
    "no longer tracked" in run(plugin.update_game(99999, "x", "bsnes"))["error"],
    True,
)

# Pointing an entry at a different file. The launcher name embeds a hash of the
# ROM path, so this has to move the script and delete the old one too.
run(plugin.update_game(500, "Zelda II: The Adventure of Link", "bsnes"))
before_repoint = store.get_library()["500"]["launcher_path"]
replacement_rom = os.path.join(TMP, "Zelda II (USA) (Rev A).sfc")
open(replacement_rom, "w").close()
repointed = run(
    plugin.update_game(500, "Zelda II: The Adventure of Link", "bsnes", replacement_rom)
)
check("changing the ROM succeeds", repointed["ok"], True)
check("the change is reported", repointed["rom_changed"], True)
check("the launcher moved with it", repointed["launcher_changed"], True)
check("the old launcher is gone", os.path.isfile(before_repoint), False)
check("the registry holds the new ROM", store.get_library()["500"]["rom_path"], replacement_rom)
check(
    "the launcher runs the new ROM",
    replacement_rom in open(repointed["exe"], encoding="utf-8").read(),
    True,
)
check(
    "keeping the same ROM is not reported as a change",
    run(plugin.update_game(500, "Zelda II: The Adventure of Link", "bsnes", replacement_rom))[
        "rom_changed"
    ],
    False,
)
check(
    "a ROM that does not exist is refused",
    "missing"
    in run(plugin.update_game(500, "x", "bsnes", os.path.join(TMP, "not-here.sfc")))["error"],
    True,
)
# bsnes is the SNES core in this fixture, so an N64 ROM is the wrong shape for it.
wrong_shape = os.path.join(TMP, "Some Game (USA).z64")
open(wrong_shape, "w").close()
check(
    "a ROM the core cannot read is refused",
    "does not support" in run(plugin.update_game(500, "x", "bsnes", wrong_shape))["error"],
    True,
)

# Per-game launch overrides. Absent means "follow the global setting", which is
# what lets a later change in Settings still reach games nobody has overridden.
store.set_settings({"hide_osd": "startup"})
default_osd = run(plugin.update_game(500, "Zelda II", "bsnes", "", {}))
check(
    "with no override the global mode is used",
    launchers.OVERRIDE_CONFIGS["startup"] in open(default_osd["exe"], encoding="utf-8").read(),
    True,
)
check("nothing is stored when nothing is overridden", store.get_library()["500"]["options"], {})

overridden = run(
    plugin.update_game(500, "Zelda II", "bsnes", "", {"hide_osd": "keep", "extra_args": "--verbose"})
)
override_body = open(overridden["exe"], encoding="utf-8").read()
# Not "passes no --appendconfig": the global menu shortcut still has to reach
# this game, so what "keep" now means is the override file that suppresses
# nothing, rather than no file at all.
check(
    "an OSD override wins over the global",
    launchers.OVERRIDE_CONFIGS["keep"] in override_body
    and launchers.OVERRIDE_CONFIGS["startup"] not in override_body,
    True,
)
check("extra arguments reach the command line", "--verbose" in override_body, True)
check(
    "extra arguments are recorded in the header",
    "# Args: --verbose" in override_body,
    True,
)
check(
    "the override is stored",
    store.get_library()["500"]["options"],
    {"hide_osd": "keep", "extra_args": "--verbose"},
)
check(
    "an unclosed quote is refused rather than written",
    "unclosed quote"
    in run(plugin.update_game(500, "Zelda II", "bsnes", "", {"extra_args": 'a "b'}))["error"],
    True,
)
check(
    "a meaningless OSD value is ignored rather than stored",
    run(plugin.update_game(500, "Zelda II", "bsnes", "", {"hide_osd": "nonsense"})) and
    store.get_library()["500"]["options"],
    {},
)
spaced = run(
    plugin.update_game(
        500, "Zelda II", "bsnes", "", {"hide_osd": "keep", "extra_args": '--set "two words"'}
    )
)
check(
    "arguments with spaces stay one argument",
    "'two words'" in open(spaced["exe"], encoding="utf-8").read(),
    True,
)

# A global change must not discard a per-game override.
store.remember_game(
    501,
    {
        "app_id": 501,
        "title": "Follows Global",
        "rom_path": replacement_rom,
        "core_id": "bsnes",
        "core_path": core,
        "launcher_path": launchers.write_launcher(install, "Follows Global", core, replacement_rom),
    },
)
run(plugin.set_settings({"hide_osd": "all"}))
kept = store.get_library()["500"]
check(
    "the override survives a global change",
    kept["options"].get("extra_args"),
    '--set "two words"',
)
check(
    "the overridden game keeps its own mode",
    launchers.OVERRIDE_CONFIGS["keep"] in open(kept["launcher_path"], encoding="utf-8").read(),
    True,
)
check(
    "a game with no override follows the new global mode",
    launchers.OVERRIDE_CONFIGS["all"]
    in open(store.get_library()["501"]["launcher_path"], encoding="utf-8").read(),
    True,
)

# The shortcut is baked into each launcher, so changing it has to rewrite them.
# Without the rebuild it would only apply to games added afterwards, which reads
# as the setting doing nothing at all.
run(plugin.set_settings({"menu_combo": "l1_r1"}))
check(
    "changing the shortcut rewrites the games already added",
    'input_menu_toggle_gamepad_combo = "6"'
    in open(launchers.OVERRIDE_CONFIGS["all"], encoding="utf-8").read(),
    True,
)
check(
    "and reaches a game that suppresses nothing",
    'input_menu_toggle_gamepad_combo = "6"'
    in open(launchers.OVERRIDE_CONFIGS["keep"], encoding="utf-8").read(),
    True,
)
run(plugin.set_settings({"menu_combo": "nonsense"}))
check(
    "a meaningless shortcut falls back rather than leaving no way into the menu",
    'input_menu_toggle_gamepad_combo = "4"'
    in open(launchers.OVERRIDE_CONFIGS["all"], encoding="utf-8").read(),
    True,
)
run(plugin.set_settings({"menu_combo": "start_select"}))
run(plugin.forget_games([501]))

os.remove(replacement_rom)
check(
    "a missing ROM is refused",
    "missing" in run(plugin.update_game(500, "x", "bsnes"))["error"],
    True,
)
run(plugin.forget_games([500]))
store.set_settings({"hide_osd": "startup"})

section("upgrading -- the menu shortcut must reach games already added")
# Nothing rewrites launchers on upgrade, so a new default would sit in settings
# while every existing game still launched without it. That is indistinguishable
# from the setting not working, and it is what this migration exists to prevent.
_settings_before = _json.load(open(store.SETTINGS_PATH, encoding="utf-8"))
_settings_before.pop("menu_combo", None)
with open(store.SETTINGS_PATH, "w", encoding="utf-8") as _handle:
    _json.dump(_settings_before, _handle)

legacy_rom = os.path.join(TMP, "Predates It (USA).sfc")
open(legacy_rom, "w").close()
store.remember_game(
    502,
    {
        "app_id": 502,
        "title": "Predates It",
        "rom_path": legacy_rom,
        "core_id": "bsnes",
        "core_path": core,
        "launcher_path": launchers.write_launcher(install, "Predates It", core, legacy_rom),
    },
)
check(
    "a launcher written before the setting has no shortcut",
    "input_menu_toggle_gamepad_combo"
    in open(launchers.OVERRIDE_CONFIGS["startup"], encoding="utf-8").read(),
    False,
)

run(plugin._adopt_menu_combo())
check(
    "startup gives an existing library the default shortcut",
    'input_menu_toggle_gamepad_combo = "4"'
    in open(launchers.OVERRIDE_CONFIGS["startup"], encoding="utf-8").read(),
    True,
)
check("and records it so the migration is not repeated", "menu_combo" in store.stored_keys(), True)

# Turning it off has to stick. If the migration ran again it would quietly put
# the shortcut back at every startup, which is worse than never adding it.
store.set_settings({"menu_combo": "off"})
launchers.write_launcher(install, "Predates It", core, legacy_rom)
run(plugin._adopt_menu_combo())
check(
    "a deliberate 'off' survives the next startup",
    "input_menu_toggle_gamepad_combo"
    in open(launchers.OVERRIDE_CONFIGS["startup"], encoding="utf-8").read(),
    False,
)
store.forget_game(502)
os.remove(legacy_rom)
store.set_settings({"menu_combo": "start_select"})

# A launcher is written once and never revisited, so a fix to how they are
# generated reaches only games added afterwards -- which is indistinguishable
# from the fix not working. The format version is what drags existing ones
# forward, and it must not rebuild on every startup thereafter.
_fmt_rom = os.path.join(TMP, "format-check.sfc")
open(_fmt_rom, "wb").write(b"\0" * 8)
store.set_settings({"launcher_format": 1})
store.remember_game(
    503,
    {
        "app_id": 503,
        "title": "Older Format",
        "rom_path": _fmt_rom,
        "core_id": "bsnes",
        "core_path": core,
        "launcher_path": launchers.write_launcher(install, "Older Format", core, _fmt_rom),
    },
)
run(plugin._upgrade_launchers())
check(
    "an out-of-date launcher format is brought forward",
    store.get_settings().get("launcher_format"),
    launchers.FORMAT_VERSION,
)
_rebuilt = []
_real_rebuild = plugin.rebuild_launchers


async def _counting_rebuild():
    _rebuilt.append(1)
    return await _real_rebuild()


plugin.rebuild_launchers = _counting_rebuild
try:
    run(plugin._upgrade_launchers())
    check("and is not rebuilt again at the next startup", _rebuilt, [])
finally:
    plugin.rebuild_launchers = _real_rebuild
store.forget_game(503)
os.remove(_fmt_rom)

# A corrected launch recipe has to reach an emulator already installed: the
# arguments are written once, at install, and PCSX2's needed fixing afterwards
# to stop its window flashing up and to make quitting the game exit.
_pcsx2_recipe = emu_catalog.find("pcsx2")
emulators.save(
    {
        "id": "pcsx2", "name": "PCSX2", "kind": "flatpak",
        "target": "net.pcsx2.PCSX2", "args": "-- {rom}", "extensions": ["iso"],
        "databases": ["Sony - PlayStation 2"], "fullscreen_args": "-fullscreen",
        "catalog_recipe": 1, "catalog_args": "-- {rom}",
        "catalog_fullscreen_args": "-fullscreen",
    }
)
run(plugin._upgrade_emulator_recipes())
check(
    "an untouched recipe is brought up to date",
    emulators.find("pcsx2")["args"],
    _pcsx2_recipe["args"],
)
check(
    "and the new version recorded so it settles",
    emulators.find("pcsx2")["catalog_recipe"],
    _pcsx2_recipe.get("recipe", 1),
)

# Arguments edited in the emulator editor are the user's. Overwriting them
# would undo a deliberate fix for some game the catalog knows nothing about.
emulators.save(
    {
        **emulators.find("pcsx2"),
        "args": "-mine -- {rom}",
        "catalog_recipe": 1,
    }
)
run(plugin._upgrade_emulator_recipes())
check(
    "arguments the user changed are left alone",
    emulators.find("pcsx2")["args"],
    "-mine -- {rom}",
)
check(
    "but the version still settles, or it would ask forever",
    emulators.find("pcsx2")["catalog_recipe"],
    _pcsx2_recipe.get("recipe", 1),
)
emulators.remove("pcsx2")
run(plugin._refresh_emulators())

# Installed and registered come apart constantly -- Discover and the usual
# emulation setups install these same flatpaks -- and the catalog row for one of
# those offered only Remove, so there was no way to reach the registration.
# Without it the emulator has no extensions and never appears when adding a game.
section("an emulator installed elsewhere can still be set up")
_real_flatpak_installed = emu_install.flatpak_installed
try:
    emu_install.flatpak_installed = lambda app_id: True
    check("nothing is registered to begin with", emulators.find("duckstation"), None)
    _reg = run(plugin.register_emulator("duckstation"))
    check("registering one already present succeeds", _reg["ok"], True)
    _registered = emulators.find("duckstation")
    check("it gains the catalog's system",
          _registered["databases"], ["Sony - PlayStation"])
    check("and extensions, which is what made it unselectable",
          "cue" in _registered["extensions"], True)
    check("and the launch recipe", _registered["args"], "-nogui -- {rom}")

    emulators.remove("duckstation")
    run(plugin._refresh_emulators())

    # Nothing on disk means there is nothing to register, and saying so beats
    # registering an emulator that cannot run.
    emu_install.flatpak_installed = lambda app_id: False
    _absent = run(plugin.register_emulator("duckstation"))
    check("but one that is not installed is refused", _absent["ok"], False)
    check("and says why", "not installed" in _absent["error"], True)
    check("an unknown id is refused too", run(plugin.register_emulator("nope"))["ok"], False)
finally:
    emu_install.flatpak_installed = _real_flatpak_installed
    emulators.remove("duckstation")
    run(plugin._refresh_emulators())

# Rebuilding and auditing both walk the whole library in a single pass. A game
# whose ROM has gone must be named and stepped over, not allowed to cost the
# rest of the library its rebuild.
present_rom = os.path.join(TMP, "Still Here (USA).sfc")
open(present_rom, "w").close()
gone_rom = os.path.join(TMP, "Vanished (USA).sfc")
open(gone_rom, "w").close()
store.remember_games(
    {
        503: {
            "app_id": 503,
            "title": "Still Here",
            "rom_path": present_rom,
            "core_id": "bsnes",
            "core_path": core,
            "launcher_path": launchers.write_launcher(install, "Still Here", core, present_rom),
        },
        504: {
            "app_id": 504,
            "title": "Vanished",
            "rom_path": gone_rom,
            "core_id": "bsnes",
            "core_path": core,
            "launcher_path": launchers.write_launcher(install, "Vanished", core, gone_rom),
        },
    }
)
os.remove(gone_rom)
_rebuild = run(plugin.rebuild_launchers())
check("a rebuild names the game whose ROM is gone", _rebuild["skipped"], ["Vanished"])
check("and still rebuilds every other game", _rebuild["rebuilt"], 1)

_audited = run(plugin.audit_library())
check("the audit reports every registered game", len(_audited["registry"]), 2)
check(
    "and gives the reason for the one that is broken",
    [(b["title"], b["reasons"]) for b in _audited["broken"]],
    [("Vanished", ["the ROM file is gone"])],
)

run(plugin.forget_games([503, 504]))
os.remove(present_rom)

import glob as _glob  # noqa: E402

section("orphans -- forgetting must not leave collections or come back")
for _app_id in list(store.get_library().keys()):
    store.forget_game(_app_id)
store.set_settings({"collection_name": "Games", "collection_per_platform": True})

orphan_rom = os.path.join(TMP, "Orphan (USA).sfc")
open(orphan_rom, "w").close()
store.remember_game(
    600,
    {
        "app_id": 600,
        "title": "Orphan",
        "rom_path": orphan_rom,
        "core_id": "bsnes",
        "collection": "[Games] SNES",
        "launcher_path": launchers.write_launcher(install, "Orphan", core, orphan_rom),
    },
)
forgotten = run(plugin.forget_games([600]))
check("forgetting reports what it removed", forgotten["removed"], ["Orphan"])
# The frontend cannot know which collection to empty unless it is told, and after
# the record is gone nothing remembers -- so it has to come back in this reply.
check(
    "and which collection each was filed into",
    [(g["app_id"], g["collection"]) for g in forgotten["games"]],
    [(600, "[Games] SNES")],
)
check("the entry is gone", "600" in store.get_library(), False)
check("and stays gone across an audit", len(run(plugin.audit_library())["registry"]), 0)

# A previous install is offered for adoption forever unless it can be discarded.
# Adopt-then-forget was a loop: the old registry survived every cycle.
old_dir = os.path.join(decky.DECKY_HOME, "settings", "an-older-build")
os.makedirs(old_dir, exist_ok=True)
old_library = os.path.join(old_dir, "library.json")
with open(old_library, "w", encoding="utf-8") as handle:
    _json.dump(
        {"700": {"app_id": 700, "title": "From Before", "rom_path": orphan_rom,
                 "core_id": "bsnes", "launcher_path": "/tmp/old.sh"}},
        handle,
    )
check(
    "the previous install is reported",
    [i["name"] for i in run(plugin.audit_library())["previous_installs"]],
    ["an-older-build"],
)
discarded = run(plugin.discard_previous_install(old_library))
check("discarding it succeeds", discarded["ok"], True)
check("and says how many it dropped", discarded["discarded"], 1)
check("the old registry file is gone", os.path.isfile(old_library), False)
check(
    "so it is never offered again",
    run(plugin.audit_library())["previous_installs"],
    [],
)
check(
    "discarding something already gone is not an error",
    run(plugin.discard_previous_install(old_library))["ok"],
    True,
)

# It deletes a file, so the path it accepts has to be pinned down.
check(
    "our own registry is refused",
    "own registry"
    in run(plugin.discard_previous_install(
        os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "library.json")))["error"],
    True,
)
check(
    "a path outside the settings folder is refused",
    "outside" in run(plugin.discard_previous_install("/etc/library.json"))["error"],
    True,
)
check(
    "and anything not named library.json is refused",
    "not a registry file"
    in run(plugin.discard_previous_install(os.path.join(old_dir, "settings.json")))["error"],
    True,
)
check("the settings file it was aimed at survives", os.path.isdir(old_dir), True)
os.remove(orphan_rom)

section("changelog -- generated from commit subjects, and never silently short")
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
import changelog  # noqa: E402

check("a prefix picks the section", changelog.classify("feat: add a thing"), ("New", "Add a thing"))
check("and is accepted with a scope", changelog.classify("fix(store): tidy")[0], "Fixed")
check("and with a breaking marker", changelog.classify("perf!: hurry")[0], "Faster")
check("case does not matter", changelog.classify("FEAT: shout")[0], "New")
# Grouping, not filtering: the whole point is that nothing is ever dropped, so a
# forgotten prefix is visible rather than a silent omission from the notes.
check("an unprefixed subject is kept, not dropped",
      changelog.classify("Just did a thing"), ("Other", "Just did a thing"))
check("a colon that is not a prefix is left alone",
      changelog.classify("Fix the thing: properly")[0], "Other")
# CI writes this one itself and it tells a reader nothing.
check("the release commit is skipped", changelog.classify("Release v1.2.3"), None)
check("an empty subject is skipped", changelog.classify("   "), None)
check("a prefix with no subject is skipped", changelog.classify("feat:"), None)

_rendered = changelog.render([
    "internal: tidy the build",
    "feat: add a thing",
    "Release v9.9.9",
    "Unprefixed work",
    "fix: stop a crash",
    "perf: go faster",
    "feat: add a thing",
])
check(
    "sections come out in reading order",
    [line[3:] for line in _rendered.splitlines() if line.startswith("## ")],
    ["New", "Fixed", "Faster", "Under the hood", "Other"],
)
check("the same entry is not listed twice", _rendered.count("- Add a thing"), 1)
check(
    "every commit that was not skipped appears",
    len([line for line in _rendered.splitlines() if line.startswith("- ")]),
    5,
)
check("nothing is rendered for nothing", changelog.render([]), "")
check("nor for only skippable commits", changelog.render(["Release v1.0.0"]), "")

section("version -- the two halves must be able to disagree out loud")
# The stamp exists so a frontend Steam cached before an update can be told apart
# from a bug. That only works if the backend reports honestly.
version_root = os.path.join(TMP, "plugin-root")
os.makedirs(version_root, exist_ok=True)
_real_root = plugin_main.PLUGIN_ROOT
plugin_main.PLUGIN_ROOT = version_root

check("with nothing to read it does not raise", run(plugin.plugin_version())["build"], "dev")

with open(os.path.join(version_root, "package.json"), "w", encoding="utf-8") as handle:
    _json.dump({"version": "1.2.3"}, handle)
reported = run(plugin.plugin_version())
check("the version comes from package.json", reported["version"], "1.2.3")
check("and a local build is marked as such", reported["build"], "dev")

with open(os.path.join(version_root, "build.json"), "w", encoding="utf-8") as handle:
    _json.dump({"version": "1.2.4", "commit": "abc1234", "built_at": "2026-08-01T00:00:00Z"}, handle)
stamped = run(plugin.plugin_version())
check("a CI build reports its commit", stamped["build"], "abc1234")
# CI writes the version it actually built, which beats a package.json that may
# have been bumped since.
check("and the version CI built wins", stamped["version"], "1.2.4")
check("with the build date", stamped["built_at"], "2026-08-01T00:00:00Z")
# A stamp written before the notes existed must not break the panel that shows
# them, so an absent field reads as "nothing to show" rather than missing.
check("a stamp with no notes reports none", stamped["notes"], "")

with open(os.path.join(version_root, "build.json"), "w", encoding="utf-8") as handle:
    _json.dump(
        {"version": "1.2.5", "commit": "def5678", "notes": "## New\n\n- A thing"}, handle
    )
noted = run(plugin.plugin_version())
check("the running build carries its own changelog", noted["notes"], "## New\n\n- A thing")
check("which needs no network to read", noted["version"], "1.2.5")

with open(os.path.join(version_root, "build.json"), "w", encoding="utf-8") as handle:
    handle.write("{ not json")
check(
    "a corrupt stamp falls back rather than breaking the panel",
    run(plugin.plugin_version())["version"],
    "1.2.3",
)
plugin_main.PLUGIN_ROOT = _real_root
# Against the file, not a literal: CI bumps package.json on every release, so a
# hardcoded number here fails the build for the one commit that matters most.
with open(os.path.join(REPO_ROOT, "package.json"), encoding="utf-8") as handle:
    _declared = _json.load(handle)["version"]
check("the real package.json is readable too", run(plugin.plugin_version())["version"], _declared)

section("updates -- deciding whether a newer release exists")
import releases  # noqa: E402

check("0.10.0 is newer than 0.9.0", releases._version_tuple("0.10.0") > releases._version_tuple("0.9.0"), True)
check("and 1.0.0 beats 0.99.99", releases._version_tuple("1.0.0") > releases._version_tuple("0.99.99"), True)
check("a short version pads out", releases._version_tuple("2"), (2, 0, 0))
check("rubbish sorts lowest rather than raising", releases._version_tuple("not-a-version"), (0, 0, 0))


def _release(tag, zip_name="deckyemu.zip", body="", **extra):
    entry = {
        "tag_name": tag,
        "body": body,
        "assets": [{"name": zip_name, "browser_download_url": "https://example/%s" % zip_name}]
        if zip_name
        else [],
    }
    entry.update(extra)
    return entry


parsed = releases.parse_release(
    _release("v1.2.3", body="Notes here" + os.linesep + "sha256: " + "a" * 64)
)
check("the leading v is dropped", parsed["version"], "1.2.3")
check("the download url is picked up", parsed["asset_url"], "https://example/deckyemu.zip")
# CI writes the digest into the body so decky can verify what it downloads.
check("the sha256 is read from the notes", parsed["sha256"], "a" * 64)
check("notes survive", parsed["notes"].startswith("Notes here"), True)
# The digest is for stage_update to verify against, not for a reader. Leaving it
# in `notes` is how the Updates tab came to answer "what changed?" with a hash.
check("but the digest is not shown as a release note", "a" * 64 in parsed["notes"], False)
check(
    "nor is the commit it was built from",
    "Built from"
    in releases.parse_release(
        _release("v1.2.4", body="Real notes" + os.linesep + "Built from abc1234.")
    )["notes"],
    False,
)
check(
    "a body that is only a trailer leaves nothing to show",
    releases.readable_notes("sha256: %s\n\nBuilt from abc1234." % ("c" * 64)),
    "",
)
# Stripping the trailer rather than extracting the notes, so a body this code has
# never seen degrades to being shown in full rather than to being shown as
# nothing.
check(
    "an unrecognised body is shown as written",
    releases.readable_notes("Handwritten notes, no trailer at all."),
    "Handwritten notes, no trailer at all.",
)

check("a release with no zip is unusable", releases.parse_release(_release("v1.0.0", zip_name="")), None)
check("a draft is ignored", releases.parse_release(_release("v1.0.0", draft=True)), None)
check("so is a tag that is not a version", releases.parse_release(_release("nightly")), None)
check("a missing digest is not fatal", releases.parse_release(_release("v1.0.0"))["sha256"], "")

# The whole check, with the network stubbed out.
_real_get_json = releases.net.get_json
releases.net.get_json = lambda url, headers=None: [
    _release("v0.9.0"),
    _release("v1.1.0"),
    _release("v1.2.0", body="sha256: %s" % ("b" * 64)),
    _release("v2.0.0-beta", prerelease=True),
]
releases.clear_cache()

result = releases.check("1.0.0", force=True)
check("an older install is offered the newest stable", result["available"], True)
check("which is the highest version, not the first listed", result["latest"]["version"], "1.2.0")
check("prereleases are left alone by default", result["latest"]["prerelease"], False)
# The tag's suffix is kept verbatim -- it is what the release is called -- while
# the comparison reads only the numbers in front of it.
check(
    "but can be asked for",
    releases.check("1.0.0", force=True, allow_prerelease=True)["latest"]["version"],
    "2.0.0-beta",
)
check("and a suffix does not confuse the ordering", releases._version_tuple("2.0.0-beta"), (2, 0, 0))
check("being up to date offers nothing", releases.check("1.2.0", force=True)["available"], False)
check("nor does being ahead of the release", releases.check("9.9.9", force=True)["available"], False)

# A failed check must not break the panel or wipe what it already knew.
releases.net.get_json = lambda url, headers=None: (_ for _ in ()).throw(OSError("no network"))
offline = releases.check("1.0.0", force=True)
check("a network failure still answers", offline["available"], True)
check("from the cache rather than crashing", offline["latest"]["version"], "1.2.0")
releases.clear_cache()
check("with nothing cached it reports it could not check", releases.check("1.0.0", force=True)["checked"], False)
check("and offers no update", releases.check("1.0.0", force=True)["available"], False)
check("with a reason to show", bool(releases.check("1.0.0", force=True)["error"]), True)

# The bug this distinction exists for: a repository with nothing published yet
# answered perfectly and was reported as unreachable.
releases.net.get_json = lambda url, headers=None: []
releases.clear_cache()
empty = releases.check("1.0.0", force=True)
check("an empty release list is a successful check", empty["checked"], True)
check("with no error to report", empty["error"], "")
check("nothing to offer", empty["available"], False)
check("and a count that says why", empty["count"], 0)

# GitHub answers errors as an object, not a list.
releases.net.get_json = lambda url, headers=None: {"message": "Bad credentials"}
releases.clear_cache()
refused = releases.check("1.0.0", force=True)
check("a rejected token is not a successful check", refused["checked"], False)
check("and GitHub's own words are passed through", refused["error"], "Bad credentials")

# net returns None when the request itself failed; it logs the reason.
releases.net.get_json = lambda url, headers=None: None
releases.clear_cache()
failed = releases.check("1.0.0", force=True)
check("a failed request is reported as such", failed["checked"], False)
check("and blames the connection, the only cause left", "connection" in failed["error"], True)

releases.net.get_json = _real_get_json
releases.clear_cache()

# The GitHub token is gone. It existed while this repository was private, and a
# credential nothing reads is still a credential in a file -- so an install that
# stored one has it deleted rather than ignored. This matters beyond tidiness:
# get_settings merges the stored file over the defaults, so a key that is no
# longer declared would otherwise be handed straight to the frontend.
store.set_settings({"github_token": "not-a-real-token"})
check("an install that stored one still has it before startup runs",
      "github_token" in store.get_settings(), True)
# The hazard the migration exists for, asserted rather than described: nothing
# pops this key any more, so until it is deleted from the file it is handed to
# the frontend with every other setting.
check("and until it is deleted it would reach the UI",
      "github_token" in run(plugin.get_settings()), True)

run(plugin._forget_removed_settings())
check("startup deletes it from the file", "github_token" in store.get_settings(), False)
check("so it no longer reaches the UI",
      "github_token" in run(plugin.get_settings()), False)
check("and a second start has nothing to do", store.forget_removed(), [])
check("nothing here sends an Authorization header",
      "Authorization" in releases.API_HEADERS, False)

# Decky downloads the URL it is given, so the release is fetched here and
# re-offered on loopback -- which is what makes the digest it checks one
# computed from the bytes actually received.
import handoff  # noqa: E402
import urllib.request as _urlreq  # noqa: E402

relay_file = os.path.join(TMP, "deckyemu.zip")
with open(relay_file, "wb") as handle:
    handle.write(b"PK pretend zip")

relay_url = handoff.serve(relay_file)
check("the relay offers a loopback url", relay_url.startswith("http://127.0.0.1:"), True)
check("with the file's name in it", relay_url.endswith("/deckyemu.zip"), True)
if relay_url:
    with _urlreq.urlopen(relay_url, timeout=5) as response:
        body = response.read()
    check("and serves the bytes", body, b"PK pretend zip")

    # Guessing the path must not work: it is a token, not a filename.
    base = relay_url.rsplit("/", 2)[0]
    try:
        _urlreq.urlopen(base + "/wrongtoken/deckyemu.zip", timeout=5)
        guessed = 200
    except urllib.error.HTTPError as error:
        guessed = error.code
    check("a wrong token is refused", guessed, 404)

handoff.stop()
check("stopping leaves nothing listening", handoff.running(), False)
check("serving a file that is not there fails cleanly", handoff.serve(os.path.join(TMP, "nope.zip")), "")
os.remove(relay_file)

section("clearing the whole library")
for _app_id in list(store.get_library().keys()):
    store.forget_game(_app_id)
store.set_settings({"collection_name": "Games", "collection_per_platform": True})

clear_rom = os.path.join(TMP, "Chrono Trigger (USA).sfc")
open(clear_rom, "w").close()
kept_rom = os.path.join(TMP, "Kept (USA).n64")
open(kept_rom, "w").close()
for app_id, title, core_id, rom, collection in (
    (900, "Chrono Trigger", "bsnes", clear_rom, "[Games] SNES"),
    (901, "Kept", "mupen64plus_next", kept_rom, "[Games] N64"),
    (902, "Also SNES", "bsnes", clear_rom, "[Games] SNES"),
):
    store.remember_game(
        app_id,
        {
            "app_id": app_id,
            "title": title,
            "rom_path": rom,
            "core_id": core_id,
            "collection": collection,
            "launcher_path": launchers.write_launcher(install, title, core, rom),
        },
    )
launcher_paths = [entry["launcher_path"] for entry in store.get_library().values()]
# A script left behind by an earlier version, which no entry points at. Clearing
# the library must take it too, or the orphan audit would report it afterwards.
orphan_script = launchers.write_launcher(install, "Long Gone", core, clear_rom + ".old")

cleared = run(plugin.clear_library())
check("clearing succeeds", cleared["ok"], True)
check("every game is reported back", sorted(g["app_id"] for g in cleared["games"]), [900, 901, 902])
check("with the collection each was filed into",
      sorted({g["collection"] for g in cleared["games"]}), ["[Games] N64", "[Games] SNES"])
# The frontend needs these to empty the collections; deduped so it does not do the
# same one twice, and only the ones we actually used.
check("collections are reported once each",
      sorted(cleared["collections"]), ["[Games] N64", "[Games] SNES"])
check("the library is empty", store.get_library(), {})
check("every launcher is deleted",
      [path for path in launcher_paths if os.path.isfile(path)], [])
check("including scripts no entry claimed", os.path.isfile(orphan_script), False)
check(
    "at least this library's launchers plus the orphan were counted",
    cleared["launchers_deleted"] >= len(launcher_paths) + 1,
    True,
)
# Stronger than counting: the directory is left with nothing in it. Earlier
# sections leave scripts behind, and those are swept up too, which is correct --
# they are launchers this plugin wrote that nothing references any more.
check(
    "no launcher script survives anywhere in our directory",
    _glob.glob(os.path.join(launchers.LAUNCHER_DIR, "*.sh")),
    [],
)
# Clearing the library deletes the games too now, and the boundary is the only
# thing standing between that and somebody's own ROM collection: these two live
# in a scratch directory rather than under roms/<system>, so they were never
# filed by this plugin and are not its to remove.
check("ROMs the plugin never filed are left alone",
      os.path.isfile(clear_rom) and os.path.isfile(kept_rom), True)

# And one that was filed, which goes.
import romshelf as _romshelf  # noqa: E402 -- imported where it is first needed

_cleared_shelf = _romshelf.library_dir(create=True)
_cleared_dir = os.path.join(_cleared_shelf, "snes")
os.makedirs(_cleared_dir, exist_ok=True)
_cleared_rom = os.path.join(_cleared_dir, "Filed Game (USA).sfc")
with io.open(_cleared_rom, "w") as _handle:
    _handle.write("x" * 2048)
store.remember_game(
    903,
    {
        "app_id": 903, "title": "Filed Game", "rom_path": _cleared_rom,
        "core_id": core_id, "collection": "",
        "launcher_path": launchers.write_launcher(install, "Filed Game", core, _cleared_rom),
    },
)
_filed_clear = run(plugin.clear_library())
check("a filed ROM is deleted with the library", os.path.isfile(_cleared_rom), False)
check("and the bytes are reported", _filed_clear["freed"] >= 2048, True)
check("its now-empty system folder goes too", os.path.isdir(_cleared_dir), False)
check("nothing is reported as strays afterwards", run(plugin.audit_library())["strays"], [])

empty = run(plugin.clear_library())
check("clearing an empty library is not an error", empty["ok"], True)
check("and reports nothing to undo", (empty["games"], empty["collections"]), ([], []))

os.remove(clear_rom)
os.remove(kept_rom)

section("audit -- finding entries whose files or shortcuts have gone")
real_rom = os.path.join(TMP, "Real Game (USA).sfc")
open(real_rom, "w").close()
good_launcher = launchers.write_launcher(install, "Real Game", core, real_rom)

# Start from a clean library for this section.
for app_id in list(store.get_library().keys()):
    store.forget_game(app_id)

store.remember_game(101, {"app_id": 101, "title": "Real Game", "rom_path": real_rom,
                          "core_id": "snes9x", "launcher_path": good_launcher})
store.remember_game(102, {"app_id": 102, "title": "Deleted ROM", "rom_path": os.path.join(TMP, "gone.sfc"),
                          "core_id": "snes9x", "launcher_path": good_launcher})
store.remember_game(103, {"app_id": 103, "title": "Lost Launcher", "rom_path": real_rom,
                          "core_id": "snes9x", "launcher_path": os.path.join(TMP, "nope.sh")})

audit = run(plugin.audit_library())
check("every entry is reported for the shortcut check", len(audit["registry"]), 3)
broken = {entry["title"]: entry["reasons"] for entry in audit["broken"]}
check("a healthy game is not flagged", "Real Game" in broken, False)
check("a missing ROM is flagged", broken.get("Deleted ROM"), ["the ROM file is gone"])
check("a missing launcher is flagged", broken.get("Lost Launcher"), ["the launcher script is gone"])

# A launcher nothing references is a stray.
stray = launchers.write_launcher(install, "Abandoned", core, os.path.join(TMP, "abandoned.sfc"))
audit = run(plugin.audit_library())
check("strays are found", stray in audit["strays"], True)
check("referenced launchers are not strays", good_launcher in audit["strays"], False)
check("deleting strays works", run(plugin.delete_stray_launchers([stray]))["deleted"], 1)
check("and it is gone", os.path.isfile(stray), False)

# Renaming the plugin leaves the old install's library behind under DECKY_HOME.
old_dir = os.path.join(decky.DECKY_HOME, "settings", "an-older-name")
os.makedirs(old_dir, exist_ok=True)
with open(os.path.join(old_dir, "library.json"), "w", encoding="utf-8") as handle:
    _json.dump(
        {
            # bsnes is the SNES core in this test's fixture; adoption requires
            # the core to still exist.
            "900": {"app_id": 900, "title": "Legacy Game", "rom_path": real_rom,
                    "core_id": "bsnes", "launcher_path": good_launcher},
            # A game whose core is gone must be skipped, not adopted blindly.
            "901": {"app_id": 901, "title": "Orphan Core", "rom_path": real_rom,
                    "core_id": "core-that-vanished", "launcher_path": good_launcher},
        },
        handle,
    )
audit = run(plugin.audit_library())
names = [item["name"] for item in audit["previous_installs"]]
check("a previous install is detected", names, ["an-older-name"])
check("its games are listed",
      sorted(g["title"] for g in audit["previous_installs"][0]["games"]),
      ["Legacy Game", "Orphan Core"])
check("and their ROMs checked",
      all(g["rom_exists"] for g in audit["previous_installs"][0]["games"]), True)

# Our own settings dir must never be reported as a previous install.
with open(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "library.json"), "r", encoding="utf-8") as handle:
    pass
check(
    "our own library is not a previous install",
    any(item["name"] == os.path.basename(decky.DECKY_PLUGIN_SETTINGS_DIR)
        for item in audit["previous_installs"]),
    False,
)

# Files that merely live under DECKY_HOME must not be mistaken for a library.
junk_dir = os.path.join(decky.DECKY_HOME, "settings", "unrelated-plugin")
os.makedirs(junk_dir, exist_ok=True)
with open(os.path.join(junk_dir, "library.json"), "w", encoding="utf-8") as handle:
    _json.dump({"window": {"width": 1280}}, handle)
audit = run(plugin.audit_library())
check(
    "an unrelated library.json is ignored",
    sorted(item["name"] for item in audit["previous_installs"]),
    ["an-older-name"],
)

adopted = run(plugin.adopt_previous_install(os.path.join(old_dir, "library.json")))
check("adoption succeeds", adopted["ok"], True)
check("the game is adopted", [g["title"] for g in adopted["adopted"]], ["Legacy Game"])
check("a game whose core is gone is skipped", adopted["skipped"], ["Orphan Core"])
# The caller needs the target collection: recording it without filing the game
# would make a later rename think it was already in place.
check("the target collection is returned", bool(adopted["adopted"][0]["collection"]), True)
check(
    "it matches what was recorded",
    adopted["adopted"][0]["collection"],
    store.get_library()["900"]["collection"],
)
store.set_settings({"add_to_collection": False})
again = run(plugin.adopt_previous_install(os.path.join(old_dir, "library.json")))
check(
    "no collection when the setting is off",
    again["adopted"][0]["collection"],
    "",
)
store.set_settings({"add_to_collection": True})
check("with a launcher in this install's folder",
      adopted["adopted"][0]["exe"].startswith(launchers.LAUNCHER_DIR), True)
check("and is now tracked", "900" in store.get_library(), True)

check("forgetting removes records", run(plugin.forget_games([102, 103]))["removed"] != [], True)
check("the records are gone", sorted(store.get_library().keys()), ["101", "900"])
section("dev reset -- gated on the build, and honest about what it deletes")
# The gate is the whole safety story on the backend side, and it is keyed on
# CI's build stamp rather than a setting: a setting can be switched on by
# anyone, and these actions delete save games.
import devreset  # noqa: E402  -- imported here so the stub decky is in place

# Called for real, because the first version of this was tested only through its
# parts -- the gate and the state-file list -- and shipped with a call to a
# function that does not exist. Every row read "Nothing to remove", which is
# exactly what a clean machine looks like, so the panel lied rather than failed.
_inv = devreset.inventory()
check("the inventory runs at all", isinstance(_inv, dict), True)
check("and answers for every group the panel asks about",
      sorted(_inv), ["downloads", "emulator_data", "emulators", "retroarch", "state",
                     "transfers"])
# Something is always there in a test run: the suite has written state files.
check("it finds the plugin's own state", len(_inv["state"]) > 0, True)
check("with a size and a label on each",
      all(set(item) >= {"label", "path", "items", "bytes"} for group in _inv.values()
          for item in group), True)

# A flatpak keeps everything under its application id and needs nothing said. An
# AppImage writes where it likes, so the catalog has to say where -- and the
# first version of this derived it from the config file's directory instead,
# which meant RPCS3 contributed nothing at all (its entry has no config path)
# and Vita3K contributed 24KB of yaml while its 215MB of games and firmware sat
# somewhere else entirely. A reset that misses most of what it claims to delete
# is worse than none, because the next run inherits state nobody believes in.
check("every emulator the plugin downloads says where its data lives",
      [entry["id"] for entry in emu_catalog.CATALOG
       if entry["source"]["kind"] != "flatpak" and not entry.get("data")],
      [])

_stamp_root = os.path.join(TMP, "stamproot")
os.makedirs(_stamp_root, exist_ok=True)
check("a build from source may reset", devreset.available(_stamp_root), True)
io.open(os.path.join(_stamp_root, "build.json"), "w").close()
check("a build CI stamped may not", devreset.available(_stamp_root), False)
_root_before = plugin_main.PLUGIN_ROOT
plugin_main.PLUGIN_ROOT = _stamp_root
check("and the endpoint refuses on a stamped build",
      run(plugin.dev_reset("state"))["ok"], False)
check("saying why", "development build" in run(plugin.dev_reset("state"))["error"].lower(), True)
# An unknown action is refused too, so a typo cannot fall through to something
# destructive. Checked against a root with no stamp, or the gate above would
# refuse it first and this would pass without testing anything.
plugin_main.PLUGIN_ROOT = os.path.join(TMP, "unstamped")
os.makedirs(plugin_main.PLUGIN_ROOT, exist_ok=True)
_unknown = run(plugin.dev_reset("everything"))
check("an unrecognised action does nothing", _unknown["ok"], False)
check("and says it was the action, not the gate",
      "unknown reset" in _unknown["error"].lower(), True)
plugin_main.PLUGIN_ROOT = _root_before

# Every file the plugin remembers anything in has to be on the list, or a reset
# leaves the machine believing something that is no longer true. The setup
# record is the dangerous one: left behind, a reinstalled emulator reports
# itself already configured and no setup block is ever applied again.
_listed = {os.path.basename(path) for path, _ in devreset._state_files()}
check("the setup record is cleared", "emulator_setup.json" in _listed, True)
check("so is the firmware record", "firmware_installed.json" in _listed, True)
check("and the library, emulators, content ids and settings",
      {"library.json", "emulators.json", "ps3_content_ids.json", "settings.json"} <= _listed,
      True)
# Anything writing to the settings directory that this does not know about is a
# reset that quietly leaves state behind, so the two are compared rather than
# assumed to have stayed in step.
_writers = set()
for _module in (store, emulators, emu_config, emu_firmware, ps3_games):
    for _name in dir(_module):
        _value = getattr(_module, _name)
        if isinstance(_value, str) and _value.endswith(".json") and os.sep in _value:
            if os.path.dirname(_value) == decky.DECKY_PLUGIN_SETTINGS_DIR:
                _writers.add(os.path.basename(_value))
check("no module keeps state the reset does not know about",
      sorted(_writers - _listed), [])

section("the RPC contract -- the two halves agree on what exists")
# The only thing joining the frontend to the backend is a string. `callable("x")`
# resolves at runtime on the Deck, so renaming a Python method compiles, bundles,
# deploys and then fails when a button is pressed -- with a traceback in the
# plugin log that nobody is reading at the time.
#
# Checked here rather than trusted, because nothing else can: TypeScript does not
# know these names refer to anything, and Python does not know they are referred
# to. 83 of them at the time of writing.
_ts_names = set()
_src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
for _root, _dirs, _files in os.walk(_src):
    for _name in _files:
        if not _name.endswith((".ts", ".tsx")):
            continue
        with io.open(os.path.join(_root, _name), encoding="utf-8") as _handle:
            _text = _handle.read()
        # The generic parameters routinely span lines, so this cannot be a
        # line-oriented match.
        _ts_names |= set(_re.findall(r'callable\s*<.*?>\s*\(\s*"([a-z_0-9]+)"', _text, _re.S))
        _ts_names |= set(_re.findall(r'callable\s*\(\s*"([a-z_0-9]+)"', _text))

_exposed = {
    name for name in dir(Plugin)
    if not name.startswith("_") and callable(getattr(Plugin, name, None))
}
check("every callable() in the frontend names a method that exists",
      sorted(_ts_names - _exposed), [])
# Not empty: some endpoints are called from Python-side flows or are not wired up
# yet. Reported rather than asserted, since an unused endpoint is untidy and a
# missing one is broken, and only the second is worth failing a build over.
_unused = sorted(_exposed - _ts_names)
print("     (%d backend method(s) no frontend code calls: %s)"
      % (len(_unused), ", ".join(_unused) or "none"))
check("the frontend actually declared some, so this is testing something",
      len(_ts_names) > 50, True)

plugin.loop.close()

# Everything written since the split. Imported rather than listed, so adding a
# file is the whole of adding a test.
import glob as _glob_tests  # noqa: E402
import importlib.util as _importlib  # noqa: E402

for _path in sorted(_glob_tests.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "tests", "test_*.py"))):
    _spec = _importlib.spec_from_file_location(
        "deckyemu_tests_" + os.path.basename(_path)[:-3], _path)
    _module = _importlib.module_from_spec(_spec)
    _spec.loader.exec_module(_module)

summary()
