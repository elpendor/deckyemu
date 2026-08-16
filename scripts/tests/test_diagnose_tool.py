#!/usr/bin/env python3
"""The developer's own way to read a report off a Deck still runs.

    python scripts/tests/test_diagnose_tool.py

`scripts/diagnose.py` carries the other half of itself as a string, to be run by
the Deck's own Python over SSH. Nothing on this side executes it, so a typo in
there would sit undiscovered until somebody reached for the tool to debug
something else -- at the moment they are least able to afford a second problem.

Four separate escapes were corrupted by a shell during the session that wrote
all of this, each producing code that compiled and did nothing. Parsing costs
nothing and is the whole of what can be checked without a Deck.
"""

import ast
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

TOOL = pathlib.Path(__file__).resolve().parent.parent / "diagnose.py"
SOURCE = TOOL.read_text(encoding="utf-8")


section("the tool itself")

ast.parse(SOURCE)
check("parses", True, True)
check("and says how to run it in its own docstring",
      "python scripts/diagnose.py" in SOURCE, True)


section("and the half of it that runs on the Deck")

_remote = re.search(r"REMOTE = r'''(.*?)'''", SOURCE, re.S)
check("is where it is expected to be", _remote is not None, True)

_filled = _remote.group(1).replace("__LOG_LINES__", "200").replace("__RAW__", "False")
ast.parse(_filled)
check("parses once its placeholders are filled", True, True)
# Both substitutions have to land, or the Deck is handed a placeholder to run.
check("with none of them left over",
      "__LOG_LINES__" in _filled or "__RAW__" in _filled, False)
# Every escape in there is one a shell could have eaten on the way in.
check("and carries no stray control characters",
      [hex(ord(c)) for c in _filled if ord(c) < 9 or 13 < ord(c) < 32], [])


section("and it reads the plugin rather than copying it")

# The report has to be the one the plugin would build. A second implementation
# here would drift, and the first thing it would drift on is the redaction.
check("it imports the installed module",
      "import diagnostics" in _filled and "diagnostics.build(" in _filled, True)
check("and the plugin's own registry rather than a guess",
      "store.get_library()" in _filled, True)
# The stub is what lets the plugin's modules import at all outside decky.
check("with decky stubbed the way the harness stubs it",
      'sys.modules["decky"] = decky' in _filled, True)


section("--raw is the flag that must be hard to use by accident")

check("it is off unless asked for", '"--raw", action="store_true"' in SOURCE, True)
check("and says what it costs when it is used",
      "Do not paste it anywhere" in SOURCE, True)


if __name__ == "__main__":
    summary()
