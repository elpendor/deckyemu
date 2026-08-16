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

from harness import TMP, check, section, summary  # noqa: E402

import decky  # noqa: E402
import diagnostics  # noqa: E402
import releases  # noqa: E402
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
    "cheevos_username": "somebodyknown",
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
                # Exactly what main.py writes. A fixture tidier than the real
                # log would let every check below pass on a report that still
                # leaks in production.
                "[INFO]: prepare_shortcut: title='A Private Game' core=bsnes "
                "rom=/home/deck/deckyemu/roms/snes/A Private Game (USA).sfc",
                "[INFO]: register_game: app_id=1 title='A Private Game'",
                "[INFO]: probe_rom: /home/deck/deckyemu/transfer/A Private Game (USA).sfc",
                "[WARNING]: GET failed for https://www.steamgriddb.com/api/v2/"
                "search/autocomplete/A%20Private%20Game: timed out",
                # A live token in a URL, which is what stage_update logs.
                "[INFO]: Staged 1.2.3 for decky at "
                "http://127.0.0.1:41234/tHiSiSaLiVeToKeN123456/deckyemu.zip",
                # Verbatim from a real device. Synthetic fixtures missed both
                # of these: the token here is a bare request path, which no URL
                # rule matches, and the filename is the game's name in a form
                # the registry cannot supply -- what it records for an installed
                # title is the eboot the emulator boots, not the package sent.
                "[INFO]: Received gravity rush.pkg (1522876960 bytes) into "
                "/home/deck/deckyemu/transfer",
                "[INFO]: fileserver: \"PUT /GcMnhBhWcdNuNWo7EY_aVg/upload/"
                "gravity%20rush.pkg HTTP/1.1\" 200 -",
                # What Vita3K prints while installing a package, immediately
                # before it copies the licence into place. Undocumented, and key
                # material beside a licence copy is not something to publish on
                # a guess.
                "[INFO]: vita3k: ef3e7908494127ae52a8ebc030f2007c	"
                "fececc0a30fd7771d4606d36a00472f8",
                "[INFO]: vita3k: [copy_license]: Success copy license file to: "
                "\"/home/deck/.local/share/Vita3K/Vita3K/ux0/license/app/"
                "PCSA00011/UP9000-PCSA00011_00-GRAVITYRUSH000000.rif\"",
                "[INFO]: Wrote launcher /home/deck/homebrew/data/deckyemu/"
                "launchers/a-private-game-6ac73bd4.sh",
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
    "1": {
        "app_id": 1, "title": "A Private Game", "platform": "SNES", "collection": "x",
        "rom_path": "/home/deck/deckyemu/roms/snes/A Private Game (USA).sfc",
        # A real entry carries this, and the name is a slug of the title.
        "launcher_path":
            "/home/deck/homebrew/data/deckyemu/launchers/a-private-game-6ac73bd4.sh",
    },
    "2": {"app_id": 2, "title": "Another One", "platform": "SNES", "collection": "x"},
    "3": {"app_id": 3, "title": "A Third", "platform": "N64", "collection": "y"},
}

# An inbox holding the package that was sent, which is how its name reaches the
# log at all.
_INBOX = os.path.join(TMP, "inbox")
os.makedirs(_INBOX, exist_ok=True)
with open(os.path.join(_INBOX, "gravity rush.pkg"), "wb") as _handle:
    _handle.write(b"PKG")
# Whatever else is lying in the inbox, including something whose name is an
# ordinary word that appears in the report's own instructions.
with open(os.path.join(_INBOX, "template.js"), "wb") as _handle:
    _handle.write(b"// not a game")

