#!/usr/bin/env python3
"""A method that fails says so in the log, without being asked to.

    python scripts/tests/test_method_logging.py

Decky hands an exception back to whoever called the method and writes it
nowhere. So the frontend shows its own wording for "that did not work" and the
plugin log -- the one place anybody looks afterwards, and the only thing a bug
report can carry -- has nothing in it.

Twice now that has been expensive. A module-shadowing bug took six rounds
because its exception never reached the log, and a method handed to the executor
while still a coroutine surfaced as "The report could not be prepared" beside a
log full of "Task was destroyed but it is pending" -- which names neither the
method nor the line.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import main as plugin_main  # noqa: E402


class _Capture(logging.Handler):
    """Keeps every record, with whatever traceback came with it."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def text(self):
        return "\n".join(
            record.getMessage() + (self.format(record) if record.exc_info else "")
            for record in self.records
        )


_capture = _Capture()
decky.logger.addHandler(_capture)
# Set rather than assumed. The suite shares one logger and other files quiet it
# while they provoke failures on purpose; this one is *about* what reaches the
# log, so it cannot inherit whichever level ran last.
_log_level = decky.logger.level
decky.logger.setLevel(logging.ERROR)
_loop = asyncio.new_event_loop()


def run(coro):
    return _loop.run_until_complete(coro)


# A stand-in for the real thing, assembled the same way: what is under test is
# the decorator, and starting a whole Plugin would drag in RetroArch detection
# and a core scan to answer a question about a try block.
@plugin_main._log_failures
class Subject:
    async def works(self):
        return "fine"

    async def fails(self):
        raise ValueError("the thing that actually went wrong")

    async def cancelled(self):
        raise asyncio.CancelledError()

    async def _private(self):
        raise ValueError("not logged here")


_subject = Subject()


section("a method that succeeds is untouched")

check("its answer comes back", run(_subject.works()), "fine")
check("and nothing is logged", _capture.records, [])
# Decky finds the methods it can call by name on the plugin object, so a wrapper
# that renamed them would take the whole API with it.
check("the method keeps its name", Subject.works.__name__, "works")


section("a method that fails writes down why, and still fails")

try:
    run(_subject.fails())
    _raised = None
except ValueError as error:
    _raised = error

# Logged, not swallowed: the frontend still has to hear about it, or a failure
# becomes a call that never returns.
check("the exception still reaches the caller", str(_raised),
      "the thing that actually went wrong")
check("the log names the method", "fails() failed" in _capture.text(), True)
check("and carries what went wrong", "the thing that actually went wrong" in
      _capture.text(), True)
# The line, which is the part that turns a report into a fix. Without it the log
# says only that something failed, which is what the panel already said.
check("with a traceback", any(record.exc_info for record in _capture.records), True)


section("but an unload is not a failure")

_capture.records.clear()
try:
    run(_subject.cancelled())
except asyncio.CancelledError:
    pass
# CancelledError is a BaseException, so `except Exception` misses it by
# construction -- decky cancels in-flight work when it unloads the plugin, and
# logging that as a fault would fill the log with noise at every shutdown.
check("a cancelled call logs nothing", _capture.records, [])


section("and private helpers are left alone")

_capture.records.clear()
try:
    run(_subject._private())
except ValueError:
    pass
# They fail inside a public method that is already covered, so wrapping them
# would log the same failure twice with two different names.
check("a private method is not wrapped", _capture.records, [])


section("the real plugin is covered")

# The decorator is applied to the class, not written at each of the hundred-odd
# methods, because a rule that has to be remembered at every call site will be
# missing from the one that needs it.
check("a method defined on Plugin is wrapped",
      plugin_main.Plugin.plugin_version.__wrapped__ is not None, True)
# Mixin methods too, and wrapped where they are defined rather than on Plugin --
# setting them here would give Plugin an attribute for every method its mixins
# own, which is the shadowing test_plugin_mixins exists to catch.
check("so is one a mixin defines",
      plugin_main.Plugin.audit_library.__wrapped__ is not None, True)
check("without Plugin claiming to define it",
      "audit_library" in vars(plugin_main.Plugin), False)

decky.logger.setLevel(_log_level)
decky.logger.removeHandler(_capture)
_loop.close()


if __name__ == "__main__":
    summary()
