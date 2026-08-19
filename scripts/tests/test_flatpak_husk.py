#!/usr/bin/env python3
"""A deploy directory flatpak has disowned is not an install.

    python scripts/tests/test_flatpak_husk.py

What this is for, from the device it happened on. A version switch ran
`flatpak update --commit=<hash>` and failed with "Directory not empty"; the ref
went, both commit trees stayed. From then on `flatpak info` said DuckStation
was not installed, while the plugin -- which answers that question off the
filesystem, because asking flatpak once per catalog entry per panel open is
eleven subprocesses -- saw `app/org.duckstation.DuckStation` and said it was.

That combination has no way out. The row offers Remove, the removal answers
"no installed refs found", the plugin reports a failure, and the row is exactly
as it was. Three things had to change for the button to be able to work, and
each is checked here: what counts as installed, what a removal that finds
nothing counts as, and who clears the leftover away.
"""

import asyncio
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, TMP, check, section, summary  # noqa: E402  -- installs the stub

sys.path.insert(0, REPO_ROOT)

import emu_install  # noqa: E402
import main  # noqa: E402
import sysenv  # noqa: E402

LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

APP = "org.example.Emulator"
ROOT = os.path.join(TMP, "flatpak-husk")


def _commit_tree(app_id, commit, root=ROOT):
    """One deployed commit, as flatpak lays it out."""
    path = os.path.join(root, "app", app_id, "x86_64", "stable", commit)
    os.makedirs(os.path.join(path, "files"), exist_ok=True)
    with open(os.path.join(path, "metadata"), "w") as handle:
        handle.write("[Application]\nname=%s\n" % app_id)
    return path


def _link(source, target):
    """A symlink where the platform has them, a file where it does not.

    Windows refuses symlinks without a privilege the test host has no reason to
    hold, and what is being checked is that the *name* is there -- `lexists` is
    what the code uses, and it answers the same for both.
    """
    if os.path.lexists(source):
        _forget(source)
    try:
        os.symlink(target, source)
    except (OSError, NotImplementedError, AttributeError):
        with open(source, "w") as handle:
            handle.write(target)


def _forget(path):
    """Take one path away, symlink or tree, without caring which it was."""
    try:
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _clear(app_id, root):
    """Start a section from nothing. The suite shares one home, and so do the
    sections in this file -- a check that reads "still installed" because the
    section above it left a symlink behind is the confusing kind of failure."""
    _forget(os.path.join(root, "app", app_id))


section("what counts as installed")

# The husk: commit trees and nothing pointing at them. Two of them, as the
# failed switch left behind -- the one that was running and the one it was
# moving to.
_commit_tree(APP, "a" * 64)
_commit_tree(APP, "b" * 64)
check("a directory of orphaned commits is not an install",
      sysenv.flatpak_deployed(ROOT, APP), False)

# The same directory, once flatpak has something deployed in it.
_link(os.path.join(ROOT, "app", APP, "x86_64", "stable", "active"), "a" * 64)
check("an `active` symlink is what makes it one",
      sysenv.flatpak_deployed(ROOT, APP), True)

# `current` is the cheap path, and the one taken for every catalog entry each
# time the panel opens.
_other = "org.example.Other"
_commit_tree(_other, "c" * 64)
check("without either symlink, still not an install",
      sysenv.flatpak_deployed(ROOT, _other), False)
_link(os.path.join(ROOT, "app", _other, "current"), "x86_64/stable")
check("`current` alone is enough", sysenv.flatpak_deployed(ROOT, _other), True)

check("and nothing at all is not an install",
      sysenv.flatpak_deployed(ROOT, "org.example.Absent"), False)


section("a removal that finds nothing to remove has succeeded")

# Matched on what flatpak says, because the exit code is the same 1 as a real
# failure. Getting this wrong is what told somebody their removal had failed
# while showing them an emulator that was not there.
check("flatpak's own words for it are recognised",
      emu_install.nothing_to_uninstall(
          "error: No installed refs found for ‘org.duckstation.DuckStation’"), True)
