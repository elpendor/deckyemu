#!/usr/bin/env python3
"""Making a cloud remote: what reaches rclone's command line, and what does not.

    python scripts/tests/test_cloudsave.py

Two things are worth pinning here and neither is about rclone working.

The first is that **a form post is the one input in this feature that comes from
outside**. Whoever fills the page in chooses every value on it, so what matters
is that only the fields the backend declared are passed on -- an extra key in
the post must not become an rclone option the panel never offered.

The second is that **the config file is ours and never the user's own**. Every
call has to carry `--config`, because a Deck that already runs rclone for
something else has a configuration this plugin has no business editing, and
there would be no way to undo it.

No real rclone runs here. `subprocess.run` is replaced, so what is checked is
the argument list built for it -- which is the part that decides both of those.
"""

import os
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py_modules"))

import cloudsave  # noqa: E402


class FakeRun:
    """Records the argv it was handed and answers with a chosen exit code."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv, self.returncode, self.stdout, self.stderr)

    @property
    def argv(self):
        return self.calls[-1] if self.calls else []


def with_run(fake, action):
    """Run `action` with subprocess.run and the binary lookup both replaced."""
    real_run, real_binary = subprocess.run, cloudsave.binary
    subprocess.run = fake
    cloudsave.binary = lambda: "/tools/rclone"
    try:
        return action()
    finally:
        subprocess.run, cloudsave.binary = real_run, real_binary


section("a remote is made from exactly the fields its backend declares")

fake = FakeRun()
ok, error = with_run(fake, lambda: cloudsave.create_remote(
    "mynas", "webdav",
    {"url": "https://nas.example/dav", "user": "pendor", "pass": "hunter2",
     # Not a field webdav declares. It must not reach the command line: this is
     # the shape of the attack a form post makes possible.
     "config_refresh_token": "true", "--dump": "bodies"}))
check("it succeeds", (ok, error), (True, ""))
check("the declared fields are passed",
      [a for a in fake.argv if a.startswith(("url=", "user=", "pass="))],
      ["url=https://nas.example/dav", "user=pendor", "pass=hunter2"])
check("an undeclared key from the form never reaches rclone",
      [a for a in fake.argv if "refresh_token" in a or a == "--dump"],
      [])
check("the backend's own fixed settings are applied",
      "vendor=nextcloud" in fake.argv, True)
check("the password is obscured rather than stored as typed",
      "--obscure" in fake.argv, True)

section("every call is against our config, never the user's own")

check("--config comes first, before the subcommand",
      fake.argv[1:3], ["--config", cloudsave.CONFIG_PATH])
check("and it is not rclone's default location",
      os.path.expanduser("~/.config/rclone") in cloudsave.CONFIG_PATH, False)

for name, action in (
    ("listremotes", cloudsave.remotes),
    ("check", lambda: cloudsave.check_remote("mynas")),
    ("remove", lambda: cloudsave.remove_remote("mynas")),
):
    probe = FakeRun(stdout="mynas:")
    with_run(probe, action)
    check("%s carries --config too" % name,
          probe.argv[1:3], ["--config", cloudsave.CONFIG_PATH])

section("a name that would not be safe as a path or a section header")

for bad in ("../evil", "a/b", "with\nnewline", "", "x" * 40, "-", "a:b"):
    check("refused: %r" % bad, cloudsave.valid_name(bad), False)
for good in ("mynas", "my nas", "nas-1", "a.b_c+d@e"):
    check("allowed: %r" % good, cloudsave.valid_name(good), True)

blocked = FakeRun()
ok, error = with_run(blocked, lambda: cloudsave.create_remote(
    "../evil", "webdav", {"url": "https://x", "user": "u", "pass": "p"}))
check("a bad name never reaches rclone at all", blocked.calls, [])
check("and says so rather than failing obscurely", ok, False)

section("an unknown storage type is refused before anything runs")

unknown = FakeRun()
ok, error = with_run(unknown, lambda: cloudsave.create_remote(
    "x", "dropbox", {"anything": "1"}))
check("nothing ran", unknown.calls, [])
check("and it is named", (ok, error), (False, "Unknown storage type."))

section("a missing field is a sentence, not a half-made remote")

partial = FakeRun()
ok, error = with_run(partial, lambda: cloudsave.create_remote(
    "mypi", "sftp", {"host": "nas.local", "user": "deck", "pass": "  "}))
check("nothing ran", partial.calls, [])
check("and the field is named", (ok, error), (False, "pass is required."))

section("what rclone says when it fails is what gets reported")

failed = FakeRun(returncode=1, stderr=(
    "2026/09/02 22:37:39 NOTICE: trying\n"
    "2026/09/02 22:37:40 ERROR : couldn't connect: no such host\n"))
ok, error = with_run(failed, lambda: cloudsave.check_remote("mynas"))
check("the last line, with rclone's timestamp and level stripped",
      (ok, error), (False, "couldn't connect: no such host"))

section("without the binary nothing is attempted")

real_binary = cloudsave.binary
cloudsave.binary = lambda: ""
try:
    check("creating says so plainly",
          cloudsave.create_remote("mynas", "webdav",
                                  {"url": "u", "user": "u", "pass": "p"}),
          (False, "rclone is not installed yet."))
    check("and listing is empty rather than an error", cloudsave.remotes(), [])
finally:
    cloudsave.binary = real_binary

section("the code out of whatever the browser ended up at")

for pasted, want in (
    ("http://localhost:53682/?code=ABC&state=XYZ", ("ABC", "XYZ")),
    ("http://127.0.0.1:53682/?state=XYZ&code=ABC", ("ABC", "XYZ")),
    # Some phones share a bare query, or append a fragment of their own.
    ("code=ABC&state=XYZ", ("ABC", "XYZ")),
    ("http://localhost:53682/?code=ABC&state=XYZ#done", ("ABC", "XYZ")),
    ("  http://localhost:53682/?code=ABC&state=XYZ  ", ("ABC", "XYZ")),
    # A provider that refused, which must not read as a code.
    ("http://localhost:53682/?error=access_denied&state=XYZ", ("", "XYZ")),
    ("https://www.dropbox.com/oauth2/authorize", ("", "")),
    ("", ("", "")),
):
    check("parsed: %r" % (pasted[:44] or "(empty)"), cloudsave._code_from(pasted), want)

section("the credential blob rclone prints")

check(
    "taken out of the chatter around it",
    cloudsave._token_from(
        'NOTICE: Got code\nPaste the following into your remote machine --->\n'
        '{"access_token":"sl.u.AAA","refresh_token":"BBB"}\n<---End paste\n'),
    '{"access_token":"sl.u.AAA","refresh_token":"BBB"}',
)
check("and absent when the login failed", cloudsave._token_from(
    "Fatal error: failed to get token: lookup api.dropboxapi.com"), "")

section("a login that is not open cannot be finished")

cloudsave._login.clear()
check("says so rather than pretending",
      cloudsave.login_finish("mydrop", "dropbox", "?code=A&state=B"),
      (False, "That login is no longer open. Start it again."))
check("an unknown provider is refused",
      cloudsave.login_finish("mydrop", "nowhere", "?code=A")[0], False)
check("and so is a name that could be read as a flag",
      cloudsave.login_finish("-x", "dropbox", "?code=A")[0], False)

section("a login with nothing pasted into it")


class FakeProcess:
    """Stands in for a waiting `rclone authorize`."""

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


held = FakeProcess()
cloudsave._login.update({"process": held, "kind": "dropbox",
                         "started": __import__("time").time()})
ok, error = cloudsave.login_finish("mydrop", "dropbox", "not a url")
check("is told what to copy", (ok, "Copy the whole" in error), (False, True))
check("and the login is left open to try again", cloudsave._login.get("process"),
      held)

check("cancelling ends it", cloudsave.login_cancel(), (True, ""))
check("the process was killed", held.killed, True)
check("and nothing is left behind", cloudsave._login, {})

section("a login already open is handed back, not restarted")

# The regression this exists for: the page asks for a link when it loads, and a
# phone browser reloads a tab it discarded while the user was away signing in.
# Restarting the login there mints a new state, so the code they had just been
# given belonged to a login that no longer existed -- rclone answers "State did
# not match" and the sign-in cannot be finished at all.


class OpenProcess:
    """A `rclone authorize` that is still waiting."""

    def __init__(self):
        self.killed = False

    def poll(self):
        return None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


import time as _time  # noqa: E402  -- only for the clock these two tests set

waiting = OpenProcess()
cloudsave._login.clear()
cloudsave._login.update({"process": waiting, "kind": "dropbox",
                         "started": _time.time(),
                         "url": "https://www.dropbox.com/oauth2/authorize?x=1"})
real_binary = cloudsave.binary
cloudsave.binary = lambda: "/tools/rclone"
try:
    check("the same provider gets the link it already had",
          cloudsave.login_start("dropbox"),
          ("https://www.dropbox.com/oauth2/authorize?x=1", ""))
    check("and the process it belongs to is left alone", waiting.killed, False)

    # A different provider is a different login, and there is only one port.
    stale = OpenProcess()
    cloudsave._login.update({"process": stale, "kind": "dropbox",
                            "started": _time.time() - 10_000,
                            "url": "https://old.example/"})
    cloudsave.login_start("dropbox")
    check("but one that has timed out is abandoned rather than reused",
          stale.killed, True)
finally:
    cloudsave.binary = real_binary
    cloudsave._login_stop()

section("only the providers rclone can still sign into")

check("Google Drive is not offered -- its shared client id retires during 2026",
      "drive" in cloudsave.OAUTH_BACKENDS, False)
check("and every one that is has a name for a person to read",
      all(spec.get("label") for spec in cloudsave.OAUTH_BACKENDS.values()), True)

section("which service each remote is, read without touching the token")

import tempfile as _tempfile  # noqa: E402

_conf = os.path.join(_tempfile.mkdtemp(), "rclone.conf")
with open(_conf, "w", encoding="utf-8") as _handle:
    _handle.write("\n".join([
        "[cloud]",
        "type = dropbox",
        # A real token: JSON, full of quotes and % signs, and none of this may
        # be read, interpreted or handed anywhere.
        'token = {"access_token":"sl.u.AAA%BBB","refresh_token":"R"}',
        "",
        "[mynas]",
        "type = webdav",
        "url = https://nas.example/dav",
        "pass = 0Is0UQhO6BrecA",
        "",
        "[halfmade]",
        "",
    ]))
_real_path = cloudsave.CONFIG_PATH
cloudsave.CONFIG_PATH = _conf
try:
    check("each remote's service is found",
          cloudsave.remote_kinds(),
          {"cloud": "dropbox", "mynas": "webdav", "halfmade": ""})
    check("a service has a name a person would recognise",
          cloudsave.label_for("dropbox"), "Dropbox")
    check("and one for the typed-in kinds too",
          cloudsave.label_for("webdav"), "Nextcloud or WebDAV")
    check("an unknown one falls back to the bare type rather than to nothing",
          cloudsave.label_for("swift"), "swift")
finally:
    cloudsave.CONFIG_PATH = _real_path

check("a missing config is empty rather than an error",
      cloudsave.remote_kinds(), {})

section("everything the provider sent is replayed, not just the code")

# pCloud is why. It returns the API host the account lives on, and that is how
# rclone knows to exchange against the EU endpoint instead of the US one.
# Rebuilding the callback from `code` and `state` dropped it, and an EU account
# then failed with `Invalid 'code' provided` -- naming the one part that was fine.
check(
    "a provider's extra parameters survive",
    sorted(cloudsave._query_from(
        "http://localhost:53682/?code=ABC&state=XYZ&hostname=eapi.pcloud.com"
    ).split("&")),
    sorted(["code=ABC", "state=XYZ", "hostname=eapi.pcloud.com"]),
)
check("a bare query works the same",
      cloudsave._query_from("code=ABC&state=XYZ"), "code=ABC&state=XYZ")
check("and a fragment the phone appended is not part of it",
      cloudsave._query_from("http://x/?code=ABC#done"), "code=ABC")
check("a value is decoded once and re-encoded, never doubled",
      cloudsave._query_from("http://x/?code=" + urllib.parse.quote("a/b c")),
      "code=" + urllib.parse.quote_plus("a/b c"))
check("nothing pasted is nothing sent", cloudsave._query_from(""), "")

section("settings the sign-in itself carried end up in the remote")

check(
    "pCloud's region is kept, because a token is regional",
    cloudsave._kept_settings(
        "pcloud", "http://localhost:53682/?code=A&state=B&hostname=eapi.pcloud.com"),
    ["hostname=eapi.pcloud.com"],
)
check("a US account sends none, and none is written",
      cloudsave._kept_settings("pcloud", "http://localhost:53682/?code=A&state=B"), [])
check("providers that declare nothing keep nothing",
      cloudsave._kept_settings(
          "dropbox", "http://localhost:53682/?code=A&hostname=evil.example"), [])
for bad in ("not a host", "a=b", "x/../y", "host name", "hos\tt"):
    check("refused as a hostname: %r" % bad,
          cloudsave._kept_settings(
              "pcloud", "http://x/?code=A&hostname=" + urllib.parse.quote(bad)),
          [])

section("the storage is named here, never asked for")

# The form used to ask for a name before it would let anybody sign in, and the
# word somebody typed was the only thing the panel could show -- "saves go to
# cloud" was a real screen. rclone needs a key for its config file and nobody
# else does, so it is chosen here and the service is what gets shown.
_existing = []
_real_remotes = cloudsave.remotes
cloudsave.remotes = lambda: list(_existing)
try:
    check("the first of a service is just the service",
          cloudsave.next_name("dropbox"), "dropbox")

    _existing.append("dropbox")
    check("a second account of the same service takes a number",
          cloudsave.next_name("dropbox"), "dropbox-2")
    check("and a different service is untouched by it",
          cloudsave.next_name("pcloud"), "pcloud")

    _existing.append("dropbox-2")
    check("the number keeps counting past what is there",
          cloudsave.next_name("dropbox"), "dropbox-3")

    # It has to survive its own output: the name goes into a config file and
    # into every command line rclone is given afterwards.
    check("every name it picks is one rclone will accept",
          all(cloudsave.valid_name(cloudsave.next_name(kind))
              for kind in list(cloudsave.BACKENDS) + list(cloudsave.OAUTH_BACKENDS)),
          True)
finally:
    cloudsave.remotes = _real_remotes

summary()
