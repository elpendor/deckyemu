#!/usr/bin/env python3
"""Assert that a release bundle contains no development-only code.

    python scripts/check_release_build.py

This exists because the guarantee it checks was already false once. The build
stamp used to be prepended to the output with rollup's `intro`, which happens
after tree-shaking -- so `IS_DEV_BUILD && <DevPanel/>` could never be folded
away, and a release build shipped the entire Reset panel, unreachable but
present. Nothing said so. The fix was to substitute the stamp in the source
instead; this is what stops it regressing.

"Unreachable" is not the bar. The Reset panel deletes save games, and the only
acceptable state of it in a published build is absent.

Python rather than the shell script this replaces: `npm run check` runs it, and
on Windows `bash` resolves to WSL, which cannot see the repository. A check that
only runs on some machines is one people learn to skip.

Leaves dist/ holding a development build, since that is what a working tree
should have.
"""

import os
import re
import subprocess
import sys

# One per development-only feature: a label the user would see, and the RPC
# name behind it.
FORBIDDEN = (
    "Forget everything the plugin knows",
    "dev_reset",
    "deckyemu batch test hook",
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Each build's panel. One rollup run builds both.
BUNDLES = {
    "service": os.path.join(REPO_ROOT, "dist", "deckyemu.js"),
    "plugin": os.path.join(REPO_ROOT, "plugin", "dist", "index.js"),
}


def build(stamp):
    """Bundle with DECKYEMU_BUILD set to `stamp`. Returns each bundle's text."""
    environment = dict(os.environ)
    if stamp:
        environment["DECKYEMU_BUILD"] = stamp
    else:
        environment.pop("DECKYEMU_BUILD", None)
    subprocess.run(
        ["npx", "rollup", "-c"],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        stdout=subprocess.DEVNULL,
        # rollup writes its progress to stderr; only a failure is interesting.
        stderr=subprocess.DEVNULL,
        shell=os.name == "nt",
    )
    texts = {}
    for kind, path in BUNDLES.items():
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            texts[kind] = handle.read()
    return texts


def main():
    failed = False

    print("Building release bundles...")
    releases = build("0" * 40)
    for kind, release in releases.items():
        for needle in FORBIDDEN:
            if needle in release:
                print("FAIL: %s release bundle contains development-only code: %s" % (kind, needle))
                failed = True
            else:
                print("ok: absent from %s release bundle -- %s" % (kind, needle))

    # Steam cannot resolve a bare import of the loader's library; the plugin
    # build has to have turned every one into a read of its global.
    if re.search(r"""from\s*['"]@decky/ui['"]""", releases["plugin"]):
        print("FAIL: plugin release bundle imports @decky/ui by name; Steam cannot load it")
        failed = True
    else:
        print("ok: no bare @decky/ui import in the plugin release bundle")

    # The inverse, so a passing run cannot be the result of the strings having
    # been renamed or the panel deleted. Both halves have to be true for the
    # check to mean anything.
    print("Building development bundles...")
    for kind, development in build("").items():
        for needle in FORBIDDEN:
            if needle in development:
                print("ok: present in %s development bundle -- %s" % (kind, needle))
            else:
                print("FAIL: %s development bundle is missing %s -- this check is testing nothing"
                      % (kind, needle))
                failed = True

    if failed:
        return 1
    print("Release bundles are clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
