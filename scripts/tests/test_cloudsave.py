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
      "vendor=owncloud" in fake.argv, True)
check("the password is obscured rather than stored as typed",
      "--obscure" in fake.argv, True)

section("a field with a sensible default is asked for, not insisted on")

# A port is the example: 21 and 22 are what these run on almost everywhere and
# rclone already knows it, but somebody running one elsewhere has nowhere else
# to say so. Empty means "not passed", so rclone's own default stands.
ported = FakeRun()
with_run(ported, lambda: cloudsave.create_remote(
    "myftp", "ftp", {"host": "nas.local", "port": "2121", "user": "u", "pass": "p"}))
check("a port that was given is passed on",
      [a for a in ported.argv if a.startswith(("host=", "port="))],
      ["host=nas.local", "port=2121"])

bare = FakeRun()
ok, error = with_run(bare, lambda: cloudsave.create_remote(
    "myftp", "ftp", {"host": "nas.local", "port": "", "user": "u", "pass": "p"}))
check("and one that was not is left out rather than refused",
      (ok, error, [a for a in bare.argv if a.startswith("port=")]),
      (True, "", []))

missing = FakeRun()
check("a field that is not optional is still required",
      with_run(missing, lambda: cloudsave.create_remote(
          "myftp", "ftp", {"host": "", "port": "21", "user": "u", "pass": "p"})),
      (False, "host is required."))

section("nobody is asked which S3 this is")

# rclone knows 53 named providers and treats any other answer as a warning it
# carries on past. Measured on the device: a storage created with "asdasd" in
# that field passed the check and worked, because the generic settings suited
# the server behind it. A field that can be got wrong without saying so is a
# field better not asked.
made = FakeRun()
with_run(made, lambda: cloudsave.create_remote(
    "mys3", "s3", {"endpoint": "http://127.0.0.1:9000",
                   "access_key_id": "AK", "secret_access_key": "SK"}))
check("the form does not collect one",
      "provider" in cloudsave.BACKENDS["s3"]["fields"], False)
check("and the generic one is applied without asking",
      "provider=Other" in made.argv, True)
check("what is asked for is what a bucket needs to answer",
      cloudsave.BACKENDS["s3"]["fields"],
      ("endpoint", "access_key_id", "secret_access_key"))

section("a WebDAV address is the one that was typed")

# A vendor is not a label for the server somebody has: it turns on that vendor's
# own upload strategy, and one of them then refuses any address that does not
# match the shape it expects. Save files are kilobytes; the chunking that buys
# is nothing against an address somebody cannot get accepted.
plain = FakeRun()
with_run(plain, lambda: cloudsave.create_remote(
    "mynas", "webdav",
    {"url": "https://example.com/dav", "user": "pendor", "pass": "hunter2"}))
check("the address reaches rclone as it was typed",
      [a for a in plain.argv if a.startswith("url=")],
      ["url=https://example.com/dav"])
# `owncloud` for what it can do, not as a claim about what anybody runs: it is
# the dialect that stores a modification time, which is the only thing left to
# compare on a server with no checksums. Measured on the device against both a
# real server and a deliberately plain one -- under `other` a same-size change
# was never copied; under `owncloud` it was, with no errors either way.
check("the dialect that can store a timestamp is asked for",
      [a for a in plain.argv if a.startswith("vendor=")], ["vendor=owncloud"])
check("and it is not the one that dictates the address",
      "vendor=nextcloud" in plain.argv, False)

section("a storage that will not answer is asked once, not four times")

# Measured on the device: an address that resolves and does not answer hung past
# two minutes on rclone's defaults, because it retries three times over connect
# timeouts of its own. Retries are what a transfer wants; this call exists to
# find out whether the storage answers at all.
probe = FakeRun(stdout="")
with_run(probe, lambda: cloudsave.check_remote("mynas"))
check("one attempt, and a short patience",
      [a for a in probe.argv if a in ("--retries", "--low-level-retries",
                                      "--contimeout", "--timeout")],
      ["--retries", "--low-level-retries", "--contimeout", "--timeout"])
check("and it is still the listing that asks the question",
      probe.argv[3:5], ["lsd", "mynas:"])

section("what a storage that cannot be reached is told to somebody")

# The real one, off the device: one useful fact wrapped in four layers of where
# it was noticed, plus a resolver address that is the Deck's own.
check(
    "a name that does not resolve says so, and names the name",
    cloudsave.said_plainly(
        'Failed to lsd with 2 errors: last error was: couldn\'t list files: '
        'Propfind "https://webdav.home.example/": dial tcp: lookup '
        "webdav.home.example on 127.0.0.53:53: no such host"),
    "The Deck could not find webdav.home.example on this network. Check the "
    "address, or use the server's IP.",
)
check("a refused connection points at the port rather than the address",
      "refused the connection" in cloudsave.said_plainly(
          "dial tcp 192.168.0.9:443: connect: connection refused"),
      True)
check("a rejected password is not described as a network problem",
      cloudsave.said_plainly('Propfind "https://nas.local/dav": 401 Unauthorized'),
      "That username or password was not accepted.")
