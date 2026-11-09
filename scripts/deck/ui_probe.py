"""Drive and inspect Steam's Game Mode UI on the Deck, over Steam's debugging
port (CDP), using the installed service's own CDP client.

Run on the Deck, or from a computer through scripts/deck-ui.sh:

    qam                       open Quick Access on DeckyEmu's tab
    nav PATH                  navigate the main window, e.g. /deckyemu/manage
    close                     close Quick Access and other side menus
    shot NAME                 screenshot through gamescope (game layer only
                              while a game runs) to ~/ui-shots/NAME.png
    capture TARGET NAME       screenshot one Steam window through CDP; works
                              over a running game
    press BUTTON...           press controller buttons: up down left right a
                              b x y l1 r1 menu, each after a human-speed pause
    focus                     what has controller focus, and where
    walk N                    press down N times, printing focus each time
    eval TARGET JS            evaluate JavaScript in a target
    html TARGET SELECTOR      outerHTML of the first match
    styles TARGET SELECTOR    computed styles of the matches

TARGET is part of a CDP page title: "Shared" (SharedJSContext, where the
panel's code runs), "Big Picture" (the main window) or "QuickAccess".
Presses go through Steam's FocusNavController, the path the pad itself takes.
"""

import base64
import glob
import json
import os
import subprocess
import sys
import time

_found = sorted(glob.glob(os.path.expanduser("~/.local/share/deckyemu/app/*/py_modules")))
if not _found:
    raise SystemExit("the DeckyEmu service is not installed; its CDP client is needed")
sys.path.insert(0, _found[-1])
import cdp  # noqa: E402

MAIN = "SteamUIStore.WindowStore.GamepadUIMainWindowInstance"
SHOTS = os.path.expanduser("~/ui-shots")
BUTTONS = {"a": 1, "b": 2, "x": 3, "y": 4, "l1": 5, "r1": 6, "up": 9, "down": 10,
           "left": 11, "right": 12, "menu": 14}
PAUSE = 0.35

PROPS = ["display", "flex-direction", "align-items", "justify-content", "gap", "padding",
         "margin", "width", "height", "font-size", "font-weight", "line-height", "color",
         "background-color", "border", "border-radius", "overflow", "scroll-margin-bottom"]

# Where focus is, from Steam's navigation tree rather than the DOM's focus,
# which can disagree with it.
FOCUS_JS = """(() => {
  const node = window.FocusNavController.GetActiveNavTree()?.GetLastFocusedNode?.();
  const e = node?.Element;
  if (!e) return 'nothing focused';
  const r = e.getBoundingClientRect();
  const bar = e.ownerDocument.defaultView.innerHeight - 40;
  const text = (e.textContent || '').trim().slice(0, 30) || e.className.split(' ')[0];
  return text.padEnd(32) + Math.round(r.y) + '..' + Math.round(r.bottom)
    + (r.bottom > bar ? '  UNDER THE BUTTON BAR' : '');
})()"""


def page(title):
    for target in cdp.targets():
        if title.lower() in (target.get("title") or "").lower() and target.get("webSocketDebuggerUrl"):
            return cdp.Page(target["webSocketDebuggerUrl"])
    raise SystemExit("no page titled like %r: %s" % (title, [t.get("title") for t in cdp.targets()]))


def run(title, js):
    return page(title).evaluate(js, await_promise=True, timeout=20)


def press(name):
    button = BUTTONS[name]
    run("Shared", "(() => { const f = window.FocusNavController; f.OnButtonDown(%d, 1);"
                  " f.OnButtonUp(%d, 1); return 1; })()" % (button, button))


def capture(title, name):
    reply = page(title).call("Page.captureScreenshot", timeout=15, format="png")
    data = reply.get("data") or (reply.get("result") or {}).get("data")
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, name + ".png")
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(data))
    return path


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "qam":
        print(run("Shared", "%s.MenuStore.OpenQuickAccessMenu(4242), 'ok'" % MAIN))
    elif cmd == "nav":
        print(run("Shared", "%s.Navigate(%s), 'ok'" % (MAIN, json.dumps(args[0]))))
    elif cmd == "close":
        print(run("Shared", "SteamUIStore.CloseSideMenus(), 'ok'"))
    elif cmd == "shot":
        os.makedirs(SHOTS, exist_ok=True)
        env = dict(os.environ, XDG_RUNTIME_DIR="/run/user/%d" % os.getuid(),
                   GAMESCOPE_WAYLAND_DISPLAY="gamescope-0")
        path = os.path.join(SHOTS, args[0] + ".png")
        subprocess.run(["gamescopectl", "screenshot", path], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        time.sleep(0.5)
        print(path)
    elif cmd == "capture":
        print(capture(args[0], args[1]))
    elif cmd == "press":
        for name in args:
            press(name)
            time.sleep(PAUSE)
        print(run("Shared", FOCUS_JS))
    elif cmd == "focus":
        print(run("Shared", FOCUS_JS))
    elif cmd == "walk":
        for _ in range(int(args[0])):
            press("down")
            time.sleep(PAUSE)
            print(run("Shared", FOCUS_JS))
    elif cmd == "eval":
        print(run(args[0], args[1]))
    elif cmd == "html":
        print(run(args[0], "(() => { const e = document.querySelector(%s);"
                           " return e ? e.outerHTML.slice(0, 8000) : 'none'; })()" % json.dumps(args[1])))
    elif cmd == "styles":
        js = """(() => [...document.querySelectorAll(%s)].slice(0, 6).map(e => {
          const s = getComputedStyle(e), out = {class: String(e.className)};
          for (const p of %s) out[p] = s.getPropertyValue(p);
          return out; }))()""" % (json.dumps(args[1]), json.dumps(PROPS))
        print(json.dumps(run(args[0], js), indent=1))
    else:
        raise SystemExit("unknown command %r\n%s" % (cmd, __doc__))


if __name__ == "__main__":
    main(sys.argv[1:])
