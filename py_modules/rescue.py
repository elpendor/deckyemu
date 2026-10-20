"""The rescue page: DeckyEmu's status and its repairs, in Steam's browser.

The library tile opens it (rescue.sh), so it works when nothing of DeckyEmu
inside Steam does -- the patch refused on a new Steam build, the panel failing
to start, or an update that went wrong. What it offers is what fixes those:
update, roll back, restart, and the log to say which is needed.

Loopback only, under a path that is new every start: a web page open in
Steam's browser can reach 127.0.0.1 too, and must not be able to press these
buttons. The path is written to `run/rescue-url`, readable by this user only,
and nowhere else.
"""

import html
import http.server
import json
import os
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
 h1 { margin:0 0 16px; } .row { margin:6px 0; } .dim { opacity:.7 }
 button { font-size:20px; padding:14px 22px; margin:8px 12px 8px 0; border:0; border-radius:4px;
          background:#3d4450; color:#fff; } button:focus, button:hover { background:#1a9fff; }
 pre { background:#0e1218; padding:12px; white-space:pre-wrap; font-size:13px; max-height:40vh; overflow:auto; }
 #result { margin:12px 0; font-weight:bold; }
</style></head><body>
<h1>DeckyEmu</h1>
%(rows)s
<div>
 <button onclick="act('update')">Update to the latest release</button>
 %(rollback)s
 <button onclick="act('restart')">Restart DeckyEmu</button>
 <button onclick="location.reload()">Refresh</button>
</div>
<div id="result"></div>
<div class="dim">The newest log:</div>
<pre>%(log)s</pre>
<script>
async function act(what) {
  const out = document.getElementById("result");
  out.textContent = "Working...";
  try {
    const r = await fetch(what, { method: "POST" });
    const j = await r.json();
    out.textContent = j.message || (j.ok ? "Done." : "That did not work.");
    if (j.ok && what !== "update") setTimeout(() => location.reload(), 4000);
  } catch (e) { out.textContent = "DeckyEmu is restarting. Refresh in a few seconds."; }
}
</script></body></html>"""


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
        self.url = "http://127.0.0.1:%d/%s" % (self._server.server_address[1], self._token)
        run_dir = os.path.join(appenv.ROOT, "run")
        os.makedirs(run_dir, exist_ok=True)
        path = os.path.join(run_dir, "rescue-url")
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
        rows = []
        for label, value in status.get("rows", []):
            rows.append('<div class="row"><span class="dim">%s:</span> %s</div>'
                        % (html.escape(str(label)), html.escape(str(value))))
        previous = status.get("previous")
        rollback = ('<button onclick="act(\'rollback\')">Go back to %s</button>' % html.escape(previous)
                    if previous else "")
        return PAGE % {"rows": "\n".join(rows), "rollback": rollback, "log": html.escape(_log_tail())}
