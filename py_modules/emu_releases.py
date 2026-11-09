"""Finding an emulator's builds: release APIs, publisher feeds, checksums.

GitHub or a self-hosted forge with the same API, or a publisher's own update
feed. Asset patterns must be anchored: assets carry aarch64 builds beside
x86_64 ones.
"""

import hashlib
import re

import appenv
import net


GITHUB_API = "https://api.github.com/repos/%s/releases/latest"


#: The same question asked of the website, which redirects to
#: `/releases/tag/<tag>`. Off the API's hourly budget, and excludes
#: pre-releases as `latest` does.
GITHUB_LATEST_PAGE = "https://github.com/%s/releases/latest"


#: What that redirect lands on. No releases lands on `/releases`, which
#: this does not match.
_TAG_IN_URL = re.compile(r"/releases/tag/([^/?#]+)")


#: Same call against a self-hosted forge, which answers the same shape.
SELF_HOSTED_API = "https://%s/api/v1/repos/%s/releases/latest"


#: A hostname, not a URL, so an entry cannot name a path or plain HTTP.
_HOST_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


#: A feed is a few hundred bytes; anything this large is not one.
MAX_FEED_BYTES = 64 * 1024


def resolve_feed_build(feed_url, want):
    """The build `want` names in a publisher's own update feed. (asset, error).

    For a project with no releases API: BigPEmu's updater reads a plain-text
    feed with one line per platform, giving the download, an unused patch
    installer, then the file's 64-bit FNV-1a:

        BUILD_INFO 1
        VERSION 1.221
        Linux64 "http://.../BigPEmu_Linux64_v1221.tar.gz" "" C1B241BBFA5135CB ...

    The scheme is forced to https; the same files serve over TLS.
    """
    if not net.is_web_url(feed_url):
        return None, "That is not a usable address for an update feed."
    payload, _content_type = net.get_bytes(feed_url, max_bytes=MAX_FEED_BYTES)
    if not payload:
        return None, "The project's update feed could not be read."
    text = payload.decode("utf-8", "replace")

    version = ""
    for line in text.splitlines():
        if line.startswith("VERSION "):
            version = line.split(None, 1)[1].strip()
            break
    if not version:
        return None, "The project's update feed named no version."

    for line in text.splitlines():
        if not line.startswith(want + " "):
            continue
        quoted = re.findall(r'"([^"]*)"', line)
        if not quoted or not quoted[0]:
            return None, "The update feed lists %s with no download." % want
        url = re.sub(r"^http://", "https://", quoted[0].strip())
        if not net.is_web_url(url):
            return None, "The update feed's download address is not usable."
        digest = ""
        after = line.split('"')[-1].split()
        if after and re.match(r"^[0-9A-Fa-f]{16}$", after[0]):
            digest = "fnv1a64:" + after[0].lower()
        return {
            "name": url.rsplit("/", 1)[-1],
            "url": url,
            "digest": digest,
            "tag": version,
        }, ""
    return None, "The project publishes no %s build." % want


#: How many past builds a feed-installed emulator offers, as for releases.
FEED_HISTORY_LIMIT = 12


def _versions_named(notes_text):
    """Every version heading in a set of release notes, in the order written."""
    found = []
    for line in (notes_text or "").splitlines():
        match = re.match(r"^Version\s+([0-9][0-9.]*)\s*$", line)
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def _clip(text, limit):
    """`text` no longer than `limit`, cut at a word and marked as cut.

    A bare slice ends mid-word and looks like a rendering fault.
    """
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "..."


def _merged(known, *more):
    """One list of versions, in the order they were first met, without repeats."""
    out = [version for version in (known or ()) if version]
    for group in more:
        for version in group or ():
            if version and version not in out:
                out.append(version)
    return out


