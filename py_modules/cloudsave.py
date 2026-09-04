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

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

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


def argv(args):
    """The whole command line for one rclone call, or [] when it is not here yet.

    Every call goes through this, including the streamed ones `cloudsync` runs
    for itself: `--config` is what keeps this plugin out of the user's own
    `~/.config/rclone`, and a second place that builds a command line is a
    second place that can forget it.
    """
    tool = binary()
    if not tool:
        return []
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    return [tool, "--config", CONFIG_PATH] + list(args)


def rclone(args, timeout):
    """One rclone call against our own config. Returns (ok, output).

    Public because `cloudsync` does the copying and this module owns where the
    config file is and how a failure is turned into a sentence. Two modules
    building the same command line differently is how one of them ends up
    writing to the user's own `~/.config/rclone`.

    Output is whatever rclone said, trimmed, and safe to log: passwords come
    back from `config create` as `*** ENCRYPTED ***` rather than as themselves.
    """
    command = argv(args)
    if not command:
        return False, "rclone is not installed yet."
    try:
        done = subprocess.run(
            command,
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


def next_name(kind):
    """A name for a new remote, decided here rather than asked for.

    rclone needs one -- it is the key of a section in a config file, and every
    command names it. Nobody else does. The form used to ask, which meant
    somebody signing in to Dropbox on a phone was made to invent a word for it
    first, and the word they invented was the only thing the Deck could show:
    "saves go to cloud" was a real screen. The service is what a person calls
    this, and the service is what the panel now names, so the config key can be
    ours to choose.

    The service is the name, and a second account of the same service takes a
    number. Two Dropbox accounts really are two things and rclone cannot hold
    them under one key.
    """
    taken = set(remotes())
    if kind not in taken:
        return kind
    nth = 2
    while "%s-%d" % (kind, nth) in taken:
        nth += 1
    return "%s-%d" % (kind, nth)


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

    ok, output = rclone(args, _CREATE_SECONDS)
    if not ok:
        return False, output
    _restrict(CONFIG_PATH)
    decky.logger.info("Created cloud remote %r (%s)", name, kind)
    return True, ""


def remotes():
    """The remotes that exist, by name. Never their contents."""
    ok, output = rclone(["listremotes"], _CREATE_SECONDS)
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
    ok, output = rclone(["lsd", "%s:" % name, "--max-depth", "1"], _CHECK_SECONDS)
    return (True, "") if ok else (False, output)


def remove_remote(name):
    """Forget a remote and its credentials. Returns (ok, error)."""
    if not valid_name(name):
        return False, "That name cannot be used."
    ok, output = rclone(["config", "delete", name], _CREATE_SECONDS)
    return (ok, "" if ok else output)


# --------------------------------------------------------------- browser login
#
# The providers whose setup is a login rather than a form, and how one gets done
# without a keyboard on the Deck and without a browser on it either.
#
# **The problem.** rclone's OAuth flow ends with the provider redirecting to
# `http://localhost:53682/`, which is registered with the client id and cannot
# be changed. Log in on a phone and that redirect lands on the phone, where
# nothing is listening, so the login appears to fail at the last step.
#
# **What makes it work anyway.** That dead page still has the answer in its
# address: `?code=...&state=...`. rclone's callback is an ordinary HTTP endpoint
# waiting for exactly those, so the Deck can make that request itself. Measured
# on the device: a replayed callback answered 200, matched the state, and went
# straight to the token exchange -- rejected only because the code was invented.
#
# So the login happens wherever the user already has a keyboard and a password
# manager, and what crosses back is a paste rather than anything typed.

#: Where rclone listens for the provider's answer. Not configurable: it is what
#: is registered as the redirect for every one of these client ids.
_AUTH_PORT = 53682

#: The providers offered. Google Drive is deliberately absent -- rclone's own
#: help says its shared client id "is being retired and will stop working during
#: 2026", so it would need the user to create their own in Google's console,
#: which is a worse experience than this whole feature is worth. The ones here
#: carry no such notice.
#: `keep` names parameters the provider puts in its redirect that have to be
#: written into the remote as settings. Only pCloud needs one, and it needs it
#: badly: accounts live in either a US or a European region, the sign-in says
#: which in `hostname`, and a remote without it asks the wrong server. That
#: fails twice over, both times naming the wrong thing -- `Invalid 'code'` while
#: exchanging, then `Invalid 'access_token' (2094)` on the first listing, when
#: the code and the token were both perfectly good.
OAUTH_BACKENDS = {
    "dropbox": {"label": "Dropbox"},
    "onedrive": {"label": "OneDrive"},
    "box": {"label": "Box"},
    "pcloud": {"label": "pCloud", "keep": ("hostname",)},
}

#: A hostname kept from a redirect, before it is written into a config file and
#: used to build URLs. Nothing about the shape of a host needs more than this,
#: and the value arrives from outside.
_HOSTNAME = re.compile(r"^[A-Za-z0-9.-]{1,253}$")

#: How long to wait for rclone to print its auth link, and how long a login may
#: stay open before the process is reaped. The second is generous because it is
#: somebody logging in on a phone, and mean enough that an abandoned attempt
#: does not hold the port for the rest of the session.
_LINK_SECONDS = 20
_LOGIN_SECONDS = 600

#: The one login that can be in progress, because there is one port. Holds the
#: running `rclone authorize` and what it was started for.
_login: dict = {}


def _login_stop():
    """End any login in progress. Safe to call when there is none."""
    process = _login.pop("process", None)
    _login.clear()
    if process is None:
        return
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def login_start(kind):
    """Begin a browser login. Returns (url to open, error).

    The URL goes to whatever device the user is holding. Nothing is written
    until `login_finish`, so abandoning this costs a killed process and nothing
    else.
    """
    if kind not in OAUTH_BACKENDS:
        return "", "Unknown storage type."
    tool = binary()
    if not tool:
        return "", "rclone is not installed yet."

    # **A login already open for this provider is handed back, not replaced.**
    # The page asks for a link when it loads, and a phone browser reloads a tab
    # it discarded while the user was away signing in -- so starting a fresh
    # login here would mint a new state, and the code they were just given
    # belonged to the old one. rclone then answers "State did not match" and the
    # sign-in cannot be completed at all. Measured on a real login.
    open_now = _login.get("process")
    if (open_now is not None and _login.get("kind") == kind
            and open_now.poll() is None
            and time.time() - _login.get("started", 0) < _LOGIN_SECONDS):
        return _login.get("url", ""), ""

    # Anything else -- a different provider, or one that has expired or died --
    # is abandoned. There is only one port to listen on.
    _login_stop()

    try:
        process = subprocess.Popen(
            [tool, "authorize", kind, "--auth-no-open-browser"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return "", "Could not start the login: %s" % error

    # rclone prints the link on its way to waiting. Read only until it appears:
    # the process must stay alive afterwards, because it is the thing that will
    # catch the code.
    deadline = time.time() + _LINK_SECONDS
    url = ""
    said = []
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            if process.poll() is not None:
                break
            continue
        said.append(line)
        found = re.search(
            r"https?://127\.0\.0\.1:%d/auth\?state=[\w-]+" % _AUTH_PORT, line)
        if found:
            url = found.group(0)
            break

    if not url:
        _login_stop()
        # The one failure worth naming, because it is the one somebody can do
        # something about and the one this feature can cause itself: a login
        # that was never finished leaves rclone sitting on the port.
        if "address already in use" in "".join(said):
            return "", ("Another login is still open on this Deck. Wait a "
                        "minute and try again.")
        return "", _last_line("".join(said)) or "rclone did not offer a login link."

    # **What the page is given is the provider's own address, not rclone's.**
    # rclone hands out `http://127.0.0.1:53682/auth?state=...`, which is a local
    # address: from the phone holding the page, `127.0.0.1` is the phone, and
    # the link goes nowhere. That endpoint only redirects to the provider
    # anyway, so the Deck follows it here and passes on where it points. The
    # phone then talks to Dropbox directly, which is the only part of this it
    # can reach.
    signin, problem = _redirect_target(url)
    if not signin:
        _login_stop()
        return "", problem or "rclone did not say where to sign in."

    _login.update({"process": process, "kind": kind, "started": time.time(),
                   "url": signin})
    decky.logger.info("Cloud login started for %s", kind)
    return signin, ""


def _redirect_target(url):
    """Where rclone's local auth endpoint points. Returns (url, error).

    Read rather than followed: what is wanted is the address to hand somebody,
    not the page behind it, and fetching the provider's login from the Deck
    would accomplish nothing except a wasted round trip.
    """
    class _KeepRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(_KeepRedirect)
    try:
        with opener.open(url, timeout=20) as answer:
            location = answer.headers.get("Location", "")
    except urllib.error.HTTPError as answer:
        location = answer.headers.get("Location", "")
    except OSError as problem:
        return "", "Could not reach rclone: %s" % problem
    return (location, "") if location.startswith("https://") else (
        "", "rclone did not offer a sign-in address.")


def _code_from(pasted):
    """The code and state out of whatever the user pasted. ("", "") if absent.

    Takes the whole address, because that is what a browser hands over and what
    somebody can copy without reading it. A bare query string works too, since
    some phones share a fragment rather than the URL.
    """
    text = (pasted or "").strip()
    if not text:
        return "", ""
    query = text.partition("?")[2] if "?" in text else text
    asked = urllib.parse.parse_qs(query.partition("#")[0])
    return (asked.get("code", [""])[0].strip(),
            asked.get("state", [""])[0].strip())


def _query_from(pasted):
    """Everything the provider put in the address, re-encoded. "" if nothing.

    Parsed and rebuilt rather than passed through as text, so what reaches
    rclone is a query this code produced from named pairs -- whatever was
    pasted, and however it was encoded on the way.
    """
    text = (pasted or "").strip()
    query = text.partition("?")[2] if "?" in text else text
    pairs = urllib.parse.parse_qsl(query.partition("#")[0], keep_blank_values=True)
    return urllib.parse.urlencode(pairs)


def _kept_settings(kind, pasted):
    """Settings the provider's own redirect carried, as `key=value` arguments.

    The sign-in answers with more than a code for some services, and that extra
    is not a detail of the exchange -- it has to end up in the remote. pCloud's
    `hostname` is the whole example: leave it out and the token is fine and
    every request goes to the wrong region's server.

    Only keys the backend declared, and only values that look like hostnames.
    This comes out of an address somebody pasted, and it is about to become a
    line in a config file.
    """
    keep = (OAUTH_BACKENDS.get(kind) or {}).get("keep") or ()
    if not keep:
        return []
    text = (pasted or "").strip()
    query = text.partition("?")[2] if "?" in text else text
    sent = dict(urllib.parse.parse_qsl(query.partition("#")[0]))
    settings = []
    for key in keep:
        value = (sent.get(key) or "").strip()
        if value and _HOSTNAME.match(value):
            settings.append("%s=%s" % (key, value))
    return settings


def _token_from(output):
    """The credential blob rclone prints between its paste markers, or "".

    Matched by shape rather than by the markers around it: the wording of those
    lines is rclone's and there is no reason for this to depend on it.
    """
    found = re.search(r'\{"access_token".*?\}', output or "", re.S)
    return found.group(0).strip() if found else ""


def login_finish(name, kind, pasted):
    """Hand rclone the code from the page that would not load. (ok, error).

    The whole trick is here: the request rclone was waiting for is made from the
    Deck instead of from the browser that could not reach it.
    """
    if not valid_name(name):
        return False, "That name cannot be used. Letters, numbers, spaces, . _ - + @"
    if kind not in OAUTH_BACKENDS:
        return False, "Unknown storage type."

    process = _login.get("process")
    if process is None or _login.get("kind") != kind:
        return False, "That login is no longer open. Start it again."
    if time.time() - _login.get("started", 0) > _LOGIN_SECONDS:
        _login_stop()
        return False, "That login took too long. Start it again."

    code, _state = _code_from(pasted)
    if not code:
        return False, ("That address has no login code in it. Copy the whole "
                       "address of the page that would not load.")

    # **Everything the provider sent is passed on, not just the code.**
    # Rebuilding the callback from `code` and `state` alone silently dropped any
    # other parameter, and some providers put load-bearing things there: pCloud
    # returns the API host its account lives on, which is how rclone knows to
    # exchange against the EU endpoint rather than the US one. Without it an EU
    # account fails with rclone reporting `Invalid 'code' provided` -- a message
    # that names the one part which was fine.
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/?%s" % (_AUTH_PORT, _query_from(pasted)),
            timeout=30,
        ) as answer:
            answer.read()
    except OSError as problem:
        _login_stop()
        return False, "The Deck could not hand the code over: %s" % problem

    # rclone exchanges the code and exits. That exchange is a *second* call to
    # the provider and is where this fails in practice -- a DNS hiccup there
    # produced "server misbehaving" on a login that had visibly worked, which
    # names nothing the user did. So it gets its own message, and the login is
    # startable again rather than leaving somebody wondering what they broke.
    try:
        output, _ = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        _login_stop()
        return False, "rclone did not finish the login. Try again."
    finally:
        _login.clear()

    token = _token_from(output or "")
    if not token:
        reason = _last_line(output) or "the login did not complete"
        if ("lookup" in reason or "no such host" in reason
                or "misbehaving" in reason):
            reason = "the Deck could not reach %s" % OAUTH_BACKENDS[kind]["label"]
        return False, "Almost -- %s. Try the login again." % reason

    # `--non-interactive` is not optional and the reason is worth keeping.
    # Handed a token it thinks needs refreshing, `config create` for an OAuth
    # backend quietly starts a *second* login: it binds rclone's auth port and
    # waits for a browser that is never coming. Measured on the Deck -- the call
    # never returned, held 53682 for the rest of the session, and every later
    # attempt failed with "address already in use". A fresh token does not
    # trigger it, which is exactly what makes it the kind of thing that works in
    # testing and hangs on somebody's device a month later.
    ok, error = rclone(
        ["config", "create", name, kind, "token=" + token]
        + _kept_settings(kind, pasted) + ["--non-interactive"],
        _CREATE_SECONDS,
    )
    if not ok:
        return False, error
    _restrict(CONFIG_PATH)
    decky.logger.info("Created cloud remote %r (%s) by login", name, kind)
    return True, ""


def login_cancel():
    """Abandon a login in progress. Always succeeds."""
    _login_stop()
    return True, ""


def label_for(kind):
    """What to call a storage type on screen, or the bare type if unknown."""
    spec = BACKENDS.get(kind) or OAUTH_BACKENDS.get(kind) or {}
    return spec.get("label") or kind


def remote_kinds():
    """Which service each configured remote is, as {name: type}.

    Read straight out of our own config rather than asked of rclone, and only
    the `type` key is taken. `rclone config show` would answer this too, but it
    prints the token beside it, and there is no reason for a credential to pass
    through here to find out that a remote is a Dropbox.

    Parsed by hand rather than with `configparser`, which is not among the
    modules this plugin has shown decky's bundled Python to have. Two line
    shapes matter and both are trivial, so the dependency buys nothing -- and
    every other line, the token included, is ignored rather than read.
    """
    kinds = {}
    section = ""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip()
                    kinds.setdefault(section, "")
                elif section and line.startswith("type"):
                    key, sep, value = line.partition("=")
                    if sep and key.strip() == "type":
                        kinds[section] = value.strip()
    except OSError:
        return {}
    return kinds


def remote_space(name):
    """How full the storage is, as {total, used, free}, or {}.

    Best effort and quiet about failing. It is the proof that a remote still
    works -- numbers can only come back from a service that answered -- but a
    panel row is not worth an error when the wifi is down.
    """
    if not valid_name(name):
        return {}
    ok, output = rclone(["about", "%s:" % name, "--json"], _CHECK_SECONDS)
    if not ok:
        return {}
    try:
        figures = json.loads(output)
    except ValueError:
        return {}
    return {key: figures[key] for key in ("total", "used", "free")
            if isinstance(figures.get(key), int)}


def account_for(name):
    """Who the remote is signed in as, or "".

    Only some services will say. Dropbox is not one of them -- it answers
    "doesn't support UserInfo" -- so this is written to come back empty as an
    ordinary outcome rather than as a failure, and the panel says the service
    without claiming to know the account.
    """
    if not valid_name(name):
        return ""
    ok, output = rclone(["config", "userinfo", "%s:" % name, "--json"],
                      _CHECK_SECONDS)
    if not ok:
        return ""
    try:
        facts = json.loads(output)
    except ValueError:
        return ""
    if not isinstance(facts, dict):
        return ""
    # Whatever the backend chose to call it. Every one of these is a name or an
    # address the user would recognise as their own.
    for key in ("email", "emailAddress", "email_address", "displayName",
                "display_name", "login", "name", "username"):
        value = facts.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
