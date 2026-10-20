"""Talking to Steam's UI over its remote-debugging port.

Steam serves the DevTools protocol on 127.0.0.1:8080 once the
`.cef-enable-remote-debugging` file exists in its install. This is a small
client for it: list the pages, open one page's websocket, send commands and
read replies. Standard library only, because the service runs on SteamOS's own
Python and nothing outside the standard library is promised to stay there.

Only ever a page's own websocket, never the browser's. A browser-level session
with auto-attach open while Steam boots stops the Big Picture window from
starting -- measured on a Deck, three times, each needing a Steam restart.
"""

import base64
import json
import os
import queue
import socket
import struct
import threading
import urllib.request

PORT = 8080
LIST_URL = "http://127.0.0.1:%d/json" % PORT

#: The file Steam looks for before it opens the debugging port.
ENABLE_FILE = ".cef-enable-remote-debugging"


def targets(timeout=0.5):
    """Every page Steam's browser has, as the list `/json` returns. Raises if
    the port is not open."""
    with urllib.request.urlopen(LIST_URL, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ui_page(listing):
    """The page Steam's UI runs in, or None.

    Named "SharedJSContext" once it has loaded. In the first few tens of
    milliseconds after it is created it has no title and no URL yet, and it is
    then the only page there is -- which is the moment worth catching.
    """
    pages = [t for t in listing if t.get("type") == "page"]
    for page in pages:
        if page.get("title") == "SharedJSContext":
            return page
    if len(pages) == 1 and not pages[0].get("url"):
        return pages[0]
    return None


def ensure_enabled(steam_dir):
    """Create the file that turns the port on. Takes effect at Steam's next
    start; returns whether it had to be created."""
    path = os.path.join(steam_dir, ENABLE_FILE)
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8"):
        pass
    return True


def _mask(data, key):
    """XOR `data` with the repeating 4-byte `key`, as one big integer: a
    byte-at-a-time loop takes seconds over a frontend bundle."""
    size = len(data)
    if not size:
        return b""
    pad = (key * (size // 4 + 1))[:size]
    return (int.from_bytes(data, "big") ^ int.from_bytes(pad, "big")).to_bytes(size, "big")


class Closed(Exception):
    """The page went away: Steam restarted, or reloaded its UI from scratch."""


class Page:
    """One page's websocket. Thread-safe to send on; one reader thread."""

    def __init__(self, ws_url, timeout=10):
        rest = ws_url.split("://", 1)[1]
        hostport, path = rest.split("/", 1)
        host, _, port = hostport.partition(":")
        self._sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self._sock.sendall((
            "GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)
        ).encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise Closed("handshake refused")
            head += chunk
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise Closed(status.decode("latin-1"))
        self._buffer = head.split(b"\r\n\r\n", 1)[1]
        self._sock.settimeout(None)
        self._send_lock = threading.Lock()
        self._next_id = 0
        self._waiting = {}
        self._waiting_lock = threading.Lock()
        self.events: "queue.Queue[dict]" = queue.Queue()
        self.closed = threading.Event()
        threading.Thread(target=self._read_loop, daemon=True).start()

    # --- framing ---------------------------------------------------------

    def _send_frame(self, payload, opcode=0x1):
        header = bytes([0x80 | opcode])
        size = len(payload)
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 1 << 16:
            header += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", size)
        mask = os.urandom(4)
        with self._send_lock:
            self._sock.sendall(header + mask + _mask(payload, mask))

    def _read_exact(self, size):
        while len(self._buffer) < size:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise Closed("connection closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def _read_message(self):
        parts = []
        while True:
            first, second = self._read_exact(2)
            opcode = first & 0x0F
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self._read_exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._read_exact(8))[0]
            if second & 0x80:
                mask = self._read_exact(4)
                data = _mask(self._read_exact(size), mask)
            else:
                data = self._read_exact(size)
            if opcode == 0x8:
                raise Closed("closed by Steam")
            if opcode == 0x9:
                self._send_frame(data, 0xA)
                continue
            if opcode == 0xA:
                continue
            parts.append(data)
            if first & 0x80:
                return b"".join(parts)

    def _read_loop(self):
        try:
            while True:
                message = json.loads(self._read_message().decode("utf-8"))
                if "id" in message:
                    with self._waiting_lock:
                        slot = self._waiting.pop(message["id"], None)
                    if slot is not None:
                        slot["reply"] = message
                        slot["done"].set()
                else:
                    self.events.put(message)
        except (Closed, OSError, ValueError):
            pass
        finally:
            self.closed.set()
            with self._waiting_lock:
                for slot in self._waiting.values():
                    slot["done"].set()
                self._waiting.clear()
            self.events.put({"method": "deckyemu.closed"})

    # --- commands --------------------------------------------------------

    def next_event(self, timeout=1.0):
        """The next event Steam sent, or None after `timeout` seconds. A
        `deckyemu.closed` event marks the end."""
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, method, **params):
        """Queue a command without waiting. Returns a handle for `wait`."""
        with self._waiting_lock:
            self._next_id += 1
            ident = self._next_id
            slot = {"done": threading.Event(), "reply": None}
            self._waiting[ident] = slot
        self._send_frame(json.dumps({"id": ident, "method": method, "params": params}).encode("utf-8"))
        return slot

    def wait(self, slot, timeout=10):
        if not slot["done"].wait(timeout):
            raise TimeoutError("no reply from Steam")
        if slot["reply"] is None:
            raise Closed("page closed before replying")
        return slot["reply"]

    def call(self, method, timeout=10, **params):
        return self.wait(self.send(method, **params), timeout)

    def evaluate(self, expression, timeout=10, await_promise=False):
        """The value of `expression` in the page. Raises on a thrown exception."""
        reply = self.call("Runtime.evaluate", timeout=timeout, expression=expression,
                          returnByValue=True, awaitPromise=await_promise)
        result = reply.get("result", {})
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = (details.get("exception") or {}).get("description") or details.get("text")
            raise RuntimeError(text or "the page threw")
        return result.get("result", {}).get("value")

    def close(self):
        try:
            self._send_frame(b"", 0x8)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
