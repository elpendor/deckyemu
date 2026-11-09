"""The rescue page: DeckyEmu's status and its repairs, in Steam's browser.

The library tile opens it (rescue.sh), so it works when nothing of DeckyEmu
inside Steam does -- the patch refused on a new Steam build, the panel failing
to start, or an update that went wrong. What it offers is what fixes those:
update, roll back, restart, and the log to say which is needed.

Loopback only, under a secret path: a web page open in Steam's browser can
reach 127.0.0.1 too, and must not be able to press these buttons. The path is
written to `run/rescue-url`, readable by this user only, and kept across
restarts so the page can reload into itself.
"""

import html
import http.server
import json
import os
import re
import secrets
import socketserver
import threading

import appenv

PORT = 41239


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _log_tail(lines=40):
    try:
        logs = sorted(
            (os.path.join(appenv.LOG_DIR, name) for name in os.listdir(appenv.LOG_DIR) if name.endswith(".log")),
            key=os.path.getmtime,
        )
        if not logs:
            return ""
        with open(logs[-1], encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:])
    except OSError:
        return ""


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>DeckyEmu</title>
<meta name="viewport" content="width=device-width">
<style>
 body { background:#171d25; color:#dcdedf; font:18px sans-serif; margin:32px; }
 h1 { margin:0 0 20px; font-size:30px; } h1 small { font-size:18px; font-weight:normal; opacity:.6; }
 .cols { display:grid; grid-template-columns:minmax(0, 1fr) 320px; gap:24px; align-items:start; }
 @media (max-width:760px) { .cols { grid-template-columns:1fr; } }
 .card { background:#23262e; border-radius:6px; padding:18px 22px; }
 .card h2 { font-size:15px; letter-spacing:.08em; text-transform:uppercase; opacity:.6; margin:0 0 10px; }
 .card h2 + .item, .card .item { display:flex; gap:12px; margin:7px 0; }
 .card .sub { margin-top:18px; }
 .mark { width:1.2em; text-align:center; font-weight:bold; }
 .ok .mark { color:#59bf40; } .bad .mark { color:#e05252; } .warn .mark { color:#e8b030; }
 .label { flex:1; } .value { opacity:.7; text-align:right; }
 .actions { display:flex; flex-direction:column; gap:10px; }
 button { font-size:20px; padding:14px 22px; border:0; border-radius:4px; text-align:left;
          background:#3d4450; color:#fff; overflow-wrap:anywhere; }
 button:focus, button:hover, .pad { background:#1a9fff; }
 summary.pad { outline:2px solid #1a9fff; outline-offset:4px; }
 button small { display:block; font-size:15px; opacity:.7; margin-top:2px; }
 #result { margin:6px 2px; font-weight:bold; }
 details { margin-top:24px; } summary { font-size:18px; cursor:pointer; opacity:.8; }
 pre { background:#0e1218; padding:12px; white-space:pre-wrap; font-size:13px; max-height:40vh; overflow:auto; }
</style></head><body>
<h1>DeckyEmu <small>%(version)s</small></h1>
<div class="cols">
 <div class="card">
  <h2>Status</h2>
%(checks)s
%(patches)s
 </div>
 <div class="actions">
%(actions)s
  <button onclick="location.reload()">Refresh</button>
  <div id="result"></div>
 </div>
</div>
<details><summary>Log</summary><pre>%(log)s</pre></details>
<script>
async function act(what) {
  const out = document.getElementById("result");
  out.textContent = "Working...";
  try {
    // From the page's own path: it has no trailing slash, so a relative
    // "update" would drop the secret segment and every button would 404.
    const r = await fetch(location.pathname.replace(/[/]+$/, "") + "/" + what, { method: "POST" });
    const j = await r.json();
    out.textContent = j.message || (j.ok ? "Done." : "That did not work.");
    if (j.ok && what !== "update" && what !== "take_over") setTimeout(() => location.reload(), 4000);
  } catch (e) { out.textContent = "DeckyEmu is restarting. Refresh in a few seconds."; }
}

// The controller, forwarded by the service (rescue_pad.py) as Steam's button
// numbers: 0 A, 20 up, 21 down, 22 left, 23 right.
let at = 0;
function pad(button) {
  // Only while showing: a page left open behind the library must not act.
  if (document.visibilityState !== "visible") return false;
  const items = [...document.querySelectorAll(".actions button, summary")];
  if (!items.length) return false;
  if (button === 0) { items[Math.min(at, items.length - 1)].click(); return true; }
  if (button === 20 || button === 22) at = Math.max(0, at - 1);
  else if (button === 21 || button === 23) at = Math.min(items.length - 1, at + 1);
  else return false;
  mark(items);
  return true;
}
function mark(items) {
  items.forEach((item, i) => item.classList.toggle("pad", i === at));
  items[at].scrollIntoView({ block: "nearest" });
}
mark([...document.querySelectorAll(".actions button, summary")]);

// The status card, kept current: a restart finishes loading the panel a few
// seconds after the page has reloaded into it.
setInterval(async () => {
  if (document.visibilityState !== "visible") return;
  try {
    const r = await fetch(location.pathname);
    const fresh = new DOMParser().parseFromString(await r.text(), "text/html").querySelector(".card");
    if (fresh) document.querySelector(".card").innerHTML = fresh.innerHTML;
  } catch (e) {}
}, 3000);
</script></body></html>"""

#: The mark beside a check, by its state.
MARKS = {"ok": "\u2713", "bad": "\u2717", "warn": "!"}


def _item(label, value, state):
    return ('  <div class="item %s"><span class="mark">%s</span><span class="label">%s</span>'
            '<span class="value">%s</span></div>'
            % (state, MARKS.get(state, ""), html.escape(str(label)), html.escape(str(value))))


def patch_state(value):
    """(what to say, state) for one patch's status from the preload."""
    value = str(value or "")
    if value.startswith("patched"):
        return "applied", "ok"
    if value.startswith("refused"):
        return "refused", "bad"
    return "not found", "bad"


STALE = """<!doctype html><meta charset="utf-8"><title>DeckyEmu</title>
<body style="background:#171d25;color:#dcdedf;font:20px sans-serif;padding:32px">
<p>This page is out of date. Launch DeckyEmu from your library again.</p></body>"""


class Rescue:
    def __init__(self, status, actions):
        """`status()` returns a dict to show; `actions[name]()` returns
        (ok, message) and may block."""
        self._status = status
        self._actions = actions
        self._token = secrets.token_urlsafe(18)
        self._server = None
        self.url = ""

    def start(self):
        rescue = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, code, body, kind="application/json"):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", kind + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _route(self):
                prefix = "/" + rescue._token
                if self.path == "/ping":
                    return "ping"
                if not self.path.startswith(prefix):
                    return None
                return self.path[len(prefix):].strip("/") or "page"

            def do_GET(self):
                route = self._route()
                if route == "ping":
                    self._send(200, '{"ok": true}')
                elif route == "page":
                    self._send(200, rescue._page(), "text/html")
                elif route == "status":
                    self._send(200, json.dumps(rescue._status(), default=str))
                elif route is None:
                    # An address from before a reinstall, or another port.
                    self._send(404, STALE, "text/html")
                else:
                    self._send(404, '{"ok": false}')

            def do_POST(self):
                route = self._route()
                action = rescue._actions.get(route or "")
                if not action:
                    self._send(404, '{"ok": false}')
                    return
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                try:
                    ok, message = action()
                except Exception as error:  # noqa: BLE001 - shown on the page
                    appenv.logger.exception("Rescue action %s failed", route)
                    ok, message = False, str(error)
                self._send(200, json.dumps({"ok": ok, "message": message}))

        for port in (PORT, 0):
            try:
                self._server = _Server(("127.0.0.1", port), Handler)
                break
            except OSError:
                continue
        if not self._server:
            appenv.logger.error("Could not start the rescue page")
            return
        run_dir = os.path.join(appenv.ROOT, "run")
        os.makedirs(run_dir, exist_ok=True)
        path = os.path.join(run_dir, "rescue-url")
        # The last start's secret, kept: the page reloads itself after a
        # restart or a rollback, and a new secret would leave it on a 404.
        try:
            with open(path, encoding="utf-8") as handle:
                kept = handle.read().strip().rsplit("/", 1)[-1]
            if re.fullmatch(r"[A-Za-z0-9_-]{24}", kept):
                self._token = kept
        except OSError:
            pass
        self.url = "http://127.0.0.1:%d/%s" % (self._server.server_address[1], self._token)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            handle.write(self.url)
        os.chmod(path + ".tmp", 0o600)
        os.replace(path + ".tmp", path)
        threading.Thread(target=self._server.serve_forever, name="rescue", daemon=True).start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def _page(self):
        status = self._status()
        checks = [_item(*check) for check in status.get("checks", [])]
        patches = [_item(name, *patch_state(value))
                   for name, value in (status.get("patches") or {}).items()]
        if status.get("standby"):
            # Started by the tile while the other build is in use: switching
            # back to this one is the only thing to offer.
            actions = ('  <button onclick="act(\'take_over\')">Use this version instead'
                       '<small>Steam restarts</small></button>')
            patches = ""
        else:
            actions = ('  <button onclick="act(\'restart\')">Restart</button>\n'
                       '  <button onclick="act(\'update\')">Update</button>')
            previous = status.get("previous")
            if previous:
                actions += ('\n  <button onclick="act(\'rollback\')">Go back<small>to %s</small></button>'
                            % html.escape(previous))
            patches = ('  <h2 class="sub">Patches</h2>\n'
                       + ("\n".join(patches) or _item("Not reported yet", "", "warn")))
        return PAGE % {
            "version": html.escape(str(status.get("version", ""))),
            "checks": "\n".join(checks),
            "patches": patches,
            "actions": actions,
            "log": html.escape(_log_tail()),
        }
