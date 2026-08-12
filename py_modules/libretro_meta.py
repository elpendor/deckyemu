"""Turn a ROM file path into a clean game name and a boxart URL.

Two problems, one solution. A file called `smw.sfc` or
`Super Mario World (USA) [!].smc` should end up in Steam as "Super Mario
World" with proper cover art, and both of those come from matching the file
against libretro's playlist naming.

Strategy, cheapest first:
  1. Try the filename verbatim against thumbnails.libretro.com.
  2. Try the de-tagged title with the usual No-Intro region suffixes.
  3. Fall back to fuzzy-matching the system's full boxart directory index,
     which is cached on disk so we pay for it at most once per system.
"""

import concurrent.futures
import difflib
import html
import json
import os
import re
import time
import urllib.parse

import decky

import net

THUMB_HOST = "https://thumbnails.libretro.com"
INDEX_CACHE_DIR = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "thumb_index")
INDEX_TTL_SECONDS = 30 * 24 * 60 * 60

# The libretro docs specify these characters are replaced with `_` in
# thumbnail filenames.
_ILLEGAL_CHARS = set('&*/:`<>?\\|')

# Region/dump tags we drop when building a display name.
_TAG_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_REGION_SUFFIXES = (
    "",
    " (USA)",
    " (World)",
    " (Europe)",
    " (Japan)",
    " (USA, Europe)",
    " (Japan, USA)",
    " (USA, Australia)",
    " (Europe, Australia)",
    " (Japan, Europe)",
    " (USA) (Rev 1)",
    " (Europe) (Rev 1)",
)
_ARTICLE_RE = re.compile(r"^(.*),\s*(The|A|An|Le|La|Les|Der|Die|Das|El|Los)$", re.IGNORECASE)


def sanitize_for_thumbnails(name):
    return "".join("_" if char in _ILLEGAL_CHARS else char for char in name)


def _fix_article(title):
    """`Legend of Zelda, The` -> `The Legend of Zelda`."""
    match = _ARTICLE_RE.match(title.strip())
    if match:
        return "%s %s" % (match.group(2), match.group(1))
    return title


def rom_stem(rom_path):
    return os.path.splitext(os.path.basename(rom_path))[0]


def display_title(name):
    """A clean, human name: no tags, no separators, articles the right way round."""
    title = _TAG_RE.sub("", name)
    title = title.replace("_", " ")
    # Dots are separators in `Super.Mario.Bros.nes` but punctuation in
    # `Super Mario Bros.`. Only treat them as separators when the name has no
    # spaces of its own, otherwise the trailing period is lost.
    if " " not in title.strip():
        title = title.replace(".", " ")
    title = re.sub(r"\s+", " ", title).strip(" -")

    # `Sonic - The Hedgehog` reads better with a colon, but only split on a
    # dash that is clearly a subtitle separator.
    parts = [part.strip() for part in title.split(" - ") if part.strip()]
    if len(parts) > 1:
        parts[0] = _fix_article(parts[0])
        title = "%s: %s" % (parts[0], " - ".join(parts[1:]))
    else:
        title = _fix_article(title)

    return title.strip()


# Spelling differences between ROM filenames and libretro's database. Without
# these, "Super Mario Brothers" only reaches "Super Mario Bros. (World)" through
# the weaker containment fallback, and scores every dump of the game equally.
_MATCH_SYNONYMS = (
    ("brothers", "bros"),
    ("brother", "bros"),
    (" and ", " "),
    ("&", " "),
)


def _normalize_for_match(name):
    stripped = _TAG_RE.sub("", name).lower()
    stripped = _fix_article(stripped.strip())
    for source, replacement in _MATCH_SYNONYMS:
        stripped = stripped.replace(source, replacement)
    return re.sub(r"[^a-z0-9]", "", stripped)


def _tag_count(name):
    """How many region/dump tags a name carries; fewer means more canonical."""
    return name.count("(") + name.count("[")


def boxart_url(system, name):
    quoted_system = urllib.parse.quote(system, safe="")
    quoted_name = urllib.parse.quote(sanitize_for_thumbnails(name) + ".png", safe="")
    return "%s/%s/Named_Boxarts/%s" % (THUMB_HOST, quoted_system, quoted_name)


