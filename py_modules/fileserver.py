"""A short-lived HTTP server for sending files to the Deck from another device.

Typing a path on a Deck is unpleasant and the files are usually somewhere else
already, so this serves a small upload page on the local network. Two ways in,
because the devices differ:

* **A QR code**, for anything with a camera. It carries the full token URL, so
  scanning it goes straight to the upload page.
* **A short address and a six-digit code**, for anything with a keyboard. A
  desktop cannot scan a QR code and will not have a 22-character token typed into
  it, so the root path serves a form; the right code redirects to the token URL.

Uploads are plain streaming PUTs rather than multipart form posts. Multipart
parsing in the standard library means `cgi.FieldStorage`, which is deprecated and
removed in newer Pythons, and it buffers awkwardly for multi-gigabyte ROMs. A PUT
of the raw body is both simpler and streamable.

Security posture, since this listens on the network:

* A random token is required in every path. The QR code carries it; without it
  every request is refused, so a port scan finds nothing usable.
* The only exception is the root path, which serves the code form and nothing
  else. Six digits are guessable in principle, so wrong answers are counted and
  no code is accepted after PIN_ATTEMPTS of them.
* Writes are confined to one directory chosen before starting, and filenames are
  reduced to their basename, so `../` cannot escape it.
* The server stops on its own after a period of inactivity, and can be stopped by
  hand at any time.
* It is HTTP on a local network -- fine for moving ROMs around a house, not
  something to expose beyond it.
"""

import base64
import html
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import decky

import diagnostics
import sysenv

# Long enough that guessing is hopeless, short enough to scan reliably.
TOKEN_BYTES = 16

IDLE_TIMEOUT = 30 * 60
_CHUNK = 1024 * 1024

# Anything not obviously a ROM or disc image is still accepted -- the point is
# moving files, not policing them -- but these are hidden from the received list
# so browser junk does not clutter it.
_IGNORED_SUFFIXES = (".crdownload", ".part", ".tmp", ".uploading")

_state_lock = threading.Lock()
_server = None
_thread = None
_token = ""
_target_dir = ""
_last_activity = 0.0
_received: list = []
# A diagnostic report waiting to be read off the device, or "".
#
# Served from the same token-gated server as the uploads because the problem is
# the same one and it is already solved here: getting something between a Deck
# in Game Mode and a device with a keyboard, over the local network, with a QR
# code for a camera and six digits for anything else. A second server for the
# other direction would be a second thing to bind, expire and lock out.
_report = ""

# A short code, so the server can be reached from a keyboard as well as a camera.
#
# A QR code answers anything with a camera, but nothing scans one on a desktop,
# and typing a 22-character token by hand is worse than not offering the feature.
# So the root path serves a form asking for six digits, and a correct code
# redirects to the real token URL. The token still guards every upload path -- the
# code only opens the door.
#
# Six digits is a million combinations, which is only safe because guessing is
# capped: after PIN_ATTEMPTS wrong answers no code is accepted until the server is
# restarted. That bounds an attacker already on the local network to a 1-in-125000
# chance during the server's 30-minute life, while staying short enough to read off
# a screen and type.
PIN_DIGITS = 6
PIN_ATTEMPTS = 8

_pin = ""
_pin_attempts = 0
_pin_locked = False

# Whether this session's address and token were reused from a previous one, which
# is what makes a bookmark keep working. Only used to decide whether the page
# offers to be bookmarked: inviting someone to save a link that dies at the end of
# the session would be worse than saying nothing.
_durable = False

# Uploads in flight: {id: {name, received, total, at}}.
#
# Closing the dialog stops the server, and a multi-gigabyte ROM must not be killed
# halfway because someone dismissed a window they were only using to read a code
# off -- so something has to know a transfer is running.
#
# The bytes are here as well as the count because a count cannot tell a 4 GB ROM
# crawling in over wifi from a connection that has stalled: both are "1 file".
# Nothing showed progress at all until the file completed and appeared in the
# received list, so a long upload looked identical to nothing happening.
#
# An entry is removed by the request that added it, after the response is sent, so
# a read taken the instant an upload finishes can still see it. That errs the safe
# way: the worst case is a server left to stop on its own idle timeout rather than
# a transfer cut off.
_in_flight: dict = {}
_upload_seq = 0

# An inbox, and named as one. It was `roms` until games began being filed into
# `roms/<system>/` as they are added, which left one folder being both the heap
# things arrive in and the parent of the tidy library -- loose files sitting
# beside sorted folders forever. Two names, two jobs.
DEFAULT_SUBDIR = "transfer"


def default_dir(create=True):
    """`<home>/deckyemu/transfer`, created on demand.

    Its own folder rather than a guess at an existing ROM library. Uploads arriving
    from another device are unsorted and of unknown system, so dropping them into
    another setup's ROM folder would mix them into a library organised by console
    -- and which of those layouts to pick is not knowable. One predictable folder
    is easier to find later and easier to clean out.

    What is in here is what has not been added yet. Adding a game moves its ROM
    out, into `~/deckyemu/roms/<system>/`, so this empties itself as it is used.

    Created here rather than in `start()` so the picker can offer it before the
    server runs; `start()` still refuses a directory that does not exist, which is
    what catches a folder the user deleted underneath us.
    """
    # Not logged: the panel polls status every few seconds while the server runs,
    # and `start()` already records the folder it is saving into.
    return sysenv.user_dir(DEFAULT_SUBDIR, create=create)


