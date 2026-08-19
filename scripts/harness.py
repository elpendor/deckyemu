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


async def _emit(event, *args):
    """Swallow progress events, and record them for anyone who wants to look.

    The real `decky.emit` reaches the frontend over decky's socket, which does
    not exist here. Without this, adding a progress event to any code path the
    suite already covers turns it into an AttributeError -- which is how it went
    the first time, on `clear_library`. A test that cares about the events
    replaces this outright; see scripts/tests/test_detach.py.
    """
    decky.emitted.append((event, args))


decky.emitted = []
decky.emit = _emit
sys.modules["decky"] = decky

for directory in (decky.DECKY_PLUGIN_RUNTIME_DIR, decky.DECKY_PLUGIN_SETTINGS_DIR):
    os.makedirs(directory, exist_ok=True)
sys.path.insert(0, os.path.join(REPO_ROOT, "py_modules"))

import launchers  # noqa: E402
import libretro_meta as meta  # noqa: E402
import ra_cores  # noqa: E402
import store  # noqa: E402

failures = []


# --- fixtures more than one file needs ---------------------------------------

def make_sfo(pairs):
    """A PARAM.SFO holding `pairs`. Strings and uint32s, which is all it uses.

    Header: magic, version, offset of the key table, offset of the data table,
    entry count. Then one 16-byte index entry per key -- key offset, format,
    used length, total length, data offset -- then the keys as null-terminated
    ASCII, then the values.

    Built byte by byte from the documented layout rather than shipped as a file.
    It used to be Braid's own PARAM.SFO, lifted off a Deck -- a kilobyte of a
    commercial game, Sony's copyright notice included, in a repository that is
    going public. Not worth it for a parser test.

    Constructing it from the spec keeps what the fixture was for. The objection
    to a generated file is that it only proves the writer and the reader agree;
    that does not apply here, because there is no writer -- this is struct.pack
    against the format as documented, and sfo.py has to meet it rather than meet
    itself. This is the pattern to copy for any other format the project reads.

    Here rather than in a test file because three of them need it: the PS3, PS4
    and Vita records all start with this container. It sat inside one section of
    test_backend.py and two other sections reached across the file for the bytes
    it happened to leave behind, which is what broke when that section moved.
    """
    import struct as _struct

    keys, values, index = b"", b"", b""
    for name, value in pairs:
        if isinstance(value, int):
            fmt, raw = 0x0404, _struct.pack("<I", value)
            used = total = 4
        else:
            fmt = 0x0204
            raw = value.encode("utf-8") + b"\x00"
            used = len(raw)
            # Real ones pad the value to a multiple of four; the reader has to
            # cope with total > used, so the fixture exercises that.
            total = (used + 3) & ~3
            raw = raw.ljust(total, b"\x00")
        index += _struct.pack("<HHIII", len(keys), fmt, used, total, len(values))
        keys += name.encode("ascii") + b"\x00"
        values += raw
    keys = keys.ljust((len(keys) + 3) & ~3, b"\x00")

    header_size = _struct.calcsize("<4sIIII")
    key_table = header_size + len(index)
    data_table = key_table + len(keys)
    return (_struct.pack("<4sIIII", b"\x00PSF", 0x0101, key_table, data_table,
                         len(pairs)) + index + keys + values)


#: One made-up game's PARAM.SFO, which is what every caller actually wanted.
#: The title id is a real product code shape, not a real product code.
SAMPLE_SFO = make_sfo([
    ("APP_VER", "01.00"),
    ("BOOTABLE", 1),
    ("CATEGORY", "HG"),
    ("PARENTAL_LEVEL", 4),
    ("TITLE", "Braid"),
    ("TITLE_ID", "NPUB30133"),
])


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




def link(source, target):
    """A symlink, or a plain file standing in for one where they are refused.

    Windows will not make a symlink without a privilege a test host has no
    reason to hold, and every check that reads one here goes through
    `os.path.lexists` -- which answers the same for both. So the fallback tests
    the same thing rather than skipping on the developer's machine and only
    running in CI.
    """
    if os.path.lexists(source):
        try:
            os.remove(source)
        except OSError:
            shutil.rmtree(source, ignore_errors=True)
    try:
        os.symlink(target, source)
    except (OSError, NotImplementedError, AttributeError):
        with io.open(source, "w") as handle:
            handle.write(target)


def deploy_flatpak(root, app_id, commit="0" * 64, arch="x86_64", branch="stable"):
    """A flatpak application as flatpak actually lays one out, under `root`.

    The commit tree *and* the two symlinks that make it a deployment: `current`
    at the top and `active` under the branch. Both matter, because a directory
    holding commit trees and neither symlink is what a failed operation leaves
    behind -- flatpak disowns it, and the plugin must not read it as an install.
    Fixtures that made only the directory reported an install for something
    flatpak would refuse to run or remove, which is the bug this shape exists to
    keep out. Returns the deploy path.
    """
    base = os.path.join(root, "app", app_id)
    deploy = os.path.join(base, arch, branch, commit)
    os.makedirs(os.path.join(deploy, "files"), exist_ok=True)
    with io.open(os.path.join(deploy, "metadata"), "w") as handle:
        handle.write(os.linesep.join(["[Application]", "name=%s" % app_id, ""]))
    link(os.path.join(base, arch, branch, "active"), commit)
    link(os.path.join(base, "current"), "%s/%s" % (arch, branch))
    return deploy


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
