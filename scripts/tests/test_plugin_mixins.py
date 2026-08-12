#!/usr/bin/env python3
"""The Plugin class is assembled from mixins, and Python will not warn you.

    python scripts/tests/test_plugin_mixins.py

Five modules contribute methods to one class. If two of them ever define the
same name, the MRO picks the leftmost silently: no error, no warning, and an
endpoint that quietly runs the wrong code. It is the one hazard the split
introduced, and nothing else can see it -- the frontend gets an answer either
way, so the contract check passes and the failure surfaces as a feature
behaving oddly.

Also checks that every mixin is actually mixed in. Writing a module and
forgetting the base class is the other way this arrangement fails, and it fails
as "that endpoint does not exist" at runtime on a Deck.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

section("the Plugin mixins -- one name, one home")

_bases = [cls for cls in main.Plugin.__mro__ if cls is not object]
check("every mixin written is mixed in",
      sorted(cls.__name__ for cls in _bases),
      ["Accounts", "Audit", "Emulators", "Firmware", "PackagedGames", "Plugin",
       "PluginContext"])

# PluginContext is the exception and the only one: it *declares* the shared
# surface every mixin uses and implements none of it, so overlapping with
# Plugin is the whole point rather than a collision. Excluded from the check
# below and given its own, stricter one.
_context = next(cls for cls in _bases if cls.__name__ == "PluginContext")
_owners = {}
for _cls in _bases:
    if _cls is _context:
        continue
    for _name, _value in vars(_cls).items():
        if _name.startswith("__"):
            continue
        _owners.setdefault(_name, []).append(_cls.__name__)

_collisions = {name: owners for name, owners in _owners.items() if len(owners) > 1}
check("no name is defined by more than one of them", _collisions, {})

# Not a tautology: the classes really do contribute, so an empty collision set
# means something.
check("and they contribute enough for that to mean something",
      len(_owners) > 100 and len(_bases) == 7, True)

# The other direction, which is what the declarations are for: everything a
# mixin is promised must actually exist further along the MRO. Without this a
# helper renamed on Plugin leaves PluginContext's stub in place, and the call
# raises NotImplementedError on a Deck instead of failing here.
_declared = {name for name in vars(_context) if not name.startswith("__")}
_unimplemented = sorted(
    name for name in _declared
    if getattr(main.Plugin, name, None) is getattr(_context, name, None)
)
check("every declared helper is implemented by something in the class",
      _unimplemented, [])
check("and the declaration is not empty", len(_declared) > 8, True)

# The frontend reaches these by name through getattr, which is what decky does.
# Covered from the other direction by the contract check in test_backend.py;
# this is the half that proves inheritance is what makes it work.
_instance = main.Plugin()
check("an inherited endpoint resolves on an instance",
      all(callable(getattr(_instance, name, None)) for name in (
          "cheevos_status", "audit_library", "install_emulator",
          "firmware_status", "packaged_game_info")),
      True)


if __name__ == "__main__":
    from harness import summary

    summary()
