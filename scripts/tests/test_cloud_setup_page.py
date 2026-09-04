#!/usr/bin/env python3
"""The storage setup form, served by the same server as everything else.

    python scripts/tests/test_cloud_setup_page.py

Against a real socket, because the things worth checking here are all about what
the *server* will and will not do, and none of them are visible from the page
function alone.

The one that matters most: a session started to collect settings must not also
be a writable ROM inbox. That rule already exists for the diagnostic report --
handing somebody a QR code should hand over exactly the errand they were told
about -- and the setup form is the third thing that has to obey it.
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import fileserver  # noqa: E402

BACKENDS = {
    "webdav": {"label": "Nextcloud or WebDAV", "fields": ("url", "user", "pass"),
               "secret": ("pass",), "fixed": {"vendor": "nextcloud"}},
    "sftp": {"label": "SFTP or SSH", "fields": ("host", "user", "pass"),
             "secret": ("pass",), "fixed": {}},
}

LOGINS = {"dropbox": {"label": "Dropbox"}, "box": {"label": "Box"}}

posted = []
logins = []


def handler(kind, values):
    posted.append((kind, dict(values)))
    if values.get("url") == "broken":
        return False, "that host did not answer"
    return True, ""


def login_handler(step, kind, pasted):
    logins.append((step, kind, pasted))
    if step == "start":
        return True, "", "https://provider.example/auth?state=abc"
    if step == "explode":
        raise RuntimeError("rclone fell over")
    if "code=" not in pasted:
        return False, "no code in that", ""
    return True, "", ""


TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cloudtmp")
os.makedirs(TARGET, exist_ok=True)

started = fileserver.start(TARGET, uploads=False)
BASE = started["url"].rstrip("/")
TOKEN = BASE.rsplit("/", 1)[-1]


def _ask(request):
    """One request, retried past a loopback that drops it.

    Windows aborts an occasional connection to 127.0.0.1 with WinError 10053 --
    seen in the transfer server's own suite, on a tree with nothing changed in
    it, and it is the socket rather than anything being tested. A retry keeps
    that from reading as a failure of whatever check happened to be next; a
    real refusal comes back as an HTTPError and is answered, not retried.
    """
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except OSError:
            if attempt == 3:
                raise
    raise AssertionError("unreachable")


def get(path):
    return _ask(BASE + path)


def post(path, payload, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    return _ask(urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={"Content-Type": "application/json"}))


try:
    section("before it is offered, nothing answers")

    status, _ = post("/cloud", {"kind": "webdav", "values": {}})
    check("posting settings to a server not collecting them is refused",
          status, 404)

    section("offered: the form is the page")

    fileserver.offer_cloud_setup(BACKENDS, handler)
    status, page = get("/")
    check("the page is served", status, 200)
    check("it offers each storage kind",
          all(('value="%s"' % kind) in page for kind in BACKENDS), True)
    check("and names them in words rather than by their rclone type",
          "Nextcloud or WebDAV" in page, True)
    check("a secret field is a password field",
          'name="pass" type="password"' in page, True)
    check("and one that is not, is not",
          'name="user" type="text"' in page, True)

    section("a filled-in form reaches the handler")

    posted.clear()
    status, body = post("/cloud", {
        "kind": "webdav",
        "values": {"url": "https://nas.example/dav", "user": "p", "pass": "s"}})
    check("answered", status, 200)
    check("the handler got it", posted,
          [("webdav",
            {"url": "https://nas.example/dav", "user": "p", "pass": "s"})])
    check("and the page is told it worked", json.loads(body)["ok"], True)

    # Nothing on the wire names the storage. rclone needs a key for its config
    # file, the Deck picks it, and asking somebody on a phone to invent a word
    # first is the question this page no longer asks.
    check("nothing was asked to be named",
          ("name" in json.loads(body), 'id="name"' in page), (False, False))

    section("a failure is reported as itself, not as a crash")

    status, body = post("/cloud", {"kind": "webdav", "values": {"url": "broken"}})
    check("still a 200, because the page has to read the reason", status, 200)
    check("which carries the handler's own words",
          json.loads(body), {"ok": False, "error": "that host did not answer",
                             "url": ""})

    section("a sign-in provider is two steps with a person in between")

    fileserver.offer_cloud_setup(BACKENDS, handler, LOGINS, login_handler)
    _, page = get("/")
    check("it is offered as something to sign in to, not a form",
          'value="dropbox" data-login="1"' in page, True)
    check("and the fields for the others are still there",
          'name="pass" type="password"' in page, True)

    logins.clear()
    status, body = post("/cloud", {"step": "start", "kind": "dropbox",
                                   "pasted": ""})
    check("starting hands back a link to open", json.loads(body)["url"],
          "https://provider.example/auth?state=abc")
    check("and nothing was written yet", logins, [("start", "dropbox", "")])

    status, body = post("/cloud", {
        "step": "finish", "kind": "dropbox",
        "pasted": "http://localhost:53682/?code=REALCODE&state=abc"})
    check("finishing carries what the browser landed on", logins[-1],
          ("finish", "dropbox",
           "http://localhost:53682/?code=REALCODE&state=abc"))
    check("and says it worked", json.loads(body)["ok"], True)

    status, body = post("/cloud", {"step": "finish",
                                   "kind": "dropbox", "pasted": "nonsense"})
    check("a paste with no code in it is a sentence, not a crash",
          json.loads(body), {"ok": False, "error": "no code in that", "url": ""})

    section("a handler that throws does not leave the page waiting")

    status, body = post("/cloud", {"step": "explode", "kind": "dropbox",
                                   "pasted": ""})
    check("still answered", status, 200)
    check("with something the page can show",
          json.loads(body)["error"], "The Deck could not finish that.")

    fileserver.offer_cloud_setup(BACKENDS, handler)

    section("what the endpoint refuses")

    posted.clear()
    check("a body that is not JSON", post("/cloud", None, raw=b"not json")[0], 400)
    check("a JSON body that is not an object",
          post("/cloud", None, raw=b'["a"]')[0], 400)
    check("an empty body", post("/cloud", None, raw=b"")[0], 400)
    check("nothing reached the handler through any of those", posted, [])

    request = urllib.request.Request(
        started["url"].rstrip("/").rsplit("/", 1)[0] + "/notthetoken/cloud",
        data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            code = response.status
    except urllib.error.HTTPError as error:
        code = error.code
    check("and a wrong token", code, 404)

    section("collecting settings does not open an inbox")

    put = urllib.request.Request(BASE + "/upload/sneaky.sfc", data=b"x",
                                 method="PUT")
    try:
        with urllib.request.urlopen(put, timeout=10) as response:
            code = response.status
    except urllib.error.HTTPError as error:
        code = error.code
    check("a PUT is still refused while the form is being served", code, 404)

    section("withdrawn: it stops answering")

    fileserver.offer_cloud_setup(None, None)
    check("the form is gone",
          post("/cloud", {"kind": "webdav", "values": {}})[0], 404)

    section("stopping forgets the handler, not just the form")

    fileserver.offer_cloud_setup(BACKENDS, handler)
    fileserver.stop()
    check("no backends left", fileserver._cloud_setup, {})
    check("and nothing still listening for a password",
          fileserver._on_cloud_setup, None)
finally:
    fileserver.stop()
    try:
        os.rmdir(TARGET)
    except OSError:
        pass

summary()
