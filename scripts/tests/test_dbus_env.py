#!/usr/bin/env python3
"""flatpak is given the session bus, because --delete-data cannot work without it.

    python scripts/tests/test_dbus_env.py

"Remove RetroArch" with "also delete saves and configuration" failed with:

    error: Cannot autolaunch D-Bus without X11 $DISPLAY

on a device that has no X11, does not need one, and already has a session bus
running with its socket sitting in /run/user/1000. The plugin is started by a
systemd service and inherits no `DBUS_SESSION_BUS_ADDRESS`, so flatpak tried to
start a bus of its own and said so in the least helpful way available.

Only `--delete-data` reaches for the bus; every install and plain uninstall this
plugin runs had worked without it, which is why it took a checkbox to find.

What made it worth more than a one-line fix is where it failed. flatpak removes
the application first and its data second, so the failure arrived *after*
RetroArch was already gone -- the panel reported an error and went on showing
RetroArch as installed. Both halves are checked here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, TMP, check, section, summary  # noqa: E402

sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

section("the environment flatpak is handed")

if os.name != "posix":
    print("SKIP the runtime dir and its socket are POSIX-only")
else:
    _runtime = os.path.join(TMP, "runtime-dir")
    os.makedirs(_runtime, exist_ok=True)
    _real_environ = dict(os.environ)
    try:
        # No socket yet. Naming an address for a bus that is not running turns a
        # clear "cannot autolaunch" into a connection refused, which is worse.
        os.environ["XDG_RUNTIME_DIR"] = _runtime
        _env = main.Plugin._subprocess_env()
        check("no bus is claimed when there is no socket",
              "DBUS_SESSION_BUS_ADDRESS" in _env, False)

        # The socket, as a plain file: what is checked is that it exists, and a
        # real one cannot be made without a bus to run it.
        open(os.path.join(_runtime, "bus"), "w").close()
        _env = main.Plugin._subprocess_env()
        check("the running bus is named once its socket is there",
              _env.get("DBUS_SESSION_BUS_ADDRESS"),
              "unix:path=%s/bus" % _runtime)
        check("and the runtime dir goes with it, which is how it is found",
              _env.get("XDG_RUNTIME_DIR"), _runtime)

        # An inherited address wins: it is the bus this process was actually
        # told about, and guessing over it would be guessing over the truth.
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/somewhere/else"
        check("an inherited address is not overridden",
              main.Plugin._subprocess_env().get("DBUS_SESSION_BUS_ADDRESS"),
              "unix:path=/somewhere/else")
    finally:
        os.environ.clear()
        os.environ.update(_real_environ)

# The rest of the environment has to survive: this is the same function that
# strips Steam's loader path, and losing that fails flatpak before it starts.
_env = main.Plugin._subprocess_env()
check("Steam's library path is still stripped", "LD_LIBRARY_PATH" in _env, False)
check("and HOME is still guaranteed", bool(_env.get("HOME")), True)


if __name__ == "__main__":
    summary()
