#!/usr/bin/env python3
"""Background work must always tell the panel it finished.

    python scripts/tests/test_detach.py

An install runs detached: it takes minutes, streams progress, and the panel's
only way to learn it is over is the done event. So a detached task that raises
without emitting one is not a logged error, it is a progress bar that never
moves again and a button that stays disabled -- the shape of every "it just
hung" report, and indistinguishable from the backend having died.

The handlers inside those coroutines only ever covered the expected failures
(flatpak missing, a non-zero exit). Everything else -- a KeyError on an entry
field, a permission error writing a config, anything from the registration step
that runs *after* a successful download -- escaped into decky's own log where
nothing was watching for it.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402  -- the stub, which has no emit of its own
import main  # noqa: E402

section("detached work always reports a result")

# Every case below throws on purpose, and each one is logged with a traceback --
# which is the behaviour being checked, and also eleven passing lines buried
# under stack traces that read like a broken run. Quietened for this file only,
# and restored at the end so nothing after it loses its logging.
_log_level = decky.logger.level
decky.logger.setLevel(logging.CRITICAL)

emitted = []


async def _record(event, *args):
    emitted.append((event, args))


decky.emit = _record

plugin = main.Plugin()
plugin.loop = asyncio.new_event_loop()


def run(coro):
    return plugin.loop.run_until_complete(coro)


def detached(coro, *args):
    """Start it and wait for it, so nothing here depends on a sleep."""
    async def go():
        await plugin._detach(coro, *args)
    run(go())


# --- the failure this exists for -------------------------------------------

async def _raises_unexpectedly():
    # Exactly the real shape: an entry missing a field the installer assumed,
    # which no `except OSError` was ever going to catch.
    entry = {"id": "azahar"}
    return entry["source"]["id"]


emitted.clear()
detached(_raises_unexpectedly(), "emulator_install_done", "azahar")
check("an unexpected failure still ends the wait", len(emitted), 1)
check("it reports on the event the panel listens to", emitted[0][0], "emulator_install_done")
check("with the id, so the right row stops spinning", emitted[0][1][0], "azahar")
check("and ok=False, so the panel shows a failure", emitted[0][1][1], False)
# Named rather than blank: `str(KeyError('source'))` is `"'source'"`, which on
# its own reads like a quoted word and says nothing about what went wrong.
check("the message names the exception type", "KeyError" in emitted[0][1][2], True)


# --- the shape with no id --------------------------------------------------

async def _boom():
    raise RuntimeError("flatpak went missing mid-install")


emitted.clear()
detached(_boom(), "retroarch_install_done")
check("the two-argument event shape is emitted as (ok, message)",
      emitted[0], ("retroarch_install_done", (False, "RuntimeError: flatpak went missing mid-install")))


# --- success is left alone -------------------------------------------------

async def _succeeds():
    await _record("emulator_install_done", "cemu", True, "")


emitted.clear()
detached(_succeeds(), "emulator_install_done", "cemu")
check("a coroutine that finishes reports once, not twice", len(emitted), 1)
check("and its own result is what the panel sees", emitted[0][1][1], True)


# --- cancellation is not a failure ----------------------------------------

async def _forever():
    await asyncio.sleep(3600)


async def _cancel_mid_flight():
    task = plugin._detach(_forever(), "emulator_install_done", "rpcs3")
    # Let it reach the sleep before cancelling, or there is nothing to cancel.
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return "re-raised"
    return "swallowed"


emitted.clear()
# Unload cancels these. Swallowing the cancellation would keep the task alive
# while the loop is closing, and emitting a failure over a socket that is going
# away is both useless and a second exception on the way out.
check("a cancellation goes back up rather than becoming a failure",
      run(_cancel_mid_flight()), "re-raised")
check("and nothing is emitted for it", emitted, [])


# --- the report itself failing --------------------------------------------

async def _refuses(*_args):
    raise ConnectionResetError("the websocket is gone")


async def _also_boom():
    raise ValueError("something went wrong")


decky.emit = _refuses
try:
    detached(_also_boom(), "emulator_install_done", "vita3k")
    survived = True
except Exception:
    # If this propagates, the loop gets an exception during shutdown instead of
    # a logged line, which is the thing being guarded against.
    survived = False
finally:
    decky.emit = _record

# The socket is the only way to report anything, so its failure ends the matter.
# What must not happen is a second exception escaping on top of the first.
check("a failure that cannot even be reported does not escape", survived, True)

plugin.loop.close()
decky.logger.setLevel(_log_level)


if __name__ == "__main__":
    from harness import summary

    summary()
