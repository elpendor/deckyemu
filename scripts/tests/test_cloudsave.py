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

summary()
