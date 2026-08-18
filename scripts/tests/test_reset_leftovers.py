#!/usr/bin/env python3
"""A state reset must empty decky's runtime directory, not two thirds of it.

    python scripts/tests/test_reset_leftovers.py

The action says "forget everything the plugin knows". It named the launcher
scripts and the artwork cache and stopped, which left the generated half of that
directory standing: RetroArch override configs baked from settings that had just
been deleted, the controller profile written to go with them, the cached core
catalog, the symlinks pointing at ROMs the same reset had removed, and any
update downloaded but not yet installed.

The override configs are the ones that matter. A reinstall read values nothing
in the plugin remembered writing, which is the exact failure a state reset
exists to rule out while testing -- and the pattern is one this file has seen
before: `clear_state` deletes settings.json and the next startup writes part of
it back, which took a session to explain because nothing said what had gone.

So this checks the two halves agree: everything the action deletes is something
the panel offered to delete first, and nothing the plugin writes into that
directory survives.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

import decky  # noqa: E402
import devreset  # noqa: E402
import emulators  # noqa: E402
import launchers  # noqa: E402

RUNTIME = decky.DECKY_PLUGIN_RUNTIME_DIR


def _make(path, is_dir):
    if is_dir:
        os.makedirs(path, exist_ok=True)
        with io.open(os.path.join(path, "something"), "w", encoding="utf-8") as handle:
            handle.write("x" * 32)
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write("x" * 32)


section("a state reset takes the whole runtime directory with it")

# Everything the plugin writes there, made to exist so the reset has something
# to find. Derived from the modules that own the paths rather than typed out --
# a list here would be the copy that goes stale.
_written = [
    (launchers.LAUNCHER_DIR, True),
    (os.path.join(RUNTIME, "thumb_index"), True),
    (launchers.AUTOCONFIG_DIR, True),
    (emulators.ARG_LINK_DIR, True),
    (os.path.join(RUNTIME, "installer"), True),
    (launchers.OVERRIDE_CONFIG, False),
    (os.path.join(RUNTIME, "deckyemu.zip"), False),
]
for _path in launchers.OVERRIDE_CONFIGS.values():
    _written.append((_path, False))

for _path, _is_dir in _written:
    _make(_path, _is_dir)

# The panel shows this before anything is pressed, and it is the whole of the
# warning: what it leaves out, the user does not know they are losing.
_offered = {os.path.normpath(item["path"]) for item in devreset.inventory()["state"]}
_missing_from_offer = sorted(
    os.path.basename(path) for path, _is_dir in _written
    if os.path.normpath(path) not in _offered
)
check("the inventory offers every one of them", _missing_from_offer, [])

# The override configs by name, because they are the reason this exists: stale
# ones are read by a reinstall as though the plugin had written them.
check("including every OSD override file",
      all(os.path.normpath(p) in _offered for p in launchers.OVERRIDE_CONFIGS.values()),
      True)
check("and the legacy override left for older launchers",
      os.path.normpath(launchers.OVERRIDE_CONFIG) in _offered, True)

devreset.clear_state()

_left = sorted(
    os.path.basename(path) for path, _is_dir in _written if os.path.exists(path)
)
check("and the reset leaves none of them behind", _left, [])

# Not a tautology: the directory itself stays, because decky owns it and the
# plugin only writes inside it.
check("the runtime directory itself is still there", os.path.isdir(RUNTIME), True)

# The other direction. A file that is not the plugin's is not the plugin's to
# delete, whatever it is doing in there.
_stranger = os.path.join(RUNTIME, "something-else.txt")
_make(_stranger, False)
devreset.clear_state()
check("something the plugin did not write is left alone",
      os.path.isfile(_stranger), True)
os.remove(_stranger)


if __name__ == "__main__":
    summary()
