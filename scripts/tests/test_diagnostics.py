#!/usr/bin/env python3
"""A diagnostic report carries what a bug needs and none of what it does not.

    python scripts/tests/test_diagnostics.py

This text is written to be pasted into a public issue by somebody who cannot
read it first -- there is no terminal on the device and the report is long. So
what it must never contain is not a matter of care at the call site; it is the
job of the module, and these are the checks that say so.

The settings file holds a SteamGridDB key, a RetroAchievements token that is
password-equivalent, and the transfer token. Any of them could also have reached
the log by some other route, which is why they are struck out of the whole
report by value rather than merely omitted from the settings section.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402
import diagnostics  # noqa: E402
import store  # noqa: E402

# Fabricated to the shape each check looks for and nothing more -- a real key of
# any kind has no place in this tree, and a made-up one exercises every path.
_SGDB = "abcdef0123456789abcdef0123456789"
_CHEEVOS = "NOTAREALCONNECTTOKEN0000"
_TRANSFER = "nOtaReAlTrAnSfErToKeN12"
_ZRIF = "KO5ifNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREAL"

store.set_settings({
    "sgdb_api_key": _SGDB,
    "cheevos_token": _CHEEVOS,
    "transfer_token": _TRANSFER,
    "cheevos_username": "somebody",
    "collection_name": "DeckyEmu",
    "hide_osd": "all",
})

# A log holding every kind of thing that must not travel: each secret by value,
# and a shape this plugin does not hold and so cannot strike out by value.
os.makedirs(decky.DECKY_PLUGIN_LOG_DIR, exist_ok=True)
_LOG = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "deckyemu.log")
with open(_LOG, "w", encoding="utf-8") as _handle:
    _handle.write(
        "\n".join(
            [
                "[INFO]: DeckyEmu starting",
                "[INFO]: sgdb request with key %s" % _SGDB,
                "[INFO]: cheevos token=%s" % _CHEEVOS,
                "[INFO]: installing with --zrif %s" % _ZRIF,
                "[INFO]: password: hunter2seventeen",
                "[INFO]: Rebuilt 3 launcher(s), skipped 0",
            ]
        )
        + "\n"
    )

_LIBRARY = {
    "1": {"app_id": 1, "title": "A Private Game", "platform": "SNES", "collection": "x"},
    "2": {"app_id": 2, "title": "Another One", "platform": "SNES", "collection": "x"},
    "3": {"app_id": 3, "title": "A Third", "platform": "N64", "collection": "y"},
}

_REPORT = diagnostics.build(
    {"version": "1.2.3", "build": "abc1234", "built_at": "2026-01-01"},
    {"kind": "flatpak", "exe": "/usr/bin/flatpak", "scope": "user"},
    [{"id": "pcsx2", "kind": "flatpak", "target": "net.pcsx2.PCSX2"}],
    _LIBRARY,
    ["vita3k (appimage)"],
)


section("nothing that unlocks anything leaves the device")

for _name, _secret in (
    ("the SteamGridDB key", _SGDB),
    ("the RetroAchievements token", _CHEEVOS),
    ("the transfer token", _TRANSFER),
):
    check("%s is not in the report" % _name, _secret in _REPORT, False)
# It reached the log from a path this plugin does not store, so no value could
# have struck it out -- the shape has to.
check("nor is a licence key that only ever appeared in the log",
      _ZRIF in _REPORT, False)
check("nor is anything the log called a password",
      "hunter2seventeen" in _REPORT, False)
# Struck out rather than dropped: a reader has to be able to tell that a line
# was edited, or the report reads as though nothing was there.
check("and what went is visible as having gone",
      diagnostics.REDACTED in _REPORT, True)

# The allowlist is the reason a setting added later is absent until somebody
# lists it, rather than exported until somebody notices.
check("settings are reported from an allowlist",
      all(key in diagnostics.REPORTED_SETTINGS for key in ("hide_osd", "art_source")), True)
check("and no secret is on it",
      [key for key in diagnostics.SECRET_SETTINGS if key in diagnostics.REPORTED_SETTINGS], [])
check("a secret is reported as set, which is the useful half",
      "set" in _REPORT.split("sgdb_api_key")[1][:20], True)


section("and the user's library is not somebody else's business")

# Which systems, and how many, is what a bug turns on. What the games are called
# is theirs, and this text is going somewhere public.
for _title in ("A Private Game", "Another One", "A Third"):
    check("the title %r is not in the report" % _title, _title in _REPORT, False)
check("but the count is", "3 game(s)" in _REPORT, True)
check("and so are the systems", "SNES" in _REPORT and "N64" in _REPORT, True)


section("what a bug actually needs is there")

for _label, _wanted in (
    ("the plugin version", "1.2.3"),
    ("the build it came from", "abc1234"),
    ("how RetroArch is installed", "flatpak"),
    ("which emulators are registered", "pcsx2"),
    ("which are installed from the catalog", "vita3k (appimage)"),
    ("and the tail of the log", "Rebuilt 3 launcher(s)"),
):
    check("%s is reported" % _label, _wanted in _REPORT, True)


section("the page it is served on cannot be broken by the report")

# The report is a log tail and can hold anything, including the closing tag of
# the element it is written into.
_PAGE = diagnostics.as_page("</textarea><script>alert(1)</script>")
check("a closing tag in the report does not close the element",
      "</textarea><script>alert(1)" in _PAGE, False)
check("and the escape survives as data", "<\\/textarea>" in _PAGE, True)
check("the page still carries the report", "document.querySelector" in _PAGE, True)


section("a missing log is a line, not a failure")

os.remove(_LOG)
check("the report is still built", "DeckyEmu diagnostic report" in
      diagnostics.build({}, None, [], {}), True)
check("and says there was no log",
      "No log file found." in diagnostics.build({}, None, [], {}), True)
# RetroArch absent is a normal state -- the emulator catalog is the whole reason
# a Deck can have none -- so it reports as such rather than as an error.
check("RetroArch being absent is reported plainly",
      "not found" in diagnostics.build({}, None, [], {}), True)


if __name__ == "__main__":
    summary()