check("a host that resolves and does not answer is a different sentence",
      cloudsave.said_plainly(
          'request send failed, Get "https://s3.example.com/?x-id=ListBuckets": '
          "dial tcp 10.1.1.1:443: i/o timeout"),
      "s3.example.com did not answer. It resolves, so check the port and that "
      "the server is reachable from the Deck.")
check("and anything rclone explains better than we would is left alone",
      cloudsave.said_plainly("directory not found"), "directory not found")

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
          cloudsave.label_for("webdav"), "WebDAV")
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

section("OneDrive needs to be told which drive, and nothing else asks")

import urllib.request as _urlrequest  # noqa: E402


class FakeAnswer:
    """One HTTP response, as a context manager."""

    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def with_handover(action):
    """Run `action` with the localhost hand-back of the login code stubbed."""
    real = _urlrequest.urlopen
    _urlrequest.urlopen = lambda request, timeout=None: FakeAnswer(b"")
    try:
        return action()
    finally:
        _urlrequest.urlopen = real


def with_drive(reply, action, status=None):
    """Run `action` with the Graph call answering `reply`. Records the headers.

    Through `net`, which is the only way this can work on the device: the
    interpreter decky bundles has a CA store too old for Microsoft's chain, and
    `net` is where the retry against the system trust store lives.
    """
    real = cloudsave.net.get_json
    asked = []

    def fake(url, headers=None, failure=None):
        asked.append((url, dict(headers or {})))
        if status is not None and failure is not None:
            failure["status"] = status
        return reply

    cloudsave.net.get_json = fake
    try:
        return action(), asked
    finally:
        cloudsave.net.get_json = real


_TOKEN = '{"access_token":"EWA","refresh_token":"R"}'
_DRIVE = {"id": "b!aB-c_1", "driveType": "business"}

(settings, problem), asked = with_drive(
    _DRIVE, lambda: cloudsave._drive_settings(_TOKEN))
check("the drive is asked for once", len(asked), 1)
check("of Microsoft rather than of rclone", asked[0][0], cloudsave._GRAPH_DRIVE)
check("with the token that just arrived",
      asked[0][1].get("Authorization"), "Bearer EWA")
check("and both settings come back",
      (settings, problem), (["drive_id=b!aB-c_1", "drive_type=business"], ""))

# Everything here arrives from outside and is about to become a line in a
# config file, so a value that is not a drive id is refused rather than written.
for reply, why in (
    ({"id": "b!ok", "driveType": "nonsense"}, "an unknown kind of drive"),
    ({"id": "line\nbreak", "driveType": "personal"}, "an id with a newline in it"),
    ({"driveType": "personal"}, "no id at all"),
    ([], "an answer that is not an object"),
):
    (settings, problem), _ = with_drive(
        reply, lambda: cloudsave._drive_settings(_TOKEN))
    check("refused: %s" % why, (settings, bool(problem)), ([], True))

(settings, problem), _ = with_drive(None, lambda: cloudsave._drive_settings(_TOKEN))
check("a drive that could not be asked for is a sentence, not a crash",
      (settings, "could not ask OneDrive" in problem), ([], True))
# A refusal and an unreachable host are different problems and read differently.
(settings, problem), _ = with_drive(
    None, lambda: cloudsave._drive_settings(_TOKEN), status=401)
check("a token the provider will not accept says so instead",
      (settings, problem), ([], "OneDrive refused the sign-in (HTTP 401)"))
check("and a token with nothing in it never asks at all",
      cloudsave._drive_settings("not json")[0], [])


class DoneProcess:
    """An `rclone authorize` that has finished and printed its token."""

    def __init__(self, output):
        self.output = output
        self.killed = False

    def communicate(self, timeout=None):
        return self.output, ""

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def finishing_onedrive(fake_run):
    """One whole OneDrive login, with only the network standing in."""
    cloudsave._login.clear()
    cloudsave._login.update({
        "process": DoneProcess("---> %s <---" % _TOKEN),
        "kind": "onedrive", "started": _time.time()})
    return lambda: with_handover(lambda: with_run(
        fake_run, lambda: cloudsave.login_finish(
            "onedrive", "onedrive", "http://localhost/?code=A&state=B")))


made = FakeRun()
((ok, error), _) = with_drive(_DRIVE, finishing_onedrive(made))
check("the login succeeds", (ok, error), (True, ""))
check("and the remote is written with the drive on it, not just a token",
      [a for a in made.argv if a.startswith(("token=", "drive_"))],
      ["token=" + _TOKEN, "drive_id=b!aB-c_1", "drive_type=business"])

# The regression: a section holding a token and no drive looks configured and
# fails on everything with `unable to get drive_id and drive_type`.
half = FakeRun()
((ok, error), _) = with_drive(None, finishing_onedrive(half))
check("a drive that cannot be read leaves no remote behind at all",
      (ok, half.calls), (False, []))
check("and the person is told to try the login again", "Try the login" in error, True)

summary()
