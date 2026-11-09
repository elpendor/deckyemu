"""The controller on the rescue page.

Steam's browser keeps the pad to itself: a page sees no key and no gamepad.
Steam's UI does see every press, so while the rescue page is open this listens
there, over the debugging port, and hands each press to the page. It needs
nothing of the panel, so it works when the panel does not load.

Steam moves its own focus with the same presses, and up takes it onto the
browser's toolbar, where A then presses Back and leaves the page. So after each
press the page handles, Steam's focus goes back to the panel the page sits in.
"""

import threading
import time

import appenv
import cdp

BINDING = "__deckyemuRescuePad"

# Pressed buttons only, as Steam numbers them in controller input messages.
# KEEP holds Steam's focus on the page's panel: the large focusable it is on
# when the page opens.
REGISTER = """(() => {
  try { window.__deckyemuRescuePadHandle && window.__deckyemuRescuePadHandle.unregister(); } catch (e) {}
  window.__deckyemuRescuePadHandle = SteamClient.Input.RegisterForControllerInputMessages(
    (_controller, button, down) => { if (down) %s(String(button)); });
  window.__deckyemuRescuePadPin = undefined;
  const focused = () => {
    const tree = FocusNavController.GetActiveNavTree();
    return tree && tree.GetLastFocusedNode && tree.GetLastFocusedNode();
  };
  const panel = (node) => {
    const element = node && node.m_element;
    if (!element) return false;
    const rect = element.getBoundingClientRect(), view = element.ownerDocument.defaultView;
    return rect.width > view.innerWidth * 0.8 && rect.height > view.innerHeight * 0.5;
  };
  window.__deckyemuRescuePadKeep = () => {
    const now = focused();
    const kept = window.__deckyemuRescuePadPin;
    if (kept && !(kept.m_element && kept.m_element.isConnected)) window.__deckyemuRescuePadPin = undefined;
    if (!window.__deckyemuRescuePadPin && panel(now)) window.__deckyemuRescuePadPin = now;
    const pin = window.__deckyemuRescuePadPin;
    if (pin && now !== pin) pin.BTakeFocus();
  };
  window.__deckyemuRescuePadKeep();
  return true;
})()""" % BINDING

KEEP = "window.__deckyemuRescuePadKeep && window.__deckyemuRescuePadKeep()"

UNREGISTER = """(() => {
  try { window.__deckyemuRescuePadHandle && window.__deckyemuRescuePadHandle.unregister(); } catch (e) {}
  window.__deckyemuRescuePadHandle = undefined;
})()"""


class PadBridge:
    def __init__(self, page_url):
        """`page_url()` is the rescue page's address, "" until it is served."""
        self._page_url = page_url
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name="rescue-pad", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                url = self._page_url()
                listing = cdp.targets() if url else []
                shared = cdp.ui_page(listing)
                pages = [t for t in listing if t.get("type") == "page" and t.get("url", "").startswith(url)]
                if url and shared and pages:
                    self._bridge(shared, pages[0])
            except Exception:  # noqa: BLE001 - Steam not up yet, or a page that went away
                pass
            self._stop.wait(1.0)

    def _bridge(self, shared_target, page_target):
        shared = cdp.Page(shared_target["webSocketDebuggerUrl"])
        page = cdp.Page(page_target["webSocketDebuggerUrl"])
        try:
            shared.send("Runtime.addBinding", name=BINDING)
            shared.send("Runtime.enable")
            shared.evaluate(REGISTER)
            appenv.logger.info("The controller reaches the rescue page")
            while not (self._stop.is_set() or page.closed.is_set() or shared.closed.is_set()):
                event = shared.next_event(timeout=1.0)
                if not event:
                    continue
                method = event.get("method")
                params = event.get("params") or {}
                if method == "Runtime.executionContextsCleared":
                    return  # Steam's UI reloaded; register again
                if method == "Runtime.bindingCalled" and params.get("name") == BINDING:
                    button = int(params.get("payload") or -1)
                    handled = page.evaluate("!!(window.pad && pad(%d))" % button, timeout=3)
                    if handled:
                        shared.send("Runtime.evaluate", expression=KEEP)
        finally:
            try:
                if not shared.closed.is_set():
                    shared.evaluate(UNREGISTER, timeout=2)
            except Exception:  # noqa: BLE001
                pass
            shared.close()
            page.close()
            time.sleep(0.5)