def _now():
    return time.time()


def local_ip():
    """The address another device on the same network can reach.

    Opening a UDP socket toward a public address reveals which interface would
    be used, without sending anything.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


def safe_name(name):
    """A filename that cannot escape the upload directory."""
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    # Keep it recognisable but harmless: no control characters, no leading dots.
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).lstrip(".")
    return name[:180] or "upload.bin"


def same_secret(given, expected):
    """Constant-time comparison that tolerates anything off the network.

    Public because `handoff` compares a token off the network too, and this is
    the only thing the two servers have any business sharing. Duplicating six
    lines is how the two would come to disagree about a fix neither remembers
    needing.

    secrets.compare_digest refuses a str holding any non-ASCII character --
    "comparing strings with non-ASCII characters is not supported" -- and both
    callers hand it text taken straight from a request. BaseHTTPRequestHandler
    decodes the request line as latin-1, so a raw high byte in the path becomes a
    non-ASCII character, and `GET /<any accented letter>` raised inside the
    handler and dropped the connection instead of answering 404. Comparing the
    encoded bytes keeps the timing property and cannot raise; the secrets
    themselves are ASCII, so anything that had to be substituted on the way in
    could never have matched.
    """
    if not expected:
        return False
    return secrets.compare_digest(
        (given or "").encode("utf-8", "replace"), expected.encode("utf-8")
    )


class _Handler(BaseHTTPRequestHandler):
    server_version = "DeckyEmu"
    sys_version = ""

    # BaseHTTPRequestHandler logs to stderr; route it to the plugin log instead.
    def log_message(self, fmt, *args):
        decky.logger.info("fileserver: " + fmt, *args)

    def _authorised(self):
        """Path segments after the token, or None when the token is wrong.

        Split before decoding, and decode each segment separately. Decoding the
        whole path first would let an encoded slash (`%2F`) invent extra segments,
        which is exactly how a crafted filename would try to climb out of the
        upload folder.
        """
        with _state_lock:
            expected = _token
        if not expected:
            return None

        raw = self.path.split("?", 1)[0].split("#", 1)[0]
        segments = [segment for segment in raw.split("/") if segment]
        if not segments or not same_secret(segments[0], expected):
            return None

        return [urllib.parse.unquote(segment) for segment in segments[1:]]

    def _deny(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, status, body, content_type="text/plain; charset=utf-8"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # No caching: the page lists files that change as they arrive.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _check_pin(self, given):
        """Whether `given` is the current code, counting failures.

        Locks out after PIN_ATTEMPTS so six digits cannot simply be enumerated.
        Compared with compare_digest even though a code is not a secret at rest --
        it is checked over the network, and there is no reason to leak its prefix
        through timing.
        """
        global _pin_attempts, _pin_locked
        with _state_lock:
            expected = _pin
            if _pin_locked or not expected:
                return False
            if same_secret((given or "").strip(), expected):
                return True
            _pin_attempts += 1
            if _pin_attempts >= PIN_ATTEMPTS:
                _pin_locked = True
        decky.logger.warning(
            "fileserver: wrong code (%d/%d)%s",
            _pin_attempts,
            PIN_ATTEMPTS,
            " -- no further codes accepted" if _pin_locked else "",
        )
        return False

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        raw = self.path.split("#", 1)[0]
        path, _, query = raw.partition("?")

        # The code form is the only thing served without a token, and only at the
        # root, so nothing else about the server is reachable without one.
        if path in ("", "/"):
            _touch()
            code = urllib.parse.parse_qs(query).get("code", [""])[0]
            if code:
                if self._check_pin(code):
                    with _state_lock:
                        token = _token
                    self._redirect("/%s/" % token)
                    return
                self._send(200, _code_page(bad=True), "text/html; charset=utf-8")
                return
            self._send(200, _code_page(), "text/html; charset=utf-8")
            return

        rest = self._authorised()
        if rest is None:
            self._deny()
            return

        _touch()
        if not rest or rest == ["index.html"]:
            self._send(200, _page(), "text/html; charset=utf-8")
        elif rest == ["files"]:
            with _state_lock:
                names = [entry["name"] for entry in _received]
            self._send(200, json.dumps(names), "application/json")
        elif rest == ["report"]:
            with _state_lock:
                report = _report
            # 404 rather than an empty page when nothing is waiting: the address
            # is guessable to anyone holding the token, and "there is no report"
            # is the honest answer rather than a blank one that looks broken.
            if not report:
                self._deny()
                return
            self._send(200, diagnostics.as_page(report), "text/html; charset=utf-8")
        else:
            self._deny()

    def do_PUT(self):
        rest = self._authorised()
        # Exactly /<token>/upload/<name>: no deeper paths to reason about.
        if rest is None or len(rest) != 2 or rest[0] != "upload":
            self._deny()
            return

        with _state_lock:
            directory = _target_dir
        if not directory or not os.path.isdir(directory):
            self._send(500, "The upload folder is no longer there.")
            return

        name = safe_name(rest[1])
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, "A Content-Length is required.")
            return
        if length <= 0:
            self._send(400, "Empty upload.")
            return

        destination = os.path.join(directory, name)
        # Written alongside then renamed, so a partial transfer is never mistaken
        # for a complete ROM.
        partial = destination + ".uploading"

        global _upload_seq
        with _state_lock:
            _upload_seq += 1
            upload_id = _upload_seq
            _in_flight[upload_id] = {
                "name": name,
                "received": 0,
                "total": length,
                "at": _now(),
                # Both are for cancel(): the socket is how a read blocked waiting
                # for the next chunk gets unstuck, and the path is what a sweep
                # must not delete while this handler still owns it.
                "connection": self.connection,
                "partial": partial,
                "cancelled": False,
            }
        try:
            self._receive(upload_id, partial, destination, name, length, directory)
        finally:
            with _state_lock:
                _in_flight.pop(upload_id, None)

    def _reply(self, status, body):
        """Reply, tolerating a connection that has already gone.

        A cancelled upload has had its socket shut down deliberately, and a client
        that walked away has closed its own. In both cases there is nobody left to
        tell, and letting the write raise here would escape the handler and be
        logged as a crash rather than the ordinary end of a transfer.
        """
        try:
            self._send(status, body)
        except OSError as error:
            decky.logger.info("No one left to reply to: %s", error)

    def _receive(self, upload_id, partial, destination, name, length, directory):
        received = 0
        cancelled = False
        try:
            with open(partial, "wb") as handle:
                while received < length:
                    chunk = self.rfile.read(min(_CHUNK, length - received))
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    # Published per chunk, which is what makes a slow transfer
                    # visibly a slow transfer rather than a stalled one, and is
                    # also where a cancel is noticed between reads.
                    with _state_lock:
                        entry = _in_flight.get(upload_id)
                        if entry is not None:
                            entry["received"] = received
                            cancelled = bool(entry["cancelled"])
                    if cancelled:
                        break
                    _touch()
        except OSError as error:
            # A cancel shuts the socket down deliberately, so the read failing is
            # the expected way this ends rather than a fault worth warning about.
            cancelled = cancelled or _was_cancelled(upload_id)
            if not cancelled:
                decky.logger.warning("Upload of %s failed: %s", name, error)
            _quiet_remove(partial)
            if not cancelled:
                self._reply(500, "Could not write the file: %s" % error)
                return

        cancelled = cancelled or _was_cancelled(upload_id)
        if cancelled:
            # Deleted rather than kept: a half-file the user asked to abandon is
            # exactly the leftover this rename-on-completion scheme exists to
            # avoid, and there is nothing to resume it with.
            _quiet_remove(partial)
            decky.logger.info("Cancelled %s after %d of %d bytes", name, received, length)
            self._reply(499, "Cancelled.")
            return

        if received != length:
            _quiet_remove(partial)
            self._reply(400, "Upload ended early.")
            return

        try:
            os.replace(partial, destination)
        except OSError as error:
            _quiet_remove(partial)
            self._reply(500, "Could not finish the file: %s" % error)
            return

        with _state_lock:
            _received.append({"name": name, "path": destination, "size": received, "at": _now()})
            del _received[:-50]

        decky.logger.info("Received %s (%d bytes) into %s", name, received, directory)
        self._reply(200, "ok")


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _was_cancelled(upload_id):
    with _state_lock:
        entry = _in_flight.get(upload_id)
        return bool(entry and entry["cancelled"])


def cancel(upload_id=None):
    """Abandon one upload, or every one. Returns how many were signalled.

    Two steps, because either alone is not enough. The flag is what tells the
    handler this was deliberate, so it deletes its partial file and says
    "cancelled" rather than reporting a fault. Shutting the socket down is what
    makes that happen *now*: the handler spends nearly all of its time blocked in
    rfile.read waiting for the next chunk, and on a connection that has stalled --
    which is the one you most want to abandon -- that read might never return on
    its own.

    The handler still owns the cleanup. Deleting the file from here would race
    the thread that is writing it.
    """
    with _state_lock:
        targets = [
            (key, entry)
            for key, entry in _in_flight.items()
            if upload_id in (None, 0, key)
        ]
        for _key, entry in targets:
            entry["cancelled"] = True
        connections = [entry.get("connection") for _key, entry in targets]

    # Outside the lock: shutdown can block, and the handler needs the lock to
    # notice the flag we just set.
    for connection in connections:
        if connection is None:
            continue
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            # Already gone, which is the outcome we were asking for.
            pass

    if targets:
        decky.logger.info("Cancelling %d upload(s)", len(targets))
    return len(targets)


def sweep_partials(directory):
    """Delete .uploading leftovers in `directory` that no live transfer owns.

    A handler deletes its own partial on every path it can control -- a client
    that disappears, a write error, a cancel. What it cannot control is the plugin
    being unloaded or the machine losing power mid-transfer, which leaves the file
    behind with nothing that remembers it. Nothing resumes an upload, so a
    leftover is only ever litter sitting in the user's ROM folder.

    Files a running upload is writing are excluded by path, so this is safe to
    call while transfers are in progress.
    """
    if not directory or not os.path.isdir(directory):
        return []

    with _state_lock:
        live = {entry["partial"] for entry in _in_flight.values() if entry.get("partial")}

    removed = []
    try:
        names = os.listdir(directory)
    except OSError as error:
        decky.logger.warning("Could not scan %s for leftovers: %s", directory, error)
        return []

    for name in names:
        if not name.endswith(".uploading"):
            continue
        path = os.path.join(directory, name)
        if path in live or not os.path.isfile(path):
            continue
        _quiet_remove(path)
        if not os.path.exists(path):
            removed.append(path)

    if removed:
        decky.logger.info("Removed %d unfinished upload(s) from %s", len(removed), directory)
    return removed


def _touch():
    global _last_activity
    with _state_lock:
        _last_activity = _now()


# An upload arrow over a tray, drawn rather than borrowed so it needs no asset.
#
# Declared inline for the same reason as everything else on these pages: the
# sending device may have a route to this host and nothing else. It also stops
# every page load asking for /favicon.ico, which this server answers with a 404
# and a line in the plugin log.
#
# Base64 rather than a raw `data:image/svg+xml,...` URI: the SVG contains `#`,
# quotes and angle brackets, all of which need encoding in a URI, and `%23` in
# particular would then have to survive a %-formatted template. Encoding once at
# import keeps the drawing readable here and the URI inert everywhere else.
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#4c6ef5"/>'
    '<path d="M32 15 L45 30 H37 V42 H27 V30 H19 Z" fill="#ffffff"/>'
    '<rect x="18" y="46" width="28" height="5" rx="2.5" fill="#ffffff"/>'
    "</svg>"
)
_FAVICON = "data:image/svg+xml;base64," + base64.b64encode(
    _FAVICON_SVG.encode("utf-8")
).decode("ascii")


def _human_size(count):
    if count >= 1024 ** 3:
        return "%.1f GB" % (count / 1024 ** 3)
    if count >= 1024 ** 2:
        return "%d MB" % round(count / 1024 ** 2)
    return "%d KB" % max(1, round(count / 1024))


# One stylesheet for both pages.
#
# Kept in a constant and substituted in rather than written inline, because these
# pages are built with the % operator and a literal percent in CSS then has to be
# written `%%`. That escaping has bitten this file before and there is no reason
# to keep paying attention to it: a value substituted in is never parsed as a
# format string.
#
# Colours come from custom properties with a light-scheme override, because this
# page is read on someone else's phone or laptop rather than on the Deck -- the
# plugin's own dark styling is not theirs to impose. Everything is sized in a
# single centred column so a desktop browser does not stretch one line of text
# across a 27-inch monitor.
_STYLE = """
  :root {
    color-scheme: dark light;
    --bg: #14171c; --card: #1e222a; --raised: #2a303a;
    --text: #e8eaed; --muted: #9aa1ac; --line: #333a45;
    --accent: #4c6ef5; --accent-soft: rgba(76,110,245,0.16);
    --ok: #5bd15b; --bad: #e35d5d;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f1f3f5; --card: #ffffff; --raised: #eceef1;
      --text: #1a1d23; --muted: #5f6672; --line: #dde0e5;
      --accent-soft: rgba(76,110,245,0.10);
      --ok: #2f9e44; --bad: #c92a2a;
    }
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0;
    padding: 22px 16px calc(28px + env(safe-area-inset-bottom, 0px));
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.45;
  }
  main { width: 100%; max-width: 620px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
  /* The heading and whatever second action the page has, on one line. `gap`
     rather than a margin so the row collapses to just the heading when there is
     no button, and `wrap` so a narrow phone drops the button below rather than
     squeezing the title into two words. */
  .head { display: flex; align-items: baseline; justify-content: space-between;
          gap: 10px 14px; flex-wrap: wrap; }
  /* Looks like a button, is a link: it navigates, and making it a <button> that
     sets location is more moving parts for the same result -- and one that
     stops working with scripting off. */
  a.report { flex: none; font-size: 13px; font-weight: 600; text-decoration: none;
             padding: 7px 12px; border-radius: 8px; white-space: nowrap;
             color: var(--text); background: var(--card);
             border: 1px solid var(--line); }
  a.report:hover { border-color: var(--accent); background: var(--accent-soft); }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em;
       color: var(--muted); margin: 24px 0 8px; font-weight: 600; }
  p.dir { color: var(--muted); font-size: 13px; margin: 0 0 18px;
          word-break: break-all; }
  p.keep { font-size: 13px; margin: 0 0 18px; padding: 11px 13px;
           background: var(--accent-soft); border: 1px solid var(--line);
           border-radius: 10px; }
  label.pick { display: block; padding: 26px 18px; text-align: center;
               border: 2px dashed var(--line); border-radius: 12px;
               background: var(--card); cursor: pointer;
               transition: border-color .15s ease, background .15s ease; }
  label.pick:hover, label.pick.drag { border-color: var(--accent);
                                      background: var(--accent-soft); }
  label.pick b { display: block; font-size: 16px; font-weight: 600; }
  label.pick span { display: block; margin-top: 3px; font-size: 13px;
                    color: var(--muted); }
  input[type=file] { display: none; }
  /* `minmax(0, 1fr)` rather than the implicit `1fr`, and `min-width: 0` on the
     row: a grid item defaults to `min-width: auto`, which means it refuses to
     shrink below the width of its own content. The name inside already clips
     with an ellipsis, but that never got the chance -- the track grew to fit
     the whole filename instead, and a ROM called
     UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6....pkg pushed the card
     clean off the side of the page. Same mistake as the panel's own ROM button,
     in a different layout system. */
  ul { list-style: none; padding: 0; margin: 0; display: grid;
       grid-template-columns: minmax(0, 1fr); gap: 8px; }
  li { min-width: 0; background: var(--card); border: 1px solid var(--line);
       border-radius: 10px; padding: 10px 12px; font-size: 14px; }
  .row { display: flex; align-items: baseline; gap: 10px; }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
          white-space: nowrap; }
  .size { color: var(--muted); font-size: 12px; white-space: nowrap; }
  .bar { height: 5px; margin-top: 8px; border-radius: 3px;
         background: var(--raised); overflow: hidden; }
  .bar i { display: block; height: 100%; width: 0;
           background: var(--accent); transition: width .2s linear; }
  li.done .name::before { content: "\\2713  "; color: var(--ok); }
  li.failed .name::before { content: "\\2717  "; color: var(--bad); }
  li.failed .size { color: var(--bad); }
  form { display: flex; flex-direction: column; gap: 12px; }
  input[type=text] { font-size: 30px; width: 100%; padding: 12px;
                     text-align: center; letter-spacing: .28em;
                     border-radius: 10px; border: 1px solid var(--line);
                     background: var(--card); color: inherit; }
  button { font-size: 16px; padding: 13px 20px; border-radius: 10px; border: 0;
           background: var(--accent); color: #fff; font-weight: 600;
           cursor: pointer; }
  .bad { color: var(--bad); }