def feed_history(entry, notes_text, probe=None, remembered=(), newest=None):
    """Past builds of a feed-installed emulator, newest first. (builds, error).

    The list is the `Version x.y` headings in the `ReadMe.txt` shipped beside
    the binary, the only enumeration that exists. An old build's address is
    the version without dots, an undocumented convention; it is only applied
    to versions the notes name, and `probe` confirms each file exists.

    The feed gives a checksum for the current release only; `newest` is that
    release, so its row uses the stated address and checksum.
    """
    source = entry.get("source") or {}
    pattern = source.get("build_name") or ""
    if not pattern:
        return [], ""

    # A heading and the lines under it, until the next: that release's notes.
    seen = list(remembered or ())
    notes = {}
    current = ""
    for line in (notes_text or "").splitlines():
        found = re.match(r"^Version\s+([0-9][0-9.]*)\s*$", line)
        if found:
            current = found.group(1)
            if current not in seen:
                seen.append(current)
            notes.setdefault(current, [])
            continue
        if current and line.strip():
            notes[current].append(line.strip().lstrip("- ").strip())
    if not seen:
        return [], "No release notes came with this build, so its past builds are not listed."

    # Newest first. The part after the dot is read as a fraction, so 1.221
    # sits above 1.22, which sits above 1.19.
    def _order(version):
        head, _, tail = version.partition(".")
        try:
            return (int(head), float("0." + tail) if tail else 0.0)
        except ValueError:
            return (0, 0.0)

    seen.sort(key=_order, reverse=True)

    builds = []
    for version in seen[:FEED_HISTORY_LIMIT]:
        # The current release's address and checksum come from the feed.
        stated = newest if newest and newest.get("tag") == version else None
        url = (stated["url"] if stated
               else pattern.replace("{version}", version.replace(".", "")))
        # One request says both whether it is still published and its size.
        size = probe(url) if probe else 0
        if not size:
            continue
        builds.append({
            "tag": version,
            "name": url.rsplit("/", 1)[-1],
            "url": url,
            "size": size,
            "digest": stated["digest"] if stated else "",
            "published": "",
            "prerelease": False,
            # Capped; the first lines say what the release was for.
            "notes": _clip(" ".join(notes.get(version, ())[:6]), 600),
        })
    if not builds:
        return [], "None of the past builds named in the release notes are still published."
    return builds, ""


def build_size(url):
    """How big a past build is, or 0 if it is no longer published.

    Separate so `feed_history` can be tested with a fake probe. Zero means
    gone or unreadable, and either way the build is not offered.
    """
    return net.head_size(url)


