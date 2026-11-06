"""The loader is named only in the plugin build's own layer.

    python scripts/tests/test_host_confinement.py

One tree builds both the standalone service and the loader plugin. Everything
loader-specific lives under plugin/; the shared code and the service's own
files are written for either host and name neither. This is what keeps it so:
a shared file that reaches for the loader quietly makes the service depend on
it. The service's built bundles are checked too, when they are there, since an
import that slipped through would show in them first.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section, summary  # noqa: E402

#: The loader, by any of the names it goes by in code. "DeckyEmu" is ours.
NAMED = re.compile(r"decky(?!emu)|pluginloader|homebrew/plugins", re.IGNORECASE)

SHARED = ("main.py", "service.py", "launcher.py", "rescue.sh", "install.sh", "py_modules", "src")
BUNDLES = (os.path.join("dist", "preload.js"), os.path.join("dist", "deckyemu.js"))


def _files(path):
    full = os.path.join(REPO_ROOT, path)
    if os.path.isfile(full):
        yield full
        return
    for top, dirs, names in os.walk(full):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
        for name in names:
            if name.endswith((".py", ".ts", ".tsx", ".sh", ".js", ".css")):
                yield os.path.join(top, name)


def _naming(paths):
    found = []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if NAMED.search(line):
                    found.append("%s:%d" % (os.path.relpath(path, REPO_ROOT), number))
    return found


section("the shared code and the service name no loader")

_shared = [path for root in SHARED for path in _files(root)]
check("there is shared code to read", len(_shared) > 100, True)
check("none of it names the loader", _naming(_shared), [])

_built = [os.path.join(REPO_ROOT, path) for path in BUNDLES if os.path.isfile(os.path.join(REPO_ROOT, path))]
check("nor do the service's bundles, when built", _naming(_built), [])

section("the plugin's layer is where it is named")

check("which the check would see", bool(_naming(_files(os.path.join("plugin", "src")))), True)


if __name__ == "__main__":
    summary()
