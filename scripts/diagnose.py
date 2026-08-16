#!/usr/bin/env python3
"""Print a Deck's diagnostic report here, without touching the Deck's screen.

    python scripts/diagnose.py                 # deck@steamdeck.local
    python scripts/diagnose.py 192.168.0.223   # when .local will not resolve
    python scripts/diagnose.py --raw           # no redaction; for your own device
    python scripts/diagnose.py --log 500       # more of the log than the report keeps

The same report the plugin offers a user under Updates -> Report a problem, and
the same module builds it -- run against the installed plugin's own settings,
library and log. What it replaces is the four commands this was assembled from a
dozen times in one session:

    ssh deck@steamdeck.local 'ls -t ~/homebrew/logs/deckyemu/*.log | head -1'
    ssh deck@steamdeck.local 'tail -n 200 "<that>"'
    ssh deck@steamdeck.local 'cat ~/homebrew/settings/deckyemu/library.json'
    ...and then reading four files to work out which build was running.

`--raw` skips the redaction, which is the right default for your own device and
the wrong one for anybody else's: paste the redacted form into an issue. The
flag exists because a name struck out of a log is a name you cannot grep for,
and half of debugging is grepping for the name.

Needs SSH keys set up, which the deploy script needs anyway. It leaves nothing
behind: the script below goes over stdin to the Deck's own Python and is never
written to its disk.
"""

import argparse
import subprocess
import sys

#: Run on the Deck, under its own Python, against the installed plugin.
#:
#: `decky` is the module the loader injects and it does not exist outside it, so
#: it is stubbed here the way the test harness stubs it -- the directories are
#: the ones decky derives from the plugin folder name, which is why renaming
#: that folder orphans everything.
REMOTE = r'''
import json, logging, os, sys, types

home = os.path.expanduser("~")
root = os.path.join(home, "homebrew")
plugin = os.path.join(root, "plugins", "deckyemu")

decky = types.ModuleType("decky")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(root, "settings", "deckyemu")
decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(root, "data", "deckyemu")
decky.DECKY_PLUGIN_LOG_DIR = os.path.join(root, "logs", "deckyemu")
decky.DECKY_USER_HOME = home
decky.DECKY_HOME = root
decky.DECKY_PLUGIN_NAME = "DeckyEmu"
decky.DECKY_PLUGIN_VERSION = "unknown"
decky.logger = logging.getLogger("decky")
sys.modules["decky"] = decky
os.environ["DECKY_USER_HOME"] = home

if not os.path.isdir(plugin):
    print("No plugin at %s -- is it installed under that name?" % plugin)
    raise SystemExit(1)
sys.path.insert(0, os.path.join(plugin, "py_modules"))

import diagnostics, store

version = {"version": "?", "build": "?", "built_at": ""}
for name in ("build.json", "package.json"):
    try:
        with open(os.path.join(plugin, name), encoding="utf-8") as handle:
            stamp = json.load(handle)
        version["version"] = stamp.get("version") or version["version"]
        version["build"] = stamp.get("commit") or version["build"]
        version["built_at"] = stamp.get("built_at") or version["built_at"]
    except (OSError, ValueError):
        pass

# `list_emulators`, not a guess at the name. The first version of this called
# `emulators.load()`, which does not exist, and the bare `except` below it
# turned that into an empty list -- so a Deck with two registered emulators
# reported none, and said so as confidently as if it had looked.
import emulators
registered = emulators.list_emulators()

# Actually detected, rather than passed as None and printed as "not found".
# Reporting an absence nobody checked for is worse than reporting nothing.
import ra_detect
install = ra_detect.detect()

diagnostics.LOG_LINES = __LOG_LINES__
if __RAW__:
    # Every value strike and every shape rule off, for your own device.
    diagnostics._redact = lambda text, secrets, words=(): text

print(diagnostics.build(
    version, install, registered, store.get_library(), [], [],
    os.path.join(home, "deckyemu", "transfer"),
))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", nargs="?", default="steamdeck.local",
                        help="the Deck, as a hostname or an address")
    parser.add_argument("--user", default="deck")
    parser.add_argument("--raw", action="store_true",
                        help="skip the redaction (your own device only)")
    parser.add_argument("--log", type=int, default=200, metavar="N",
                        help="how many log lines to carry (default 200)")
    args = parser.parse_args()

    script = REMOTE.replace("__LOG_LINES__", str(args.log))
    script = script.replace("__RAW__", "True" if args.raw else "False")
    target = "%s@%s" % (args.user, args.host)

    # Over stdin rather than as an argument: the script is a few kilobytes and
    # quoting it through two shells is how it would come to be corrupted.
    finished = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target,
         "python3 - "],
        input=script, text=True, capture_output=True,
    )

    if finished.returncode != 0:
        sys.stderr.write(finished.stderr or "ssh failed\n")
        # The two that actually happen, and neither says so plainly on its own.
        if "Could not resolve" in (finished.stderr or ""):
            sys.stderr.write(
                "\n.local needs mDNS. Try the address instead:"
                "\n    python scripts/diagnose.py 192.168.0.223\n"
            )
        elif "Permission denied" in (finished.stderr or ""):
            sys.stderr.write("\nSSH keys are not set up for %s.\n" % target)
        return 1

    sys.stdout.write(finished.stdout)
    if args.raw:
        sys.stderr.write(
            "\n-- unredacted: this names games, paths and possibly keys. "
            "Do not paste it anywhere.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
