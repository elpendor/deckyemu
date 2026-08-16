"""Optional SteamGridDB lookups, for art that is actually shaped like Steam art.

libretro boxarts are box-shaped, so they letterbox inside Steam's 600x900
portrait capsule. When the user supplies an API key we can do better and pull
purpose-made capsules, heroes and logos.
"""

import concurrent.futures
import difflib
import glob
import json
import os
import re
import time
import urllib.parse

import decky

import net

API_BASE = "https://www.steamgriddb.com/api/v2"

# SteamGridDB keys are long alphanumeric strings. Used to spot one in a config
# file without relying on a particular field name.
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")

# Deliberately strict. A bare "key" substring would also match hotkey/keybind
# fields, and importing the wrong value silently would be worse than not
# offering the import at all.
_KEY_FIELD_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "sgdb_api_key",
    "sgdbapikey",
    "steamgriddb_api_key",
    "token",
    "api_token",
}


def _is_key_field(leaf):
    leaf = leaf.lower()
    return leaf in _KEY_FIELD_NAMES or ("api" in leaf and "key" in leaf)


def _looks_like_key(value):
    return isinstance(value, str) and bool(_KEY_RE.match(value.strip()))


def _search_json_for_key(payload):
    """Depth-first search for a plausible API key in a parsed config file."""
    stack = [("", payload)]
    while stack:
        path, node = stack.pop()
        if isinstance(node, dict):
            for name, value in node.items():
                stack.append(("%s/%s" % (path, name), value))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                stack.append(("%s/%d" % (path, index), value))
        elif _looks_like_key(node) and _is_key_field(path.rsplit("/", 1)[-1]):
            return node.strip(), path
    return "", ""


def discover_existing_key():
    """Look for a SteamGridDB key already stored by another decky plugin.

    Saves the user typing a long key on a touchscreen keyboard. Only reads
    plugin settings under DECKY_HOME, and is only ever called when the user
    explicitly asks to import.
    """
    settings_root = os.path.join(decky.DECKY_HOME, "settings")
    candidates = []
    for name in ("decky-steamgriddb", "SteamGridDB", "steamgriddb"):
        candidates.extend(glob.glob(os.path.join(settings_root, name, "*.json")))

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        key, field = _search_json_for_key(payload)
        if key:
            decky.logger.info("Found a candidate API key in %s (%s)", path, field)
            return {"key": key, "source": os.path.basename(os.path.dirname(path))}

    return {"key": "", "source": ""}


def _headers(api_key):
    return {"Authorization": "Bearer %s" % api_key}


def _first_url(payload):
    """The best usable image in a SteamGridDB listing, skipping locked ones.

    A locked asset is one SteamGridDB has taken down. It is not removed from
    the listing and its URL does not fail: it serves a placeholder saying the
    asset was removed following a DMCA request, at the dimensions the real
    artwork had. So it downloads cleanly and passes every check we have, and
    the game ends up in Steam wearing a notice instead of a cover.

    Measured against SteamGridDB on 2026-08-12, over four Mario games: 51 of
    322 assets carried lock, every locked one was a 10-13 KB PNG, and locked
    assets of the same dimensions were byte-identical to each other, while real
    artwork ran 500-650 KB. One placeholder, served for all of them.

    `lock` is what the API says, so it is what is trusted here -- the file size
    tells the same story but would refuse genuinely small artwork too. Skipping
    a locked entry falls through to the next candidate, and a slot where every
    candidate is locked comes back empty, which sends the caller to libretro's
    thumbnail exactly as an empty listing would.
    """
    if not payload or not payload.get("success"):
        return ""
    data = payload.get("data") or []
    for item in data:
        url = item.get("url")
        if url and not item.get("lock"):
            return url
    return ""


# SteamGridDB's autocomplete is fuzzy and its first result is often wrong:
# searching "Super Mario Brothers" returns "Super Mario Galaxy 2" ahead of the
# actual NES game, and "Legend of Zelda" returns "Four Swords Adventures".
# Taking data[0] therefore produces confidently wrong artwork, so candidates are
# scored and a weak best match is rejected in favour of libretro's thumbnail.
_MIN_SCORE = 0.82

# Words that differ between ROM filenames and SteamGridDB titles.
_TITLE_SYNONYMS = (
    ("brothers", "bros"),
    ("brother", "bros"),
    (" and ", " "),
    ("&", " "),
    ("the ", " "),
)

