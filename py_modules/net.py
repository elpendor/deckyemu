"""Small blocking HTTP helpers, meant to be run through an executor.

Deliberately stdlib-only: the plugin sandbox's third-party packages vary
between decky versions, and none of this needs more than urllib.
"""

import base64
import http.client
import json
import os
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

import decky

USER_AGENT = "DeckyEmu/1.0 (+https://github.com/SteamDeckHomebrew)"
DEFAULT_TIMEOUT = 20

# A JSON reply that is not small is a reply from something that is not the API
# we asked, so it is capped rather than read into memory unbounded.
_MAX_JSON_BYTES = 64 * 1024

# Decky runs plugins inside a frozen interpreter whose bundled CA store can be
# older than the operating system's. That is not academic: thumbnails.libretro.com
# is served under a recent Let's Encrypt root which the bundled store may not
# know, so artwork lookups fail with CERTIFICATE_VERIFY_FAILED while other hosts
# on newer chains keep working. The OS trust store is the more current of the
# two, so fall back to it rather than turning verification off.
_SYSTEM_CA_FILES = (
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
)

# Set once we discover the default context cannot verify a host we need.
_fallback_context = None
_fallback_checked = False


def _system_ca_context():
    global _fallback_checked
    _fallback_checked = True
    for path in _SYSTEM_CA_FILES:
        if not os.path.isfile(path):
            continue
        try:
            context = ssl.create_default_context(cafile=path)
        except (OSError, ssl.SSLError) as error:
            decky.logger.warning("Could not load CA bundle %s: %s", path, error)
            continue
        decky.logger.info("Using system CA bundle %s for TLS verification", path)
        return context
    decky.logger.error(
        "No usable system CA bundle found; HTTPS requests to some hosts may fail"
    )
    return None


def _is_cert_error(error):
    if isinstance(error, ssl.SSLCertVerificationError):
        return True
    return isinstance(getattr(error, "reason", None), ssl.SSLCertVerificationError)


def _urlopen(request, timeout=DEFAULT_TIMEOUT):
    """urlopen that retries against the OS trust store on a cert failure."""
    global _fallback_context

    if _fallback_context is not None:
        return urllib.request.urlopen(request, timeout=timeout, context=_fallback_context)

    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except (urllib.error.URLError, ssl.SSLError) as error:
        if not _is_cert_error(error) or _fallback_checked:
            raise
        context = _system_ca_context()
        if context is None:
            raise
        _fallback_context = context
        return urllib.request.urlopen(request, timeout=timeout, context=context)


def _request(url, headers=None, method="GET"):
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    return request


# Probing artwork means a dozen to two dozen requests to the same host in a row,
# and urllib opens a new connection -- and so a new TLS handshake -- for every one
# of them. Measured against thumbnails.libretro.com that is 838ms per probe
# against 330ms when the connection is reused, and it is most of the wait behind
# "Looking up name and artwork".
#
# Per thread, because http.client connections cannot be shared and the probe pool
# runs several at once. Keyed by host so a redirect elsewhere does not reuse the
# wrong socket.
_connections = threading.local()


def close_connections():
    """Drop this thread's kept-alive connections."""
    pool = getattr(_connections, "pool", None)
    if not pool:
        return
    for connection in pool.values():
        try:
            connection.close()
        except OSError:
            pass
    pool.clear()


def _open_connection(scheme, host, timeout):
    if scheme == "https":
        # None means urllib's default context, which is what _urlopen would use
        # until a cert failure teaches it otherwise.
        return http.client.HTTPSConnection(host, timeout=timeout, context=_fallback_context)
    return http.client.HTTPConnection(host, timeout=timeout)


def _connection(key, timeout):
    pool = getattr(_connections, "pool", None)
    if pool is None:
        pool = _connections.pool = {}
    connection = pool.get(key)
    if connection is None:
        connection = pool[key] = _open_connection(key[0], key[1], timeout)
    return connection


def _discard(key):
    """Close and forget a connection, so the next attempt opens a new one."""
    pool = getattr(_connections, "pool", None)
    if not pool:
        return
    connection = pool.pop(key, None)
    if connection is not None:
        try:
            connection.close()
        except OSError:
            pass


def _once(method, url, headers=None, timeout=DEFAULT_TIMEOUT):
    """One request. Returns (status, redirect target), or (None, None) on failure.

    A status -- any status, including 404 -- means the server answered and the
    caller can decide what it means. None means the request failed outright, which
    is the case worth logging.
    """
    global _fallback_context

    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        decky.logger.warning("Refusing to probe non-HTTP url %s", url)
        return None, None

    key = (parsed.scheme, parsed.netloc)
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query

    sent = dict(headers or {})
    sent.setdefault("User-Agent", USER_AGENT)

    # Two attempts, because a kept-alive connection can be closed by the server
    # between requests and that only shows up as a failure on the next one. The
    # retry is on a fresh connection, so a genuinely broken host still fails fast.
    for attempt in range(2):
        connection = _connection(key, timeout)
        try:
            connection.request(method, target, headers=sent)
            response = connection.getresponse()
            location = response.getheader("Location") or ""
            # Drained even for HEAD: an unread response leaves the connection
            # unusable for the next request, which would defeat the whole point.
            response.read()
            return response.status, urllib.parse.urljoin(url, location) if location else ""
        except (ssl.SSLError, OSError) as error:
            _discard(key)
            if _is_cert_error(error) and not _fallback_checked:
                # The frozen interpreter's CA bundle is too old for this host. Same
                # fallback _urlopen makes, and it has to be made here too or the
                # pooled path would fail where the urllib one recovers.
                context = _system_ca_context()
                if context is not None:
                    _fallback_context = context
                    continue
            if attempt:
                decky.logger.warning("%s failed for %s: %s", method, url, error)
                return None, None
        except http.client.HTTPException as error:
            _discard(key)
            if attempt:
                decky.logger.warning("%s failed for %s: %s", method, url, error)
                return None, None
    return None, None


