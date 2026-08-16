"""A report somebody can paste into a bug report, gathered without a terminal.

The plugin logs plenty. None of it is reachable from Game Mode: the log is a
file under `~/homebrew/logs/deckyemu`, the frontend's own errors go to a CEF
console nobody opens, and the device has no keyboard worth the name. So the best
report a user can give today is "it didn't work", which is also the least useful
one -- and that gets worse the moment this is installed by people who cannot be
asked to SSH in.

What is gathered is what has actually been needed to diagnose something here:
which build is running, what RetroArch is and how it was installed, which
emulators are registered and how, how big the library is, and the tail of the
log. Not the library itself -- a list of somebody's games is theirs, it is
rarely what a bug turns on, and this text is going into a public issue.

**Redaction is the point of this module, not a feature of it.** The settings
file holds a SteamGridDB key, a RetroAchievements token that is
password-equivalent, and the transfer token; the log holds paths and can hold
any of those if something logged one. Two rules, and both are needed:

* settings are read through an allowlist, so a secret added later is absent
  until somebody deliberately lists it, rather than exported until somebody
  notices;
* every known secret value is struck out of the *whole* report by value, so a
  key that reached the log by another route goes too.

The same goes for what is merely personal. The log names games as it works --
the title and the path when one is added, the name inside an artwork URL when a
lookup fails -- so leaving the library listing out of the report did not stop
the report listing somebody's library. Titles and ROM paths are struck by value
too, in their plain and percent-encoded forms.
"""

import glob
import json
import os
import re
import urllib.parse

import decky

import store
import sysenv

#: Settings worth reporting, and safe to. An allowlist because the alternative
#: is a blocklist that is correct only until the next setting is added.
REPORTED_SETTINGS = (
    "art_source",
    "hide_osd",
    "menu_combo",
    "add_to_collection",
    "collection_per_platform",
    "collection_template",
    "platform_names",
    "emulator_fullscreen",
    "cheevos_enable",
    "cheevos_hardcore",
    "launcher_format",
    "transfer_remember",
)

#: Settings that hold a secret. Reported as whether they are set, never as what
#: they are, and struck out of the rest of the report by value.
SECRET_SETTINGS = ("sgdb_api_key", "cheevos_token", "transfer_token", "github_token")

#: How much of the log to carry. Enough for the run that went wrong and the
#: startup before it; not so much that nobody reads it.
LOG_LINES = 200

#: How much of the file to read to find those lines. Generous for 200 ordinary
#: lines and a hard ceiling on the work regardless of how big the log has grown
#: -- which it does: an emulator's own output is streamed into it a line per
#: file unpacked, so one large game can write thousands.
TAIL_BYTES = 256 * 1024

#: A last defence over the log, for a secret this plugin does not hold and so
#: cannot strike out by value -- a zRIF in a path, a token some other tool
#: logged. Deliberately crude: a false positive costs a line of a log, and a
#: false negative costs somebody their account.
_SECRET_SHAPES = (
    # A zRIF licence key, which is what `find_zrif` looks for.
    re.compile(r"KO5if[A-Za-z0-9+/=]{20,}"),
    # Anything calling itself a token, key or password with a value after it.
    re.compile(r"(?i)\b(?:token|api[_-]?key|password|secret)\b\s*[=:]\s*\S+"),
    # A token sitting in a URL path, which is how both of this plugin's own
    # servers address themselves: the transfer server mints one per session and
    # `stage_update` logs the loopback address it offers a download at, token
    # and all. Neither is in the settings, so no value could strike them -- and
    # the transfer one is live on the network at the moment the report is read.
    # The host is kept, because which host it was is the useful half.
    re.compile(r"(://[^/\s]+/)[A-Za-z0-9_\-]{16,}"),
    # A long run of hex. Vita3K prints two 128-bit values of its own while
    # installing a package, immediately before it copies the licence into place;
    # what they are is not documented anywhere this project can check, and key
    # material beside a licence copy is not something to publish on a guess. The
    # cost of being wrong this way is a line of a log nobody needed.
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)

REDACTED = "[removed]"


