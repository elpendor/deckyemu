#!/usr/bin/env python3
"""Ask SteamGridDB for every size of the shape Steam wants, not one of them.

    python scripts/tests/test_art_dimensions.py

SteamGridDB publishes wide grids at 460x215 and at 920x430. They are the same
aspect -- the second is the first at twice the resolution -- and the plugin
asked only for the small one. A game whose wide grids are all 920x430 therefore
had none at all: Gravity Rush has ten, and the panel showed no wide capsule for
it while "matched 'Gravity Rush' (score 1.00)" sat in the log two lines above
"art for 5254322: capsule, hero, logo".

Nothing failed, which is why it went unnoticed. Mario Tennis has both sizes.

These checks are on the queries rather than on the network -- the live suite
covers the fetching. What broke here was what we asked for.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402  -- installs the decky stub

import sgdb  # noqa: E402

section("SteamGridDB -- the wide slot asks for both wide sizes")

_slots = {name: (query, fallback) for name, _path, query, fallback in sgdb._ART_SLOTS}


def _dimensions(query):
    found = re.search(r"dimensions=([^&]*)", query)
    return found.group(1).split(",") if found else []


_header_query, _header_fallback = _slots["header"]
check("the wide slot asks for both sizes SteamGridDB publishes",
      sorted(_dimensions(_header_query)), ["460x215", "920x430"])
# Same aspect at twice the resolution, so this is not a looser match -- it is
# the same shape, and asking for one of the two was the bug.
check("which are the same shape as each other",
      [round(int(w) / int(h), 3) for w, h in
       (d.split("x") for d in _dimensions(_header_query))],
      [2.14, 2.14])
check("and needs no fallback, having asked for everything", _header_fallback, "")

section("SteamGridDB -- the cover keeps Steam's own shape as the ask")

_capsule_query, _capsule_fallback = _slots["capsule"]
# 600x900 is what Steam draws and there are usually dozens. The other vertical
# sizes are a taller ratio, so preferring them over the right shape would trade
# a correct cover for a redrawn one.
check("the cover asks for Steam's shape first", _dimensions(_capsule_query), ["600x900"])
check("with the other vertical sizes only as a fallback",
      sorted(_dimensions(_capsule_fallback)), ["342x482", "660x930"])
check("and the fallback is a different shape, which is why it is second",
      round(342 / 482, 2) != round(600 / 900, 2), True)

section("SteamGridDB -- every slot is still well formed")

for _name, _path, _query, _fallback in sgdb._ART_SLOTS:
    check("%s asks only for static images" % _name, "types=static" in _query, True)
    # A fallback that repeats the query is two round trips for one answer.
    check("%s does not ask the same thing twice" % _name, _fallback == _query, False)

check("every slot has somewhere to fetch from",
      sorted({path for _n, path, _q, _f in sgdb._ART_SLOTS}), ["grids", "heroes", "logos"])


if __name__ == "__main__":
    from harness import summary

    summary()
