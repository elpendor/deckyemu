"""Reading what a subprocess says while it is still saying it.

Three things here run something and stream its output to the UI: the RetroArch
flatpak install, the emulator flatpak install, and an emulator run headlessly as
a command-line tool. All three want the same two things out of a pipe -- whole
lines as they arrive, and the last few of them kept back in case the process
fails and the exit code turns out to explain nothing.

Both are less obvious than they look, which is why they are here rather than
written out three times.

**Whole lines.** flatpak redraws its progress line with carriage returns rather
than newlines, so output has to be split on both. And a read of a fixed number
of bytes lands wherever it lands: a percentage split across two reads yields a
nonsense number, so the tail of each read is held back until the rest of its
line arrives.

**Including the last one.** The held-back remainder is only a partial line while
more is coming; once the pipe closes it is a whole line that nothing else will
terminate. Dropping it silently is what two of the three copies did, and it is
the worst line to lose: the reason a run failed is the last thing it says, so
the failure was reported as "no output" precisely when there was something to
report. The one copy that got this right was the RetroArch installer, and it
being right there and wrong twice elsewhere is the argument for one copy.
"""

import collections
import re

#: How many lines of output to keep for explaining a failure. Enough for a
#: reason plus the line before it that gives the reason context; few enough that
#: a process which fails after printing a thousand files does not paste them
#: into a dialog.
TAIL_LINES = 5

#: flatpak and the emulators disagree about which of these ends a line, and
#: flatpak uses both -- carriage returns to redraw progress in place, newlines
#: between messages.
_BREAK = re.compile(r"[\r\n]+")

#: Small enough that a progress bar moves smoothly rather than in jumps.
_CHUNK = 256


class Output:
    """The lines a process writes, and the last few of them.

    One object rather than a bare generator plus a list the caller maintains,
    because the tail is not optional -- every caller here needs it, and each one
    that kept its own wrote the same two lines to bound it.
    """

    def __init__(self, keep=TAIL_LINES):
        # A bounded deque rather than a list trimmed after each append: the
        # bound is the point, and stating it once beats `del tail[:-5]` at every
        # site that kept its own.
        self._tail = collections.deque(maxlen=keep)

    async def segments(self, stream):
        """Yield each whole line `stream` produces, stripped, skipping blank ones.

        Ends when the pipe closes. The caller still has to wait on the process
        itself: output stopping and the process exiting are not the same event,
        and the exit code only exists after the second.
        """
        buffer = ""
        while True:
            chunk = await stream.read(_CHUNK)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            pieces = _BREAK.split(buffer)
            # The last piece may be half a line; hold it back for the next read.
            buffer = pieces.pop()
            for piece in pieces:
                text = piece.strip()
                if text:
                    self._tail.append(text)
                    yield text

        # Whatever was being held back is a whole line now -- see the module
        # docstring for what losing it cost.
        text = buffer.strip()
        if text:
            self._tail.append(text)
            yield text

    @property
    def reason(self):
        """The last lines, for a failure message. Never empty -- says so instead.

        A process that failed silently and one that was never read look the same
        to whoever reads the dialog, so the difference is spelled out rather
        than left as an empty string trailing a colon.
        """
        return " ".join(self._tail).strip() or "no output"
