"""The upload page in a real browser, end to end against the Deck.

    python scripts/upload_page_e2e.py --chrome PATH [--deck deck@steamdeck.local]

Runs on a computer with Playwright, driving a Chromium named by --chrome (any
build: nothing is downloaded, and no installed browser or profile is touched).
The Deck's transfer dialog is opened over SSH, so its server is up and its code
on screen; the code is read from there and typed, never guessed -- the page
locks out after wrong attempts.

Every file it sends has a made-up name and is deleted from the Deck afterwards,
with the platform it was sent as. One file is a PS3 licence RPCS3 already has,
copied from the Deck itself so the "already in RPCS3" note can be seen; sending
it changes nothing there.
"""

import argparse
import json
import os
import re
import shlex
import socket
import threading
import shutil
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright
from urllib.parse import urlsplit

DECK_UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck-ui.sh")
# By PATH, not CreateProcess's search: on Windows that finds System32's WSL
# bash before Git's, and deck-ui.sh needs the one on PATH.
BASH = shutil.which("bash") or "bash"
PREFIX = "E2E Upload"
results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("%s %-62s %s" % ("PASS" if ok else "FAIL", label, "" if ok else detail))


def ssh(deck, command, timeout=60):
    return subprocess.run(["ssh", deck, command], capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def deck_js(js, target="Steam Big Picture Mode"):
    """Evaluate in a Steam window, through the Deck's own CDP client."""
    # As one JSON string: a result with line breaks in it is one value. And
    # sent as character codes: quotes in an argument do not survive Windows,
    # Git Bash and SSH each quoting it their own way; digits and commas do.
    codes = ",".join(str(ord(char)) for char in "JSON.stringify(%s)" % js)
    out = subprocess.run([BASH, DECK_UI, "eval", target,
                          "eval(String.fromCharCode(%s))" % codes],
                         capture_output=True, text=True, timeout=90).stdout.strip()
    try:
        return json.loads(out.splitlines()[-1]) if out else ""
    except ValueError:
        return ""


def open_transfer_dialog():
    subprocess.run([BASH, DECK_UI, "qam"], capture_output=True, timeout=90)
    time.sleep(3)
    subprocess.run([BASH, DECK_UI, "eval", "QuickAccess",
                    '[...document.querySelectorAll("button,[role=button]")]'
                    '.find(b=>b.textContent.trim()==="Transfer to Deck").click()'],
                   capture_output=True, timeout=90)
    time.sleep(6)


def deck_code():
    """The address and six-digit code the Deck's dialog shows."""
    # The address, "then" and the code are separate lines of the dialog.
    text = deck_js('(document.body.innerText.match(/http:\\/\\/[\\d.]+:\\d+\\/\\s*then\\s*[\\d\\s]{6,}/) || [""])[0]')
    match = re.search(r"(http://[\d.]+:\d+)/\s*then\s*([\d ]+)", text)
    if not match:
        raise SystemExit("the Deck's transfer dialog is not showing a code: %r" % text)
    return match.group(1), match.group(2).replace(" ", "")


class Relay:
    """Between the browser and the Deck: uploads at a steady rate, and every
    connection cut on demand, the way a dropped Wi-Fi link cuts them.

    Chrome's own network emulation does not slow an upload, and a local
    network carries a test file before anything can be done mid-way."""

    def __init__(self, target, rate):
        self.target, self.rate = target, rate
        self.sockets, self.lock = [], threading.Lock()
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            upstream = socket.create_connection(self.target)
            with self.lock:
                self.sockets += [client, upstream]
            threading.Thread(target=self._pump, args=(client, upstream, True), daemon=True).start()
            threading.Thread(target=self._pump, args=(upstream, client, False), daemon=True).start()

    def _pump(self, source, sink, limited):
        chunk = 64 * 1024
        try:
            while True:
                data = source.recv(chunk)
                if not data:
                    break
                sink.sendall(data)
                if limited:
                    time.sleep(len(data) / self.rate)
        except OSError:
            pass
        finally:
            for one in (source, sink):
                try:
                    one.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def drop(self):
        """Cut every open connection, mid-request."""
        with self.lock:
            dropped, self.sockets = self.sockets, []
        for one in dropped:
            try:
                one.shutdown(socket.SHUT_RDWR)
                one.close()
            except OSError:
                pass

    def close(self):
        self.drop()
        self.listener.close()


def make(folder, name, size):
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(os.urandom(size))
    return path


def received(page):
    return page.evaluate("[...document.querySelectorAll('#already > li')].map((li) => ({"
                         " text: li.textContent, shown: li.offsetParent !== null }))")


def wait_received(page, name, timeout=120):
    page.wait_for_function(
        "(n) => [...document.querySelectorAll('#already > li')].some((li) => li.textContent.includes(n))",
        arg=name, timeout=timeout * 1000)
    return next(row for row in received(page) if name in row["text"])


def fits(page, label):
    width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check("%s fits a phone, nothing spills sideways" % label, width[0] <= width[1], width)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", required=True)
    parser.add_argument("--deck", default="deck@steamdeck.local")
    args = parser.parse_args()
    deck = args.deck
    work = tempfile.mkdtemp(prefix="upload-e2e-")
    server = None

    open_transfer_dialog()
    base, code = deck_code()
    print("Deck at %s, code shown on its screen" % base)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.chrome, headless=True)

            # --- the code, typed; then the bookmark -----------------------
            phone = browser.new_context(viewport={"width": 375, "height": 800})
            page = phone.new_page()
            page.goto(base + "/")
            check("without the link, the page asks for the Deck's code",
                  page.locator("input[name=code]").count() == 1)
            fits(page, "the code page")
            page.fill("input[name=code]", code)
            page.click("button[type=submit]")
            page.wait_for_selector("#pick", state="attached", timeout=15000)
            check("the right code opens the upload page", page.locator("#pick").count() == 1)
            fits(page, "the upload page")
            token_url = page.url
            fresh = browser.new_context()
            bookmark = fresh.new_page()
            bookmark.goto(token_url)
            check("the page's own address opens it again, with no code",
                  bookmark.locator("#pick").count() == 1, bookmark.url)
            fresh.close()
            page.screenshot(path=os.path.join(work, "phone.png"), full_page=True)

            desk = browser.new_context(viewport={"width": 1280, "height": 900})
            page = desk.new_page()
            requests = []
            page.on("request", lambda r: requests.append((r.method, r.url, r.headers)))
            page.goto(token_url)

            # --- several files at once, and the fold ----------------------
            names = ["%s %d.bin" % (PREFIX, n) for n in range(1, 6)]
            page.set_input_files("#pick", [make(work, name, 4096) for name in names])
            for name in names:
                wait_received(page, name)
            rows = [row for row in received(page) if PREFIX in row["text"]]
            check("five files picked at once all arrive", len(rows) == 5, len(rows))
            total = len(received(page))
            shown = [row for row in received(page) if row["shown"]]
            more = page.locator("#moreReceived")
            check("the list keeps three in view", len(shown) == 3, len(shown))
            check("its heading counts them all",
                  page.inner_text("#receivedHeading") == "Received (%d)" % total,
                  page.inner_text("#receivedHeading"))
            check("and says how many it holds back", more.inner_text() == "Show all %d" % total, more.inner_text())
            more.click()
            check("Show all shows them all",
                  all(row["shown"] for row in received(page)) and more.inner_text() == "Show fewer",
                  more.inner_text())
            more.click()

            # --- drag and drop --------------------------------------------
            dropped = "%s Dropped.bin" % PREFIX
            page.evaluate("""(name) => {
              const data = new DataTransfer();
              data.items.add(new File([new Uint8Array(2048)], name));
              const zone = document.getElementById('zone');
              for (const type of ['dragenter', 'dragover', 'drop']) {
                zone.dispatchEvent(new DragEvent(type, { dataTransfer: data, bubbles: true, cancelable: true }));
              }
            }""", dropped)
            wait_received(page, dropped)
            check("a file dropped on the page arrives", True)

            # --- the platform picked goes with the file -------------------
            options = page.eval_on_selector_all("#platform option", "(o) => o.map((x) => x.value)")
            if "Sony - PlayStation 2" in options:
                page.select_option("#platform", "Sony - PlayStation 2")
                iso = "%s Game (USA).iso" % PREFIX
                page.set_input_files("#pick", [make(work, iso, 8192)])
                row = wait_received(page, iso)
                hints = json.loads(ssh(deck, "cat ~/.local/share/deckyemu/data/system-hints.json") or "{}")
                picked = next((v for k, v in hints.items() if k.endswith("/" + iso)), "")
                check("the platform picked is kept for the file", picked == "Sony - PlayStation 2", picked)
                check("and the row says so", "PS2" in row["text"] or "PlayStation 2" in row["text"], row["text"])
                page.select_option("#platform", "")
            else:
                print("     (skipped the platform check: PlayStation 2 is not offered)")

            # --- a licence RPCS3 already has ------------------------------
            rap = ssh(deck, "ls ~/.config/rpcs3/dev_hdd0/home/00000001/exdata/*.rap 2>/dev/null | head -1")
            if rap:
                local = os.path.join(work, os.path.basename(rap))
                subprocess.run(["scp", "-q", "%s:%s" % (deck, shlex.quote(rap)), local], check=True)
                page.set_input_files("#pick", [local])
                row = wait_received(page, os.path.basename(rap))
                check("a licence RPCS3 already has says so on its row", "already in RPCS3" in row["text"], row["text"])
            else:
                print("     (skipped the licence check: RPCS3 has no licence to send back)")

            # --- a connection lost halfway, carried on --------------------
            # Through the relay: 4 MB/s, so a 40 MB file takes ten seconds.
            deck_url = urlsplit(token_url)
            relay = Relay((deck_url.hostname, deck_url.port), 4 * 1024 * 1024)
            slow = desk.new_page()
            slow_requests = []
            slow.on("request", lambda r: slow_requests.append((r.method, r.url, r.headers)))
            slow.goto("http://127.0.0.1:%d%s" % (relay.port, deck_url.path))
            big = "%s Resumed.bin" % PREFIX
            size = 40 * 1024 * 1024
            slow.set_input_files("#pick", [make(work, big, size)])
            time.sleep(3)
            relay.drop()
            wait_received(slow, big, timeout=240)
            offsets = [int(h.get("x-upload-offset") or 0) for m, u, h in slow_requests
                       if m == "PUT" and "Resumed" in u]
            check("a dropped connection carries on from where it stopped",
                  len(offsets) >= 2 and max(offsets) > 0, offsets)
            got = ssh(deck, "stat -c %%s %s" % shlex.quote("deckyemu/transfer/" + big))
            check("and the file on the Deck is whole", got == str(size), got)

            # --- cancelled on the Deck ------------------------------------
            doomed = "%s Cancelled.bin" % PREFIX
            slow_requests.clear()
            slow.set_input_files("#pick", [make(work, doomed, size)])
            time.sleep(4)
            # The dialog sums up what arrives; each file's Cancel is in Details.
            press = ('(()=>{const b=[...document.querySelectorAll("[class*=DialogButton],button")]'
                     '.find(b=>b.textContent.trim()==="%s"); if(!b) return "none"; b.click(); return "ok"})()')
            deck_js(press % "Details")
            time.sleep(2)
            pressed = deck_js(press % "Cancel")
            time.sleep(2)
            # Not B: Details closes by itself once nothing is arriving, and a
            # B then would close the dialog, which stops the server.
            check("the Deck's dialog shows the upload with a Cancel to press", pressed == "ok", pressed)
            row_text = ""
            for _ in range(60):
                row_text = slow.evaluate(
                    "(n) => ([...document.querySelectorAll('#queue > li, #already > li')]"
                    ".find((li) => li.textContent.includes(n)) || {}).textContent || ''", doomed)
                if "cancelled on the Deck" in row_text:
                    break
                time.sleep(1)
            puts = len([1 for m, u, _h in slow_requests if m == "PUT" and "Cancelled" in u])
            time.sleep(5)
            again = len([1 for m, u, _h in slow_requests if m == "PUT" and "Cancelled" in u])
            check("Cancel on the Deck says so on the page", "cancelled on the Deck" in row_text, row_text)
            check("and the upload does not come back", again == puts, (puts, again))
            # Its partial file is kept on purpose, so sending it again resumes.
            whole = ssh(deck, "test -f %s && echo yes || echo no"
                        % shlex.quote("deckyemu/transfer/" + doomed))
            check("and it is not offered as a file that arrived", whole == "no", whole)
            relay.close()

            # --- an emulator definition from a link ----------------------
            definition = "%s Emulator.deckyemu.json" % PREFIX
            ssh(deck, "mkdir -p /tmp/e2e-link && printf '%s' > %s" % (
                json.dumps({"id": "e2e-upload", "definitions": []}),
                shlex.quote("/tmp/e2e-link/" + definition)))
            server = ssh(deck, "systemd-run --user --unit=e2e-link --collect "
                               "python3 -m http.server 8765 --bind 127.0.0.1 --directory /tmp/e2e-link "
                               ">/dev/null 2>&1; echo started")
            time.sleep(2)
            page.click("details.link summary")
            page.fill("#linkUrl", "http://127.0.0.1:8765/" + definition.replace(" ", "%20"))
            page.click("#linkGo")
            # Saved under its own name or its id: what arrived decides.
            page.wait_for_function(
                "() => [...document.querySelectorAll('#already > li')].some("
                "(li) => /Emulator|e2e-upload/.test(li.textContent))",
                timeout=60000)
            check("a definition fetched from a link lands in Received", True)
            try:
                page.screenshot(path=os.path.join(work, "desk.png"), full_page=True, timeout=10000)
            except Exception as error:  # noqa: BLE001 -- a picture, not a check
                print("     (no screenshot: %s)" % str(error).splitlines()[0])
            browser.close()
    finally:
        # The licence lines its sends left in the Deck's transfer list.
        try:
            deck_js("(async () => { await window.__deckyemu.batchTest.forgetTakenLicences(null); return 1; })()",
                    target="SharedJSContext")
        except Exception:  # noqa: BLE001 -- cleanup goes on
            pass
        if server:
            ssh(deck, "systemctl --user stop e2e-link 2>/dev/null; rm -rf /tmp/e2e-link")
        # Everything sent here, and the platform it was sent as.
        ssh(deck, "cd ~/deckyemu/transfer && rm -f -- %s* *Emulator*.deckyemu.json e2e-upload*.deckyemu.json; python3 - <<'EOF'\n"
                  "import json, os\n"
                  "p = os.path.expanduser('~/.local/share/deckyemu/data/system-hints.json')\n"
                  "if os.path.isfile(p):\n"
                  "    d = json.load(open(p))\n"
                  "    json.dump({k: v for k, v in d.items() if %r not in k}, open(p, 'w'))\n"
                  "EOF" % (shlex.quote(PREFIX), PREFIX))
        print("screenshots in %s" % work)

    failed = results.count(False)
    print("\n%d passed, %d failed" % (results.count(True), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
