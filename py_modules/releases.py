"""Find out whether a newer DeckyEmu has been released.

Not called `updater`: decky_loader has a module by that name, and since py_modules
is appended to a sys.path that already holds decky's packages, `import updater`
resolved to theirs. Everything loaded and only the update check failed, with
"module 'decky_loader.updater' has no attribute 'check'".

This module only *looks*. Installing is decky's job: its loader runs as root and
already knows how to download a plugin zip, verify it, unpack it into
~/homebrew/plugins and reload the result. This plugin's backend runs as `deck` and
cannot write its own directory, so anything else would mean either a privileged
helper or asking the user to loosen permissions on the plugin folder.

The frontend passes what is found here to decky's `utilities/install_plugin`
route. See src/updater.ts for that half.

Releases come from the GitHub API, which needs no credentials to read a public
repository. There was a stored token here for the period when this repository
was private; it is gone, along with the settings entry it lived in. Nothing this
module reaches is authenticated, which is why it can say so plainly when GitHub
does not answer instead of having to wonder whether a token was wrong.
"""

import json
import os
import re
import threading
import time

import decky

import net

REPO = "elpendor/deckyemu"
RELEASES_URL = "https://api.github.com/repos/%s/releases" % REPO

# GitHub allows 60 unauthenticated requests an hour per address. One check an hour
# leaves that budget almost untouched even with the panel opened repeatedly.
CACHE_SECONDS = 60 * 60

#: Where a successful check is kept, so a restart does not repeat it.
#:
#: The cache below is module state, and decky restarts this backend every time
#: the plugin's files change -- so without a copy on disk the hour it promises
#: only lasts as long as the process. That was survivable while the only caller
#: was a button somebody pressed; it is not, now that opening the panel asks.
#:
#: Only a successful fetch is written. A failure kept for an hour would be a
#: check that refuses to retry, which is the opposite of what a cache is for.
CACHE_PATH = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "releases.json")

#: Bumped when the shape of a cached release changes. An older file is ignored
#: rather than migrated: it is a cache, so the cost of throwing it away is one
#: request, and the cost of reading a stale shape is a crash in the panel.
CACHE_FORMAT = 1

# CI writes this line into the release body so the download can be verified.
_SHA256_RE = re.compile(r"sha256:\s*([0-9a-f]{64})", re.IGNORECASE)

# `ok` is whether the last request *succeeded*, which is not the same as whether
# it found anything. A repository with no releases yet returns an empty list, and
# reporting that as a failure told the user GitHub was unreachable when it had
# answered perfectly.
_cache = {"at": 0.0, "releases": [], "ok": False, "error": "Not checked yet.",
          "failed_at": 0.0}

#: How long a *failed* check waits before going back to GitHub.
#:
#: Separate from CACHE_SECONDS, and much shorter, because the two are answers to
#: different questions. A success is worth keeping for an hour; a failure is
#: worth not repeating for a few minutes.
#:
#: Without it a failure was not recorded at all, so the next call went straight
#: back out. That was invisible while the only caller was a button, and became a
#: hole the moment the panel started asking: somebody being rate-limited -- 60
#: an hour shared by an address, which a household reaches without doing
#: anything wrong -- would spend a request on every panel open, which is exactly
#: what keeps them rate-limited.
#:
#: `force` still ignores this. Pressing "check now" is somebody saying they know
#: it failed and want it tried again.
FAILURE_BACKOFF_SECONDS = 15 * 60