"""

# The upload page's behaviour, kept out of the format string for the same reason
# as the stylesheet: it builds a percentage, and `'%'` inside a %-formatted
# template would have to be written `'%%'`.
_SCRIPT = """
const queue = document.getElementById('queue');
const zone = document.getElementById('zone');
const already = document.getElementById('already');
const arrivingHeading = document.getElementById('arrivingHeading');
const receivedHeading = document.getElementById('receivedHeading');

// A file moves between the two lists exactly as it does on the Deck: it is
// Arriving while it is in flight, and Received once the server has it. Leaving
// finished uploads in the first list would make "Arriving" a lie within
// seconds, and is what the panel does not do.
//
// A failed one stays put. It did not arrive, and moving it under Received --
// or hiding it -- would be the page claiming something the Deck does not have.
function reflowHeadings() {
  arrivingHeading.style.display = queue.children.length ? '' : 'none';
  if (already.children.length) receivedHeading.style.display = '';
}

function humanSize(n) {
  if (n >= 1073741824) return (n / 1073741824).toFixed(1) + ' GB';
  if (n >= 1048576) return Math.round(n / 1048576) + ' MB';
  return Math.max(1, Math.round(n / 1024)) + ' KB';
}

// How many uploads are still running, so leaving the page can be questioned.
//
// Closing the tab aborts the request, and a multi-gigabyte ROM then has to start
// over from nothing -- there is no resume. The Deck cleans up the half-written
// file either way, so this guards the user's time rather than the disk.
//
// Advisory only: the browser decides the wording, the user can still leave, and
// several mobile browsers ignore beforeunload entirely. The server therefore
// still treats a vanished connection as normal, because it is.
let active = 0;