def _candidate_names(stem):
    """Names worth trying directly, in order, without any network listing."""
    candidates = []

    def push(value):
        value = value.strip()
        if value and value not in candidates:
            candidates.append(value)

    push(stem)
    # Drop `[!]`-style dump flags but keep `(USA)`-style region info.
    push(re.sub(r"\s*\[[^\]]*\]", "", stem))

    bare = _TAG_RE.sub("", stem).replace("_", " ")
    bare = re.sub(r"\s+", " ", bare).strip(" -")
    for suffix in _REGION_SUFFIXES:
        push(bare + suffix)

    # Some collections store `The Legend of Zelda` where libretro has
    # `Legend of Zelda, The`.
    match = re.match(
        r"^(The|A|An)\s+(.*)$", bare, re.IGNORECASE
    )
    if match:
        swapped = "%s, %s" % (match.group(2), match.group(1))
        for suffix in _REGION_SUFFIXES:
            push(swapped + suffix)

    return candidates


# How many thumbnail probes to have in flight at once.
#
# Each candidate name is its own HEAD request on its own connection -- urllib
# keeps none alive -- and _candidate_names produces twelve for a plain filename
# and two dozen for one starting with an article. Serially, at a couple of
# hundred milliseconds each over wifi, that is most of the wait behind "Looking
# up name and artwork".
#
# Probed in waves rather than all at once, so a hit near the front does not pay
# for the whole tail. The first wave usually answers, because the first
# candidate is the filename verbatim and a No-Intro name matches it outright.
_PROBE_WORKERS = 6


def _first_existing(urls):
    """Index of the first URL in `urls` that exists, or -1.

    Order is the whole point: candidates arrive best-guess first, so that
    ordering *is* the match quality. Results are therefore read back in
    submission order and never in the order they happened to come home --
    a later, worse name answering sooner must not win.
    """
    if not urls:
        return -1

    with concurrent.futures.ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as pool:
        for start in range(0, len(urls), _PROBE_WORKERS):
            wave = urls[start:start + _PROBE_WORKERS]
            # Executor.map yields in submission order, not completion order.
            for offset, exists in enumerate(pool.map(net.head_ok, wave)):
                if exists:
                    return start + offset
    return -1


def _index_cache_path(system):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", system)
    return os.path.join(INDEX_CACHE_DIR, safe + ".json")


def _load_cached_index(system):
    path = _index_cache_path(system)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if time.time() - payload.get("fetched_at", 0) > INDEX_TTL_SECONDS:
            return None
        names = payload.get("names")
        return names if isinstance(names, list) else None
    except (OSError, ValueError):
        return None


def _store_cached_index(system, names):
    os.makedirs(INDEX_CACHE_DIR, exist_ok=True)
    path = _index_cache_path(system)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "names": names}, handle)
    except OSError as error:
        decky.logger.warning("Could not cache thumbnail index: %s", error)


_HREF_RE = re.compile(r'<a href="([^"?/][^"]*\.png)"', re.IGNORECASE)

# The disk cache spares us the network, but not the open + json.load: an index is
# read once per system per search, and again by resolve's fallback, which is a
# measurable cost on the big systems (MAME's index is tens of thousands of names).
# Held per process and dropped on unload, so the on-disk TTL still decides how
# long an index is trusted across sessions.
_memory_index: dict = {}


def forget_cached_indexes():
    """Drop the in-process index cache. For tests, and for a settings reset."""
    _memory_index.clear()


def fetch_boxart_index(system):
    """Every boxart filename for `system`, from the server's directory index."""
    remembered = _memory_index.get(system)
    if remembered is not None:
        return remembered

    cached = _load_cached_index(system)
    if cached is not None:
        _memory_index[system] = cached
        return cached

    url = "%s/%s/Named_Boxarts/" % (THUMB_HOST, urllib.parse.quote(system, safe=""))
    payload, _ = net.get_bytes(url, max_bytes=32 * 1024 * 1024)
    if not payload:
        return []

    listing = payload.decode("utf-8", errors="replace")
    names = []
    for href in _HREF_RE.findall(listing):
        decoded = html.unescape(urllib.parse.unquote(href))
        if decoded.lower().endswith(".png"):
            names.append(decoded[:-4])

    if names:
        # Only a non-empty index is worth keeping, on disk or in memory. An empty
        # one means the listing failed, and remembering that would turn a moment
        # without a network into "this system has no artwork" for the whole session.
        _store_cached_index(system, names)
        _memory_index[system] = names
    decky.logger.info("Indexed %d boxarts for %s", len(names), system)
    return names


