#!/usr/bin/env python3
"""The transfer dialog lists the folder the server is actually saving into.

    python scripts/tests/test_inbox_folder.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import fileserver  # noqa: E402

section("a send pointed somewhere other than the ROM inbox")

# `FirmwarePanel` starts the server on the firmware folder so a BIOS does not
# land among the games. Everything that answered "what is waiting" read the ROM
# inbox regardless, so the file vanished from the dialog's list the moment it
# arrived -- which reads as a failed transfer -- and the delete button beside
# such a row could never find the file it was about.

_elsewhere = os.path.join(TMP, "not-the-rom-inbox")
os.makedirs(_elsewhere, exist_ok=True)

_served = fileserver.start(_elsewhere)

if _served.get("error"):
    print("SKIP file server (%s)" % _served["error"])
else:
    check("the list reads the folder this server was started on",
          fileserver.saving_into(), _elsewhere)

    with io.open(os.path.join(_elsewhere, "bios.bin"), "wb") as _handle:
        _handle.write(b"not a rom")
    check("so a file that landed there is listed",
          [entry["name"] for entry in fileserver.received_files()], ["bios.bin"])
    check("and the buttons beside that row can reach it",
          os.path.dirname(fileserver.inbox_path("bios.bin")), _elsewhere)

    fileserver.stop()
    # With nothing running there is no server to follow, and the ROM inbox is
    # the honest answer -- it is what a panel asking outside a transfer means.
    check("with the server stopped it falls back to the ROM inbox",
          fileserver.saving_into(), fileserver.default_dir(create=False))

if __name__ == "__main__":
    summary()
