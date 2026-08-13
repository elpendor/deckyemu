#!/usr/bin/env python3
"""Nothing in a generated launcher can be made to run by naming a file.

    python scripts/tests/test_launcher_comments.py

The `exec` line quotes every argument, so the arguments were never the way in.
The header comments were: they are built with `%`, and a value carrying a
newline closes the comment and leaves the rest of the line as the next command
in a script Steam runs. A title is whatever was typed and a ROM filename may
contain a newline on Linux, so neither is ours to trust.

Checked by tokenising the script the way a shell reads it rather than by
looking at lines. A line-based check cannot tell a second command apart from
the middle of a correctly quoted argument -- `shlex.quote` of a path with a
newline in it is a single-quoted string spanning two lines, which is safe and
looks exactly like the bug.
"""

import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import launchers  # noqa: E402

section("a launcher's header comments cannot become commands")

_rom = "/roms/rom\nrm -rf ~\n.sfc"
_core = "/cores/snes9x_libretro.so"
_path = launchers.write_launcher(
    {"kind": "native", "exe": "/usr/bin/retroarch"},
    "Game\ntouch /tmp/pwned\n",
    _core,
    _rom,
    hide_osd="keep",
)
_body = open(_path, encoding="utf-8").read()

# comments=True is the whole point: it strips `#` to end of line exactly as sh
# does, so anything a value pushed past a newline survives as a word here.
_words = shlex.split(_body, comments=True)

check("nothing the title carried survives as a word",
      [w for w in _words if w in ("touch", "/tmp/pwned")], [])
check("and nothing the ROM path carried does either",
      [w for w in _words if w in ("rm", "-rf", "~")], [])
check("the script still runs exactly one command", _words.count("exec"), 1)
check("which is the emulator", _words[_words.index("exec") + 1], "/usr/bin/retroarch")
check("with the whole ROM path as one argument, newlines and all",
      _words[-1], _rom)
check("and the core it was asked for", _words[-2:], [_core, _rom][-2:])

# Flattened rather than dropped: the header is what someone reads to find out
# which ROM a launcher points at, so the value still has to be shown.
_lines = _body.splitlines()
check("the title is still readable in the header",
      any(line.startswith("# Game: Game touch /tmp/pwned") for line in _lines), True)
check("and so is the ROM path",
      any("rom rm -rf ~ .sfc" in line for line in _lines if line.startswith("# ROM:")),
      True)

section("the same for the launcher that opens an emulator's own window")

_gui = launchers.write_gui_launcher(
    {"id": "example", "kind": "appimage", "target": "/emus/example.AppImage"},
    "Example\necho no\n",
)
_gui_words = shlex.split(open(_gui, encoding="utf-8").read(), comments=True)
check("an emulator's name cannot add a command either",
      [w for w in _gui_words if w in ("echo", "no")], [])
check("and that launcher runs one command too", _gui_words.count("exec"), 1)


if __name__ == "__main__":
    summary()