def _version_tuple(version):
    """(1, 2, 3) from "1.2.3", padded, so comparisons are numeric not textual.

    "0.10.0" is newer than "0.9.0"; comparing the strings says otherwise.
    """
    parts = []
    for piece in (version or "").split("."):
        digits = re.match(r"\d+", piece.strip())
        parts.append(int(digits.group()) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


# The machine-readable trailer CI appends under the changelog. Both lines are for
# this code rather than for a reader: the digest is what stage_update verifies the
# download against, and the commit is already shown in the Updates tab as the
# build. Showing them as "release notes" is how a user ended up being told a
# sha256 when they asked what changed.
_TRAILER_RE = re.compile(
    r"^\s*(sha256:\s*[0-9a-f]{64}|Built from [0-9a-f]{7,40}\.?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def readable_notes(body):
    """The part of a release body worth showing someone, without the trailer.

    The trailer is stripped rather than the notes extracted, so a body written by
    hand -- or by a future CI that appends something else -- degrades to being
    shown in full rather than to being shown as nothing.
    """
    return _TRAILER_RE.sub("", body or "").strip()


def parse_release(entry):
    """One GitHub release, or None when it is not something we can install."""
    if not isinstance(entry, dict) or entry.get("draft"):
        return None

    tag = entry.get("tag_name") or ""
    version = tag[1:] if tag[:1].lower() == "v" else tag
    if not re.match(r"^\d+\.\d+", version or ""):
        return None

    asset = None
    for candidate in entry.get("assets") or []:
        name = (candidate.get("name") or "").lower()
        if name.endswith(".zip") and candidate.get("browser_download_url"):
            asset = candidate
            break
    if not asset:
        # A release with no zip is a release nobody can install.
        return None

    body = entry.get("body") or ""
    digest = _SHA256_RE.search(body)
    return {
        "version": version,
        "tag": tag,
        "notes": readable_notes(body),
        "asset_url": asset["browser_download_url"],
        "asset_name": asset.get("name", ""),
        "sha256": digest.group(1).lower() if digest else "",
        "prerelease": bool(entry.get("prerelease")),
        "published_at": entry.get("published_at") or "",
    }


#: The API version GitHub asks callers to pin. Nothing else is sent -- there is
#: no Authorization header here, and an unauthenticated caller gets 60 requests
#: an hour per address, which one check an hour leaves almost untouched.
API_HEADERS = {"X-GitHub-Api-Version": "2022-11-28"}


def _failure_message(failure):
    """What to tell the user when the releases API returned nothing usable.

    Every failure used to read "GitHub did not answer. Check the connection.",
    which sends someone to look at their wifi while the connection is fine. The
    rate limit is the case that made this worth splitting: nothing here
    authenticates, so the budget is 60 requests an hour shared by every caller
    on the address, and a household behind one address can reach it without
    anybody doing anything wrong.

    The reading of the dict is `net.failure_message`, because the dict is net's
    and two callers reading it independently is how the same 403 came to be
    reported here as a rate limit and, in the emulator downloads, as the
    project having moved off GitHub. Only the wording either side of it belongs
    to a caller: this one knows the 404 means the plugin's own releases page,
    and that "check by hand" is a thing the reader can actually do.
    """
    return net.failure_message(
        failure,
        "a newer DeckyEmu",
        not_found="The releases page was not found. Check for a newer DeckyEmu by hand.",
    ) or "GitHub did not answer. Check the connection."


_loaded = False


def _load_cache():
    """Fill the in-process cache from disk. Once per process, and never raises."""
    global _loaded
    _loaded = True
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        return
    if not isinstance(saved, dict) or saved.get("format") != CACHE_FORMAT:
        return

    at, releases = saved.get("at"), saved.get("releases")
    if not isinstance(releases, list) or not isinstance(at, (int, float)):
        return
    # A timestamp in the future would hold this answer past the hour it is
    # entitled to -- a clock that has not caught up after a suspend, or a
    # settings folder restored from another machine.
    if at > time.time():
        return

    _cache["releases"] = releases
    _cache["at"] = float(at)
    # Loaded from a file that is only written on success, so this *is* a
    # successful check -- an older one, which is what the timestamp is for.
    _cache["ok"] = True
    _cache["error"] = ""


def _save_cache():
    """Keep the current answer for the next process. Failure is not worth raising."""
    # Written beside and renamed over, the way store.py writes settings: a
    # half-written file is still valid JSON often enough to be worth not risking,
    # and os.replace is atomic on the same filesystem.
    tmp = CACHE_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "format": CACHE_FORMAT,
                    "at": _cache["at"],
                    "releases": _cache["releases"],
                },
                handle,
            )
        os.replace(tmp, CACHE_PATH)
    except OSError as error:
        decky.logger.warning("Could not keep the release cache: %s", error)
        try:
            os.remove(tmp)
        except OSError:
            pass


#: Held while a check is talking to GitHub, so callers cannot overlap.
#:
#: The backoff above is sequential: `failed_at` is written when a request
#: *finishes*, so it says nothing about one still in flight. Overlapping callers
#: therefore each saw an empty backoff and each went out.
#:
#: That is not hypothetical. A single slow reply produced **23 requests in about
#: fifteen seconds** from one backend process, against a budget of sixty an
#: hour. The panel wraps this call in a retry with a two-second per-attempt
#: timeout -- reasonable for a backend call that takes milliseconds, wrong for
#: one that crosses the network -- and decky cannot cancel work, so every
#: abandoned attempt left its request running and started another.
#:
#: Taken without blocking, deliberately. A caller who cannot have the lock is
#: not made to wait for a request that may take thirty seconds: it gets whatever
#: is cached and returns immediately, which is the right answer for an update
#: check and keeps slow calls from filling the executor's thread pool.
_fetch_lock = threading.Lock()

