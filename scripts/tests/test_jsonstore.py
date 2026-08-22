#!/usr/bin/env python3
"""The plugin's own JSON: written whole or not at all, and read back in shape.

    python scripts/tests/test_jsonstore.py

Seven files were kept by seven copies of the same twelve lines, and the copies
had drifted in the two directions that only show up on a bad day. Both are
checked here because neither is visible in normal use: a settings directory
works exactly the same whether or not a failed write left a `.tmp` beside it,
right up until somebody wonders what those files are.

The read half matters for a different reason. A file that parses but holds the
wrong *shape* -- an object where a list belongs, because somebody edited it by
hand -- used to reach the caller, and the failure was an AttributeError several
frames from the file that caused it.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import jsonstore  # noqa: E402

_DIR = tempfile.mkdtemp(prefix="deckyemu-jsonstore-")


def _path(name):
    return os.path.join(_DIR, name)


def _leftovers():
    """Anything in the scratch directory that is not a file somebody asked for."""
    return sorted(name for name in os.listdir(_DIR) if name.endswith(".tmp"))


section("a write lands whole, or leaves nothing behind")

_settings = _path("settings.json")
jsonstore.write_json(_settings, {"a": 1, "b": [2, 3]})
check("what was written is what comes back",
      jsonstore.read_json(_settings, {}), {"a": 1, "b": [2, 3]})
check("and nothing is left beside it", _leftovers(), [])

# The failure the copies disagreed about. A payload that will not serialise
# raises part way through the write, and six of the seven left the temporary
# file sitting in the settings directory forever -- nothing reads it, nothing
# replaces it, and it is named after a real file so it looks like one.
_broken = _path("broken.json")
try:
    jsonstore.write_json(_broken, {"fine": 1, "not": object()})
    _raised = ""
except Exception as error:  # noqa: BLE001 -- the type is what is being checked
    _raised = type(error).__name__

check("a payload that cannot be serialised still fails", _raised, "TypeError")
check("but leaves no half-written file behind", _leftovers(), [])
check("and does not create the file it was asked to write",
      os.path.exists(_broken), False)

# Replacing is the ordinary case and must not lose the old file when the new
# one cannot be written: the rename is the last thing that happens.
jsonstore.write_json(_settings, {"kept": True})
try:
    jsonstore.write_json(_settings, {"bad": object()})
except TypeError:
    pass
check("a failed rewrite leaves the previous contents intact",
      jsonstore.read_json(_settings, {}), {"kept": True})
check("and still no leftovers", _leftovers(), [])


section("a read gives back the shape that was asked for")

_wrong = _path("wrong-shape.json")
with open(_wrong, "w", encoding="utf-8") as _handle:
    json.dump(["not", "a", "mapping"], _handle)
check("a list where a dict belongs falls back", jsonstore.read_json(_wrong, {}), {})

with open(_wrong, "w", encoding="utf-8") as _handle:
    json.dump({"not": "a list"}, _handle)
check("and a dict where a list belongs falls back", jsonstore.read_json(_wrong, []), [])

# The shape being right is not the same as the shape being non-empty.
with open(_wrong, "w", encoding="utf-8") as _handle:
    json.dump({}, _handle)
check("an empty file of the right shape is not a fallback",
      jsonstore.read_json(_wrong, {"default": True}), {})

_torn = _path("torn.json")
with open(_torn, "w", encoding="utf-8") as _handle:
    _handle.write('{"half writ')
check("a truncated file falls back rather than raising",
      jsonstore.read_json(_torn, {"safe": True}), {"safe": True})

check("so does a file that is not there at all",
      jsonstore.read_json(_path("never-existed.json"), []), [])


section("the directory is made, and the mode is asked for rather than assumed")

_nested = os.path.join(_DIR, "made", "up", "path", "deep.json")
jsonstore.write_json(_nested, {"deep": True})
check("a write creates the directories it needs",
      jsonstore.read_json(_nested, {}), {"deep": True})

# Only the caller holding credentials asks for this, and the check is that the
# flag reaches the file rather than that any particular mode results -- the
# suite runs on Windows too, where st_mode says something else entirely.
_private = _path("private.json")
jsonstore.write_json(_private, {"token": "not a real one"}, private=True)
check("a private write still round-trips",
      jsonstore.read_json(_private, {}), {"token": "not a real one"})
if os.name == "posix":
    check("and is readable only by its owner",
          oct(os.stat(_private).st_mode & 0o777), "0o600")
else:
    print("SKIP file modes are not POSIX here")

# The record files -- what firmware went where, which content id a game came
# from -- are sorted so that a diff between two of them reads as what changed
# rather than as everything having moved.
_sorted = _path("sorted.json")
jsonstore.write_json(_sorted, {"b": 1, "a": 2}, sort_keys=True)
with open(_sorted, encoding="utf-8") as _handle:
    _order = list(json.load(_handle))
check("sort_keys is honoured, so a diff of a record file is readable",
      _order, ["a", "b"])


if __name__ == "__main__":
    summary()
