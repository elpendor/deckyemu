#!/usr/bin/env python3
"""Reading Steam's shortcuts.vdf, which is the only record a reset leaves.

    python scripts/tests/test_steam_shortcuts.py

The registry and the launcher scripts are both the plugin's, and a reset
deletes both. Steam's shortcuts survive it, so after a reset they are the only
evidence that twenty games were ever added -- and the audit could not see them,
because every check it makes starts from a registry entry.

The bytes here are built rather than copied from a device: a fixture taken off a
real Deck would carry that person's library, and the format is small enough to
write. The shapes that matter are the ones a real file actually contains --
mixed key casing between Steam versions, quoted and unquoted paths, and an
appid whose top bit is set, which is every non-Steam shortcut.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "py_modules"))

import launchers  # noqa: E402
import steam_shortcuts  # noqa: E402

section("shortcuts.vdf -- the half of the library a reset does not touch")


def _string(key, value):
    return b"\x01" + key.encode() + b"\x00" + value.encode() + b"\x00"


def _int(key, value):
    return b"\x02" + key.encode() + b"\x00" + struct.pack("<I", value)


def _entry(index, fields):
    return b"\x00" + str(index).encode() + b"\x00" + b"".join(fields) + b"\x08"


def _file(*entries):
    body = b"".join(_entry(i, fields) for i, fields in enumerate(entries))
    return b"\x00shortcuts\x00" + body + b"\x08\x08"


LAUNCHER_DIR = launchers.LAUNCHER_DIR

# Capitalised keys, as older clients wrote them.
_OLD = [_int("appid", 3740231350), _string("AppName", "Super Mario 3D World"),
        _string("Exe", os.path.join(LAUNCHER_DIR, "smw-e29cf16c.sh"))]
# Lowercase, as the client on the test device writes them. A reader that
# matched one casing found nothing at all on a client that used the other.
_NEW = [_int("appid", 2861890934), _string("appname", "Wind Waker HD"),
        _string("exe", '"%s"' % os.path.join(LAUNCHER_DIR, "ww-a8924350.sh"))]
# Somebody else's shortcut. Never ours, whatever it is called.
_FOREIGN = [_int("appid", 1234567890), _string("appname", "Super Mario 3D World"),
            _string("exe", "/usr/bin/retroarch")]

_parsed = steam_shortcuts.parse_shortcuts(_file(_OLD, _NEW, _FOREIGN))
check("every shortcut is read", len(_parsed), 3)
check("keys are matched whatever their casing", _parsed[0].get("appname"),
      "Super Mario 3D World")
check("and so are the lowercase ones", _parsed[1].get("appname"), "Wind Waker HD")

# Steam stores the appid as a signed int32 and every non-Steam id has the top
# bit set. Read signed, they come back negative and match nothing in the
# registry -- so every shortcut would be reported as one we do not know.
check("a high appid survives the round trip", _parsed[0].get("appid"), 3740231350)
check("and is not read as negative", _parsed[1].get("appid") > 0, True)


# ------------------------------------------------------------------ ownership

import tempfile  # noqa: E402

# A real file in a real place: reading it is half of what `ours` does, and a
# stubbed `open` would have tested the half that was already covered above.
_tmp = tempfile.mkdtemp(prefix="deckyemu-shortcuts-")
_vdf = os.path.join(_tmp, "shortcuts.vdf")
with open(_vdf, "wb") as _handle:
    _handle.write(_file(_OLD, _NEW, _FOREIGN))

# One of the two launchers exists and one does not, which is the distinction the
# whole cleanup rests on: a shortcut whose script was deleted cannot launch.
os.makedirs(LAUNCHER_DIR, exist_ok=True)
with open(os.path.join(LAUNCHER_DIR, "smw-e29cf16c.sh"), "w", encoding="utf-8") as _handle:
    _handle.write("#!/bin/sh\n")

_real_files = steam_shortcuts.shortcuts_files
steam_shortcuts.shortcuts_files = lambda: [_vdf]
_ours = steam_shortcuts.ours()
steam_shortcuts.shortcuts_files = _real_files

check("only shortcuts pointing into our launcher directory are ours", len(_ours), 2)
# The foreign entry shares a name with one of ours on purpose. Matching on the
# name would have offered to delete a real Steam game.
check("a shortcut with the same name but another exe is left alone",
      [item["title"] for item in _ours], ["Super Mario 3D World", "Wind Waker HD"])
check("a quoted path is unquoted", _ours[1]["launcher"], "ww-a8924350.sh")
check("the appid comes through for the frontend to act on", _ours[0]["app_id"], 3740231350)
# The distinction the cleanup rests on. One of these scripts was written above
# and the other never existed: a shortcut whose script is gone cannot launch, so
# it is dead rather than merely untracked, and only one of those is safe to
# offer for deletion without qualification.
check("a launcher still on disk is seen", _ours[0]["launcher_exists"], True)
check("and one that is gone is reported as missing", _ours[1]["launcher_exists"], False)


# --------------------------------------------- entries pointing somewhere else

# The other direction, and the one nothing asked. Every check in the audit
# starts from a registry entry and asks whether the *files* it names are still
# there; whether the Steam shortcut it claims is still that game was never
# tested, though the appid and the executable are written down side by side in
# the file read above.
#
# It matters because Steam reuses the appids of deleted shortcuts. An entry can
# come to name an id that is now another game, and then editing this game
# rewrites that one and removing it deletes it. The frontend cannot see any of
# this: from there a shortcut's executable is not readable at all, so an app
# existing under that id looks like agreement.
import plugin_audit  # noqa: E402

steam_shortcuts.shortcuts_files = lambda: [_vdf]

_library = {
    # Correct: the appid and the launcher are the pair the file records.
    "3740231350": {
        "app_id": 3740231350, "title": "Super Mario 3D World",
        "launcher_path": os.path.join(LAUNCHER_DIR, "smw-e29cf16c.sh"),
    },
    # Wrong: this id belongs to the Wind Waker shortcut now.
    "2861890934": {
        "app_id": 2861890934, "title": "Metroid Prime",
        "launcher_path": os.path.join(LAUNCHER_DIR, "prime-11112222.sh"),
    },
    # An id Steam's file says nothing about -- a real Steam game, or a shortcut
    # not written out yet. Neither is something to report: the first is not ours
    # to comment on and the second would appear for a moment after every add.
    "999": {
        "app_id": 999, "title": "Just Added",
        "launcher_path": os.path.join(LAUNCHER_DIR, "just-added-33334444.sh"),
    },
}

_mispointed = plugin_audit.Audit._mispointed_entries(_library)
check("an entry whose id runs another game is found", len(_mispointed), 1)
check("and it is the one that disagrees", _mispointed[0]["title"], "Metroid Prime")
# So the report can name the game that would have been rewritten, which is the
# whole reason this is not simply "forget it".
check("the game it actually points at is named", _mispointed[0]["runs_title"], "Wind Waker HD")
check("an entry pointing at its own launcher is not reported",
      [item["app_id"] for item in _mispointed], [2861890934])
check("nor is one Steam's file has never heard of",
      any(item["app_id"] == 999 for item in _mispointed), False)
check("and a library with nothing wrong reports nothing",
      plugin_audit.Audit._mispointed_entries({"3740231350": _library["3740231350"]}), [])

steam_shortcuts.shortcuts_files = _real_files


# ------------------------------------------------------------------- damage

# A cleanup screen that raises is worse than one that offers nothing: the file
# belongs to Steam and may be mid-write, truncated, or from a version that
# writes something unfamiliar.
check("a truncated file yields nothing rather than raising",
      steam_shortcuts.parse_shortcuts(_file(_OLD)[:20]), [])
check("an empty file is not an error", steam_shortcuts.parse_shortcuts(b""), [])
check("a file with no shortcuts map is not an error",
      steam_shortcuts.parse_shortcuts(b"\x00other\x00\x08\x08"), [])


if __name__ == "__main__":
    from harness import summary

    summary()