# SteamGridDB has no console filter -- its `types` field lists stores (eshop,
# steam, egs), not hardware. Release date is the usable proxy: a 2010 game is
# not an NES title. Windows are deliberately generous, covering late releases
# and homebrew, and an unknown system imposes no constraint at all.
_SYSTEM_ERAS = {
    "Nintendo - Nintendo Entertainment System": (1983, 1996),
    "Nintendo - Family Computer Disk System": (1986, 1993),
    "Nintendo - Super Nintendo Entertainment System": (1990, 2002),
    "Nintendo - Nintendo 64": (1996, 2003),
    "Nintendo - Game Boy": (1989, 2000),
    "Nintendo - Game Boy Color": (1998, 2003),
    "Nintendo - Game Boy Advance": (2001, 2009),
    "Nintendo - Nintendo DS": (2004, 2014),
    "Nintendo - GameCube": (2001, 2008),
    "Nintendo - Wii": (2006, 2013),
    "Sega - Master System - Mark III": (1985, 1996),
    "Sega - Mega Drive - Genesis": (1988, 1999),
    "Sega - Game Gear": (1990, 1998),
    "Sega - Saturn": (1994, 2001),
    "Sega - Dreamcast": (1998, 2003),
    "Sony - PlayStation": (1994, 2006),
    "Sony - PlayStation 2": (2000, 2014),
    "Sony - PlayStation Portable": (2004, 2015),
    "NEC - PC Engine - TurboGrafx 16": (1987, 1996),
    "Atari - 2600": (1977, 1992),
    "Atari - 7800": (1986, 1992),
    "SNK - Neo Geo": (1990, 2005),
}

# Years of slack before a release date counts against a candidate.
_ERA_GRACE = 3


_TAG_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def _normalize_title(value):
    # Region and dump tags must come off first, or "Super Mario Bros. (World)"
    # scores only 0.85 against "Super Mario Bros." and sits far too close to the
    # rejection threshold.
    text = _TAG_RE.sub("", value or "").lower()
    for source, replacement in _TITLE_SYNONYMS:
        text = text.replace(source, replacement)
    return re.sub(r"[^a-z0-9]", "", text)


def _era_penalty(release_date, databases):
    """How badly a candidate's release date contradicts the ROM's system."""
    if not release_date or not databases:
        return 0.0

    window = None
    for database in databases:
        if database in _SYSTEM_ERAS:
            window = _SYSTEM_ERAS[database]
            break
    if window is None:
        return 0.0

    try:
        # SteamGridDB reports release dates as unix seconds.
        year = time.gmtime(int(release_date)).tm_year
    except (TypeError, ValueError, OSError, OverflowError):
        return 0.0

    start, end = window
    if start - _ERA_GRACE <= year <= end + _ERA_GRACE:
        return 0.0

    # Scale with the size of the discrepancy so a slightly-late re-release is
    # tolerated while a two-decade gap is not.
    distance = year - end if year > end else start - year
    return min(0.5, 0.03 * distance)


def _query_variants(title, matched_name):
    """Search terms worth trying, best first, deduplicated."""
    variants = []
    for candidate in (matched_name, title):
        if not candidate:
            continue
        cleaned = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", candidate).strip()
        for value in (cleaned, candidate):
            if value and value not in variants:
                variants.append(value)

    # "Super Mario Brothers" finds the wrong game; "Super Mario Bros" does not.
    expanded = []
    for value in variants:
        swapped = re.sub(r"\bbrothers\b", "Bros.", value, flags=re.IGNORECASE)
        if swapped != value and swapped not in variants:
            expanded.append(swapped)
    variants.extend(expanded)

    return variants[:4]


def _autocomplete(api_key, term):
    url = "%s/search/autocomplete/%s" % (API_BASE, urllib.parse.quote(term, safe=""))
    payload = net.get_json(url, _headers(api_key))
    if not payload or not payload.get("success"):
        return []
    return payload.get("data") or []