def fetch_releases(force=False):
    """Installable releases, newest first. Cached, and never raises."""
    if not _loaded:
        _load_cache()

    now = time.time()
    if not force and _cache["releases"] and now - _cache["at"] < CACHE_SECONDS:
        return _cache["releases"]

    # Nothing usable cached, and the last attempt failed recently. Whatever it
    # said then is still what it says now -- `ok` and `error` are untouched here
    # on purpose, so the Updates tab keeps explaining the real reason rather
    # than reporting a check that never ran.
    if not force and _cache["failed_at"] and now - _cache["failed_at"] < FAILURE_BACKOFF_SECONDS:
        return _cache["releases"]

    if not _fetch_lock.acquire(blocking=False):
        # Somebody else is already asking. Their answer will be this one.
        return _cache["releases"]
    try:
        return _fetch_locked(force)
    finally:
        _fetch_lock.release()


def _fetch_locked(force):
    """The request itself. Only ever entered by one caller at a time."""
    now = time.time()
    # Re-read the cache now the lock is held: a request that finished while this
    # caller was queued behind it has already answered the question.
    if not force and _cache["releases"] and now - _cache["at"] < CACHE_SECONDS:
        return _cache["releases"]

    failure = {}
    try:
        raw = net.get_json(RELEASES_URL, API_HEADERS, failure=failure)
    except Exception as error:  # noqa: BLE001 - a failed check must not break the UI
        decky.logger.warning("Could not read releases: %s", error)
        _cache["ok"] = False
        _cache["error"] = str(error)
        _cache["failed_at"] = now
        return _cache["releases"]

    if raw is None:
        # net logs the reason; say something the user can act on, which means
        # telling a refusal apart from silence rather than blaming the network
        # for both.
        _cache["ok"] = False
        _cache["error"] = _failure_message(failure)
        _cache["failed_at"] = now
        return _cache["releases"]

    if not isinstance(raw, list):
        # An object here is GitHub's error shape, e.g. {"message": "Bad credentials"}.
        message = raw.get("message") if isinstance(raw, dict) else ""
        decky.logger.warning("Unexpected reply from the releases API: %s", message or raw)
        _cache["ok"] = False
        _cache["error"] = message or "Unexpected reply from GitHub."
        _cache["failed_at"] = now
        return _cache["releases"]

    releases = [release for release in (parse_release(item) for item in raw) if release]
    releases.sort(key=lambda release: _version_tuple(release["version"]), reverse=True)

    _cache["releases"] = releases
    _cache["at"] = now
    _cache["ok"] = True
    _cache["error"] = ""
    _cache["failed_at"] = 0.0
    _save_cache()
    return releases


def download(release):
    """The release zip's bytes.

    The plain browser download URL, which is what a public asset answers on.
    There was an API-URL branch here for the authenticated case; with no token
    it only ever asked GitHub for the asset's JSON metadata instead of the file.
    """
    url = release.get("asset_url") or ""
    if not url:
        return b""
    payload, _ = net.get_bytes(url, max_bytes=64 * 1024 * 1024)
    return payload or b""


def newest(releases, allow_prerelease=False):
    """The release to offer, or None."""
    usable = [r for r in releases if allow_prerelease or not r["prerelease"]]
    return usable[0] if usable else None


def check(current_version, force=False, allow_prerelease=False):
    """Whether `current_version` is behind the newest release.

    `checked` says the request worked. A repository with nothing published yet is
    a successful check that found nothing, and must not be reported as a failure.
    """
    releases = fetch_releases(force=force)
    result = {
        "available": False,
        "current": current_version,
        "checked": bool(_cache["ok"]),
        "error": "" if _cache["ok"] else _cache["error"],
        "count": len(releases),
    }

    latest = newest(releases, allow_prerelease)
    if not latest:
        return result

    result["latest"] = latest
    result["available"] = _version_tuple(latest["version"]) > _version_tuple(current_version)
    return result


def clear_cache():
    global _loaded
    _cache["releases"] = []
    _cache["at"] = 0.0
    _cache["ok"] = False
    _cache["error"] = "Not checked yet."
    _cache["failed_at"] = 0.0
    # Both halves, or "clear" would only mean "until the next call reads the
    # file back". `_loaded` stays true for the same reason: this is a request
    # for no cached answer, not for the old one to be loaded again.
    _loaded = True
    try:
        os.remove(CACHE_PATH)
    except OSError:
        pass
