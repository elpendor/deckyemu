#!/usr/bin/env python3
"""A release that ships the program inside an archive.

    python scripts/tests/test_install_extract.py

Most projects publish the AppImage itself. Some publish a zip holding it beside
a readme, and downloading that as though it were the program leaves Steam
launching a zip: the execute bit goes on, `exec` fails, and the game closes
instantly with nothing naming why.

So a source may say what to take out of the archive, and the rest of the
install -- the folder per emulator, the execute bit, the build record, the
sweep of the previous build -- is unchanged.

Every project and file here is made up.
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import net  # noqa: E402
from emulator_catalog import schema  # noqa: E402

_ENTRY = {
    "id": "packaged-port",
    "name": "Packaged Port",
    "source": {
        "kind": "github",
        "repo": "someone/packaged",
        "asset": "^Packaged-Linux\\.zip$",
        "extract": "^packaged\\.appimage$",
    },
    "args": "{rom}",
}

_ARCHIVE = os.path.join(TMP, "release", "Packaged-Linux.zip")
os.makedirs(os.path.dirname(_ARCHIVE), exist_ok=True)
with zipfile.ZipFile(_ARCHIVE, "w") as _bundle:
    _bundle.writestr("packaged.appimage", "#!/bin/sh\nexit 0\n")
    _bundle.writestr("readme.txt", "put your own copy of the game beside this")


def _fake_download(url, path, max_bytes=0, on_progress=None):
    """Stand in for the network: copy the archive where the installer wants it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(_ARCHIVE, "rb") as source, io.open(path, "wb") as handle:
        handle.write(source.read())
    return True, ""


section("the program is taken out of the archive")

_real_download = net.download
net.download = _fake_download
try:
    _path, _error = emu_install.install_appimage(
        _ENTRY, {"name": "Packaged-Linux.zip", "url": "https://example.test/a.zip",
                 "tag": "1.2.3"})
    check("the install succeeds", _error, "")
    check("and what is installed is the program, not the archive",
          os.path.basename(_path), "packaged.appimage")
    # Not the execute bit: this suite runs on Windows too, where chmod cannot
    # set one. What it can check is that the file the launcher will exec is the
    # one that exists.
    check("and it is really there", os.path.isfile(_path), True)

    _folder = sorted(os.listdir(os.path.dirname(_path)))
    # The archive goes: it is 28MB of what was already unpacked beside it, and
    # the sweep that clears a previous build would otherwise keep it forever as
    # the file the record names.
    check("the archive is not left behind", "Packaged-Linux.zip" in _folder, False)
    check("nor is anything else it held", "readme.txt" in _folder, False)
    check("and the build record names the release it came from",
          emu_install.installed_build(_ENTRY), "1.2.3")
finally:
    net.download = _real_download
    emulator_catalog.reload_imported()


section("an extract pattern has to be one")

_bad = dict(_ENTRY, source=dict(_ENTRY["source"], extract="^(unclosed"))
check("a pattern that is not a regex is refused",
      any("not a valid regex" in problem
          for problem in schema.validate(_bad, known_platforms=(), imported=True)),
      True)

_empty = dict(_ENTRY, source=dict(_ENTRY["source"], extract=""))
check("an empty one is refused, since it would match nothing",
      any("regex naming one file" in problem
          for problem in schema.validate(_empty, known_platforms=(), imported=True)),
      True)


if __name__ == "__main__":
    summary()
