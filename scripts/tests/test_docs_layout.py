#!/usr/bin/env python3
"""The layout in docs/development.md must not name a path that is not there.

    python scripts/tests/test_docs_layout.py

That block described `src/steam.ts` and `src/backend.ts` for several releases
after both had become directories, and listed sixteen of the forty backend
modules. The two failures are not equally bad. An omission is a gap -- somebody
looks the module up and finds it. A path that no longer exists sends them
looking for a file nobody will ever find, and it is the only public document
that says where anything lives, so there is nothing to correct it against.

So this checks the direction that misleads: everything the layout names must
exist. It deliberately does not require every file to be listed -- `src/` is
one module per panel and enumerating them was what rotted in the first place.
The doc says as much, and groups the frontend by role instead.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

section("docs/development.md -- the layout points at things that exist")

_doc = os.path.join(REPO_ROOT, "docs", "development.md")
with open(_doc, "r", encoding="utf-8") as handle:
    _text = handle.read()

# The fenced block under "## Layout", and only that one: the file has other code
# fences and they hold shell commands, not paths.
_block = re.search(r"^## Layout\b.*?^```\n(.*?)^```", _text, re.S | re.M)
check("the layout block is still findable", _block is not None, True)

# A path is the first token on a line, indented or not. Descriptions follow two
# or more spaces, so a single token ending in / or a known extension is the name.
_paths = []
for _line in (_block.group(1).splitlines() if _block else []):
    _token = _line.strip().split("  ")[0].strip()
    if not _token or _token.startswith("#"):
        continue
    # `*Panel.tsx` and `<name>.ts` are patterns describing a family, not files.
    if "*" in _token or "<" in _token:
        continue
    if not (_token.endswith("/") or re.search(r"\.(py|ts|tsx|sh|json)$", _token)):
        continue
    _paths.append(_token)

check("and it names a useful number of them", len(_paths) > 40, True)

# Indented entries are relative to the directory heading above them, so the
# lookup tries each plausible root rather than parsing the indentation.
_roots = ("", "py_modules", "src", "scripts", "src/steam", "src/backend")


def _exists(path):
    return any(
        os.path.exists(os.path.join(REPO_ROOT, root, path.rstrip("/")))
        for root in _roots
    )


_missing = sorted({path for path in _paths if not _exists(path)})
check("every path in the layout exists", _missing, [])

# The specific regression, named so a future edit that reintroduces it fails on
# the reason rather than on a generic list. Scoped to the block: the prose around
# it names both old paths on purpose, to say what went wrong and why it mattered.
_listing = _block.group(1) if _block else ""
check("steam.ts is not listed as a file", "steam.ts" not in _listing, True)
check("nor is backend.ts", "backend.ts" not in _listing, True)


section("docs/development.md -- and the log prefix it tells you to grep for")

# The other half of the same drift: the doc told anyone debugging to filter the
# backend log on `[retroarch]`, from before the project was renamed, long after
# nothing wrote it. A stale instruction is not in the layout block, so nothing
# above would have caught it -- this ties the claim to the code instead.


def _sources():
    """Every line of source the log prefixes could be written from."""
    text = []
    for folder in ("src", "py_modules"):
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, folder)):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith((".ts", ".tsx", ".py")):
                    continue
                with open(os.path.join(root, name), "r", encoding="utf-8",
                          errors="replace") as handle:
                    text.append(handle.read())
    return "\n".join(text)


_code = _sources()
check("nothing writes the old prefix any more", "[retroarch]" in _code, False)
check("so the doc does not send anyone grepping for it", "[retroarch]" in _text, False)
# The claim the doc makes instead, checked in the direction that can go stale:
# if these ever stop being written, the doc is wrong again and this says so.
check("the frontend prefix the doc names is real", "[deckyemu]" in _code, True)


if __name__ == "__main__":
    from harness import summary

    summary()
