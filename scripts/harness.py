#!/usr/bin/env python3
"""The scaffolding every backend test needs, and nothing else.

Everything under py_modules/ is plain Python whose only decky dependency is a
logger and a few directory paths, so it can run anywhere once those are stubbed.
This module does the stubbing, owns the scratch directory, and keeps the score.

Import it before anything from py_modules: installing the fake `decky` into
sys.modules has to happen first, and importing this module is what does it.

    from harness import check, section, summary, TMP

Lived at the top of test_backend.py until that file reached six and a half
thousand lines. Splitting it out is what lets a test live in its own file and be
run on its own -- see scripts/tests/.
"""

import logging
import atexit
import io
import os
import shutil
import sys
import tempfile
import types

OFFLINE = "--offline" in sys.argv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="retroarch-to-steam-test-")


@atexit.register
def _remove_tmp():
    """Take the scratch directory with us.

    Without this every run left one behind: four hundred of them accumulated
    during one long session, and because the firmware tests wrote real files
    the pile reached twenty-five gigabytes and filled the disk. A test suite
    that quietly consumes the machine it runs on is its own bug.

    Best effort -- a failed cleanup must never turn a passing run into a
    failing one, and on Windows a file the run still holds open cannot go.
    """
    shutil.rmtree(TMP, ignore_errors=True)

# --- stub the decky module the plugin normally runs inside ------------------
decky = types.ModuleType("decky")
decky.DECKY_PLUGIN_RUNTIME_DIR = os.path.join(TMP, "runtime")
decky.DECKY_PLUGIN_SETTINGS_DIR = os.path.join(TMP, "settings")
decky.DECKY_PLUGIN_LOG_DIR = os.path.join(TMP, "logs")
decky.DECKY_PLUGIN_NAME = "RetroArch to Steam"
# Not asserted anywhere -- CI rewrites the real one on release.
decky.DECKY_PLUGIN_VERSION = "0.0.0-test"
decky.DECKY_USER_HOME = os.path.join(TMP, "home")
# Sandboxed for the whole run, not just where a section sets it: anything that
# resolves the user's home would otherwise create folders in the developer's real
# home. `sysenv.user_home()` reads this variable, which is the point of it.
os.environ["DECKY_USER_HOME"] = decky.DECKY_USER_HOME
os.makedirs(decky.DECKY_USER_HOME, exist_ok=True)
# Sandboxed inside the temp dir so key discovery cannot read a real install.
decky.DECKY_HOME = os.path.join(TMP, "homebrew")
logging.basicConfig(level=logging.WARNING, format="[decky] %(message)s")
decky.logger = logging.getLogger("decky")
sys.modules["decky"] = decky

for directory in (decky.DECKY_PLUGIN_RUNTIME_DIR, decky.DECKY_PLUGIN_SETTINGS_DIR):
    os.makedirs(directory, exist_ok=True)
sys.path.insert(0, os.path.join(REPO_ROOT, "py_modules"))

import launchers  # noqa: E402
import libretro_meta as meta  # noqa: E402
import ra_cores  # noqa: E402
import store  # noqa: E402

failures = []


def check(label, actual, expected):
    ok = actual == expected
    print("%s %-52s %r" % ("PASS" if ok else "FAIL", label, actual))
    if not ok:
        failures.append("%s: got %r, expected %r" % (label, actual, expected))


def section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)




def summary():
    """Print the result and exit. Called by whatever was run directly."""
    print()
    print("=" * 78)
    if failures:
        print("%d FAILURE(S):" % len(failures))
        for failure in failures:
            print("  -", failure)
        sys.exit(1)
    print("ALL CHECKS PASSED")
