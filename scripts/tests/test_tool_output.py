#!/usr/bin/env python3
"""An emulator's output goes in the log without burying what the plugin said.

    python scripts/tests/test_tool_output.py

`_run_emulator_tool` logs every line an emulator prints, and some of it is one
line per file. Installing a 1.5GB package on a real device wrote 183 `Decrypted:`
lines into the last 200 -- a log that had recorded the weather rather than the
news, and a diagnostic report whose log section held twelve useful lines, all of
them pushed out of the top.

So a run of near-identical lines is counted rather than repeated. What is lost
is the middle of a list of filenames; what is kept is that the list happened and
how long it was.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402
import plugin_firmware  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


_capture = _Capture()
decky.logger.addHandler(_capture)
_level = decky.logger.level
decky.logger.setLevel(logging.INFO)


def _feed(lines):
    """Put `lines` through the real collapser and return what reached the log.

    The collapser is its own class precisely so this can drive it. A test that
    reimplemented the reader loop around it would be testing the copy.
    """
    _capture.lines.clear()
    collapsed = plugin_firmware.CollapsedLog("vita3k")
    for line in lines:
        collapsed.write(line)
    collapsed.finish()
    return list(_capture.lines)


section("a run of near-identical lines is counted, not repeated")

_logged = _feed(
    "[23:32:%02d.%03d] |I| [install_pkg]: sce_sys/manual/17/%03d.png" % (i % 60, i, i)
    for i in range(400)
)

check("the first few go in", len([line for line in _logged if "install_pkg" in line]),
      plugin_firmware.REPEATS_SHOWN)
check("and the rest are one line",
      any("and 397 more like the above" in line for line in _logged), True)
# Four lines for four hundred. The ratio is not the point -- the point is that a
# package with ten thousand files in it also costs four.
check("so the whole run is four lines", len(_logged), 4)


section("but nothing else is lost")

_logged = _feed([
    "[23:32:43.100] |I| [install_pkg]: sce_sys/a.png",
    "[23:32:43.101] |I| [install_pkg]: sce_sys/b.png",
    "[23:32:43.102] |I| [install_pkg]: sce_sys/c.png",
    "[23:32:43.103] |I| [install_pkg]: sce_sys/d.png",
    "[23:32:43.104] |I| [install_pkg]: sce_sys/e.png",
    "[23:32:44.000] |I| [copy_license]: Success copy license file",
    "[23:32:45.000] |E| Fatal: could not mount ux0",
])

# The two lines somebody actually needs, which the run above was burying.
check("a line of another kind still appears",
      any("copy_license" in line for line in _logged), True)
check("and so does the error after it",
      any("Fatal: could not mount" in line for line in _logged), True)
check("the run before them is summarised",
      any("and 2 more like the above" in line for line in _logged), True)
# The summary has to come out before the line that ended the run, or the log
# reads as though the run continued past it.
_summary_at = next(i for i, line in enumerate(_logged) if "more like the above" in line)
_next_at = next(i for i, line in enumerate(_logged) if "copy_license" in line)
check("in that order", _summary_at < _next_at, True)


section("a short run is left exactly as it was")

_logged = _feed([
    "[23:32:43.100] |I| [install_pkg]: a.png",
    "[23:32:43.101] |I| [install_pkg]: b.png",
])
check("two lines stay two lines", len(_logged), 2)
check("with nothing summarised",
      any("more like the above" in line for line in _logged), False)


section("and a run still going when the process ends is still counted")

# The last thing an installer prints is usually the middle of its longest run,
# so a summary only written when the *next* kind of line arrives would never be
# written at all.
_capture.lines.clear()
_collapsed = plugin_firmware.CollapsedLog("vita3k")
for _index in range(50):
    _collapsed.write("[23:32:43.%03d] |I| [install_pkg]: %03d.png" % (_index, _index))
check("nothing is summarised until it ends",
      any("more like" in line for line in _capture.lines), False)
_collapsed.finish()
check("and then it is", any("and 47 more like the above" in line
                            for line in _capture.lines), True)

decky.logger.setLevel(_level)
decky.logger.removeHandler(_capture)


if __name__ == "__main__":
    summary()
