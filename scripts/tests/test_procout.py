#!/usr/bin/env python3
"""Reading a subprocess's output: whole lines, and the last one too.

    python scripts/tests/test_procout.py

The three things that stream a process to the UI -- the RetroArch install, an
emulator install, an emulator run as a command-line tool -- each had their own
copy of this loop, and the copies had drifted. Two of the three dropped the
final line when it arrived without a trailing newline, which is the worst line
to lose: what a failing process says last is the reason it failed, so those two
reported "no output" exactly when there was something to report.

So the cases here are the ones that told the copies apart, and the awkward
reads are the point: a process does not write in lines, it writes in bytes that
happen to arrive in whatever size the pipe gives up.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import procout  # noqa: E402


class FakeStream:
    """A pipe that hands back exactly the chunks it was given, then EOF.

    Fixed chunks rather than a real process, because the behaviour under test
    is what happens at the seams: a line split across two reads, and a last
    line with nothing after it.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, _size):
        return self._chunks.pop(0) if self._chunks else b""


def _collect(chunks):
    """(lines yielded, reason) for a stream that produced `chunks`."""
    output = procout.Output()

    async def run():
        return [text async for text in output.segments(FakeStream(chunks))]

    lines = asyncio.new_event_loop().run_until_complete(run())
    return lines, output.reason


section("whole lines, however the bytes arrive")

check("plain newline-separated output",
      _collect([b"one\ntwo\nthree\n"])[0], ["one", "two", "three"])

# The bug the buffering exists for: a percentage split across two reads.
check("a line split across two reads is one line",
      _collect([b"Downloading 45", b"% of 90MB\n"])[0], ["Downloading 45% of 90MB"])

# flatpak redraws its progress line in place rather than writing new ones.
check("carriage returns end a line the same way newlines do",
      _collect([b"10%\r20%\r30%\n"])[0], ["10%", "20%", "30%"])

check("a run of breaks is not a run of blank lines",
      _collect([b"one\r\n\r\ntwo\n"])[0], ["one", "two"])

check("whitespace-only output yields nothing",
      _collect([b"   \n\t\n"])[0], [])

section("the last line counts, even unterminated")

# The divergence itself. Two of the three copies ended the loop at EOF and
# dropped whatever was still held back.
check("output with no trailing newline still yields its last line",
      _collect([b"error: nothing to install\n", b"flatpak failed"])[0],
      ["error: nothing to install", "flatpak failed"])

check("and a single unterminated line is not lost",
      _collect([b"the only thing it said"])[0], ["the only thing it said"])

section("the reason a failure gives")

# The point of keeping a tail at all: the exit code says a number, and the
# process has already said why.
check("the reason is the last lines, not the first",
      _collect([bytes("line %d\n" % n, "utf-8") for n in range(1, 9)])[1],
      "line 4 line 5 line 6 line 7 line 8")

check("an unterminated last line reaches the reason",
      _collect([b"working\n", b"error: disk full"])[1],
      "working error: disk full")

check("a process that said nothing says so",
      _collect([])[1], "no output")

check("and one that said only whitespace does too",
      _collect([b"\n\n"])[1], "no output")

check("the tail is bounded rather than the whole log",
      len(_collect([bytes("line %d\n" % n, "utf-8") for n in range(200)])[1].split()),
      procout.TAIL_LINES * 2)

section("decoding is never fatal")

# An emulator writing a filename in some other encoding must not take the
# install down with it.
#
# Compared against the expected text rather than printed as itself: the suite
# runs on Windows too, where the console is cp1252 and `check` printing the
# replacement character raises UnicodeEncodeError out of the reporting rather
# than out of the code under test -- a failure in the one place that must not
# have one.
_decoded = _collect([b"caf\xff\n"])[0]
check("undecodable bytes are replaced, not raised",
      _decoded == ["caf�"], True)
check("and the line survives at its own length",
      [len(line) for line in _decoded], [4])


section("against a real pipe, not only a stand-in")

# FakeStream hands back whatever chunks it was given, which is the only way to
# test the seams -- but it also means every check above would still pass if
# `segments` did not work against an actual asyncio subprocess pipe at all.
# This one costs a process and covers that: `sys.executable` is here on both
# platforms the suite runs on, so it needs no guard.
_SCRIPT = (
    "import sys;"
    "sys.stdout.write('first\\n');"
    "sys.stdout.write('second\\r');"
    "sys.stdout.write('last, unterminated');"
    "sys.stdout.flush()"
)


async def _from_real_process():
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", _SCRIPT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output = procout.Output()
    lines = [text async for text in output.segments(process.stdout)]
    return lines, output.reason, await process.wait()


_real_lines, _real_reason, _real_code = asyncio.new_event_loop().run_until_complete(
    _from_real_process()
)
check("a real process's lines arrive whole",
      _real_lines, ["first", "second", "last, unterminated"])
check("including the one it never terminated",
      _real_reason, "first second last, unterminated")
check("and the exit code is still there to be read", _real_code, 0)


if __name__ == "__main__":
    summary()