def _redact(text, secrets):
    """`text` with every known secret and secret-shaped run struck out.

    Each value is struck in the forms it can appear in. A game's name reaches
    the log as itself and, when an artwork lookup fails, inside the URL that
    failed -- where it is percent-encoded and a literal match walks straight
    past it.
    """
    wanted = []
    for secret in secrets:
        wanted.append(secret)
        wanted.append(urllib.parse.quote(secret))
        wanted.append(urllib.parse.quote_plus(secret))

    for secret in dict.fromkeys(wanted):
        # Short values are not secrets worth striking, and striking a one or two
        # character string would redact half the report.
        if secret and len(secret) >= 8:
            text = text.replace(secret, REDACTED)
    for shape in _SECRET_SHAPES:
        # A rule that captures a group keeps it. The URL one keeps the host,
        # because which host it was is the useful half and the token after it is
        # the part that must not travel.
        text = shape.sub(lambda found: (found.group(1) if found.groups() else "") + REDACTED, text)
    return text


def _log_tail(lines=LOG_LINES):
    """The end of the newest log file, or a line saying why there is none."""
    try:
        paths = sorted(
            glob.glob(os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "*.log")),
            key=os.path.getmtime,
        )
    except OSError as error:
        return "Could not list the log directory: %s" % error
    if not paths:
        return "No log file found."

    try:
        with open(paths[-1], "rb") as handle:
            # Read the end, not the file. An earlier version read all of it on
            # the reasoning that a plugin log is a few hundred kilobytes at
            # worst -- which is wrong, and observably so: `_run_emulator_tool`
            # streams every line an emulator prints, and Vita3K's installer
            # prints one per file in the package, so a single large game writes
            # thousands of lines. Pulling all of that into memory to keep the
            # last two hundred is work that grows with how much somebody has
            # installed, on the device least able to afford it.
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            raw = handle.read()
    except OSError as error:
        return "Could not read %s: %s" % (os.path.basename(paths[-1]), error)

    found = raw.decode("utf-8", "replace").splitlines()
    # The first line is a fragment whenever the seek landed mid-line.
    if size > TAIL_BYTES and found:
        found = found[1:]

    return "\n".join(found[-lines:]) or "The log is empty."


def _os_release():
    """What SteamOS says it is, for the two lines of it that matter."""
    wanted = ("PRETTY_NAME", "VERSION_ID", "BUILD_ID")
    found = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key in wanted:
                    found[key] = value.strip('"')
    except OSError:
        return ""
    return " ".join("%s=%s" % (key, found[key]) for key in wanted if key in found)


def _section(title, body):
    return "## %s\n%s\n" % (title, body if body else "(nothing)")


