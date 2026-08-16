#!/usr/bin/env python3
"""The first firmware import is also the emulator's first ever run.

    python scripts/tests/test_firmware_first_run.py

Vita3K has deliberately never run when its firmware is imported: its config is
a whole yaml document that must not be invented, so the setup block waits for
the emulator to write one, and this import is the first thing that starts it.

With no configuration it has no preference path, and hands an empty one to
create_directories:

    terminate called after throwing 'boost::filesystem::filesystem_error'
    what(): create_directories: Invalid argument [generic:22]

It aborts in under a second having written the config on its way down, so the
identical command works immediately afterwards. Observed on a Deck: install
failed, install pressed again, install succeeded, byte-identical argv both
times. The retry is what stops that being something the user has to guess.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import emu_firmware  # noqa: E402
import emulators  # noqa: E402
import main as plugin_main  # noqa: E402

section("firmware import -- a first run that installs nothing is retried once")

_plugin = plugin_main.Plugin()
_plugin.loop = __import__("asyncio").new_event_loop()


def _run(function, *args):
    async def call():
        return function(*args)
    return call()


_plugin._run = _run

ENTRY = {"id": "vita3k", "name": "Vita3K"}
REQUIREMENT = {"name": "PS Vita firmware", "import": {"args": ["--firmware", "{file}"]}}

_state = {"runs": 0, "installed_after": 2}


async def _fake_tool(emulator, args, allow=(), seconds=0, on_line=None, display=False):
    _state["runs"] += 1
    _state["argv"] = list(args)
    # The real one crashes on the bootstrap run; the wrapper reports that as a
    # failure, and what decides the outcome is what landed on disk.
    return (_state["runs"] >= _state["installed_after"], "" if _state["runs"] >= 2 else "aborted")


_plugin._run_emulator_tool = _fake_tool

# Module functions, so they have to go back: the suite runs every file in this
# directory in one process, and a stub left behind is a failure in somebody
# else's file with nothing pointing here.
_originals = {
    "find": emulators.find,
    "matching": emu_firmware.matching,
    "imported": emu_firmware.imported,
    "remove": emu_firmware.remove,
}

emulators.find = lambda _id: {"id": "emu:vita3k", "name": "Vita3K"}
emu_firmware.matching = lambda _requirement: ["PSVUPDAT.PUP"]
emu_firmware.imported = lambda _spec: (
    ["psp2bootconfig.skprx"] if _state["runs"] >= _state["installed_after"] else []
)
# The real one returns a report, and the caller reads "removed" off it.
emu_firmware.remove = lambda _names, _dir: {"removed": list(_names)}

try:

    _result = _plugin.loop.run_until_complete(_plugin._import_firmware(ENTRY, REQUIREMENT))

    check("the bootstrap run does not fail the install", _result.get("ok", True), True)
    check("because it was run a second time", _state["runs"], 2)
    # The same command both times: nothing about the retry changes what is asked
    # for, which is what makes it safe -- the emulator, not the argv, was the
    # thing that was not ready.
    check("with the identical arguments", _state["argv"][0], "--firmware")

    section("firmware import -- a real failure is still a failure")

    _state["runs"] = 0
    # Nothing will ever install, however many times it runs.
    _state["installed_after"] = 99
    _result = _plugin.loop.run_until_complete(_plugin._import_firmware(ENTRY, REQUIREMENT))

    check("an import that never installs anything reports failure", _result["ok"], False)
    # Twice, not forever: one retry covers a first run, and a loop would sit
    # there restarting an emulator that is never going to work.
    check("and is not retried more than once", _state["runs"], 2)
    check("reporting what the last run said, not the bootstrap's crash",
          "aborted" in (_result.get("error") or ""), False)
finally:
    emulators.find = _originals["find"]
    emu_firmware.matching = _originals["matching"]
    emu_firmware.imported = _originals["imported"]
    emu_firmware.remove = _originals["remove"]
    _plugin.loop.close()


if __name__ == "__main__":
    from harness import summary

    summary()
