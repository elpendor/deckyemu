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
import fileserver_page
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
# Whether this server accepts files, as opposed to only handing one out.
#
# It exists because "show somebody a report" must not also mean "let them write
# into the ROM folder". Reading a report needs a server, and starting one for
# that reason used to open the upload endpoint with it -- so handing over a QR
# code handed over a writable inbox nobody asked to offer. A transfer turns it
# back on, since that is the whole point of a transfer.
_uploads = True

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


def waiting_dir():
    """`default_dir()` when a file is sitting in it, otherwise "".

    The ROM picker opens here when this answers, and that is the only condition
    under which it should: this folder empties itself as games are added --
    adding one moves its ROM into `roms/<system>/` -- so it is empty most of the
    time, and opening a picker in an empty folder is precisely the miss that
    `ra_detect.default_rom_dir` stopped guessing to avoid.

    It exists because the received list is the only route to a transferred file
    and that list does not survive: `start()` clears it, so a file sent before a
    plugin reload, or one the user did not add before closing the dialog, has
    nowhere left to be reached from. It is still on disk, three navigations away
    from wherever the picker last opened.

    `create=False`, because this only asks a question. `default_dir()` creates on
    demand, and answering "is anything waiting?" must not be what brings the
    folder into existence.
    """
    directory = default_dir(create=False)
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                # The same two exclusions the received list uses: a partial
                # upload is not a file anyone can add, and a dotfile is not
                # something the user sent.
                if entry.name.startswith("."):
                    continue
                if entry.name.lower().endswith(_IGNORED_SUFFIXES):
                    continue
                if entry.is_file():
                    return directory
    except OSError:
        # Missing is the normal answer before anything has ever been sent, and
        # unreadable is not worth failing a status call over.
        return ""
    return ""


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
            with _state_lock:
                report_only = not _uploads and bool(_report)
            # Whoever came in by the six-digit code lands here. On a server that
            # exists only to hand out a report, an upload form is both wrong and
            # a lie -- the PUT behind it refuses -- so the report is the page.
            if report_only:
                self._send(200, diagnostics.as_page(_report), "text/html; charset=utf-8")
                return
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
        # A server started to hand out a report does not take files. The token
        # is the same one, so anyone shown the report could otherwise write into
        # the ROM folder -- which is not what showing somebody a report is meant
        # to offer, and not something they could tell they had been given.
        with _state_lock:
            if not _uploads:
                self._deny()
                return

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


def _code_page(bad=False):
    """The code form, rendered from the server's own attempt counters."""
    with _state_lock:
        locked = _pin_locked
        remaining = max(0, PIN_ATTEMPTS - _pin_attempts)
    return fileserver_page.code_page(locked, remaining, bad=bad, digits=PIN_DIGITS)


def _page():
    """The upload page, rendered from one consistent read of the state.

    Everything the page shows is taken under the lock in one go and handed over
    together, rather than read field by field while the markup is assembled: an
    upload finishing between two of those reads would put a file in the Received
    list and the pre-change heading above it.
    """
    with _state_lock:
        directory = _target_dir
        arrived = [(entry["name"], entry["size"]) for entry in _received]
        token = _token
        durable = _durable
        report = bool(_report)
    return fileserver_page.upload_page(directory, arrived, token, durable, report)


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


def allow_uploads():
    """Let a server started for a report accept files after all.

    Called when a transfer begins on a server that is already up. Without it,
    reading a report first and sending a ROM second would refuse the ROM.
    """
    global _uploads
    with _state_lock:
        _uploads = True


def start(target_dir, port=0, token="", uploads=True):
    """Start the server, returning the same shape as `status()`.

    `port` and `token` are how a bookmarked link keeps working. Both default to
    "mint a new one", which is the behaviour that leaves nothing usable behind at
    the end of a session. Passing the pair recorded from a previous session
    reproduces the same URL, so a device that saved it needs neither the address
    nor the code again -- and the caller is expected to persist whatever comes
    back, since a requested port may have been taken and fallen back from.
    """
    global _server, _thread, _token, _target_dir, _last_activity, _host_ip
    global _pin, _pin_attempts, _pin_locked, _durable, _uploads

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
        _uploads = bool(uploads)
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
