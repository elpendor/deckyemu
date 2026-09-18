#!/usr/bin/env python3
"""What arrives is what the release said would arrive.

    python scripts/tests/test_download_integrity.py

The plugin verifies the sha256 of its *own* updates and identifies BIOS files by
hash, and installed emulators and ports on the strength of a filename. GitHub
publishes a digest per release asset, so the asymmetry cost nothing to keep and
nothing to close.

**This is an integrity check, not an authenticity one.** The checksum arrives in
the same API response as the download URL, so whoever could swap one could swap
the other. What it catches is a download that came down wrong, which otherwise
reaches somebody as an emulator that will not start and says nothing about why.

Every project here is made up. Nothing touches the network.
"""

import hashlib
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import net  # noqa: E402

_ENTRY = {
    "id": "checked-port",
    "name": "Checked Port",
    "source": {"kind": "github", "repo": "someone/checked",
               "asset": r"^Checked\.zip$", "extract": r"^checked\.appimage$"},
    "args": "{rom}",
}

_ARCHIVE = os.path.join(TMP, "release", "Checked.zip")
os.makedirs(os.path.dirname(_ARCHIVE), exist_ok=True)
with zipfile.ZipFile(_ARCHIVE, "w") as _bundle:
    _bundle.writestr("checked.appimage", "#!/bin/sh\nexit 0\n")

with io.open(_ARCHIVE, "rb") as _handle:
    _REAL = hashlib.sha256(_handle.read()).hexdigest()


def _fake_download(url, path, max_bytes=0, on_progress=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(_ARCHIVE, "rb") as source, io.open(path, "wb") as handle:
        handle.write(source.read())
    return True, ""


def _install(digest):
    return emu_install.install_appimage(
        _ENTRY, {"name": "Checked.zip", "url": "https://example.test/c.zip",
                 "tag": "1.0.0", "digest": digest})


section("a download that matches what was published")

_real_download = net.download
net.download = _fake_download
try:
    _path, _error = _install("sha256:" + _REAL)
    check("installs", _error, "")
    check("and what runs is the program", os.path.basename(_path), "checked.appimage")

    # GitHub only began publishing these recently, and a self-hosted forge an
    # imported definition names may publish none. Refusing those would be
    # refusing to install from anywhere but github.com.
    _path, _error = _install("")
    check("an asset with no digest is still installed", _error, "")


    section("a download that does not")

    _path, _error = _install("sha256:" + "0" * 64)
    check("is refused", bool(_error), True)
    check("and says what happened rather than naming a hash",
          "checksum" in _error and "Nothing was installed" in _error, True)
    check("nothing is left behind to be run later",
          os.path.isfile(os.path.join(emu_install.emulators_dir(_ENTRY["id"]),
                                      "Checked.zip")),
          False)

    # A digest in a form we do not read is not a failed check. Refusing on one
    # would turn any future format -- sha512, or a bare hash -- into an
    # emulator nobody can install.
    _path, _error = _install("sha512:whatever")
    check("a digest in an unknown form is not treated as a mismatch", _error, "")
finally:
    net.download = _real_download
    emulator_catalog.reload_imported()


if __name__ == "__main__":
    summary()
