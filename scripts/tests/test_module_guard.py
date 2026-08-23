#!/usr/bin/env python3
"""py_modules can be shadowed, and the guard against it must cover all of it.

    python scripts/tests/test_module_guard.py

py_modules is *appended* to a sys.path that already holds decky_loader's own
packages, so a module of ours with a generic name resolves to decky's instead --
silently, and only in the parts that use it. `updater.py` cost six rounds of
debugging that way, because the exception never reached the plugin log.

`_check_own_modules` is what turns that into one line at startup, and it used to
work from a hand-written list of every module main.py imports. That list drifted
twice -- eight modules the first time, `diagnostics` the second -- and neither
was noticed, because a guard covering some of the names prints exactly what a
clean run prints. There is nothing to see.

So the list is derived from the directory now, and these checks are about the
derivation: that it finds every module there is, and that a shadowed one is
still reported once it does.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import decky  # noqa: E402  -- the stub, whose logger these checks read
import main  # noqa: E402

section("module shadowing -- the guard covers every name py_modules offers")

_names = main.own_module_names(REPO_ROOT)
_on_disk = {
    entry[:-3] for entry in os.listdir(os.path.join(REPO_ROOT, "py_modules"))
    if entry.endswith(".py") and not entry.startswith(("_", "."))
}

# The drift itself, stated as the property that was false. Both times the list
# went stale it was because a module had been added and nobody edited main.py.
check("every module file in py_modules is a name the guard knows",
      sorted(_on_disk - _names), [])
check("including the ones only another module imports",
      {"sfo", "plugin_base", "steam_shortcuts"} <= _names, True)
# A package, not a file, so it is found by a different branch than the rest.
check("a package counts too", "emulator_catalog" in _names, True)
# `.keep` has no extension and `__pycache__` is not ours; neither is importable.
check("and nothing that is not a module does",
      any(name.startswith(("_", ".")) or "." in name for name in _names), False)


section("module shadowing -- and reports a name that resolved elsewhere")


class _Recorder:
    """Stands in for decky's logger just long enough to read what was logged."""

    def __init__(self):
        self.errors = []

    def error(self, message, *args):
        self.errors.append(message % args)


_real_logger = decky.logger
_recorder = _Recorder()
decky.logger = _recorder
main.decky.logger = _recorder
try:
    # The clean case first: whatever this run has imported is ours, so a guard
    # that reports nothing here is reporting nothing for the right reason.
    main._check_own_modules()
    check("nothing is reported when every import resolved inside the plugin",
          _recorder.errors, [])

    # Now one that did not. A module object whose __file__ points outside the
    # plugin is exactly what a decky package of the same name looks like.
    _victim = sorted(_on_disk)[0]
    _shadow = types.ModuleType(_victim)
    _shadow.__file__ = os.path.join(os.sep, "usr", "lib", "decky_loader", _victim + ".py")
    _was = sys.modules.get(_victim)
    sys.modules[_victim] = _shadow
    try:
        main._check_own_modules()
    finally:
        if _was is None:
            del sys.modules[_victim]
        else:
            sys.modules[_victim] = _was

    check("a shadowed module is reported", len(_recorder.errors), 1)
    # The message has to name the module and where it came from: the whole value
    # of this guard is that it says which name to rename, in the one log anybody
    # reads afterwards.
    check("and the message names it", _victim in _recorder.errors[0], True)
    check("and says where it resolved to instead",
          "decky_loader" in _recorder.errors[0], True)
finally:
    # The suite shares one logger; a file that swaps it must put it back.
    decky.logger = _real_logger
    main.decky.logger = _real_logger


section("the standard library the sandbox actually has")

# The other way an import fails, and it is not shadowing: decky's plugin sandbox
# ships a *trimmed* Python, and a stdlib module that is missing there is not a
# degraded feature -- it is ModuleNotFoundError at import time and the backend
# never starts. `import xml.etree.ElementTree` did exactly that. Nothing on a
# development machine can notice: the host has the whole standard library, every
# test passes, and the first sign is a plugin that will not load.
#
# So the set is recorded rather than reasoned about. Every name in it has been
# seen working on a Deck; a new one has not, and the point of failing here is to
# make somebody check before it ships rather than after. Adding to this list is
# a deliberate act, which is the whole idea.
#
# Only top-level names, because that is the granularity the failure has: `xml`
# is present in the sandbox and `xml.etree` is not, so listing `xml` would have
# allowed the exact import that broke.
PROVEN_STDLIB = frozenset((
    "asyncio", "base64", "collections", "concurrent", "difflib", "functools",
    "glob", "hashlib", "html", "http", "inspect", "io", "json", "os",
    "posixpath", "re", "secrets", "shlex", "shutil", "socket", "ssl", "stat",
    "struct", "subprocess", "sys", "threading", "time", "typing", "urllib",
    "zipfile",
))

import ast  # noqa: E402  -- host-side only, this file never runs on a Deck

_local = {os.path.splitext(name)[0]
          for name in os.listdir(os.path.join(REPO_ROOT, "py_modules"))
          if name.endswith(".py")}
_local |= {name for name in os.listdir(os.path.join(REPO_ROOT, "py_modules"))
           if os.path.isdir(os.path.join(REPO_ROOT, "py_modules", name))}
_local.add("decky")

_sources = [os.path.join(REPO_ROOT, "main.py")]
for _root, _dirs, _names in os.walk(os.path.join(REPO_ROOT, "py_modules")):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    _sources += [os.path.join(_root, n) for n in _names if n.endswith(".py")]

_unproven = {}
for _path in sorted(_sources):
    with open(_path, encoding="utf-8") as _handle:
        _tree = ast.parse(_handle.read(), _path)
    for _node in ast.walk(_tree):
        if isinstance(_node, ast.Import):
            _names = [alias.name for alias in _node.names]
        elif isinstance(_node, ast.ImportFrom):
            # A relative import is one of ours by definition.
            _names = [] if _node.level else [_node.module or ""]
        else:
            continue
        for _name in _names:
            _top = _name.split(".")[0]
            if _top and _top not in _local and _top not in PROVEN_STDLIB:
                _unproven.setdefault(_name, os.path.relpath(_path, REPO_ROOT))

check("nothing imports a module the sandbox has not been shown to have",
      _unproven, {})

# And the guard has to be able to fail, or it is a list nobody maintains that
# reports success for every possible tree.
check("an import outside the list is caught",
      "xml.etree.ElementTree".split(".")[0] in PROVEN_STDLIB, False)


if __name__ == "__main__":
    from harness import summary

    summary()
