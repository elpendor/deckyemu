#!/usr/bin/env python3
"""A PS Vita game has one way in, and it is not the ROM picker.

    python scripts/tests/test_vita_route.py

Vita3K decrypts content as it installs, so a game has to be installed before
anything can start it -- and it is started by title id, because its AppImage
re-splits any path containing a space. A `.vpk` was nonetheless listed as Vita
content, so the picker matched it to Vita3K and offered "Add to Steam"; the
shortcut that produced handed the emulator a path and failed at launch with
"is not a supported content type", naming a word from the middle of the
filename.

So the picker recognises those files in order to explain them, and the one gate
every add goes through refuses to write a launcher that could not work.
"""

import asyncio
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emulator_catalog  # noqa: E402
import emulators  # noqa: E402
import vita_games  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from main import Plugin  # noqa: E402

_VITA3K = {
    "id": "vita3k",
    "name": "Vita3K",
    "kind": "path",
    "target": os.path.join(TMP, "Vita3K-x86_64.AppImage"),
    "args": "{rom}",
    "fullscreen_args": "--fullscreen",
    "installed_args": "-r {title}",
    "splits_args": True,
    "databases": [],
    "platform": "PS Vita",
    "platform_full": "Sony - PlayStation Vita",
    "extensions": ["pkg"],
}

plugin = Plugin()
plugin.loop = asyncio.new_event_loop()
plugin._cores = []
plugin._emulators = [_VITA3K]
plugin._install = None


def run(coro):
    return plugin.loop.run_until_complete(coro)


# A release is a zip carrying the file every Vita game has and no ROM archive
# does. A .vpk is the same zip under another extension, which is why both are
# recognised the same way.
def _release(path):
    with zipfile.ZipFile(path, "w") as bundle:
        # Built to the documented layout rather than copied off a game: a
        # PARAM.SFO taken from somebody's install has no place in this tree.
        bundle.writestr("sce_sys/param.sfo", _param_sfo())
        bundle.writestr("eboot.bin", b"\x00" * 16)
    return path


def _param_sfo():
    """A minimal PARAM.SFO holding TITLE and TITLE_ID, built from the format."""
    import struct

    entries = [("TITLE", b"Gravity Rush\x00"), ("TITLE_ID", b"PCSA00011\x00")]
    key_table = b"".join(key.encode() + b"\x00" for key, _ in entries)
    data_table = b"".join(value for _, value in entries)

    header_size = 20 + len(entries) * 16
    key_offset = header_size
    data_offset = key_offset + len(key_table)

    out = struct.pack("<4sIIII", b"\x00PSF", 0x0101, key_offset, data_offset, len(entries))
    key_at = 0
    data_at = 0
    for key, value in entries:
        out += struct.pack(
            "<HHIII", key_at, 0x0204, len(value), len(value), data_at
        )
        key_at += len(key) + 1
        data_at += len(value)
    return out + key_table + data_table


section("the picker no longer treats Vita content as something to run")

_vita_extensions = emulator_catalog.MANUAL_EXTENSIONS["Sony - PlayStation Vita"]
check("a .vpk is not listed as content Vita3K can be pointed at",
      "vpk" in _vita_extensions, False)
# The one format that does work, and it is here for the same reason the PS3 line
# carries it: a package is what the user has, so it has to be pickable.
check("a .pkg is, because that is the format this plugin can install",
      _vita_extensions, ["pkg"])


section("an emulator already installed stops claiming .vpk too")

# The list is derived once, when the emulator is registered, and stored. So
# narrowing it in the catalog reached nobody who already had Vita3K: the picker
# read the stored list, matched the .vpk, and offered a "Run with" that could
# not work. Exactly the shape of the `installed_args` problem next to it, and it
# needs the same refresh.
_stale = dict(_VITA3K, extensions=["self", "vpk"], catalog_recipe=3)
plugin._emulators = [_stale]
_derived = emulator_catalog.extensions_for(emulator_catalog.find("vita3k"), {})
check("the catalog now derives only the format this plugin can install",
      _derived, ["pkg"])
check("which is not what an install from before this carries",
      _stale["extensions"], ["self", "vpk"])
