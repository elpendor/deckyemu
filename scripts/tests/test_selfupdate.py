#!/usr/bin/env python3
"""Installing a release beside the running one, and getting back from it.

    python scripts/tests/test_selfupdate.py

The update path is the one thing that has to keep working when everything else
has gone wrong, so each way back is exercised here: a release that is not whole
is refused before anything switches, the rescue page's rollback swaps the two
versions, and the launcher puts the last good version back after a new one has
failed to start MAX_STARTS times -- without leaving the failed one on offer.

Needs POSIX symlinks -- a link replaced in one rename -- so it is skipped on
Windows, which the service never runs on.
"""

import json
import os
import subprocess
import sys
import io
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, TMP, check, section, summary  # noqa: E402

import appenv  # noqa: E402

if os.name == "nt":
    print("SKIPPED test_selfupdate.py: needs POSIX symlinks")
    sys.exit(0)

import migrate  # noqa: E402
import selfupdate  # noqa: E402


def _tar(path, members):
    with tarfile.open(path, "w:gz") as tarred:
        for name, body in members.items():
            data = body.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            tarred.addfile(info, io.BytesIO(data))
    return path


def release(name, files):
    """A release, laid out the way CI builds one: everything under one folder."""
    path = os.path.join(tempfile.mkdtemp(dir=TMP), name + ".tar.gz")
    return _tar(path, {"deckyemu/" + rel: body for rel, body in files.items()})


WHOLE = {name: "" for name in selfupdate.REQUIRED}
WHOLE["service.py"] = "print('service')\n"
WHOLE["launcher.py"] = open(os.path.join(REPO_ROOT, "launcher.py"), encoding="utf-8").read()
WHOLE["package.json"] = '{"version": "1.0.0"}'


section("a release that is not whole is refused before anything switches")

partial = dict(WHOLE)
del partial["dist/deckyemu.js"]
try:
    selfupdate.install(release("partial", partial), "1.0.0")
    refused = ""
except selfupdate.Refused as refusal:
    refused = str(refusal)
check("a missing file is named", "dist/deckyemu.js" in refused, True)
check("and nothing is switched to", os.path.lexists(selfupdate.CURRENT), False)

broken = dict(WHOLE, **{"main.py": "def (:\n"})
try:
    selfupdate.install(release("broken", broken), "1.0.0")
    refused = ""
except selfupdate.Refused as refusal:
    refused = str(refusal)
check("so is Python that does not compile", "main.py" in refused, True)

escaping = _tar(os.path.join(tempfile.mkdtemp(dir=TMP), "escape.tar.gz"), {"../outside.txt": "x"})
try:
    selfupdate.install(escaping, "1.0.0")
    refused = ""
except selfupdate.Refused as refusal:
    refused = str(refusal)
check("and an archive that names a path outside itself", "outside itself" in refused, True)

linking = os.path.join(tempfile.mkdtemp(dir=TMP), "link.tar.gz")
with tarfile.open(linking, "w:gz") as tarred:
    link = tarfile.TarInfo("deckyemu/main.py")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    tarred.addfile(link)
try:
    selfupdate.install(linking, "1.0.0")
    refused = ""
except selfupdate.Refused as refusal:
    refused = str(refusal)
check("and one that holds a link", "not a file" in refused, True)
check("no staging folder is left behind",
      [n for n in os.listdir(selfupdate.APP) if n.startswith(".staging-")], [])


section("installing switches, keeping the running version as previous")

first = selfupdate.install(release("one", WHOLE), "1.0.0")
check("the first install is current", os.path.realpath(selfupdate.CURRENT), os.path.realpath(first))
selfupdate.commit()
second = selfupdate.install(release("two", WHOLE), "1.1.0")
check("a second install is current", os.path.realpath(selfupdate.CURRENT), os.path.realpath(second))
check("and the first is previous", os.path.realpath(selfupdate.PREVIOUS), os.path.realpath(first))
check("with the switch pending until it reports healthy",
      json.load(open(selfupdate.PENDING))["attempts"], 0)


section("the launcher counts starts, then goes back")

launcher = os.path.join(appenv.ROOT, "launcher.py")
with open(launcher, "w", encoding="utf-8") as handle:
    handle.write(WHOLE["launcher.py"])


def start():
    """One start, as the unit makes it; the service it would exec just prints."""
    return subprocess.run([sys.executable, launcher], capture_output=True, text=True)


for attempt in (1, 2, 3):
    start()
check("three starts are allowed", json.load(open(selfupdate.PENDING))["attempts"], 3)
check("and the new version is still current after them",
      os.path.realpath(selfupdate.CURRENT), os.path.realpath(second))
start()
check("the fourth puts the previous one back",
      os.path.realpath(selfupdate.CURRENT), os.path.realpath(first))
check("without offering the failed one to go back to", os.path.lexists(selfupdate.PREVIOUS), False)
check("and says it happened", os.path.exists(os.path.join(appenv.ROOT, "rolled-back.json")), True)
check("with nothing left pending", os.path.exists(selfupdate.PENDING), False)


section("committing a later update clears the old news and prunes")

third = selfupdate.install(release("three", WHOLE), "1.2.0")
selfupdate.commit()
check("the rollback note goes once a switch works",
      os.path.exists(os.path.join(appenv.ROOT, "rolled-back.json")), False)
check("only current and previous are kept",
      sorted(os.path.realpath(os.path.join(selfupdate.APP, n)) for n in os.listdir(selfupdate.APP)),
      sorted([os.path.realpath(first), os.path.realpath(third)]))


section("the rescue page's rollback swaps the two")

back = selfupdate.rollback()
check("previous becomes current", os.path.realpath(selfupdate.CURRENT), os.path.realpath(first))
check("and current becomes previous", os.path.realpath(selfupdate.PREVIOUS), os.path.realpath(third))
check("and it says where it went", os.path.realpath(back), os.path.realpath(first))


section("an older install's state is carried over once")

old_settings = os.path.join(appenv.PREVIOUS_ROOT, "settings", "deckyemu")
os.makedirs(old_settings)
with open(os.path.join(old_settings, "library.json"), "w", encoding="utf-8") as handle:
    handle.write("{}")
_saved = appenv.SETTINGS_DIR
appenv.SETTINGS_DIR = os.path.join(TMP, "carried", "settings")
try:
    notes = migrate.carry_over()
    check("it moves", os.path.exists(os.path.join(appenv.SETTINGS_DIR, "library.json")), True)
    check("and leaves a link where it was, for the shortcuts that name it",
          os.path.realpath(old_settings), os.path.realpath(appenv.SETTINGS_DIR))
    check("and says so", any("moved" in note for note in notes), True)
    check("a second run changes nothing", migrate.carry_over(), [])

    # An older build put back an empty folder where the link was.
    os.remove(old_settings)
    os.makedirs(old_settings)
    notes = migrate.carry_over()
    check("an empty folder at the old path becomes the link again",
          os.path.realpath(old_settings), os.path.realpath(appenv.SETTINGS_DIR))
    check("and the state stays put", os.path.exists(os.path.join(appenv.SETTINGS_DIR, "library.json")), True)
    check("and says so", any("linked" in note for note in notes), True)
finally:
    appenv.SETTINGS_DIR = _saved


if __name__ == "__main__":
    summary()