# Redirects are followed by hand because http.client, unlike urlopen, does not do
# it. Dropping that would quietly turn a moved thumbnail into "no artwork found".
_MAX_REDIRECTS = 4


def _status_for(method, url, headers=None, timeout=DEFAULT_TIMEOUT):
    """The HTTP status for a request, following redirects as urlopen would."""
    seen = set()
    for _hop in range(_MAX_REDIRECTS):
        status, location = _once(method, url, headers, timeout)
        if status is None:
            return None
        if status not in (301, 302, 303, 307, 308) or not location:
            return status
        if location in seen:
            decky.logger.warning("Redirect loop probing %s", url)
            return status
        seen.add(location)
        url = location
    decky.logger.warning("Too many redirects probing %s", url)
    return None


def head_ok(url, headers=None):
    """True if `url` exists. Falls back to a ranged GET for servers that 405 HEAD."""
    status = _status_for("HEAD", url, headers)
    if status is None:
        # A 404 is the normal "no artwork under this name" answer and says nothing
        # worth logging; a request that got no answer at all is different, and
        # _status_for has already logged it. That distinction is why this is not
        # silent -- a TLS failure once went unnoticed as "no artwork found".
        return False
    if 200 <= status < 300:
        return True
    if status in (403, 405, 501):
        ranged = dict(headers or {})
        ranged["Range"] = "bytes=0-0"
        status = _status_for("GET", url, ranged)
        return status is not None and 200 <= status < 300
    return False


def get_bytes(url, headers=None, max_bytes=12 * 1024 * 1024):
    """Returns (bytes, content_type) or (None, None)."""
    try:
        with _urlopen(_request(url, headers)) as response:
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                decky.logger.warning("Refusing oversized download: %s", url)
                return None, None
            return payload, response.headers.get("Content-Type", "")
    except (urllib.error.URLError, OSError) as error:
        decky.logger.warning("GET failed for %s: %s", url, error)
        return None, None


def download(url, dest, headers=None, max_bytes=512 * 1024 * 1024, on_progress=None):
    """Stream a URL to `dest`. Returns (ok, error).

    Separate from get_bytes because an emulator AppImage is a couple of hundred
    megabytes: holding that in memory on a device with 16GB shared between Steam,
    the compositor and the game is avoidable, and a download with no progress at
    all looks identical to one that has hung.

    `on_progress` is called with (bytes_so_far, total_or_zero). It is called at
    most once per chunk and must not raise.

    Writes to a `.part` file and renames, so an interrupted download can never be
    mistaken for a complete one -- which for an executable would mean a game that
    closes instantly with nothing to explain why.
    """
    tmp = dest + ".part"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    except OSError as error:
        return False, "Cannot create %s: %s" % (os.path.dirname(dest), error)

    try:
        with _urlopen(_request(url, headers), timeout=60) as response:
            try:
                total = int(response.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            if total > max_bytes:
                return False, "That download is %d MB, which is larger than expected." % (
                    total // (1024 * 1024)
                )

            done = 0
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > max_bytes:
                        raise OSError("download exceeded %d bytes" % max_bytes)
                    handle.write(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
    except (urllib.error.URLError, OSError) as error:
        decky.logger.warning("Download failed for %s: %s", url, error)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, str(error)

    try:
        os.replace(tmp, dest)
    except OSError as error:
        return False, "Could not save %s: %s" % (dest, error)
    return True, ""


def post_json(url, fields, headers=None, timeout=DEFAULT_TIMEOUT):
    """POST a form body and decode the JSON reply, or None.

    A POST rather than a GET with a query string because the only caller sends a
    password: query strings reach proxy logs, browser history and `ps` output,
    request bodies do not.

    An HTTP error status is read rather than raised: this endpoint answers 401
    with a JSON body saying *why* the sign-in failed, and that message is worth
    far more to the user than "HTTP Error 401".
    """
    body = urllib.parse.urlencode(fields or {}).encode("utf-8")
    request = _request(url, headers, method="POST")
    request.data = body
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with _urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_JSON_BYTES)
    except urllib.error.HTTPError as error:
        try:
            payload = error.read(_MAX_JSON_BYTES)
        except OSError:
            decky.logger.warning("POST failed for %s: %s", url, error)
            return None
    except (urllib.error.URLError, OSError) as error:
        # Never log `fields`: it holds the password.
        decky.logger.warning("POST failed for %s: %s", url, error)
        return None

    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        decky.logger.warning("Bad JSON from %s: %s", url, error)
        return None


def get_json(url, headers=None):
    payload, _ = get_bytes(url, headers)
    if payload is None:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        decky.logger.warning("Bad JSON from %s: %s", url, error)
        return None


def get_data_uri(url, headers=None):
    """Fetch an image and return (data_uri, 'png'|'jpg') for the Steam client."""
    payload, content_type = get_bytes(url, headers)
    if not payload:
        return None, None

    lowered = (content_type or "").lower()
    if "jpeg" in lowered or "jpg" in lowered:
        kind = "jpg"
    elif "png" in lowered:
        kind = "png"
    elif payload[:3] == b"\xff\xd8\xff":
        kind = "jpg"
    elif payload[:8] == b"\x89PNG\r\n\x1a\n":
        kind = "png"
    else:
        kind = "png"

    mime = "image/jpeg" if kind == "jpg" else "image/png"
    encoded = base64.b64encode(payload).decode("ascii")
    return "data:%s;base64,%s" % (mime, encoded), kind
