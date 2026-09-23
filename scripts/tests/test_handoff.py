#!/usr/bin/env python3
"""Every dialog that hands an address to another device draws it the same way.

    python scripts/tests/test_handoff.py

Four features cross to a phone or a PC -- a transfer, a diagnostic report, a
save backup and a cloud sign-in -- and for a while each drew the crossing
itself. They drifted into two dialects: the transfer's, at 19px for the address
and 28px for the code, and a smaller one the other three copied from each other,
with different words for the same two instructions ("or go to" against "or open
this on a computer"). Nothing was wrong with either, which is the problem:
somebody who has scanned one of these has scanned all of them, and a difference
they cannot account for makes them look twice.

So there is one component, and this checks that it stays the only one. A rule
about consistency that nothing enforces is how the four copies happened.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")


def _frontend(name):
    with open(os.path.join(_SRC, name), encoding="utf-8") as handle:
        return handle.read()


# The dialogs that make the crossing, and the file they all go through.
_CROSSERS = (
    "TransferModal.tsx",
    # The transfer dialog's second crossing: the compact line in the dialog, and
    # the square over the top of it once the list is what the dialog is about.
    "TransferCodeModal.tsx",
    "ReportModal.tsx",
    "SaveBackupModal.tsx",
    "CloudSetupModal.tsx",
)
_HANDOFF = "HandoffCode.tsx"

_sources = {name: _frontend(name) for name in _CROSSERS + (_HANDOFF,)}

section("one component draws the code, and only it")

# Read off the directory rather than from the list above: a fifth dialog that
# grows its own QR block is exactly the drift this file is about, and it would
# not be in a list written here.
_drawing = sorted(
    name for name in os.listdir(_SRC)
    if name.endswith((".tsx", ".ts")) and name not in ("QrCode.tsx", _HANDOFF)
    and "<QrCode" in _frontend(name)
)
check("no dialog draws a QR code for itself", _drawing, [])

check("the component does draw one", "<QrCode" in _sources[_HANDOFF], True)

for name in _CROSSERS:
    check("%s goes through it" % name,
          'from "./HandoffCode"' in _sources[name], True)

section("the two instructions are written once")

# The sizes are the argued-out ones from the transfer dialog: 190px of QR is
# scannable at arm's length, and the six digits are read off this screen by
# somebody typing them into a laptop.
check("the address is sized in the component",
      'fontSize: "19px"' in _sources[_HANDOFF], True)
check("and the code, spaced so the digits can be read apart",
      ('fontSize: "28px"' in _sources[_HANDOFF],
       'letterSpacing: "0.24em"' in _sources[_HANDOFF]), (True, True))

# The wording, not just the markup: two dialogs saying "scan the code" in
# different words is the same failure as two sizes.
check("it says how to reach the page",
      "Scan the code" in _sources[_HANDOFF], True)
for name in _CROSSERS:
    check("%s does not word it again" % name,
          ("Scan the code" in _sources[name],
           bool(re.search(r"letterSpacing", _sources[name]))),
          (False, False))

section("a spent code is reported wherever it can happen")

# Only the transfer used to say this, because only the transfer had drawn its
# own block. Every one of these serves behind the same six digits, so every one
# of them can be locked out by somebody guessing at them.
check("the component says so", "Too many wrong codes" in _sources[_HANDOFF], True)
check("and each dialog passes what it needs to know that",
      sorted(name for name in _CROSSERS if "pinLocked" in _sources[name]),
      sorted(_CROSSERS))

section("the muted style every one of them uses lives in one file")

_style = _frontend("dialogStyle.ts")
check("stated once", ('export const MUTED' in _style, 'export const COLUMN' in _style),
      (True, True))
check("and not restated in the dialogs",
      sorted(name for name in _CROSSERS
             if re.search(r"const (MUTED|LABEL|COLUMN)\s*[:=]", _sources[name])),
      [])

summary()