def resolve_release_asset(repo, pattern, host="", failure=None):
    """Newest release asset matching `pattern`, from GitHub or a self-hosted forge.

    `host` empty means GitHub; otherwise a host running the same releases
    API. No token is sent: the plugin's own is scoped to this project.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo or ""):
        return None, "Not a valid repository name."
    if host and not _HOST_RE.match(host):
        return None, "Not a valid host name."
    api = SELF_HOSTED_API % (host, repo) if host else GITHUB_API % repo
    return _resolve_asset(api, pattern, "%s on %s" % (repo, host) if host else repo,
                          failure=failure)


#: Releases rather than only the newest one, for choosing a build to go back to.
GITHUB_RELEASES = "https://api.github.com/repos/%s/releases"


SELF_HOSTED_RELEASES = "https://%s/api/v1/repos/%s/releases"


#: A release tag. Permissive on shape, strict on characters, since it comes
#: from the frontend.
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def valid_tag(tag):
    return bool(_TAG_RE.match(tag or ""))


def resolve_release_list(repo, pattern, host="", limit=30):
    """Recent releases carrying an asset that matches, newest first.

    Returns (builds, error). Each build is {tag, name, url, size, published}.

    Releases with no matching asset, such as aarch64-only ones, are skipped.
    """
    if not re.match(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", repo or ""):
        return [], "Not a valid repository name."
    if host and not _HOST_RE.match(host):
        return [], "Not a valid host name."

    api = SELF_HOSTED_RELEASES % (host, repo) if host else GITHUB_RELEASES % repo
    if not host:
        # GitHub's default of 30 can be two weeks for a project that tags
        # every build.
        api += "?per_page=100"
    label = "%s on %s" % (repo, host) if host else repo
    failure = {}
    payload = net.get_json(api, failure=failure)
    if not isinstance(payload, list):
        # Name the real failure; see `_resolve_asset`.
        return [], (
            net.failure_message(failure, "the builds of %s" % label)
            or "No releases came back for %s. The project may have moved off "
               "GitHub." % label
        )

    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return [], "Bad asset pattern: %s" % error

    builds = []
    for release in payload:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name") or ""
        if not valid_tag(tag):
            continue
        for asset in release.get("assets") or []:
            name = asset.get("name") or ""
            url = asset.get("browser_download_url")
            if not url or not matcher.match(name):
                continue
            builds.append({
                "tag": tag,
                "name": name,
                "url": url,
                "size": asset.get("size") or 0,
                "digest": asset.get("digest") or "",
                "published": (release.get("published_at") or "")[:10],
                "prerelease": bool(release.get("prerelease")),
            })
            break
        if len(builds) >= limit:
            break
    if not builds:
        return [], "No release of %s carries a download this device can use." % label
    return builds, ""


def resolve_github_asset(repo, pattern):
    """`resolve_release_asset` against GitHub. Kept for the bundled entries."""
    return resolve_release_asset(repo, pattern)


def _resolve_asset(api_url, pattern, label, failure=None):
    # The caller may want the details: a rate limit says when it lifts.
    failure = {} if failure is None else failure
    payload = net.get_json(api_url, failure=failure)
    if payload is None:
        # Name the real failure: a rate limit once read as the project having
        # moved. 451 (taken-down repositories) falls to the generic line.
        return None, (
            net.failure_message(failure, "the latest release of %s" % label)
            or "No release came back for %s. The project may have moved off "
               "GitHub." % label
        )
    if not isinstance(payload, dict) or payload.get("message"):
        return None, payload.get("message", "Unexpected reply from %s." % label) if isinstance(
            payload, dict
        ) else "Unexpected reply from %s." % label

    try:
        matcher = re.compile(pattern)
    except re.error as error:
        return None, "Bad asset pattern: %s" % error

    for asset in payload.get("assets") or []:
        name = asset.get("name") or ""
        if not matcher.match(name):
            continue
        url = asset.get("browser_download_url")
        if not url:
            continue
        return (
            {
                "name": name,
                "url": url,
                "tag": payload.get("tag_name") or "",
                "size": asset.get("size") or 0,
                "digest": asset.get("digest") or "",
            },
            "",
        )

    return None, "No download in the latest release of %s matched what was expected." % label


#: How GitHub states an asset's checksum, e.g. "sha256:5c73...".
_DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$", re.IGNORECASE)


#: BigPEmu's feed states a 64-bit FNV-1a of each build and nothing else;
#: checked against a published value.
_FNV_RE = re.compile(r"^fnv1a64:([0-9a-f]{16})$", re.IGNORECASE)


_FNV_PRIME = 1099511628211


_FNV_OFFSET = 14695981039346656037


_FNV_MASK = (1 << 64) - 1


def _fnv1a64(path):
    """The 64-bit FNV-1a of a file, as lowercase hex. "" if it cannot be read."""
    value = _FNV_OFFSET
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                for byte in block:
                    value = ((value ^ byte) * _FNV_PRIME) & _FNV_MASK
    except OSError:
        return ""
    return "%016x" % value


def _digest_matches(path, digest):
    """Whether the file at `path` is what the release said it would be. (ok, error).

    Integrity, not authenticity: the checksum comes in the same reply as the
    URL. It catches a truncated or stale download. An asset with no digest
    passes, since many sources publish none.
    """
    weak = _FNV_RE.match((digest or "").strip())
    if weak:
        wanted = weak.group(1).lower()
        got = _fnv1a64(path)
        if not got:
            return False, "Could not read the download."
    else:
        stated = _DIGEST_RE.match((digest or "").strip())
        if not stated:
            return True, ""
        wanted = stated.group(1).lower()
        reader = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    reader.update(block)
        except OSError as error:
            return False, "Could not read the download: %s" % error
        got = reader.hexdigest()
    if got != wanted:
        appenv.logger.warning("Digest mismatch for %s: wanted %s, got %s",
                             path, wanted, got)
        return False, ("The download does not match the checksum the release "
                       "published, so it arrived damaged or altered. Nothing "
                       "was installed.")
    return True, ""
