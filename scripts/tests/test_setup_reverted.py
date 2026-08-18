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


if __name__ == "__main__":
    summary()
