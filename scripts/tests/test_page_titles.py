#!/usr/bin/env python3
"""Every page the transfer server serves is titled DeckyEmu.

    python scripts/tests/test_page_titles.py

One address serves all of them -- the code form, the upload page, a save
backup, the cloud storages, the diagnostic report -- and the browser names a
bookmark after `<title>`. A per-page title therefore produces a bookmark called
"Transfer to Deck" that a month later opens the cloud page, so the title says
what the address is rather than what happened to be open when it was saved.

The `<h1>` still names the feature: it is read with the page in front of you,
where the useful thing is what this page does, not which plugin serves it.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import fileserver  # noqa: E402

_MODULES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "py_modules")

_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_NAME = "DeckyEmu"


def _renders_pages(path):
    """Files that build a page, found by the doctype rather than by a list.

    A list here would be a list of the pages that existed when this was
    written; a module added later would serve whatever title it liked and
    nothing would say so.
    """
    with open(path, encoding="utf-8") as handle:
        body = handle.read()
    return body if "<!doctype html>" in body.lower() else ""


section("the address has one name, whatever it is showing")

_found = {}
for _entry in sorted(os.listdir(_MODULES)):
    if not _entry.endswith(".py"):
        continue
    _body = _renders_pages(os.path.join(_MODULES, _entry))
    if _body:
        _titles = _TITLE.findall(_body)
        if _titles:
            _found[_entry] = _titles

check("more than one module builds a page, so the rule has something to bind",
      len(_found) >= 2, True)
check("and they hold every page the server can send",
      sum(len(t) for t in _found.values()) >= 5, True)
check("each of those pages is titled DeckyEmu",
      sorted({t for titles in _found.values() for t in titles}), [_NAME])

# Rendered, not just written: a title inside a template the renderer never
# reaches would pass the sweep above and still ship the wrong name.
check("the code form renders it", _TITLE.findall(fileserver._code_page()), [_NAME])
check("so does the upload page", _TITLE.findall(fileserver._page()), [_NAME])

section("and the heading still says which page you are on")

check("the upload page names the feature in its heading",
      "<h1>Transfer to Deck</h1>" in fileserver._page(), True)


if __name__ == "__main__":
    summary()
