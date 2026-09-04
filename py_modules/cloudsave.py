"""Talking to rclone: where the config lives, and how a remote gets made.

**Nothing here holds a credential.** rclone keeps its own configuration file and
this module never reads a password back out of it -- what it can answer is which
remotes exist and whether one currently works, which is all the panel has any
business knowing. A password goes in through `create_remote` and is never seen
again by anything on this side.

**The config is ours and is never the user's own.** Every call passes `--config`
explicitly, so a Deck that already runs rclone for something else keeps its
`~/.config/rclone/rclone.conf` untouched: a plugin that quietly edited a config
file it did not create would be a genuinely bad surprise, and there is no way to
undo it. Ours lives beside the plugin's settings, which is also what decides its
lifetime -- decky clears that directory on uninstall, and a cloud token left
behind by a plugin somebody removed is exactly the wrong thing to keep.

**Why the plain command line and not the rc API.** rclone can be driven over
HTTP, and for the OAuth providers it has to be, because those ask questions and
the answers come back as a state machine. Everything here is the other kind: a
remote whose settings are a form -- a URL, a user, a password -- and
`rclone config create` takes those in one call, with no daemon, no port and
nothing listening. Measured against v1.75.0: exit 0, the password obscured in
the file rather than stored as typed, and the echoed output says
`*** ENCRYPTED ***` rather than the password, so it is safe to log.
"""

import os
import re
import subprocess

import decky

import emu_install

#: Where rclone's configuration lives. Never `~/.config/rclone`.
CONFIG_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "rclone.conf")

#: Long enough for a slow remote to answer, short enough that a wrong hostname
#: does not hang the panel. Creating a remote writes a file and needs none of
#: this; checking one talks to the network.
_CREATE_SECONDS = 20
_CHECK_SECONDS = 45

#: What rclone itself accepts as a remote name, which is stricter than it looks:
#: the name becomes a section header in an ini file and a prefix in every path.
#: rclone refuses the rest with exit 2, so this is the earlier of two checks
#: rather than the only one -- but a name that never reaches a command line
#: cannot do anything clever on the way there.
#:
#: **The first character may not be `-`**, which rclone itself allows and this
#: does not: the name is a positional argument, and one that starts with a dash
#: is read as a flag by anything that parses a command line left to right.
_NAME = re.compile(r"^[A-Za-z0-9_.+@][A-Za-z0-9_.+@ -]{0,31}$")

#: The remotes whose whole configuration is a form somebody can fill in, with
#: the fields that form has to collect. Deliberately not every backend rclone
#: supports: this is the list the panel offers, and each one here is a service
#: whose setup needs no browser, no OAuth and no second device.
#:
#: `secret` names the fields to render as passwords and to keep out of logs.
BACKENDS = {
    "webdav": {
        "label": "Nextcloud or WebDAV",
        "fields": ("url", "user", "pass"),
        "secret": ("pass",),
        "fixed": {"vendor": "nextcloud"},
    },
    "sftp": {
        "label": "SFTP or SSH",
        "fields": ("host", "user", "pass"),
        "secret": ("pass",),
        "fixed": {},
    },
    "s3": {
        "label": "S3 storage",
        "fields": ("provider", "endpoint", "access_key_id", "secret_access_key"),
        "secret": ("secret_access_key",),
        "fixed": {},
    },
}


def binary():
    """The fetched rclone, or "" when it is not here yet."""
    return emu_install.installed_tool("rclone")


def _last_line(text):
    """The final non-empty line, which is where rclone puts the actual error."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line:
            # rclone prefixes its own notices with a timestamp and a level;
            # neither is anything to show somebody.
            return re.sub(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d\s+\w+\s*:\s*", "", line)
    return ""


def _run(args, timeout):
    """One rclone call against our own config. Returns (ok, output).

    Output is whatever rclone said, trimmed, and safe to log: passwords come
    back from `config create` as `*** ENCRYPTED ***` rather than as themselves.
    """
    tool = binary()
    if not tool:
        return False, "rclone is not installed yet."
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    try:
        done = subprocess.run(
            [tool, "--config", CONFIG_PATH] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "rclone did not answer in time."
    except (OSError, subprocess.SubprocessError) as error:
        return False, "Could not run rclone: %s" % error
    if done.returncode != 0:
        return False, (_last_line(done.stderr) or _last_line(done.stdout)
                       or "rclone failed.")
    return True, (done.stdout or "").strip()


def valid_name(name):
    return bool(_NAME.match(name or ""))


def _restrict(path):
    """Owner-only, because the file holds an obscured password and a token."""
    try:
        os.chmod(path, 0o600)
    except OSError as error:
        decky.logger.warning("Could not restrict %s: %s", path, error)


def create_remote(name, kind, values):
    """Write one remote into our config. Returns (ok, error).

    `values` is what the form collected. Only the fields the backend declares
    are passed on: a form post is the one input here that comes from outside,
    and handing rclone an arbitrary key from it would let a caller set options
    the panel never offered.
    """
    if not valid_name(name):
        return False, "That name cannot be used. Letters, numbers, spaces, . _ - + @"
    backend = BACKENDS.get(kind)
    if not backend:
        return False, "Unknown storage type."

    args = ["config", "create", name, kind]
    for field in backend["fields"]:
        value = (values.get(field) or "").strip()
        if not value:
            return False, "%s is required." % field.replace("_", " ")
        args.append("%s=%s" % (field, value))
    for field, value in backend["fixed"].items():
        args.append("%s=%s" % (field, value))
    # Obscuring is rclone's own reversible encoding, not encryption, and it is
    # what every rclone config on earth stores. What it buys is that a password
    # is not sitting in a file in the clear where a screenshot or a support log
    # would carry it.
    args.append("--obscure")

    ok, output = _run(args, _CREATE_SECONDS)
    if not ok:
        return False, output
    _restrict(CONFIG_PATH)
    decky.logger.info("Created cloud remote %r (%s)", name, kind)
    return True, ""


def remotes():
    """The remotes that exist, by name. Never their contents."""
    ok, output = _run(["listremotes"], _CREATE_SECONDS)
    if not ok:
        return []
    return [line.rstrip(":") for line in output.splitlines() if line.strip()]


def check_remote(name):
    """Ask the remote whether it is actually reachable. Returns (ok, error).

    Worth doing at setup rather than at the first backup: a typo in a hostname
    should be a sentence on the page somebody is already looking at, not a
    failure hours later behind a game that just closed.
    """
    if not valid_name(name):
        return False, "That name cannot be used."
    ok, output = _run(["lsd", "%s:" % name, "--max-depth", "1"], _CHECK_SECONDS)
    return (True, "") if ok else (False, output)


def remove_remote(name):
    """Forget a remote and its credentials. Returns (ok, error)."""
    if not valid_name(name):
        return False, "That name cannot be used."
    ok, output = _run(["config", "delete", name], _CREATE_SECONDS)
    return (ok, "" if ok else output)
