#!/usr/bin/env python3
"""A port's artwork is the port's, and its name is still the game's.

    python scripts/tests/test_port_art.py

A native port has its own SteamGridDB entry, with covers drawn for the port
rather than scanned from the original box -- and that is what is running. So the
lookup asks for the port's name first.

Exact matches only. These names collide: "Starship" returns three unrelated
games, and "Dusklight" also matches "Pitch Black: A Dusklight Story". The fuzzy
scoring that suits a ROM filename would take one of those, confidently.

Every port and every game here is made up.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import sgdb  # noqa: E402

_ANSWERS = {}


def _fake_autocomplete(api_key, term):
    return _ANSWERS.get(term, [])


section("a port is matched on its own name, exactly")

_real = sgdb._autocomplete
sgdb._autocomplete = _fake_autocomplete
try:
    _ANSWERS["Some Port"] = [
        {"id": 111, "name": "Some Portal Story"},
        {"id": 222, "name": "Some Port"},
        {"id": 333, "name": "Some Port II"},
    ]
    check("the entry whose name is the port's is taken, wherever it sits",
          sgdb.search_exact("key", "Some Port"), 222)

    # Punctuation and case are not the difference between two names.
    _ANSWERS["Zelda 64 Recompiled"] = [{"id": 444, "name": "Zelda 64: Recompiled"}]
    check("punctuation and case do not separate a name from itself",
          sgdb.search_exact("key", "Zelda 64 Recompiled"), 444)

    # The case this exists for: a name that only half matches.
    _ANSWERS["Starship"] = [
        {"id": 555, "name": "Starship Corporation"},
        {"id": 666, "name": "Starship Troopers"},
    ]
    check("a near miss is refused rather than taken",
          sgdb.search_exact("key", "Starship"), 0)

    # A space is what separates two names. Dropping it made "Ghost Ship",
    # somebody else's game, an exact match for the port called "Ghostship", and
    # a Super Mario 64 shortcut wore its cover.
    _ANSWERS["Ghostship"] = [{"id": 777, "name": "Ghost Ship"}]
    check("a name that differs only by a space is a different game",
          sgdb.search_exact("key", "Ghostship"), 0)

    # Three games really are called Starship, and the first of them was taken --
    # it had no artwork at all, so the port got none and nobody could see which
    # entry had been picked. A name several games share names none of them.
    _ANSWERS["Shared Name"] = [
        {"id": 888, "name": "Shared Name"},
        {"id": 999, "name": "Shared name"},
    ]
    check("a name several entries share matches none of them",
          sgdb.search_exact("key", "Shared Name"), 0)

    check("nothing found is not an error", sgdb.search_exact("key", "Unheard Of"), 0)
    check("and no key means no lookup", sgdb.search_exact("", "Some Port"), 0)
finally:
    sgdb._autocomplete = _real


section("the shortcut names the game and the port")

# The game, because that is what somebody looks for; the port, because that is
# what runs and what the artwork is of. Two dumps on one port stay apart, which
# the port's name alone would not manage.
def _named(title, port_name, title_source="libretro", plays=""):
    """What `resolve_game` does to a title once the port is known."""
    if port_name and title_source == "filename":
        return ("%s (%s)" % (plays, port_name) if plays else port_name), "port"
    if port_name and port_name.lower() not in title.lower():
        return "%s (%s)" % (title, port_name), title_source
    return title, title_source


check("the port is added in brackets",
      _named("Some Game", "Some Port")[0], "Some Game (Some Port)")
check("a title that already says it is left alone",
      _named("Some Port", "Some Port")[0], "Some Port")
check("and an emulator's game keeps its own name",
      _named("Some Game", "")[0], "Some Game")

# Nothing recognised the file, so the name was its stem. A port plays one known
# game, and `spawn.mpq` became "spawn (DevilutionX)" where the game is
# DevilutionX.
check("a file nothing recognised is named after the port",
      _named("spawn", "Some Port", "filename"), ("Some Port", "port"))
# And reads like every other port's shortcut when the entry says which game it
# plays, which is the only thing that knows: no filename, no database and no
# search can tell that a data file belongs to one.
check("with the game in front when the entry names it",
      _named("spawn", "Some Port", "filename", "Some Game"),
      ("Some Game (Some Port)", "port"))


section("the panel is told one of the three words it knows")

# The panel compares this string exactly. A fourth spelling for the port case
# read better in the log and labelled SteamGridDB artwork as libretro on screen.
import re  # noqa: E402 -- only this check needs it

_main = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "main.py"), encoding="utf-8").read()
_assigned = set(re.findall(r'source_used = "([^"]*)"', _main))
check("nothing else is ever assigned to it", sorted(_assigned),
      ["libretro", "none", "steamgriddb"])

# The same trap for the name: the panel has a label per source, and a value it
# does not know shows nothing at all.
_LABELLED = {"libretro", "steamgriddb", "filename", "port"}
_panel = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src", "AddGamePanel.tsx"),
    encoding="utf-8").read()
_block = _panel.split("NAME_SOURCE_LABELS")[1].split("};")[0]
_labels = set(re.findall(r"^  ([a-z]+):", _block, re.M))
check("every name source the panel knows is one the backend sends",
      _labels, _LABELLED)
check("and the backend sends no other",
      set(re.findall(r'title_source = "([^"]*)"', _main)) - _LABELLED, set())


if __name__ == "__main__":
    summary()
