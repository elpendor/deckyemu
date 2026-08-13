#!/usr/bin/env python3
"""What settings.json is allowed to hold, and who may read it.

    python scripts/tests/test_settings_store.py

Two properties, both about the same file. It holds the SteamGridDB key, the
GitHub token and the RetroAchievements Connect token -- which is
password-equivalent -- so it is written 0600, the way the override config that
carries that same token already is. And it takes only settings that exist, so a
dict arriving from outside cannot fill it with keys nothing reads.
"""

import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import store  # noqa: E402

section("the file holding the tokens is not readable by anyone else")

store.set_settings({"collection_name": "Shelf"})
if os.name == "posix":
    _mode = stat.S_IMODE(os.stat(store.SETTINGS_PATH).st_mode)
    check("settings.json is 0600", oct(_mode), oct(0o600))
    # Not a secret, but it records where every ROM on the device lives, and one
    # rule for the pair is one fewer thing to get wrong when a writer is added.
    store.remember_game(1, {"title": "x"})
    check("and so is library.json",
          oct(stat.S_IMODE(os.stat(store.LIBRARY_PATH).st_mode)), oct(0o600))
else:
    print("SKIP file modes are POSIX-only; this run is on %s" % os.name)

section("only settings that exist are written")

_kept, _dropped = store.known_only({"hide_osd": "all", "hide_OSD": "all", "x": 1})
check("a known key is kept", _kept, {"hide_osd": "all"})
# The everyday case this catches, not the hostile one: a misspelt key is written
# and then never read, which is indistinguishable from the setting not working.
check("a misspelling is not", sorted(_dropped), ["hide_OSD", "x"])
check("nothing in, nothing out", store.known_only(None), ({}, []))

# Every key the plugin writes has to be declared, or startup would be dropping
# its own state. launcher_format was exactly that: written and read for
# migrations, and missing from DEFAULT_SETTINGS until this check existed.
_written = set()
for _name in ("main.py", os.path.join("py_modules", "plugin_accounts.py"),
              os.path.join("py_modules", "plugin_emulators.py")):
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), _name), encoding="utf-8") as _handle:
        _source = _handle.read()
    import re as _re
    for _match in _re.finditer(r'store\.set_settings,\s*\{([^}]*)\}', _source):
        _written.update(_re.findall(r'"([a-z_]+)"\s*:', _match.group(1)))
check("every setting the backend writes is declared in DEFAULT_SETTINGS",
      sorted(_written - set(store.DEFAULT_SETTINGS)), [])
check("and the scan found some, so it is testing something", len(_written) > 3, True)


if __name__ == "__main__":
    summary()
