#!/usr/bin/env python3
"""Timing a storage: real-sized files, the real flags, and nothing left behind.

    python scripts/tests/test_cloud_speed.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import TMP, check, section, summary  # noqa: E402

import cloudsave  # noqa: E402
import cloudsync  # noqa: E402

_scratch = os.path.join(TMP, "speed-scratch")
_calls = []
_real_rclone = cloudsave.rclone
_real_compare = cloudsync._by_content


def _fake(args, _timeout):
    _calls.append(list(args))
    if args[0] == "copy":
        sent = os.listdir(args[1])
        _calls[-1].append(len(sent))
    return True, ""


try:
    cloudsave.rclone = _fake
    cloudsync._by_content = lambda _remote: ["--checksum"]

    section("a storage that answers")
    _result = cloudsync.speed_test("box", _scratch)
    _copies = [call for call in _calls if call[0] == "copy"]
    check("copies twice: once to send, once with nothing changed", len(_copies), 2)
    check("the files saves are made of", _copies[0][-1], cloudsync.SPEED_FILES)
    check("with the flags a real copy uses",
          ("--checkers" in _copies[0], "--checksum" in _copies[0]), (True, True))
    check("into its own folder", _copies[0][2], "box:DeckyEmu/.speed-test")
    check("which is removed after", _calls[-1], ["purge", "box:DeckyEmu/.speed-test"])
    check("and so is the local copy", os.path.exists(_scratch), False)
    check("timed", (_result["ok"], "upload" in _result, "check" in _result), (True, True, True))

    section("a storage that does not")
    _calls.clear()
    cloudsave.rclone = lambda args, _t: (_calls.append(list(args)) or
                                         (args[0] != "copy", "no route to host"))
    _failed = cloudsync.speed_test("box", _scratch)
    check("says why", _failed, {"ok": False, "error": "no route to host"})
    check("and still cleans up", (_calls[-1][0], os.path.exists(_scratch)), ("purge", False))
    section("a bucket storage")
    _real_kinds = cloudsave.remote_kinds
    cloudsave.remote_kinds = lambda: {"bucket": "s3"}
    try:
        check("uses the lowercase root", cloudsync.speed_folder("bucket"),
              "deckyemu/.speed-test")
    finally:
        cloudsave.remote_kinds = _real_kinds
finally:
    cloudsave.rclone = _real_rclone
    cloudsync._by_content = _real_compare

if __name__ == "__main__":
    summary()