window.addEventListener('beforeunload', (event) => {
  if (active === 0) return;
  event.preventDefault();
  // Required for the prompt to appear at all; the string itself is ignored by
  // every current browser in favour of its own wording.
  event.returnValue = '';
  return '';
});

document.getElementById('pick').addEventListener('change', (event) => {
  const files = [...event.target.files];
  event.target.value = '';
  files.forEach(send);
});

// Drag and drop, for the desktop half of the audience. The document-level
// handlers matter as much as the drop zone's: without them a file dropped just
// outside the target replaces the page with itself, losing the queue.
['dragenter', 'dragover', 'dragleave', 'drop'].forEach((name) => {
  document.addEventListener(name, (event) => event.preventDefault());
});
['dragenter', 'dragover'].forEach((name) => {
  zone.addEventListener(name, () => zone.classList.add('drag'));
});
['dragleave', 'drop'].forEach((name) => {
  zone.addEventListener(name, () => zone.classList.remove('drag'));
});
zone.addEventListener('drop', (event) => {
  [...(event.dataTransfer ? event.dataTransfer.files : [])].forEach(send);
});

function send(file) {
  const row = document.createElement('li');
  const head = document.createElement('div');
  head.className = 'row';
  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = file.name;
  const size = document.createElement('div');
  size.className = 'size';
  size.textContent = humanSize(file.size);
  head.appendChild(name);
  head.appendChild(size);
  const bar = document.createElement('div');
  bar.className = 'bar';
  const fill = document.createElement('i');
  bar.appendChild(fill);
  row.appendChild(head);
  row.appendChild(bar);
  queue.appendChild(row);
  reflowHeadings();

  // XHR rather than fetch: it reports upload progress, which matters for ROMs.
  const request = new XMLHttpRequest();
  request.open('PUT', UPLOAD_BASE + encodeURIComponent(file.name));
  request.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) fill.style.width = ((e.loaded / e.total) * 100) + '%';
  });
  // loadend rather than load: it fires for success, failure and abort alike, so
  // the count cannot be left standing by a path that forgot to decrement it and
  // then question every attempt to leave the page forever after.
  request.addEventListener('loadend', () => { active -= 1; });
  request.addEventListener('load', () => {
    bar.remove();
    if (request.status === 200) {
      row.className = 'done';
      // Newest first, matching the order the server lists what it already had.
      already.insertBefore(row, already.firstChild);
    } else {
      row.className = 'failed';
      size.textContent = request.responseText || 'failed';
    }
    reflowHeadings();
  });
  request.addEventListener('error', () => {
    bar.remove();
    row.className = 'failed';
    size.textContent = 'connection lost';
    reflowHeadings();
  });
  active += 1;
  request.send(file);
}
"""


def _code_page(bad=False):
    """The form shown at the root, asking for the six-digit code.

    A GET form, so it works with scripting disabled and needs no CSRF thinking --
    the code itself is the only credential and submitting it is idempotent.
    """
    with _state_lock:
        locked = _pin_locked
        remaining = max(0, PIN_ATTEMPTS - _pin_attempts)

    if locked:
        # Names the two buttons as they are labelled on the Deck. The sender is
        # reading this on another device and cannot see the panel, so "restart
        # the transfer" left them looking for a control with that name, which
        # does not exist.
        message = (
            '<p class="bad">Too many wrong codes. On your Deck, press '
            "<b>Stop receiving</b> and then <b>Start receiving</b> for a new "
            "code.</p>"
        )
        form = ""
    else:
        message = (
            '<p class="bad">That code is not right. %d attempt(s) left.</p>' % remaining
            if bad
            else "<p>Enter the code shown on your Deck.</p>"
        )
        form = """<form method="get" action="/">
  <input type="text" name="code" inputmode="numeric" pattern="[0-9]*" maxlength="%d"
         autocomplete="one-time-code" autofocus placeholder="000000">
  <button type="submit">Continue</button>
