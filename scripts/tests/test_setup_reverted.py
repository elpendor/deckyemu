#!/usr/bin/env python3
"""An emulator that rewrites its own config gets its recommended settings back.

    python scripts/tests/test_setup_reverted.py

DuckStation shipped a setup block that clears `SetupWizardIncomplete`, wrote it
correctly at install, recorded writing it -- and still put a setup wizard in
front of every game Steam launched.

The emulator had never run at that point, so the plugin created settings.ini
from nothing. On its first real run DuckStation regenerated the file with its
own defaults, the wizard flag among them, and nothing ever looked again: the
settings were applied once, at install, and `needs_setup` compared only a
version number that had not changed.

So the version is no longer the only reason to apply. A config file that has
moved since this plugin wrote it is a config that may no longer hold what was
put there, and re-applying is safe by construction -- the writers already leave
alone any value that differs from what was recorded, which is how a setting the
user changed themselves survives the repair.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402  -- installs the decky stub

import emu_config  # noqa: E402
import sysenv  # noqa: E402

_home = os.path.join(TMP, "reverthome")
_relative = os.path.join(".config", "fakestation", "settings.ini")
_path = os.path.join(_home, _relative)
os.makedirs(os.path.dirname(_path), exist_ok=True)

# Shaped like DuckStation's: a wizard flag whose default is the value that
# blocks the game, and one ordinary setting beside it.
ENTRY = {
    "id": "fakestation",
    "name": "FakeStation",
    "setup": {
        "version": 1,
        "format": "plain-ini",
        "path": _relative,
        "sections": {
            "Main": {
                "SetupWizardIncomplete": {"value": "false", "default": "true"},
                "ConfirmPowerOff": {"value": "false", "default": "true"},
            },
        },
    },
}


def _write(text):
    with io.open(_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _read():
    with io.open(_path, encoding="utf-8") as handle:
        return handle.read()


section("settings survive the emulator writing its own config")

_real_home = sysenv.user_home
sysenv.user_home = lambda: _home
try:
    # Installed: the emulator has never run, so the file does not exist yet and
    # the plugin creates it. This is the case that went wrong.
    _result = emu_config.apply_setup(ENTRY)
    check("the setup applies at install", _result["ok"], True)
    check("and the wizard flag is cleared", "SetupWizardIncomplete = false" in _read(), True)
    check("so there is nothing left to do", emu_config.needs_setup(ENTRY), False)

    # The emulator's first real run: it regenerates the file from its own
    # defaults, wizard flag included, and adds a version key of its own that
    # nothing here wrote.
    _write(
        "[Main]\n"
        "SetupWizardIncomplete = true\n"
        "ConfirmPowerOff = true\n"
        "SettingsVersion = 3\n"
    )
    check("a regenerated config is noticed", emu_config.needs_setup(ENTRY), True)

    _result = emu_config.apply_setup(ENTRY)
    check("and applying puts the wizard flag back", _result["ok"], True)
    check("really back", "SetupWizardIncomplete = false" in _read(), True)
    check("with the rest of the block", "ConfirmPowerOff = false" in _read(), True)
    # The emulator's own key is not this plugin's business and stays.
    check("and what the emulator added is left alone",
          "SettingsVersion = 3" in _read(), True)
    check("and it settles rather than repairing forever",
          emu_config.needs_setup(ENTRY), False)

    # The half that must not regress: a value the *user* changed is theirs, and
    # the repair must not stamp over it. Written by hand to something that is
    # neither the default nor what the plugin wrote.
    _write(
        "[Main]\n"
        "SetupWizardIncomplete = false\n"
        "ConfirmPowerOff = maybe\n"
    )
    check("a hand-edited config is noticed too", emu_config.needs_setup(ENTRY), True)
    _result = emu_config.apply_setup(ENTRY)
    check("and the user's own value is kept",
          "ConfirmPowerOff = maybe" in _read(), True)
    check("while the plugin's is still asserted",
          "SetupWizardIncomplete = false" in _read(), True)
    check("and it is reported as left alone, not written",
          any("ConfirmPowerOff" in name for name in _result["skipped"]), True)

    # A config deleted since is the same problem as one regenerated.
    os.remove(_path)
    check("a config that has gone is noticed", emu_config.needs_setup(ENTRY), True)
finally:
    sysenv.user_home = _real_home

check("the real home resolver is back", sysenv.user_home is _real_home, True)


section("and something asks between one startup and the next")
# The repair above was reached only by the startup sweep, and an emulator
# installed and then played in the same session never sees another startup.
# Azahar on a real device: settings written at install into a config Azahar had
# never made (2189 bytes, 17 keys), Azahar's first run regenerating it (34086
# bytes, every binding back to a keyboard default), and the game launched
# minutes later with no controls. `needs_setup` was True the whole time and
# nothing asked it.

import asyncio  # noqa: E402
import plugin_startup  # noqa: E402

_asked = []


class _Fake:
    """Enough of the composed Plugin for the wrapper under test."""

    async def _upgrade_emulator_setups(self):
        _asked.append(True)


asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
    plugin_startup.Startup._recheck_emulator_setups(_Fake())
)
check("the re-check runs the same sweep startup does", _asked, [True])


class _Broken(_Fake):
    async def _upgrade_emulator_setups(self):
        raise RuntimeError("flatpak is not there")


# It is called from `get_status`, which is what the panel opens on: a failure
# here has to cost stale settings, never a panel that will not load.
try:
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        plugin_startup.Startup._recheck_emulator_setups(_Broken())
    )
    _raised = False
except Exception:
    _raised = True
check("and a failure inside it never reaches the caller", _raised, False)

# The wiring itself, because the behaviour above is one line in each caller and
# what breaks is somebody removing it. Both are named: `get_status` is every
# panel open, `prepare_shortcut` is the last plugin code before a game exists to
# be launched.
_main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "main.py")
with io.open(_main, "r", encoding="utf-8") as handle:
    _source = handle.read()

_NEXT_METHOD = "    async def "

for _caller in ("get_status", "prepare_shortcut"):
    _at = _source.index("async def %s(" % _caller)
    _end = _source.find(_NEXT_METHOD, _at + 1)
    _body = _source[_at:_end if _end != -1 else len(_source)]
    check("%s re-checks the emulator settings" % _caller,
          "_recheck_emulator_setups" in _body, True)


if __name__ == "__main__":
    summary()
