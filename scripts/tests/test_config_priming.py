#!/usr/bin/env python3
"""An emulator writes its own config before this plugin edits one.

    python scripts/tests/test_config_priming.py

Settings written into a file the emulator has never made do not survive its
first run. The emulator does not recognise the file as its own -- DuckStation
checks `SettingsVersion`, Azahar checks `firstStart` -- so it regenerates it
from its own defaults, and the first game anyone launches is the one that pays:
a setup wizard no gamepad can dismiss, or a 3DS game with nothing bound.

Both halves of this were measured on a Deck rather than reasoned about.
DuckStation with `QT_QPA_PLATFORM=offscreen` and `SDL_VIDEODRIVER=dummy` wrote a
complete 8392-byte settings.ini before the timeout stopped it. Azahar's AppImage
would not: its Qt ships only the `xcb` platform plugin, so `offscreen` is not an
option it has and it dumps core -- but under `gamescope --backend headless` the
same AppImage wrote its whole 32658-byte config.
"""

import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emu_config  # noqa: E402
import emulators  # noqa: E402
import plugin_emulators  # noqa: E402
import sysenv  # noqa: E402

section("which configs are not there yet")

_home = os.path.join(TMP, "primehome")
_relative = os.path.join(".config", "fakestation", "settings.ini")
os.makedirs(os.path.join(_home, os.path.dirname(_relative)), exist_ok=True)

_real_home = sysenv.user_home
sysenv.user_home = lambda: _home

SETUP = {
    "format": emu_config.PLAIN_INI,
    "version": 1,
    "files": {_relative.replace(os.sep, "/"): {"Main": {"Wizard": {"value": "false"}}}},
}
ENTRY = {"id": "fakestation", "name": "FakeStation", "setup": SETUP}
EMULATOR = {"id": "fakestation", "name": "FakeStation", "kind": "flatpak",
            "target": "org.fake.Station"}

_path = os.path.join(_home, _relative)

try:
    check("a config that has never been written is reported",
          emu_config.missing_files(SETUP), [_relative.replace(os.sep, "/")])

    with io.open(_path, "w", encoding="utf-8") as handle:
        handle.write("[Main]\n")
    check("and one the emulator has written is not",
          emu_config.missing_files(SETUP), [])
    check("an entry with no setup asks for nothing",
          emu_config.missing_files(None), [])
    os.remove(_path)

    section("how the emulator is asked to write it")

    class _Fake:
        """Enough of the composed Plugin to drive `_prime_emulator_config`.

        The constants come from the real class rather than being restated, so
        the checks below are asserting what ships, not a copy of it.
        """

        _OFFSCREEN = plugin_emulators.Emulators._OFFSCREEN
        _HEADLESS_WRAPPER = plugin_emulators.Emulators._HEADLESS_WRAPPER
        _PRIME_SECONDS = plugin_emulators.Emulators._PRIME_SECONDS

        def __init__(self, writes_on=None):
            self.attempts = []
            self.writes_on = writes_on

        async def _run(self, function, *args):
            return function(*args)

        async def _run_emulator_tool(self, emulator, args, seconds=0,
                                     env_overrides=None, wrapper=()):
            self.attempts.append({"wrapper": tuple(wrapper), "env": dict(env_overrides or {}),
                                  "seconds": seconds})
            if self.writes_on is not None and len(self.attempts) >= self.writes_on:
                with io.open(_path, "w", encoding="utf-8") as handle:
                    handle.write("[Main]\nSettingsVersion = 3\n")
            return True, ""

    def _prime(fake):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                plugin_emulators.Emulators._prime_emulator_config(fake, ENTRY, EMULATOR)
            )
        finally:
            loop.close()

    # The cheap attempt is the one that works for a Qt flatpak, and nothing else
    # runs once the file is there: an emulator that has written its config has
    # done the only job this asked of it.
    _first = _Fake(writes_on=1)
    check("the emulator writes its config and that is the end of it",
          (_prime(_first), len(_first.attempts)), (True, 1))
    check("asked with nowhere to draw",
          _first.attempts[0]["env"],
          {"QT_QPA_PLATFORM": "offscreen", "SDL_VIDEODRIVER": "dummy"})
    check("and with no wrapper around it", _first.attempts[0]["wrapper"], ())
    os.remove(_path)

    # Azahar's case: its Qt has no `offscreen` plugin at all, so the first
    # attempt cannot write anything and a real display has to be arranged.
    _second = _Fake(writes_on=2)
    check("an emulator that needs a display gets one that shows nothing",
          (_prime(_second), len(_second.attempts)), (True, 2))
    check("which is gamescope's headless backend",
          _second.attempts[1]["wrapper"],
          ("gamescope", "--backend", "headless", "--"))
    os.remove(_path)

    # Nothing written by either attempt. Reported, not raised: the settings are
    # still written into a new file as before, and the repair after the
    # emulator's first run is what catches it -- one bad launch instead of a
    # failed install.
    _never = _Fake()
    check("an emulator that writes nothing is given up on, not failed on",
          (_prime(_never), len(_never.attempts)), (False, 2))

    # Priming is for the first time only. An emulator that already has a config
    # must never be started behind the user's back.
    with io.open(_path, "w", encoding="utf-8") as handle:
        handle.write("[Main]\n")
    _already = _Fake()
    check("an emulator that already has a config is left alone",
          (_prime(_already), _already.attempts), (False, []))
finally:
    sysenv.user_home = _real_home

check("the real home resolver is back", sysenv.user_home is _real_home, True)

section("the environment reaches the sandbox")

# A flatpak does not inherit the caller's environment, so a variable the run
# depends on has to be on `flatpak run`'s own command line, before the app id.
_argv = emulators.tool_argv(EMULATOR, [], (), {"QT_QPA_PLATFORM": "offscreen"})
check("a flatpak is handed the variable on its command line",
      "--env=QT_QPA_PLATFORM=offscreen" in _argv, True)
check("before the application id, or flatpak reads it as an argument to the app",
      _argv.index("--env=QT_QPA_PLATFORM=offscreen") < _argv.index("org.fake.Station"),
      True)

# Everything outside a sandbox reads it from the process environment the runner
# sets, so there is nothing to add to the command line.
_appimage = emulators.tool_argv(
    {"kind": "appimage", "target": "/home/deck/emus/azahar.AppImage"}, [], (),
    {"QT_QPA_PLATFORM": "offscreen"},
)
check("while an AppImage is run directly", _appimage, ["/home/deck/emus/azahar.AppImage"])


if __name__ == "__main__":
    summary()