check("singular too", emu_install.nothing_to_uninstall("No installed ref found"), True)
# The failure that started all of this, and the one thing that must not be
# swallowed: it means the removal genuinely did not happen.
check("a directory that would not go is still a failure",
      emu_install.nothing_to_uninstall(
          "Error: Failed to uninstall org.duckstation.DuckStation: Directory not empty"),
      False)
check("and so is nothing at all", emu_install.nothing_to_uninstall(""), False)


section("the leftover is swept, and only when flatpak has disowned it")

# Against the real user root, which is what `remove_flatpak_husk` reads: the
# harness points DECKY_USER_HOME at the scratch directory for the whole run.
_system, _user_root = sysenv.flatpak_roots()

_clear(APP, _user_root)
_husk = _commit_tree(APP, "d" * 64, root=_user_root)
check("the husk is there to start with", os.path.isdir(_husk), True)
_freed = emu_install.remove_flatpak_husk(APP)
check("sweeping it reports the bytes it recovered", _freed > 0, True)
check("and the directory is gone",
      os.path.isdir(os.path.join(_user_root, "app", APP)), False)

# The guard that makes deleting inside flatpak's own store safe at all. A real
# install has a deployment; a download in flight writes the ref first, so it
# looks like one too.
_live = _commit_tree(APP, "e" * 64, root=_user_root)
_link(os.path.join(_user_root, "app", APP, "current"), "x86_64/stable")
check("a real install is left alone", emu_install.remove_flatpak_husk(APP), 0)
check("with its files where they were", os.path.isdir(_live), True)


section("so the uninstall endpoint can finish rather than fail forever")


class _Plugin(main.Plugin):
    """flatpak faked at the runner, which is where its words come back from."""

    def __init__(self, reply):
        self.reply = reply
        self.argv = []

    async def _run_flatpak(self, argv):
        self.argv.append(list(argv))
        return self.reply

    async def refresh_retroarch(self):
        self._install = None
        return {}


def _plugin(reply):
    plugin = _Plugin(reply)
    plugin.loop = LOOP
    plugin._install = None
    return plugin


_real_binary = emu_install.flatpak_binary
emu_install.flatpak_binary = lambda: "/usr/bin/flatpak"
try:
    # The stuck state end to end: flatpak has no ref, the deploy directory is
    # still there, and the user presses Remove.
    _clear(APP, _user_root)
    _stuck = _commit_tree(APP, "f" * 64, root=_user_root)
    check("the husk no longer reads as an install",
          emu_install.flatpak_installed(APP), False)

    _plug = _plugin({"ok": False, "error": "error: No installed refs found for %s" % APP})
    _out = LOOP.run_until_complete(_plug._flatpak_uninstall(APP, True))
    check("removing it reports success rather than flatpak's complaint",
          _out.get("ok"), True)
    check("and the leftover was taken with it", os.path.isdir(_stuck), False)

    # A real failure still is one. Swallowing this would be the worse bug:
    # the emulator is still installed and the user would be told it is not.
    _clear(APP, _user_root)
    _commit_tree(APP, "0" * 64, root=_user_root)
    _link(os.path.join(_user_root, "app", APP, "current"), "x86_64/stable")
    _plug = _plugin({"ok": False, "error": "Error: Failed to uninstall %s: Directory not empty"
                     % APP})
    _out = LOOP.run_until_complete(_plug._flatpak_uninstall(APP, True))
    check("a removal that really failed still says so", _out.get("ok"), False)
    check("with flatpak's reason kept", "Directory not empty" in _out.get("error", ""), True)
    check("and nothing deleted behind it",
          os.path.isdir(os.path.join(_user_root, "app", APP)), True)
finally:
    emu_install.flatpak_binary = _real_binary
    # The scratch home is shared with every file after this one, and a flatpak
    # that never existed sitting in it is somebody else's confusing failure.
    _clear(APP, _user_root)
    LOOP.close()

summary()
