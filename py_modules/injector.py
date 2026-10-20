"""Keeping DeckyEmu inside Steam's UI for as long as the service runs.

One thread. It polls Steam's page list hard while it holds no UI page -- a new
one is listed only tens of milliseconds before it starts loading -- and as soon
as one appears it connects to that page alone and, in one burst:

  - registers the preload for every document the page will load, which also
    covers Steam reloading its own UI;
  - evaluates the preload in the document already loading, whose 16 MB main
    bundle is still ahead of it, so even attaching late usually wins;
  - gives the page `__deckyemuHost`, the binding the panel calls the service
    through.

Then it waits for Steam to render our Quick Access placeholder, which is when
Steam's React is on hand, and evaluates the panel's bundle. A reload of Steam's
UI starts a new document; the preload runs in it by itself and the bundle is
evaluated again once our tab renders.

Two things are never done, because each left Steam stuck on its boot screen:
a browser-level debugger session, and reloading Steam's UI. A boot that is
missed is reported, not forced.
"""

import json
import os
import threading
import time

import appenv
import cdp

POLL_SECONDS = 0.015
RENDER_WAIT_SECONDS = 120

BINDING = "__deckyemuHost"


def _js(value):
    return json.dumps(value, default=str)


class Injector:
    def __init__(self, app_dir, dispatch):
        """`dispatch(method, args, done)` runs a call and invokes
        `done(ok, value)` when it finishes, from any thread."""
        self._app_dir = app_dir
        self._dispatch = dispatch
        self._page = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.state = {
            "steam": "not running",
            "page": None,
            "patches": {},
            "rendered": False,
            "bundle": "not loaded",
            "attached_at": None,
            "late": None,
        }
        self.on_bundle_started = None

    # --- the outside world
    # -----------------------------------------------------

    def start(self):
        threading.Thread(target=self._run, name="injector", daemon=True).start()

    def stop(self):
        self._stop.set()
        with self._lock:
            page = self._page
        if page:
            page.close()

    def emit(self, event, args):
        """Deliver a backend event to the panel, if a page is attached."""
        with self._lock:
            page = self._page
        if page is None or page.closed.is_set():
            return
        try:
            page.send("Runtime.evaluate", expression="window.__deckyemu&&window.__deckyemu.event&&"
                      "window.__deckyemu.event(%s,%s)" % (_js(event), _js(list(args))))
        except OSError:
            pass

    def _read(self, name):
        with open(os.path.join(self._app_dir, "dist", name), encoding="utf-8") as handle:
            return handle.read()

    # --- the loop
    # -----------------------------------------------------------------

    def _run(self):
        seen = None
        while not self._stop.is_set():
            try:
                target = cdp.ui_page(cdp.targets())
            except (OSError, ValueError):
                target = None
                self.state["steam"] = "not running"
            if target and target.get("id") != seen:
                seen = target["id"]
                try:
                    self._tend(target)
                except Exception:  # noqa: BLE001 - the loop must outlive any one page
                    appenv.logger.exception("Lost Steam's UI page")
                finally:
                    with self._lock:
                        self._page = None
                    self.state["page"] = None
                    self.state["bundle"] = "not loaded"
            self._stop.wait(POLL_SECONDS)

    def _tend(self, target):
        preload = self._read("preload.js")
        page = cdp.Page(target["webSocketDebuggerUrl"])
        # Registration first: the navigation it has to beat is imminent.
        registered = page.send("Page.addScriptToEvaluateOnNewDocument", source=preload)
        now = page.send("Runtime.evaluate", expression=preload)
        # Without the Page domain enabled the registration is accepted and never
        # runs: measured on a Deck, a boot attached before navigation and no
        # preload in the document that followed.
        page.send("Page.enable")
        bound = page.send("Runtime.addBinding", name=BINDING)
        page.send("Runtime.enable")
        for label, slot in (("register the preload", registered), ("run the preload", now),
                            ("add the binding", bound)):
            reply = page.wait(slot)
            if "error" in reply:
                # A navigation interrupting the first run is ordinary; the loop
                # below runs it again.
                quiet = "navigated" in str(reply["error"].get("message", ""))
                (appenv.logger.info if quiet else appenv.logger.error)(
                    "Steam did not %s: %s", label, reply["error"])
        self._ensure_preload(page, preload)
        with self._lock:
            self._page = page
        self.state.update({
            "steam": "running",
            "page": target["id"],
            "attached_at": time.time(),
            "late": bool(target.get("url")),
        })
        appenv.logger.info("Attached to Steam's UI (%s)", target.get("url") or "not navigated yet")
        # Calls in flight to a previous service will never be answered.
        page.send("Runtime.evaluate", expression="window.__deckyemu&&window.__deckyemu.reconnected&&"
                  "window.__deckyemu.reconnected()")

        loading = threading.Event()
        self._load_bundle_soon(page, loading)
        while True:
            event = page.next_event(timeout=1.0)
            if event is None:
                if page.closed.is_set():
                    break
                continue
            method = event.get("method")
            if method == "deckyemu.closed":
                break
            params = event.get("params") or {}
            if method == "Runtime.bindingCalled" and params.get("name") == BINDING:
                self._call(page, params.get("payload") or "")
            elif method == "Runtime.executionContextsCleared":
                # Steam reloaded its UI. The preload runs in the new document by
                # itself; the bundle has to be evaluated there again.
                self.state["bundle"] = "not loaded"
                self.state["rendered"] = False
                self._load_bundle_soon(page, loading)
        appenv.logger.info("Steam's UI page went away")

    def _ensure_preload(self, page, preload, seconds=5.0):
        """Run the preload again until it is in a Steam UI document.

        The registration only covers documents created after Steam processes
        it, and the first evaluate runs in whatever document is there when it
        arrives. A navigation committing between the two leaves neither in the
        new document -- seen on the Deck, two boots in four. The preload is
        idempotent and Steam's main bundle takes hundreds of milliseconds to
        load after the commit, so running it again straight away still wins.
        """
        probe = preload + ';location.host==="steamloopback.host"&&!!window.__deckyemu'
        deadline = time.time() + seconds
        while time.time() < deadline and not page.closed.is_set():
            try:
                if page.evaluate(probe, timeout=5):
                    return True
            except (RuntimeError, TimeoutError, cdp.Closed):
                pass
            time.sleep(0.025)
        appenv.logger.error("The preload is not in Steam's UI document after %.0fs", seconds)
        return False

    def _load_bundle_soon(self, page, loading):
        if loading.is_set():
            return
        loading.set()

        def load():
            try:
                self._load_bundle(page)
            finally:
                loading.clear()

        threading.Thread(target=load, name="bundle", daemon=True).start()

    def _load_bundle(self, page):
        deadline = time.time() + RENDER_WAIT_SECONDS
        status = None
        while time.time() < deadline and not page.closed.is_set():
            try:
                raw = page.evaluate("JSON.stringify((window.__deckyemu||{}).status||null)")
                status = json.loads(raw) if raw else None
            except (RuntimeError, TimeoutError, cdp.Closed, ValueError):
                status = None
            if status:
                self.state["patches"] = status.get("patches", {})
                if status.get("rendered"):
                    break
            time.sleep(0.5)
        if not status or not status.get("rendered"):
            self.state["bundle"] = "waiting for Steam to show our tab"
            appenv.logger.error("Our Quick Access tab never rendered: %s", json.dumps(status))
            return
        self.state["rendered"] = True
        try:
            bundle = self._read("deckyemu.js")
            page.evaluate("window.__deckyemu.service=%s;true" % _js({"version": appenv.VERSION}))
            page.evaluate(bundle, timeout=60)
            failed = page.evaluate("(window.__deckyemu.status||{}).failed||''")
        except Exception as error:  # noqa: BLE001 - reported where it is seen
            self.state["bundle"] = "failed: %s" % error
            appenv.logger.exception("The panel bundle did not load")
            return
        if failed:
            self.state["bundle"] = "failed: %s" % failed
            appenv.logger.error("The panel could not start: %s", failed)
            return
        self.state["bundle"] = "loaded"
        appenv.logger.info("Panel loaded in Steam (patches: %s)", json.dumps(self.state["patches"]))
        if self.on_bundle_started:
            try:
                self.on_bundle_started()
            except Exception:  # noqa: BLE001
                appenv.logger.exception("on_bundle_started failed")

    def _call(self, page, payload):
        try:
            request = json.loads(payload)
            ident = int(request["id"])
            method = str(request["method"])
            args = list(request.get("args") or [])
        except (ValueError, KeyError, TypeError):
            appenv.logger.error("Unreadable call from the panel: %.200s", payload)
            return

        def done(ok, value):
            if page.closed.is_set():
                return
            try:
                page.send("Runtime.evaluate", expression="window.__deckyemu&&window.__deckyemu.reply&&"
                          "window.__deckyemu.reply(%d,%s,%s)" % (ident, _js(bool(ok)), _js(value)))
            except OSError:
                pass

        self._dispatch(method, args, done)
