#!/usr/bin/env python3
"""The platform picked on the upload page, from the request to the probe.

    python scripts/tests/test_system_hint.py

Only formats several systems share need it, so it is a hint: kept by path,
read where a system-named folder would be, and dropped when it names a system
the page never offered.
"""

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import fileserver  # noqa: E402
import fileserver_page  # noqa: E402
import systemhint  # noqa: E402

_DIR = os.path.join(TMP, "system-hint")
os.makedirs(_DIR, exist_ok=True)

_OFFERED = [("Sony - PlayStation 2", "PS2"), ("Sega - Saturn", "Saturn")]


section("the store")

_one = os.path.join(_DIR, "a.chd")
with open(_one, "wb") as handle:
    handle.write(b"x")
check("nothing is known about a file nobody hinted", systemhint.hint_for(_one), "")
systemhint.remember(_one, "Sega - Saturn")
check("a hint is read back by path", systemhint.hint_for(_one), "Sega - Saturn")
check("and labelled for a row", systemhint.label_for(_one), "Saturn")
systemhint.remember(_one, "Sony - PlayStation 2")
check("a second pick right after replaces the first", systemhint.label_for(_one), "PS2")
os.remove(_one)
_two = os.path.join(_DIR, "b.chd")
with open(_two, "wb") as handle:
    handle.write(b"x")
systemhint.remember(_two, "Sony - PlayStation 2")
check("a hint for a file that has gone is dropped on the next write",
      _one in str(systemhint._read()), False)


section("what the page offers")

_cores = [
    {"id": "pcsx2_libretro", "databases": ["Sony - PlayStation 2"]},
    {"id": "genesis_plus_gx_libretro",
     "databases": ["Sega - Mega Drive - Genesis", "Sega - Game Gear"]},
    {"id": "other_libretro", "databases": ["Sony - PlayStation 2"]},
]
_listed = systemhint.systems_for(_cores)
check("each system once, sorted by label",
      [label for _db, label in _listed],
      sorted({label for _db, label in _listed}, key=str.lower))
check("a system two cores cover is listed once",
      [db for db, _label in _listed].count("Sony - PlayStation 2"), 1)

_odd = dict(systemhint.systems_for([
    {"id": "a_libretro", "databases": ["Apple - II"]},
    {"id": "b_libretro", "databases": ["MAME", "FBNeo - Arcade Games"]},
]))
check("a system with no short name keeps its full name", _odd["Apple - II"], "Apple - II")
check("two systems one label apart are told apart",
      (_odd["MAME"], _odd["FBNeo - Arcade Games"]), ("MAME", "FBNeo - Arcade Games"))

_page = fileserver_page.upload_page(_DIR, [], "tok", False, False,
                                    [("Sega - <Test>", "A & B")])
check("the dropdown is on the page", 'id="platform"' in _page, True)
check("detecting stays the default", '<option value="">Detect' in _page, True)
check("names are escaped", "Sega - &lt;Test&gt;" in _page and "A &amp; B" in _page, True)
check("no dropdown when nothing is installed",
      'id="platform"' in fileserver_page.upload_page(_DIR, [], "tok", False, False), False)


section("systems not installed yet")

systemhint.learn_catalog([
    {"id": "picodrive_libretro", "databases": ["Sega - Mega Drive - Genesis"]},
    {"id": "pcsx2_libretro", "databases": ["Sony - PlayStation 2"]},
])
_both = systemhint.offered([{"id": "pcsx2_libretro", "databases": ["Sony - PlayStation 2"]}])
check("installed first, then the rest, each once",
      [(db, installed) for db, _label, installed in _both],
      [("Sony - PlayStation 2", True), ("Sega - Mega Drive - Genesis", False)])
_grouped = fileserver_page.upload_page(_DIR, [], "tok", False, False, _both)
check("the two groups are labelled",
      'label="Installed"' in _grouped and 'label="Not installed yet"' in _grouped, True)
check("one group needs no labels",
      "optgroup" in fileserver_page.upload_page(_DIR, [], "tok", False, False, _OFFERED), False)
systemhint.learn_catalog([])


section("an upload carries it")


def _put(base, name, system):
    request = urllib.request.Request(
        "%s/upload/%s" % (base, urllib.parse.quote(name)), data=b"game", method="PUT")
    request.add_header("X-Upload-Id", name)
    request.add_header("X-Upload-Offset", "0")
    request.add_header("X-Upload-Restart", "1")
    if system:
        request.add_header("X-Upload-System", system)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


fileserver.set_systems_source(lambda: _OFFERED)
_state = fileserver.start(_DIR)
check("the server started", _state.get("error", ""), "")
_BASE = "http://127.0.0.1:%d/%s" % (_state["port"], fileserver._token)
try:
    check("a hinted upload lands", _put(_BASE, "Game One.chd", "Sega - Saturn"), 200)
    check("and its platform is kept",
          systemhint.hint_for(os.path.join(_DIR, "Game One.chd")), "Sega - Saturn")
    check("a reload still says which platform it went as",
          'for Saturn</div>' in fileserver._page(), True)
    check("an upload without one lands too", _put(_BASE, "Game Two.chd", ""), 200)
    check("and has none", systemhint.hint_for(os.path.join(_DIR, "Game Two.chd")), "")
    fileserver.set_systems_source(lambda: [(db, label, False) for db, label in _OFFERED])
    check("a platform not installed yet is kept too",
          (_put(_BASE, "Game Four.chd", "Sega - Saturn"),
           systemhint.hint_for(os.path.join(_DIR, "Game Four.chd"))), (200, "Sega - Saturn"))
    check("a platform the page never offered is ignored",
          (_put(_BASE, "Game Three.chd", "Made - Up"),
           systemhint.hint_for(os.path.join(_DIR, "Game Three.chd"))), (200, ""))
finally:
    fileserver.stop()
    fileserver.set_systems_source(None)

if __name__ == "__main__":
    summary()
