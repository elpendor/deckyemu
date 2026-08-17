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

import re
import time

import decky

import net

REPO = "elpendor/deckyemu"
RELEASES_URL = "https://api.github.com/repos/%s/releases" % REPO

# GitHub allows 60 unauthenticated requests an hour per address. One check an hour
# leaves that budget almost untouched even with the panel opened repeatedly.
CACHE_SECONDS = 60 * 60

# CI writes this line into the release body so the download can be verified.
_SHA256_RE = re.compile(r"sha256:\s*([0-9a-f]{64})", re.IGNORECASE)

# `ok` is whether the last request *succeeded*, which is not the same as whether
# it found anything. A repository with no releases yet returns an empty list, and
# reporting that as a failure told the user GitHub was unreachable when it had
# answered perfectly.
_cache = {"at": 0.0, "releases": [], "ok": False, "error": "Not checked yet."}


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


def fetch_releases(force=False):
    """Installable releases, newest first. Cached, and never raises."""
    now = time.time()
    if not force and _cache["releases"] and now - _cache["at"] < CACHE_SECONDS:
        return _cache["releases"]

    failure = {}
    try:
        raw = net.get_json(RELEASES_URL, API_HEADERS, failure=failure)
    except Exception as error:  # noqa: BLE001 - a failed check must not break the UI
        decky.logger.warning("Could not read releases: %s", error)
        _cache["ok"] = False
        _cache["error"] = str(error)
        return _cache["releases"]

    if raw is None:
        # net logs the reason; say something the user can act on, which means
        # telling a refusal apart from silence rather than blaming the network
        # for both.
        _cache["ok"] = False
        _cache["error"] = _failure_message(failure)
        return _cache["releases"]

    if not isinstance(raw, list):
        # An object here is GitHub's error shape, e.g. {"message": "Bad credentials"}.
        message = raw.get("message") if isinstance(raw, dict) else ""
        decky.logger.warning("Unexpected reply from the releases API: %s", message or raw)
        _cache["ok"] = False
        _cache["error"] = message or "Unexpected reply from GitHub."
        return _cache["releases"]

    releases = [release for release in (parse_release(item) for item in raw) if release]
    releases.sort(key=lambda release: _version_tuple(release["version"]), reverse=True)

    _cache["releases"] = releases
    _cache["at"] = now
    _cache["ok"] = True
    _cache["error"] = ""
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
    _cache["releases"] = []
    _cache["at"] = 0.0
    _cache["ok"] = False
    _cache["error"] = "Not checked yet."