</form>""" % PIN_DIGITS

    # Centred in the viewport rather than at the top: this page holds one control
    # and nothing else, so there is nothing below the fold to scroll toward.
    return """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="icon" href="%(icon)s">
<title>Transfer to Deck</title>
<style>%(style)s
  body { min-height: 100vh; display: grid; place-items: center; }
  main { max-width: 22rem; text-align: center; }
  h1 { margin-bottom: 14px; }
</style>
</head><body><main>
<h1>Transfer to Deck</h1>
%(message)s
%(form)s
</main></body></html>""" % {
        "message": message,
        "form": form,
        "style": _STYLE,
        "icon": _FAVICON,
    }


# Offered only when the link is durable, and it is a hint rather than a button
# because no browser will let a page bookmark itself. window.external.AddFavorite
# and window.sidebar.addPanel were both removed years ago and nothing replaced
# them; the install-to-home-screen route needs a secure context, which plain HTTP
# on a LAN address is not. So the most a page can honestly do is name the gesture,
# and name the right one for the device holding it.
_BOOKMARK_HINT = """  <p class="keep" id="keep"></p>
<script>
(function () {
  const ua = navigator.userAgent;
  const line = document.getElementById('keep');
  let how;
  if (/iPhone|iPad|iPod/.test(ua)) {
    how = 'tap Share, then "Add to Home Screen"';
  } else if (/Android/.test(ua)) {
    how = 'open the browser menu, then "Add to Home screen"';
  } else if (/Mac OS X/.test(ua)) {
    how = 'press Cmd-D';
  } else {
    how = 'press Ctrl-D';
  }
  line.textContent = 'Keep this page - ' + how + ' - and next time it opens straight here, with no code to type.';
})();
</script>"""


def _page():
    """The upload page. Deliberately one self-contained file, no assets.

    No external stylesheet, font or script: this is served over plain HTTP from a
    Deck on someone's home network, and every asset would be one more thing that
    has to resolve from a device that may only have a route to this one host.
    """
    with _state_lock:
        directory = _target_dir
        arrived = [(entry["name"], entry["size"]) for entry in _received]
        token = _token
        durable = _durable
        report = bool(_report)

    listed = "".join(
        '<li class="done"><div class="row"><div class="name">%s</div>'
        '<div class="size">%s</div></div></li>'
        % (html.escape(name), _human_size(size))
        for name, size in reversed(arrived)
    )

    return """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="icon" href="%(icon)s">
