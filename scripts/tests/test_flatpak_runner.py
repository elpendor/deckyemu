#!/usr/bin/env python3
"""Every flatpak removal goes through one runner, and it carries the environment.

    python scripts/tests/test_flatpak_runner.py

This block has been written wrongly twice, both times by being written again.
The dev-reset tab grew its own copy and left out `env=`, so Steam's runtime
libraries were still on the path and flatpak died on `libcrypto.so.3: version
OPENSSL_3.4.0 not found` before it did anything -- and that copy logged nothing,
so the failure arrived as a toast with no trace to read afterwards. Then the
emulator uninstall and the RetroArch uninstall carried two more copies,
identical line for line, one of them under a docstring saying it should be
shared.

So the thing worth checking is not that a removal works. It is that there is one
place where it happens, that the place strips Steam's environment, and that a
failure comes back as what flatpak said rather than as an exit code -- because
each of those is a property the next copy would silently drop.
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402
import emu_install  # noqa: E402
import installer  # noqa: E402
import main  # noqa: E402

# One loop for the run: `self._run` hands work to this loop's executor, so a
# fresh loop per call would leave the plugin holding a closed one.
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def _run(coro):
    return LOOP.run_until_complete(coro)


def _plugin_on_loop(cls=main.Plugin):
    plugin = cls()
    plugin.loop = LOOP
    plugin._install = None
    return plugin


section("removing a flatpak -- one runner, and it is the one that is used")

# Both endpoints build their own argv, because only each of them knows the id.
# Neither may run it: a second `create_subprocess_exec` is how the environment
# got lost last time.
seen = []


class _Shared(main.Plugin):
    async def _run_flatpak(self, argv):
        seen.append(list(argv))
        return {"ok": True}

    async def can_uninstall_retroarch(self):
        return {"ok": True, "kind": "flatpak", "scope": "user"}

    async def refresh_retroarch(self):
        self._install = None
        return {}


_shared = _plugin_on_loop(_Shared)

# A real argv, so what reaches the runner is the command that would really run.
# Both sides build their own, from their own module's binary lookup.
_real_binary = installer.flatpak_binary
_real_emu_binary = emu_install.flatpak_binary
installer.flatpak_binary = lambda: "/usr/bin/flatpak"
emu_install.flatpak_binary = lambda: "/usr/bin/flatpak"
try:
    _out = _run(_shared.uninstall_retroarch(False))
    check("removing RetroArch reaches the shared runner", len(seen), 1)
    check("and it is flatpak that gets run", "flatpak" in " ".join(seen[0]).lower(), True)
    check("and the caller still reports its own result", _out.get("ok"), True)

    _out = _run(_shared._flatpak_uninstall("org.example.Nothing"))
    check("removing an emulator reaches the same one", len(seen), 2)
    check("with the id it was asked about", seen[1][-1], "org.example.Nothing")
finally:
    installer.flatpak_binary = _real_binary
    emu_install.flatpak_binary = _real_emu_binary


section("and the runner carries what flatpak needs to work at all")

# The failures below are logged with tracebacks, which is correct and also reads
# like a broken run. Restored at the end.
_log_level = decky.logger.level
decky.logger.setLevel(logging.CRITICAL)


class _FakeProcess:
    def __init__(self, output, code, hang=False):
        self._output = output
        self.returncode = code
        self._hang = hang

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(3600)
        return self._output, b""


def _with_process(process, error=None):
    """Replace asyncio's spawn with one that records how it was called."""
    recorded = {}

    async def _spawn(*argv, **kwargs):
        recorded["argv"] = list(argv)
        recorded["kwargs"] = kwargs
        if error is not None:
            raise error
        return process

    return recorded, _spawn


_real_spawn = asyncio.create_subprocess_exec
_plugin = _plugin_on_loop()
try:
    _recorded, asyncio.create_subprocess_exec = _with_process(
        _FakeProcess(b"Uninstalling org.libretro.RetroArch...\n", 0)
    )
    _result = _run(_plugin._run_flatpak(["/usr/bin/flatpak", "uninstall", "--user", "x"]))
    check("a clean removal reports ok", _result, {"ok": True})

    _env = _recorded["kwargs"].get("env") or {}
    # The one that broke it: Steam's loader path makes flatpak die on an OPENSSL
    # symbol before it does anything, and the exit code says nothing about why.
    check("Steam's library path is not passed on", "LD_LIBRARY_PATH" in _env, False)
    check("HOME is set, since --user resolves its install from it", bool(_env.get("HOME")), True)
    check("and the output is captured rather than discarded",
          _recorded["kwargs"].get("stdout") is not None, True)
    check("stderr comes back on the same stream, so a reason is never split",
          _recorded["kwargs"].get("stderr"), asyncio.subprocess.STDOUT)

    # A failure has to arrive as what flatpak said. "exited with code 1" cost a
    # debugging round once, which is why the last lines are kept.
    _recorded, asyncio.create_subprocess_exec = _with_process(
        _FakeProcess(b"Looking for matches...\nerror: No installed refs found\n", 1)
    )
    _result = _run(_plugin._run_flatpak(["/usr/bin/flatpak", "uninstall", "x"]))
    check("a failed removal is not reported as ok", _result.get("ok"), False)
    check("and the error is flatpak's own words",
          "No installed refs found" in _result.get("error", ""), True)

    # Nothing to read is still an answer, and it must not be an empty string --
    # the panel shows this text and would show a blank row instead.
    _recorded, asyncio.create_subprocess_exec = _with_process(_FakeProcess(b"", 1))
    _result = _run(_plugin._run_flatpak(["/usr/bin/flatpak", "uninstall", "x"]))
    check("a silent failure still says something", bool(_result.get("error")), True)

    # flatpak asking a question nothing can answer used to hang the panel with a
    # spinner and no way out; --noninteractive covers the known case and the
    # timeout covers the rest.
    _recorded, asyncio.create_subprocess_exec = _with_process(
        _FakeProcess(b"", 0, hang=True)
    )
    _real_wait_for = asyncio.wait_for

    async def _instant_timeout(awaitable, timeout=None):
        # The timeout is what is being checked, not how long it takes to arrive.
        return await _real_wait_for(awaitable, 0.05)

    asyncio.wait_for = _instant_timeout
    try:
        _result = _run(_plugin._run_flatpak(["/usr/bin/flatpak", "uninstall", "x"]))
    finally:
        asyncio.wait_for = _real_wait_for
    check("a command that never finishes is given up on", _result.get("ok"), False)
    check("and says so in words a panel can show",
          "three minutes" in _result.get("error", ""), True)

    # flatpak missing entirely. The endpoints guard against an empty argv, but a
    # binary that is there and unrunnable reaches this instead.
    _recorded, asyncio.create_subprocess_exec = _with_process(
        None, error=OSError("[Errno 13] Permission denied: '/usr/bin/flatpak'")
    )
    _result = _run(_plugin._run_flatpak(["/usr/bin/flatpak", "uninstall", "x"]))
    check("a binary that cannot be run is reported, not raised", _result.get("ok"), False)
    check("and names what could not be run", "flatpak" in _result.get("error", ""), True)
finally:
    asyncio.create_subprocess_exec = _real_spawn
    decky.logger.setLevel(_log_level)
    asyncio.set_event_loop(None)
    LOOP.close()


if __name__ == "__main__":
    from harness import summary

    summary()
