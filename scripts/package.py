#!/usr/bin/env python3
"""Lay out one build of DeckyEmu, ready to pack, under <out>/deckyemu/.

    python scripts/package.py service <out>
    python scripts/package.py plugin <out>

Both builds share the backend and the panel. The service adds its own runner,
launcher and Steam injection, and bundles from dist/. The plugin swaps in its
own `appenv` and `buildhost` from plugin/py_modules, adds its loader-only
modules, and ships plugin/dist/index.js as dist/index.js with plugin.json; the
service's own modules stay out of it. Run after `rollup -c`, which builds both.

One top-level folder either way: selfupdate unpacks that shape, and the loader
names a plugin's settings after its folder.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: In both builds.
COMMON = ("main.py", "package.json", "assets", "bin")

#: Python modules only the service runs.
SERVICE_ONLY = ("cdp.py", "injector.py", "rescue.py", "selfupdate.py", "hostcalls.py")

#: What must be there, or the package is not worth shipping.
REQUIRED = {
    "service": ("service.py", "launcher.py", "rescue.sh", "main.py", "py_modules/appenv.py",
                "py_modules/buildhost.py", "dist/preload.js", "dist/deckyemu.js", "assets/game-icon.png"),
    "plugin": ("plugin.json", "main.py", "py_modules/appenv.py", "py_modules/buildhost.py",
               "py_modules/handoff.py", "dist/index.js", "assets/game-icon.png"),
}


def _copy(source, dest):
    source = os.path.join(ROOT, source)
    if os.path.isdir(source):
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    elif os.path.isfile(source):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(source, dest)


def lay_out(kind, out):
    """Build `kind` under `out/deckyemu`; returns that folder."""
    target = os.path.join(out, "deckyemu")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    for name in COMMON:
        _copy(name, os.path.join(target, name))
    modules = os.path.join(target, "py_modules")
    _copy("py_modules", modules)

    if kind == "service":
        for name in ("service.py", "launcher.py", "rescue.sh", "install.sh"):
            _copy(name, os.path.join(target, name))
        for name in ("preload.js", "deckyemu.js"):
            _copy(os.path.join("dist", name), os.path.join(target, "dist", name))
    elif kind == "plugin":
        for name in SERVICE_ONLY:
            os.remove(os.path.join(modules, name))
        overlay = os.path.join(ROOT, "plugin", "py_modules")
        for name in sorted(os.listdir(overlay)):
            if name.endswith(".py"):
                shutil.copy2(os.path.join(overlay, name), os.path.join(modules, name))
        _copy(os.path.join("plugin", "plugin.json"), os.path.join(target, "plugin.json"))
        _copy(os.path.join("plugin", "dist", "index.js"), os.path.join(target, "dist", "index.js"))
    else:
        raise SystemExit("unknown build %r: service or plugin" % kind)

    missing = [name for name in REQUIRED[kind] if not os.path.isfile(os.path.join(target, name))]
    if missing:
        raise SystemExit("the %s package is missing %s" % (kind, ", ".join(missing)))
    for name in ("rescue.sh", "install.sh"):
        path = os.path.join(target, name)
        if os.path.exists(path):
            os.chmod(path, 0o755)
    return target


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(lay_out(sys.argv[1], sys.argv[2]))