<title>Transfer to Deck</title>
<style>%(style)s</style>
</head><body>
<main>
  <div class="head">
    <h1>Transfer to Deck</h1>
%(report)s
  </div>
  <p class="dir">Saving into %(dir)s</p>
%(keep)s
  <label class="pick" id="zone">
    <b>Choose files</b>
    <span>or drag them here</span>
    <input id="pick" type="file" multiple>
  </label>

  <!-- The same two words the panel on the Deck uses for the same two lists:
       a file is Arriving until it lands, then it is Received. Both sides of a
       transfer describing it differently is how someone watching one screen
       and holding the other ends up unsure whether they are looking at the
       same thing. -->
  <h2 id="arrivingHeading" style="display:none">Arriving</h2>
  <ul id="queue"></ul>

  <h2 id="receivedHeading"%(hide)s>Received</h2>
  <ul id="already">%(listed)s</ul>
</main>

<script>
// An absolute path including the token. A relative 'upload/...' would resolve
// against /<token> -- which the browser treats as a file, not a directory -- and
// drop the token, so every upload would be refused.
const UPLOAD_BASE = '/%(token)s/upload/';
%(script)s
</script>
</body></html>""" % {
        "dir": html.escape(directory or "?"),
        "token": token,
        "listed": listed,
        "hide": "" if arrived else ' style="display:none"',
        "keep": _BOOKMARK_HINT if durable else "",
        # The report is reached by its own address, which a camera gets from the
        # QR code. Somebody who came the other way -- short address, six digits
        # -- lands here instead, so the door has to be on this page too or the
        # keyboard route reaches everything except the thing they came for.
        # A button beside the heading rather than a line of text under it.
        # This page is a place you were sent to do one thing -- send files -- and
        # the report is the other reason somebody is here at all, so it belongs
        # where a second action belongs: on the header row, out of the way of the
        # thing the page is for, and not dressed up as prose to be read past.
        "report": (
            '    <a class="report" href="/%s/report">Diagnostic report</a>' % token
        ) if report else "",
        "style": _STYLE,
        "script": _SCRIPT,
        "icon": _FAVICON,
    }


def offer_report(report):
    """Make a diagnostic report readable at `/<token>/report`. "" withdraws it.

    Held in memory only. It is a snapshot of a moment worth reporting, not a
    file the plugin owns, and writing it down would leave a copy of the log tail
    on the device for nobody to clean up.
    """
    global _report
    with _state_lock:
        _report = report or ""
    return bool(report)


def status():
    with _state_lock:
        running = _server is not None
        return {
            "running": running,
            # Where the report is, when there is one. Given as a whole address
            # rather than as a flag so the panel has nothing to assemble.
            "report_url": ("http://%s:%d/%s/report" % (_host_ip, _server.server_port, _token))
            if running and _host_ip and _report
            else "",
            # Trailing slash so the address also works if typed by hand and any
            # relative link on the page resolves inside the token path.
            "url": ("http://%s:%d/%s/" % (_host_ip, _server.server_port, _token))
            if running and _host_ip
            else "",
            # What to type on a device with a keyboard: short address, then code.
            "short_url": ("http://%s:%d/" % (_host_ip, _server.server_port))
            if running and _host_ip
            else "",
            "pin": _pin if running else "",
            "pin_locked": _pin_locked,
            # Non-zero means a transfer would be cut off by stopping now.
            "uploading": len(_in_flight),
            # Oldest first, so a list of them stays in a stable order as they
            # come and go rather than reshuffling under the reader.
            "uploads": [
                {
                    # The handle cancel() is addressed by. A name would not do:
                    # two devices can send the same filename at once.
                    "id": key,
                    "name": entry["name"],
                    "received": entry["received"],
                    "total": entry["total"],
                    "cancelled": entry["cancelled"],
                }
                for key, entry in sorted(
                    _in_flight.items(), key=lambda item: item[1]["at"]
                )
            ],
            "port": _server.server_port if running else 0,
            "target_dir": _target_dir,
            "received": list(reversed(_received)),
            "idle_seconds": int(_now() - _last_activity) if running else 0,
            "idle_timeout": IDLE_TIMEOUT,
        }


_host_ip = ""


def _bind(port):
    """(server, error). Falls back to any free port when a chosen one is taken."""
    candidates = [port, 0] if port else [0]
    last = None
    for candidate in candidates:
        try:
            # Port 0 lets the OS pick a free one; 8080 in particular is taken by
            # Steam's CEF debugging, which is why nothing here is hardcoded.
            return ThreadingHTTPServer(("0.0.0.0", candidate), _Handler), ""
        except OSError as error:
            last = error
            if candidate:
                # A remembered port that something else has taken should cost a
                # changed address, not a failed transfer.
                decky.logger.warning(
                    "Port %d is unavailable (%s); taking any free port instead",
                    candidate,
                    error,
                )
    return None, "Could not start the server: %s" % last


def start(target_dir, port=0, token=""):
    """Start the server, returning the same shape as `status()`.

    `port` and `token` are how a bookmarked link keeps working. Both default to
    "mint a new one", which is the behaviour that leaves nothing usable behind at
    the end of a session. Passing the pair recorded from a previous session
    reproduces the same URL, so a device that saved it needs neither the address
    nor the code again -- and the caller is expected to persist whatever comes
    back, since a requested port may have been taken and fallen back from.
    """
    global _server, _thread, _token, _target_dir, _last_activity, _host_ip
    global _pin, _pin_attempts, _pin_locked, _durable

    if not target_dir or not os.path.isdir(target_dir):
        return {"error": "Choose a folder that exists to receive files into."}
    if not os.access(target_dir, os.W_OK):
        return {"error": "Cannot write into %s" % target_dir}

    with _state_lock:
        already = _server is not None
    if already:
        stop()

    ip = local_ip()
    if not ip:
        return {"error": "This Deck does not appear to be on a network."}

    server, bind_error = _bind(port)
    if server is None:
        return {"error": bind_error}

    server.daemon_threads = True

    with _state_lock:
        _server = server
        _host_ip = ip
        # Reused when one was supplied, which is what a saved link depends on.
        _token = token or secrets.token_urlsafe(TOKEN_BYTES)
        # Only a link that is both the same address and the same token is worth
        # bookmarking, and a fallen-back port is neither.
        _durable = bool(token) and server.server_port == port
        # A fresh code per session, and a fresh allowance of wrong guesses. Both
        # reset here rather than on stop, so a locked-out server recovers by being
        # started again -- which is what the panel tells the user to do.
        _pin = "".join(str(secrets.randbelow(10)) for _ in range(PIN_DIGITS))
        _pin_attempts = 0
        _pin_locked = False
        # The one place this is cleared. Nothing uploaded to the previous server
        # is still in flight against this one, so a leftover entry would show a
        # transfer that no longer exists and hold the panel open on it.
        _in_flight.clear()
        _target_dir = target_dir
        _last_activity = _now()
        _received.clear()

    # After the clear above, so nothing is treated as live that is not. This is
    # where a partial abandoned by an unload or a power cut finally goes: the
    # handler that would have deleted it no longer exists.
    sweep_partials(target_dir)

    thread = threading.Thread(target=server.serve_forever, name="deckyemu-fileserver", daemon=True)
    thread.start()
    _thread = thread

    threading.Thread(target=_watch_idle, name="deckyemu-fileserver-idle", daemon=True).start()

    decky.logger.info(
        "File server listening on %s:%d, saving into %s", ip, server.server_port, target_dir
    )
    return status()


def _watch_idle():
    """Stop the server once nothing has happened for a while."""
    while True:
        time.sleep(15)
        with _state_lock:
            if _server is None:
                return
            idle = _now() - _last_activity
        if idle >= IDLE_TIMEOUT:
            decky.logger.info("File server idle for %.0fs, stopping", idle)
            stop()
            return


def stop():
    global _server, _thread, _token, _pin, _report
    with _state_lock:
        server = _server
        _server = None
        _token = ""
        # Cleared as well, so a stopped server never reports a code that would
        # still be shown on screen next to a dead address.
        _pin = ""
        # And the report goes with the server that was serving it. It holds the
        # tail of a log, so keeping it in memory past the moment somebody asked
        # for it is a copy of that sitting around for no reason.
        _report = ""
        # _in_flight is deliberately left alone. Clearing it here while a PUT was
        # still running would drop an entry its own handler is about to remove --
        # the counter version of this bug drove the count to -1, and since start()
        # never reset it the panel could no longer tell that nothing was in
        # flight for the rest of the session. The requests that added entries are
        # the only things entitled to remove them; start() clears the slate.

    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except OSError as error:
            decky.logger.warning("File server did not stop cleanly: %s", error)
        decky.logger.info("File server stopped")

    _thread = None
    return status()


def current_token():
    """The token this session is serving under, so the caller can persist it.

    Deliberately not part of status(): that payload is for display, and this is
    the credential itself. The URL in status() embeds it because the page has to
    be reachable, but nothing else needs it spelled out.
    """
    with _state_lock:
        return _token


def received_files():
    """Uploaded files that are still on disk, newest first."""
    with _state_lock:
        entries = list(reversed(_received))
    alive = []
    for entry in entries:
        if not os.path.isfile(entry["path"]):
            continue
        if entry["name"].lower().endswith(_IGNORED_SUFFIXES):
            continue
        alive.append(entry)
    return alive
