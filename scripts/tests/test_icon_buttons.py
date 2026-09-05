#!/usr/bin/env python3
"""A square icon button never holds words.

    python scripts/tests/test_icon_buttons.py

`ICON_BUTTON` states `width: 48px` because it exists to hold one glyph, and
`ICON_BUTTON_WIDE` is the same button with the width left to the words. Put a
label in the square one and the text wraps inside 48px and spills out of
whatever row it is in: "Use this build" reached the Deck as three stacked words
running off the edge of the RetroArch dialog, and the firmware rows had the
same thing waiting in "Delete file" and "Install".

Reading the frontend rather than listing the offenders, because the mistake is
easy to make again -- the two names differ by a suffix, and the wrong one still
compiles, still renders, and only looks wrong on the device.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")

_OPEN = "<DialogButton"
_CLOSE = "</DialogButton>"


def _elements(body):
    """Each `<DialogButton>` as (opening tag, children).

    The opening tag ends at the first `>` outside braces: a style prop is full
    of them (`() =>` alone accounts for most), and splitting on the first `>`
    cuts the element in half.
    """
    for piece in body.split(_OPEN)[1:]:
        depth = 0
        for index, letter in enumerate(piece):
            if letter == "{":
                depth += 1
            elif letter == "}":
                depth -= 1
            elif letter == ">" and depth == 0:
                yield piece[:index], piece[index + 1:].partition(_CLOSE)[0]
                break


def _words(children):
    """What is left once the markup is taken out: the visible label, if any."""
    text = re.sub(r"\{/\*.*?\*/\}", " ", children, flags=re.S)   # JSX comments
    text = re.sub(r"\{[^{}]*\}", " ", text)                       # expressions
    text = re.sub(r"<[^>]*>", " ", text)                          # nested tags
    return " ".join(text.split())


section("a label goes in the button shaped for labels")

_labelled = []
for _name in sorted(os.listdir(_SRC)):
    if not _name.endswith(".tsx"):
        continue
    with open(os.path.join(_SRC, _name), encoding="utf-8") as handle:
        _body = handle.read()
    for _tag, _children in _elements(_body):
        if "ICON_BUTTON" not in _tag or "ICON_BUTTON_WIDE" in _tag:
            continue
        _label = _words(_children)
        if re.search(r"[A-Za-z]", _label):
            _labelled.append("%s: %r" % (_name, _label[:40]))

check("the parser finds the buttons it is meant to police",
      sum(1 for _n in sorted(os.listdir(_SRC)) if _n.endswith(".tsx")
          for _t, _c in _elements(open(os.path.join(_SRC, _n), encoding="utf-8").read())
          if "ICON_BUTTON" in _t and "ICON_BUTTON_WIDE" not in _t) > 10, True)
check("and none of them holds a word", _labelled, [])


if __name__ == "__main__":
    summary()