def _fuzzy_match(stem, names):
    """Best index entry for `stem`, or None."""
    if not names:
        return None

    target = _normalize_for_match(stem)
    if not target:
        return None

    buckets = {}
    for name in names:
        buckets.setdefault(_normalize_for_match(name), name)

    # An exact normalized hit is the common case: same game, different tags.
    if target in buckets:
        return buckets[target]

    close = difflib.get_close_matches(target, list(buckets.keys()), n=1, cutoff=0.9)
    if close:
        return buckets[close[0]]

    # Short filenames like `smw` should not fuzzily grab an unrelated game, so
    # only accept containment when the stem is substantial.
    if len(target) >= 8:
        for normalized, original in buckets.items():
            if normalized.startswith(target) or target.startswith(normalized):
                return original

    return None


def index_candidates(databases, query, limit=10):
    """Plausible libretro boxart names for `query`, best first.

    Powers the manual picker, so the user can correct a bad automatic match
    without needing a SteamGridDB key.
    """
    target = _normalize_for_match(query)
    if not target or not databases:
        return []

    # Reused across every name so difflib's cheap upper bounds can be consulted
    # before the real comparison. `target` is seq1 because SequenceMatcher.ratio()
    # is *not* symmetric -- swapping the two arguments changes which names come
    # back, so the orientation here has to stay the way the scoring below reads.
    matcher = difflib.SequenceMatcher()
    matcher.set_seq1(target)

    results = []
    for system in databases:
        names = fetch_boxart_index(system)
        if not names:
            continue

        # A system holds many dumps of the same game -- PlayChoice-10, bad-dump
        # flags, date-stamped variants. Showing five of those instead of five
        # different games makes the picker useless, so collapse them and keep
        # the most canonical-looking name for each.
        best_per_game = {}
        for name in names:
            normalized = _normalize_for_match(name)
            if not normalized:
                continue
            if normalized == target:
                score = 1.0
            elif target in normalized or normalized in target:
                # Substring hits are usually the right game with extra tags.
                score = 0.9
            else:
                # real_quick_ratio and quick_ratio are guaranteed upper bounds on
                # ratio(), and cost a fraction of it. A name they place under the
                # cutoff cannot reach it for real, so rejecting here drops nothing
                # the full comparison would have kept -- it only skips computing a
                # score that was going to be discarded. Worth it because this loop
                # runs over every name in the system: MAME's index is ~30,000.
                matcher.set_seq2(normalized)
                if matcher.real_quick_ratio() < 0.5 or matcher.quick_ratio() < 0.5:
                    continue
                score = matcher.ratio()
            if score < 0.5:
                continue

            existing = best_per_game.get(normalized)
            rank = (_tag_count(name), len(name), name)
            if existing is None or rank < existing[1]:
                best_per_game[normalized] = ((score, name), rank)

        scored = [entry[0] for entry in best_per_game.values()]
        scored.sort(key=lambda item: (-item[0], _tag_count(item[1]), len(item[1]), item[1]))
        for score, name in scored[:limit]:
            results.append(
                {
                    "name": name,
                    "system": system,
                    "score": round(score, 4),
                    "url": boxart_url(system, name),
                }
            )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def resolve(rom_path, databases, allow_index=True):
    """Find a canonical name + boxart for a ROM.

    Returns a dict with `title`, `boxart_url`, `system`, `matched_name` and
    `match_kind` ('exact' | 'index' | 'none'). `title` is always usable, even
    when no artwork was found.
    """
    stem = rom_stem(rom_path)
    fallback = {
        "title": display_title(stem),
        "boxart_url": "",
        "system": databases[0] if databases else "",
        "matched_name": "",
        "match_kind": "none",
    }

    if not databases:
        return fallback

    candidates = _candidate_names(stem)
    for system in databases:
        urls = [boxart_url(system, candidate) for candidate in candidates]
        index = _first_existing(urls)
        if index >= 0:
            return {
                "title": display_title(candidates[index]),
                "boxart_url": urls[index],
                "system": system,
                "matched_name": candidates[index],
                "match_kind": "exact",
            }

    if allow_index:
        for system in databases:
            match = _fuzzy_match(stem, fetch_boxart_index(system))
            if match:
                return {
                    "title": display_title(match),
                    "boxart_url": boxart_url(system, match),
                    "system": system,
                    "matched_name": match,
                    "match_kind": "index",
                }

    return fallback
