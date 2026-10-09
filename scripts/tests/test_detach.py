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

import decky  # noqa: E402  -- the stub; its recording emit is replaced below
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

section("the same work is never started twice")

# The panel keeps "running" in component state, and Steam throws that away each
# time the Quick Access panel closes. So the button came back mid-install and a
# second press started a second `flatpak install` of the same app: two
# identical processes under one plugin, 78 seconds apart, on one repo lock,
# behind a bar that cannot tell either of them from a hang.
started = []
_gate = {}


async def _slow(tag):
    started.append(tag)
    await _gate["open"].wait()


async def _twice():
    _gate["open"] = asyncio.Event()
    emitted.clear()
    started.clear()

    first = plugin._detach(_slow("first"), "emulator_install_done", "cemu", once=True)
    await asyncio.sleep(0)
    again = _slow("again")
    second = plugin._detach(again, "emulator_install_done", "cemu", once=True)
    await asyncio.sleep(0)
    # A different emulator is different work, and must not be refused for it.
    other = plugin._detach(_slow("other"), "emulator_install_done", "azahar", once=True)
    await asyncio.sleep(0)
    listed = await plugin.running_work()

    _gate["open"].set()
    await asyncio.gather(first, other)
    return first, second, other, again, listed


_first, _second, _other, _again, _listed = run(_twice())

check("a second start returns the one already running", _second is _first, True)
check("and runs nothing", sorted(started), ["first", "other"])
# Closed, not dropped: a coroutine nobody awaits warns on collection, and the
# warning names nothing.
check("the refused coroutine is closed rather than left to warn",
      _again.cr_frame is None, True)
check("different arguments are different work", _other is not _first, True)
check("a panel asking what is running is told, with the event it will hear",
      sorted((w["event"], tuple(w["args"])) for w in _listed),
      [("emulator_install_done", ("azahar",)), ("emulator_install_done", ("cemu",))])
check("and nothing is listed once it is over", run(plugin.running_work()), [])


async def _again_after():
    _gate["open"] = asyncio.Event()
    _gate["open"].set()
    started.clear()
    await plugin._detach(_slow("later"), "emulator_install_done", "cemu", once=True)


run(_again_after())
check("finished work can be started again", started, ["later"])


async def _fails_then_again():
    started.clear()
    await plugin._detach(_boom(), "retroarch_install_done", once=True)
    _gate["open"] = asyncio.Event()
    _gate["open"].set()
    await plugin._detach(_slow("after-failure"), "retroarch_install_done", once=True)


run(_fails_then_again())
# The failure path is where a stuck entry would hide: if only a clean finish
# removed the key, one crash would refuse every install after it until reload.
check("work that failed does not block the next attempt", started, ["after-failure"])


# --- and only where asked --------------------------------------------------

# Opt-in, because it turns a second request into a no-op. Cloud saves pass a
# list among their arguments and have their own way of refusing a second copy;
# an unhashable argument must not break them, and they must not be made to
# swallow a request they used to answer.
async def _unrelated():
    _gate["open"] = asyncio.Event()
    started.clear()
    a = plugin._detach(_slow("a"), "cloud_sync_done", False, "", [])
    await asyncio.sleep(0)
    b = plugin._detach(_slow("b"), "cloud_sync_done", False, "", [])
    await asyncio.sleep(0)
    listed = await plugin.running_work()
    _gate["open"].set()
    await asyncio.gather(a, b)
    return a, b, listed


_a, _b, _unlisted = run(_unrelated())
check("without once, the same call starts both, as it always did", _b is not _a, True)
# Reaching this line is the check that a list among the arguments (as the cloud
# sites pass) did not raise: `once` is what would have hashed it.
check("and both ran", sorted(started), ["a", "b"])
check("and it is not listed as work a panel should resume", _unlisted, [])

plugin.loop.close()
decky.logger.setLevel(_log_level)


if __name__ == "__main__":
    from harness import summary

    summary()
