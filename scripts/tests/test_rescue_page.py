"""The rescue page's buttons reach their actions.

    python scripts/tests/test_rescue_page.py

The page is served at http://127.0.0.1:<port>/<secret>, with no trailing slash,
so a button posting to a relative "update" went to /update and 404ed: every
button on the page said "That did not work." This follows the URL the way a
browser builds it from the page's own script.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- points appenv at scratch

import rescue  # noqa: E402

_pressed = []
page = rescue.Rescue(
    lambda: {"Version": "test"},
    {"restart": lambda: (_pressed.append("restart") or True, "DeckyEmu is restarting.")},
)
rescue.PORT = 0
page.start()


def _post(url):
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as reply:
            return json.loads(reply.read())
    except urllib.error.HTTPError as error:
        return json.loads(error.read() or b"{}")


try:
    section("a button posts to the action it names")

    with urllib.request.urlopen(page.url, timeout=5) as reply:
        html = reply.read().decode("utf-8")
    script = re.search(r"fetch\((.*?), \{ method", html).group(1)
    check("the script builds the address from the page's own path",
          "location.pathname" in script, True)

    # What the browser does with that script on this page.
    path = urllib.parse.urlparse(page.url).path
    posted = urllib.parse.urljoin(page.url, path.rstrip("/") + "/restart")
    check("which keeps the secret segment", posted, page.url + "/restart")
    check("and reaches the action", (_post(posted), _pressed),
          ({"ok": True, "message": "DeckyEmu is restarting."}, ["restart"]))

    # The bug, for the record: a relative address from this page drops it.
    check("a relative address would not have",
          urllib.parse.urljoin(page.url, "restart").endswith("/restart")
          and page.url.rsplit("/", 1)[1] not in urllib.parse.urljoin(page.url, "restart"),
          True)
    section("and the page survives the restart it asks for")

    # The page reloads itself after a restart or a rollback. A new secret per
    # start left it on a bare 404.
    again = rescue.Rescue(lambda: {}, {})
    again.start()
    try:
        check("the next start keeps the secret",
              again.url.rsplit("/", 1)[1], page.url.rsplit("/", 1)[1])
    finally:
        again.stop()

    stale = page.url.rsplit("/", 1)[0] + "/" + "x" * 24
    try:
        urllib.request.urlopen(stale, timeout=5)
        said = ""
    except urllib.error.HTTPError as error:
        said = error.read().decode("utf-8")
    check("an address that is out of date says what to do",
          "Launch DeckyEmu from your library again" in said, True)
finally:
    page.stop()


if __name__ == "__main__":
    summary()