def build(version, install, emulators_registered, library, catalog_installed=(),
          live_secrets=(), inbox=""):
    """The report, as text.

    Everything it needs is passed in: this module reads settings and the log,
    and asks nothing of the Plugin class, so the whole thing is testable without
    starting one.

    `live_secrets` is anything secret that exists only in memory right now --
    the transfer server's token above all. It is minted per session, so it is in
    no settings file for a value strike to find, and it appears in the log as a
    bare request path (`PUT /<token>/upload/...`) that no URL rule catches. It is
    also live on the network at the moment somebody reads the report.
    """
    settings = store.get_settings()
    secrets = [str(settings.get(key) or "") for key in SECRET_SETTINGS]

    # The log names games, and the report carries the log.
    #
    # `prepare_shortcut` logs the title and the ROM path, `register_game` logs
    # the title, `probe_rom` logs the path, and a failed SteamGridDB lookup logs
    # a URL with the game's name in it. So a report that merely left the library
    # section out still listed somebody's games, several lines at a time --
    # while the dialog offering it promised the opposite.
    #
    # Struck by value, the same way the secrets are, out of what the registry
    # already knows. A title shorter than the length guard survives, and so does
    # a game probed but never added, because neither is a value this can know:
    # the wording says titles are removed rather than that none can appear.
    personal = [str(settings.get("cheevos_username") or "")]
    # What is sitting in the inbox. A transferred file is logged by name --
    # "Received gravity rush.pkg" -- and its name is the game's name, which the
    # registry cannot supply: what it records for an installed title is the
    # eboot the emulator boots, not the package the user sent.
    #
    # The folder is passed in rather than asked of `fileserver`, which imports
    # this module to serve the report: the cycle happens to work today because
    # neither touches the other at import time, and that is not a thing to leave
    # for somebody to discover by moving one line.
    try:
        for name in os.listdir(inbox or ""):
            personal.append(name)
            personal.append(os.path.splitext(name)[0])
    except OSError:
        pass
    for entry in library.values():
        title = str(entry.get("title") or "")
        personal.append(title)
        personal.append(str(entry.get("rom_path") or ""))
        # The launcher is named after the title, slugified -- "Wrote launcher
        # .../gravity-rush-6ac73bd4.sh" names the game as surely as the title
        # does, and striking the title does not touch it.
        launcher = str(entry.get("launcher_path") or "")
        personal.append(launcher)
        personal.append(os.path.basename(launcher))
        personal.append(os.path.splitext(os.path.basename(launcher))[0])
        # And squashed, which is how it appears inside a Vita content id:
        # UP9000-PCSA00011_00-GRAVITYRUSH000000.
        personal.append(re.sub(r"[^A-Za-z0-9]", "", title).upper())
        # Its own name too: a ROM is filed under one and the folder is not it.
        personal.append(os.path.basename(str(entry.get("rom_path") or "")))

    systems = {}
    for entry in library.values():
        systems[entry.get("platform") or "?"] = systems.get(entry.get("platform") or "?", 0) + 1

    parts = [
        "# DeckyEmu diagnostic report",
        "",
        "Paste this into the issue. Keys, tokens, and the names of the games in",
        "your library are removed -- see py_modules/diagnostics.py for the rules.",
        "",
        _section(
            "Build",
            "\n".join(
                [
                    "plugin  %s (%s)" % (version.get("version", "?"), version.get("build", "?")),
                    "built   %s" % (version.get("built_at") or "locally"),
                    "os      %s" % (_os_release() or "unknown"),
                    "home    %s" % sysenv.user_home(),
                ]
            ),
        ),
        _section(
            "RetroArch",
            "not found"
            if not install
            else "\n".join(
                [
                    "kind    %s" % install.get("kind", "?"),
                    "exe     %s" % install.get("exe", "?"),
                    "scope   %s" % (install.get("scope") or "n/a"),
                ]
            ),
        ),
        _section(
            "Emulators registered",
            "\n".join(
                "%-12s %-8s %s"
                % (
                    emulator.get("id", "?"),
                    emulator.get("kind", "?"),
                    emulator.get("target", ""),
                )
                for emulator in emulators_registered
            ),
        ),
        _section("Emulators installed from the catalog", "\n".join(catalog_installed)),
        _section(
            "Library",
            "\n".join(
                ["%d game(s)" % len(library)]
                + ["%-24s %d" % (name, count) for name, count in sorted(systems.items())]
                # Names, not contents: which shelves exist is what collection
                # bugs turn on, and the games on them are the user's business.
                + ["%d collection(s) recorded" % len(store.known_collections())]
            ),
        ),
        _section(
            "Settings",
            "\n".join(
                ["%-26s %s" % (key, settings.get(key)) for key in REPORTED_SETTINGS]
                + [
                    "%-26s %s" % (key, "set" if settings.get(key) else "not set")
                    for key in SECRET_SETTINGS
                ]
            ),
        ),
        _section("Log (last %d lines)" % LOG_LINES, _log_tail()),
    ]

    return _redact("\n".join(parts), list(live_secrets) + secrets + personal)


def as_page(report):
    """The report in a page a phone browser can show and select in one tap.

    A textarea rather than a copy button: the transfer server speaks http on the
    LAN, which is not a secure context, so `navigator.clipboard` is unavailable
    and a button that silently does nothing is worse than none. Tapping the box
    selects all of it, which is the same number of taps and always works.
    """
    # Concatenated rather than interpolated: the stylesheet is full of per-cent
    # signs and `%` formatting reads the first of them as a placeholder.
    return (
        "<!doctype html><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>DeckyEmu diagnostic report</title>"
        "<style>body{font:14px system-ui;margin:0;padding:12px;background:#1a1c22;color:#e6e6e6}"
        "h1{font-size:17px;margin:0 0 4px}p{opacity:.7;margin:0 0 10px}"
        "textarea{width:100%;height:78vh;box-sizing:border-box;background:#0f1116;color:#dfe3ea;"
        "border:1px solid #333;border-radius:6px;padding:10px;font:12px ui-monospace,monospace}"
        "</style>"
        "<h1>DeckyEmu diagnostic report</h1>"
        "<p>Tap the box to select it all, then copy and paste it into the issue.</p>"
        "<textarea readonly onclick='this.select()'></textarea>"
        # Through JSON rather than into the markup: the report is a log tail and
        # can hold anything, including the closing tag of the element it would
        # otherwise be written into.
        "<script>document.querySelector('textarea').value="
        + json.dumps(report).replace("</", "<\\/")
        + ";</script>"
    )