# Vita3K declares no libretro databases, so its formats come entirely from
# MANUAL_EXTENSIONS and no info.zip is needed to work them out -- which is what
# makes refreshing this one safe with no network at all.
check("and it needs no libretro map to say so",
      emulator_catalog.find("vita3k").get("databases"), [])

plugin._emulators = [_VITA3K]


section("a release is recognised so it can be explained")

_vpk = _release(os.path.join(TMP, "GRAVITY RUSH (PCSA00011).vpk"))
_probe = run(plugin.probe_rom(_vpk))

check("a .vpk is read as a PS Vita release", _probe["vita_release"]["vita"], True)
check("and its own name is offered as the title",
      _probe["provisional_title"], "Gravity Rush")
# The whole point. Offering Vita3K here is what wrote a shortcut that could
# never start, and the failure only appeared when the game was launched.
check("but Vita3K is not offered as something to run it with",
      [core["id"] for core in _probe["matching_cores"] if "vita3k" in core["id"]], [])
check("so nothing is suggested", _probe["suggested_core_id"], "")


section("and no launcher can be written that hands it a path")

_refused = run(plugin.prepare_shortcut("Gravity Rush", "emu:vita3k", _vpk))
check("adding it by path is refused", _refused["ok"], False)
check("and the message says what to do instead",
      "installed list" in _refused["error"], True)

# The route that works: an installed title, started by an id that cannot be
# split because it has no spaces in it.
# Under the folder Vita3K really installs into, not a scratch one: the title id
# a launcher needs is *derived* from the eboot's position beneath that root, so
# a fixture parked anywhere else derives "" and quietly proves nothing.
_installed = os.path.join(vita_games.games_dir(), "PCSA00011")
os.makedirs(_installed, exist_ok=True)
_eboot = os.path.join(_installed, "eboot.bin")
with open(_eboot, "wb") as _handle:
    _handle.write(b"\x00" * 16)

_prepared = run(plugin.prepare_shortcut(
    "Gravity Rush", "emu:vita3k", _eboot, "Sony - PlayStation Vita",
    title_id="PCSA00011",
))
check("an installed title is prepared normally", _prepared["ok"], True)
with open(_prepared["exe"], "r", encoding="utf-8") as _handle:
    _script = _handle.read()
check("and its launcher starts the title by id, not by path",
      "-r PCSA00011" in _script, True)
check("with no path to the game in it at all", _eboot in _script.split("exec")[-1], False)

section("editing a Vita game leaves it still launching by id")

# The editor rewrites the launcher on save, and it used to write a different
# one from the add flow: `write_launcher` takes `title_id` last, `update_game`
# passed its arguments positionally and stopped one short, and the default is a
# launcher that opens the eboot by path. Vita3K opens its own interface for
# that and no game -- so choosing new artwork and pressing Save quietly stopped
# the game booting, with a launcher that still looked plausible.
_APP_ID = 424242
run(plugin.register_game(
    _APP_ID, "Gravity Rush", _eboot, "emu:vita3k", _prepared["exe"],
    "Sony - PlayStation Vita",
))
# A rename, which is the commonest edit and the one that follows picking new
# artwork -- exactly what the user had done when the game stopped booting.
_updated = run(plugin.update_game(_APP_ID, "Gravity Rush Remastered", "emu:vita3k"))
check("the edit succeeds", _updated.get("ok"), True)

# The rename produces a new launcher file -- the filename embeds the title --
# so the one to read is whatever the registry now points at, not the old path.
_entry_after = run(plugin.list_added())
_launcher_after = next(
    game["launcher_path"] for game in _entry_after if game["app_id"] == _APP_ID
)
with open(_launcher_after, "r", encoding="utf-8") as _handle:
    _after = _handle.read()
check("and the rewritten launcher still starts the title by id",
      "-r PCSA00011" in _after, True)
# The failure as the user met it: the game boots into Vita3K's interface,
# because the eboot path is an argument Vita3K does not treat as a game.
check("rather than handing it the eboot path",
      _eboot in _after.split("exec")[-1], False)

plugin.loop.close()


if __name__ == "__main__":
    summary()