def search_candidates(api_key, title, databases=None, matched_name="", limit=10):
    """Scored SteamGridDB candidates, best first.

    Used both to pick a match automatically and to populate the manual picker
    when the automatic choice is wrong.
    """
    if not api_key:
        return []

    target = _normalize_title(matched_name or title)
    if not target:
        return []

    scored = {}
    for term in _query_variants(title, matched_name):
        # An exact normalized match cannot be beaten, so stop paying for extra
        # requests once one is in hand -- unless the caller wants a full list to
        # choose from.
        if limit <= 1 and any(item["score"] >= 0.999 for item in scored.values()):
            break

        for candidate in _autocomplete(api_key, term):
            game_id = candidate.get("id")
            name = candidate.get("name") or ""
            if not game_id or game_id in scored or not name:
                continue

            normalized = _normalize_title(name)
            if not normalized:
                continue
            if normalized == target:
                similarity = 1.0
            else:
                similarity = difflib.SequenceMatcher(None, target, normalized).ratio()

            release = candidate.get("release_date")
            year = 0
            try:
                if release:
                    year = time.gmtime(int(release)).tm_year
            except (TypeError, ValueError, OSError, OverflowError):
                year = 0

            scored[game_id] = {
                "id": game_id,
                "name": name,
                "year": year,
                "score": round(similarity - _era_penalty(release, databases), 4),
            }

    ranked = sorted(scored.values(), key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def search_game(api_key, title, databases=None, matched_name=""):
    """Best SteamGridDB game for a ROM, or 0 when nothing matches well enough.

    Returning 0 is a feature: the caller falls back to libretro's thumbnail,
    which is far better than confident artwork for the wrong game.
    """
    if not api_key or not title:
        return 0

    ranked = search_candidates(api_key, title, databases, matched_name, limit=1)
    if not ranked:
        decky.logger.info("SteamGridDB: no candidates for %r", title)
        return 0

    best = ranked[0]
    if best["score"] < _MIN_SCORE:
        decky.logger.info(
            "SteamGridDB: rejected best match %r (score %.2f) for %r; using libretro instead",
            best["name"],
            best["score"],
            matched_name or title,
        )
        return 0

    decky.logger.info(
        "SteamGridDB: matched %r (id=%s, score %.2f) for %r",
        best["name"],
        best["id"],
        best["score"],
        matched_name or title,
    )
    return best["id"]


def game_name(api_key, game_id):
    """The SteamGridDB title for `game_id`, for showing which game art came from."""
    if not api_key or not game_id:
        return ""
    payload = net.get_json("%s/games/id/%d" % (API_BASE, game_id), _headers(api_key))
    if not payload or not payload.get("success"):
        return ""
    data = payload.get("data") or {}
    return data.get("name") or ""


# The four artwork slots: the endpoint each comes from, the query that asks for
# the shape Steam wants, and a second query to try when the first finds nothing.
#
# The wide one is asked for at both of SteamGridDB's horizontal sizes, and that
# is not a widening of the net -- 920x430 is 460x215 at twice the resolution,
# the identical aspect. Asking for the small one alone meant a game with only
# large wide grids had none at all: Gravity Rush has ten, every one 920x430, and
# the panel showed no wide capsule for it while a perfect title match sat in the
# log. Mario Tennis happened to have both sizes, which is why this looked fine.
#
# The capsule keeps 600x900 as the ask, because that is Steam's own shape and
# there are usually dozens. The other two vertical sizes SteamGridDB publishes
# are a slightly taller ratio, so they are a fallback rather than a peer: worth
# having when the alternative is no cover, not worth preferring over the right
# shape. `capsuleFit` redraws whatever arrives to fit.
_ART_SLOTS = (
    ("capsule", "grids", "?dimensions=600x900&types=static",
     "?dimensions=342x482,660x930&types=static"),
    ("header", "grids", "?dimensions=460x215,920x430&types=static", ""),
    ("hero", "heroes", "?types=static", ""),
    ("logo", "logos", "?types=static", ""),
)


def art_urls(api_key, game_id):
    """{capsule, header, hero, logo} URLs; any of them may be empty."""
    if not api_key or not game_id:
        return {}

    def fetch(slot):
        _name, path, query, fallback = slot

        def ask(where):
            url = "%s/%s/game/%d%s" % (API_BASE, path, game_id, where)
            return _first_url(net.get_json(url, _headers(api_key)))

        # The fallback costs a second round trip and only pays it when the first
        # asked for a shape this game does not have, which is the case where the
        # alternative is an empty slot.
        return ask(query) or (ask(fallback) if fallback else "")

    # Four independent lookups that tell each other nothing. Run one after
    # another they stack four round trips to steamgriddb.com in front of the
    # image downloads that follow, all of it inside the wait for one cover.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_ART_SLOTS)) as pool:
        found = list(pool.map(fetch, _ART_SLOTS))

    art = {slot[0]: url for slot, url in zip(_ART_SLOTS, found) if url}
    decky.logger.info(
        "SteamGridDB art for %d: %s",
        game_id,
        ", ".join(art.keys()) or "none",
    )
    return art
