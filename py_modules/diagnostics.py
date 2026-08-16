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
"""

import glob
import json
import os
import re

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

#: A last defence over the log, for a secret this plugin does not hold and so
#: cannot strike out by value -- a zRIF in a path, a token some other tool
#: logged. Deliberately crude: a false positive costs a line of a log, and a
#: false negative costs somebody their account.
_SECRET_SHAPES = (
    # A zRIF licence key, which is what `find_zrif` looks for.
    re.compile(r"KO5if[A-Za-z0-9+/=]{20,}"),
    # Anything calling itself a token, key or password with a value after it.
    re.compile(r"(?i)\b(token|api[_-]?key|password|secret)\b\s*[=:]\s*\S+"),
)

REDACTED = "[removed]"


def _redact(text, secrets):
    """`text` with every known secret and secret-shaped run struck out."""
    for secret in secrets:
        # Short values are not secrets worth striking, and striking a one or two
        # character string would redact half the report.
        if secret and len(secret) >= 8:
            text = text.replace(secret, REDACTED)
    for shape in _SECRET_SHAPES:
        text = shape.sub(REDACTED, text)
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
        with open(paths[-1], "r", encoding="utf-8", errors="replace") as handle:
            # Read it all and keep the end: a plugin log is a few hundred
            # kilobytes at worst, and seeking backwards for N lines is more code
            # than the saving is worth.
            found = handle.read().splitlines()
    except OSError as error:
        return "Could not read %s: %s" % (os.path.basename(paths[-1]), error)

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


def build(version, install, emulators_registered, library, catalog_installed=()):
    """The report, as text.

    Everything it needs is passed in: this module reads settings and the log,
    and asks nothing of the Plugin class, so the whole thing is testable without
    starting one.
    """
    settings = store.get_settings()
    secrets = [str(settings.get(key) or "") for key in SECRET_SETTINGS]

    systems = {}
    for entry in library.values():
        systems[entry.get("platform") or "?"] = systems.get(entry.get("platform") or "?", 0) + 1

    parts = [
        "# DeckyEmu diagnostic report",
        "",
        "Paste this into the issue. It carries no keys, tokens or game titles --",
        "see py_modules/diagnostics.py for exactly what is gathered and removed.",
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

    return _redact("\n".join(parts), secrets)


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
