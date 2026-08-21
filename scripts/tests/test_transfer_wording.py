#!/usr/bin/env python3
"""The upload page and the panel call the same things by the same names.

    python scripts/tests/test_transfer_wording.py

A transfer is the one feature with a user interface on two devices at once:
the panel on the Deck and a web page on whatever is sending. Someone watching
one and holding the other has to be able to tell that a file listed there is the
file listed here, and different words for the same state is exactly what stops
that -- the page said "Already received" for what the panel calls "Received",
and labelled the in-flight list not at all.

The words are read out of the frontend rather than written down here. A list
kept by hand beside the thing it describes is the thing that drifts, which is
what this file exists to prevent.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import fileserver  # noqa: E402
import fileserver_page  # noqa: E402  -- the markup half; fileserver renders through it

_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")


def _frontend(name):
    with open(os.path.join(_SRC, name), encoding="utf-8") as handle:
        return handle.read()


_modal = _frontend("TransferModal.tsx")
_status = _frontend("TransferStatusPanel.tsx")
_page = fileserver._page()
_code_page = fileserver._code_page()
_locked_page = None

section("both screens name the two lists the same way")

# The panel's own words, taken from its source so a rename there fails here
# rather than quietly leaving the two halves disagreeing.
check("the panel calls files in flight 'Arriving'",
      bool(re.search(r">\s*Arriving\s*<|\"Arriving\"", _modal + _status)), True)
check("and the page uses that word for the same list",
      "<h2 id=\"arrivingHeading\"" in _page and ">Arriving</h2>" in _page, True)

check("the panel calls what landed 'Received'",
      bool(re.search(r">\s*Received\b", _modal)), True)
check("and the page says Received, not 'Already received'",
      (">Received</h2>" in _page, "Already received" in _page), (True, False))

section("the page is named after the button that opened it")

# The panel already learned this once: TransferModal's heading was changed to
# match the button that opens it because "arriving here read as having gone
# somewhere else". The page on the sending device is the third surface of the
# same feature, and was the one still using different words.
_button = "Transfer to Deck"
check("the panel's button and heading say it", _modal.count(_button) >= 1, True)
check("the upload page's title and heading say it",
      (_page.count("<title>%s</title>" % _button),
       _page.count("<h1>%s</h1>" % _button)), (1, 1))
check("and so does the code form, which is where a bookmark lands",
      (_code_page.count("<title>%s</title>" % _button),
       _code_page.count("<h1>%s</h1>" % _button)), (1, 1))
check("neither page still says 'Send files to your Deck'",
      "Send files to your Deck" in _page + _code_page, False)

section("a file moves between the lists as it does on the Deck")

# Not a rendering test -- there is no DOM here. What is asserted is that the
# page's script moves a finished upload into the received list rather than
# leaving it under a heading that then means nothing.
check("a completed upload is moved into the received list",
      "already.insertBefore(job.row, already.firstChild)" in _page, True)
check("newest first, matching the order the server lists what it already had",
      "firstChild" in _page, True)
# Two things change a list -- a file joining the queue and a file leaving it --
# and both have to re-flow. Since an upload can now be several attempts, the
# endings converge in `settle`, which is where the second one has to be.
_settle = _page.partition("function settle(job) {")[2].partition("\n}")[0]
check("and the headings follow whatever the lists actually hold",
      (_page.count("reflowHeadings()") >= 3, "reflowHeadings()" in _settle), (True, True))
# A failure did not arrive, so it must not be filed as though it had. Asserted
# by where the move sits rather than by what comes before what: the page's one
# move into Received is in `finish`, and only a 200 reaches it. Every other
# ending -- a retry, a give-up -- goes the other way.
_finish = _page.partition("function finish(job) {")[2].partition("\n}")[0]
check("the only move is the one that ran on a 200",
      (_page.count("already.insertBefore"), "already.insertBefore" in _finish),
      (1, True))
check("and nothing else calls it",
      "if (request.status === 200) finish(job);" in _page, True)

section("instructions name the controls the reader will actually see")

# The sender is on another device and cannot see the panel, so an instruction
# that describes an action has to use the label on the button.
check("the panel's buttons are Start receiving and Stop receiving",
      ("Start receiving" in _modal, "Stop receiving" in _modal), (True, True))

fileserver._pin_locked = True
try:
    _locked_page = fileserver._code_page()
finally:
    fileserver._pin_locked = False

check("the lockout message names both of them",
      ("Stop receiving" in _locked_page, "Start receiving" in _locked_page),
      (True, True))
check("and no longer names a control that does not exist",
      "restart the transfer" in _locked_page, False)
check("the code form still calls the six digits a code, as the panel does",
      "Enter the code shown on your Deck." in _code_page, True)


section("the page's own script is at least syntactically a program")

# Nothing else looks at this. It is JavaScript living in a Python string, so it
# is outside tsc, outside the frontend bundle and outside every lint the project
# runs -- a stray bracket here is found by loading the page on a phone, which is
# the most expensive place this project has to find anything.
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

_node = shutil.which("node")
if _node:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as _handle:
        # The page's script runs after its elements exist; parsing needs no DOM.
        _handle.write(fileserver_page._SCRIPT)
        _script_path = _handle.name
    try:
        _parsed = subprocess.run([_node, "--check", _script_path],
                                 capture_output=True, text=True)
        check("the upload page's script parses",
              (_parsed.returncode, _parsed.stderr.strip()[:120]), (0, ""))
    finally:
        os.unlink(_script_path)
else:
    print("SKIP node is not on PATH, so the page script was not parsed")


if __name__ == "__main__":
    summary()
