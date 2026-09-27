#!/usr/bin/env python3
"""Write the README into docs/index.md as the site's home page.

    python scripts/readme_as_index.py

The site needs a page at `/` and the README is already the project's front
page, so it is generated rather than written twice. `docs/index.md` is ignored
by git and rebuilt on every run.

Only the links move. The README's paths are relative to the repository root,
which is right when GitHub renders it and wrong one directory down: `docs/x.md`
becomes `x.md`, and anything outside `docs/` becomes a URL, since the site
carries no copy of it.
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOB = "https://github.com/elpendor/deckyemu/blob/main/"

#: Files the README links that the site does not carry. Anything else outside
#: `docs/` is a failure rather than a guess -- see `_rewrite`.
OUTSIDE = ("CONTRIBUTING.md", "LICENSE")

HEADER = (
    "<!-- Generated from README.md by scripts/readme_as_index.py. "
    "Edit the README, not this file. -->\n\n"
)


def _rewrite(text):
    """(markdown, problems) with every relative link made right for docs/."""
    problems = []

    for name in OUTSIDE:
        text = text.replace("](%s)" % name, "](%s%s)" % (BLOB, name))

    # `docs/` is where this file is going, so the prefix comes off.
    text = re.sub(r"\]\(docs/", "](", text)

    for link in re.findall(r"\]\((?!https?:|#)([^)]+)\)", text):
        target = link.split("#", 1)[0]
        if target and not os.path.exists(os.path.join(REPO, "docs", target)):
            problems.append("index.md would link %r, which is not in docs/" % link)

    return text, problems


def main():
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as handle:
        text = handle.read()

    text, problems = _rewrite(text)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1

    out = os.path.join(REPO, "docs", "index.md")
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(HEADER + text)
    print("wrote docs/index.md from README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