_REPORT = diagnostics.build(
    {"version": "1.2.3", "build": "abc1234", "built_at": "2026-01-01"},
    {"kind": "flatpak", "exe": "/usr/bin/flatpak", "scope": "user"},
    [{"id": "pcsx2", "kind": "flatpak", "target": "net.pcsx2.PCSX2"}],
    _LIBRARY,
    ["vita3k (appimage)"],
    ["GcMnhBhWcdNuNWo7EY_aVg"],
    _INBOX,
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
# The rule for this went in without a check, and shipped inert: a shell turned
# its `` into a real backspace on the way into the file, so it compiled, type
# checked, and matched nothing. Only a real device noticed.
check("nor a long run of hex an emulator printed",
      "ef3e7908494127ae52a8ebc030f2007c" in _REPORT, False)
# Struck out rather than dropped: a reader has to be able to tell that a line
# was edited, or the report reads as though nothing was there.
check("and what went is visible as having gone",
      diagnostics.REDACTED in _REPORT, True)

# A token in a URL path is how both of this plugin's own servers address
# themselves, and neither is in the settings -- so no value could strike them.
# The transfer one is live on the network at the moment the report is read.
check("a token in a URL path does not travel",
      "tHiSiSaLiVeToKeN123456" in _REPORT, False)
check("though which host it was still does",
      "http://127.0.0.1:41234/" in _REPORT, True)
# The form the shape rule cannot see: a logged request line is a bare path, with
# no scheme and host in front of the token. It is also the token of the very
# server handing the report out, so it is live while somebody reads it. Struck
# by value instead, from what the server has in memory.
check("a token logged as a bare request path goes too",
      "GcMnhBhWcdNuNWo7EY_aVg" in _REPORT, False)

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
# The half that was wrong. Leaving the library section out did not stop the log
# naming games: prepare_shortcut logs the title and the path, register_game logs
# the title, probe_rom logs the path, and a failed artwork lookup logs a URL
# with the name in it -- four lines in this fixture, while the dialog offering
# the report promised no game titles.
check("nor is it in the log the report carries",
      "prepare_shortcut: title='[removed]'" in _REPORT, True)
check("nor is the path a ROM was filed at",
      "roms/snes/A Private Game" in _REPORT, False)
check("nor the name inside an artwork lookup that failed",
      "autocomplete/A%20Private%20Game" in _REPORT, False)
# The account name is not a secret and is not the user's to have published
# either.
# The registry could not supply this one: what it records for an installed Vita
# title is the eboot the emulator boots, so the name of the package that was
# sent is only knowable from the inbox it is still sitting in.
check("the name of a file waiting in the inbox is not published",
      "gravity rush" in _REPORT.lower(), False)
# The launcher is named after the title, slugified. Striking the title does not
# touch it, and "Wrote launcher .../a-private-game-6ac73bd4.sh" names the game
# as surely as the title does.
check("nor the launcher named after it",
      "a-private-game" in _REPORT, False)
# And squashed, which is how a title appears inside a Vita content id.
check("nor the title squashed into a content id",
      "APRIVATEGAME" in _REPORT.upper().replace("[REMOVED]", ""), False)
check("and neither is the RetroAchievements username",
      "somebodyknown" in _REPORT, False)
check("but the count is", "3 game(s)" in _REPORT, True)
check("and so are the systems", "SNES" in _REPORT and "N64" in _REPORT, True)


section("and it says where it is meant to go")

# The report is read on a phone, away from the device that made it, by somebody
# who then has to find the repository. Both ends carry the address so neither
# has to be remembered.
check("the report names the issue form", diagnostics.NEW_ISSUE_URL in _REPORT, True)
check("and the page offers it as a link",
      diagnostics.NEW_ISSUE_URL in diagnostics.as_page(_REPORT), True)
# It goes through the same redaction as everything else, and the rules that
# strike tokens out of URLs and stems out of filenames both have opinions about
# a URL. An address the reader cannot use is worse than no address.
check("which survives the redaction intact",
      "github.com/elpendor/deckyemu/issues/new" in _REPORT, True)
# It survives because it is added after the redaction rather than put through
# it. A `template.js` sitting in the inbox put "template" on the strike list and
# the address came out as `?[removed]=bug_report.yml` -- a report telling its
# reader to visit a URL that does not exist.
check("even with a file in the inbox named after a word in it",
      "?template=bug_report.yml" in _REPORT, True)
check("and is built from the repository the updater reads",
      diagnostics.NEW_ISSUE_URL.startswith("https://github.com/%s/" % releases.REPO), True)


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


section("a log that has grown is read from the end, not swallowed whole")

# `_run_emulator_tool` streams every line an emulator prints, and Vita3K's
# installer prints one per file in the package -- so one large game writes
# thousands of lines and the file is not the few hundred kilobytes an earlier
# version of this assumed. Reading all of it to keep the last two hundred is
# work that grows with how much somebody has installed.
_BIG = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "big.log")
with open(_BIG, "w", encoding="utf-8") as _handle:
    for _line in range(120000):
        # A plain "\n" in text mode, which Python turns into whatever this
        # platform uses. Writing `os.linesep` here instead gets translated a
        # second time on Windows, producing "\r\r\n" -- and `splitlines` counts
        # that stray carriage return as a line of its own.
        _handle.write("[INFO]: vita3k: [install_pkg]: sce_sys/manual/%d.png\n" % _line)
check("the log really is bigger than the cap",
      os.path.getsize(_BIG) > diagnostics.TAIL_BYTES * 4, True)
_tail = diagnostics._log_tail()
check("only the last lines are kept", len(_tail.splitlines()), diagnostics.LOG_LINES)
check("and they are the end of the file, not the start",
      "sce_sys/manual/119999.png" in _tail, True)
# A seek into the middle of the file lands mid-line as often as not.
check("the partial line the seek landed in is dropped",
      _tail.splitlines()[0].startswith("[INFO]"), True)
os.remove(_BIG)


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
