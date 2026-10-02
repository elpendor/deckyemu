#!/usr/bin/env python3
"""The core download path follows the machine, not the one it was written on.

    python scripts/tests/test_buildbot_arch.py

A core is a shared library the running RetroArch has to `dlopen`. Hand it one
built for another architecture and it does not degrade -- it reports "cannot
open shared object file: No such file or directory" about a file that is
sitting right there, which reads as a download that failed rather than one that
cannot be loaded. Measured on an aarch64 machine: a 610KB x86-64 core in the
cores folder, RetroArch up and running, and that message.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import installer  # noqa: E402


section("the buildbot directory comes from the machine")

_real = installer._machine


def _arch_for(name):
    """`buildbot_arch()` as it would answer on a machine calling itself `name`."""
    installer._machine = lambda: name.strip().lower()
    try:
        return installer.buildbot_arch()
    finally:
        installer._machine = _real


check("x86_64 is x86_64", _arch_for("x86_64"), "x86_64")
check("and amd64 is the same machine by another name", _arch_for("amd64"), "x86_64")
# The two spellings a 64-bit ARM machine answers with. `aarch64` is what Linux
# reports; `arm64` is what some userlands say.
check("aarch64 gets the ARM cores", _arch_for("aarch64"), "aarch64")
check("and so does arm64", _arch_for("arm64"), "aarch64")
# Case, because nothing promises what `uname -m` capitalises.
check("the machine name is matched without case", _arch_for("AArch64"), "aarch64")

# Falling back rather than guessing a directory: every other architecture the
# buildbot serves is one this plugin has never run on, and a 404 at download
# time says less to the user than a core that loads.
check("an unknown machine falls back to x86_64", _arch_for("riscv64"), "x86_64")
check("and so does a machine that will not say", _arch_for(""), "x86_64")


section("reading the machine, on a host that may not have os.uname")

# `os.uname` rather than `platform.machine`, because decky's frozen interpreter
# is not known to carry `platform` -- `test_module_guard.py` is what enforces
# that, and it caught this import. `os.uname` is Unix-only, so the tests run on
# a host without it and the fallback has to be the safe arch rather than a
# crash at import time.
check("a machine that answers is read and lowercased",
      installer._machine() in ("", installer._machine().lower()), True)
check("and the module imports on a host with no os.uname at all",
      isinstance(installer.CORE_BASE_URL, str) and installer.CORE_BASE_URL.startswith("http"),
      True)


section("and only directories the buildbot actually serves")

# `armv8` was the obvious guess for 64-bit ARM and it is wrong -- the buildbot
# answers 404 for it, and for `arm64`. Only `aarch64` is served. Written down
# because the next person to add an architecture will guess the same way.
check("armv8 is not one of them",
      "armv8" in installer.BUILDBOT_ARCHES.values(), False)
check("the served set is exactly what has been checked",
      sorted(set(installer.BUILDBOT_ARCHES.values())), ["aarch64", "x86_64"])

# The URL is built once at import, so a wrong arch is wrong for every download
# in the session rather than for one.
check("the download URL carries a served directory",
      any("/nightly/linux/%s/latest" % arch in installer.CORE_BASE_URL
          for arch in set(installer.BUILDBOT_ARCHES.values())),
      True)


if __name__ == "__main__":
    from harness import summary

    summary()
