#!/usr/bin/env python3
"""A rate-limited address must not be reported as a project that moved away.

    python scripts/tests/test_asset_failures.py

GitHub gives an unauthenticated caller 60 requests an hour per address, and a
Deck sitting on the same network as the machine being developed on shares that
budget with it. Reaching zero is ordinary and temporary.

What made it expensive was the reading. `net.get_json` answers None for every
kind of failure, and the emulator downloads took None to mean the repository was
gone: "No release came back for xemu-project/xemu-hdd-image. The project may
have moved off GitHub." Nothing had moved, the file was exactly where it always
is, and the state cleared itself within the hour -- but the sentence sends the
reader to look at somebody else's repository instead of at the clock.

The update check had already been fixed for the identical status, in its own
file, with its own reading of the same three keys. That is the part worth
keeping an eye on: two callers interpreting one dict is how they came to
disagree, so the reading is `net.failure_message` now and this checks both ends
of it agree.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402  -- installs the decky stub

import emu_install  # noqa: E402
import net  # noqa: E402
import releases  # noqa: E402


def _answering(status, remaining="", payload=None):
    """A `net.get_json` that fails the way a real server does, or succeeds."""

    def fake(url, headers=None, failure=None):
        if status and failure is not None:
            failure["status"] = status
            failure["rate_remaining"] = remaining
            failure["retry_after"] = ""
        return payload

    return fake


section("the reading of a failed request -- one dict, one interpretation")

check("a spent budget is named as one",
      "rate-limiting" in net.failure_message(
          {"status": 403, "rate_remaining": "0"}, "the thing"),
      True)
check("and so is the newer status GitHub returns for it",
      "rate-limiting" in net.failure_message(
          {"status": 429, "rate_remaining": "0"}, "the thing"),
      True)
# A 403 with budget left is a refusal about this request, not about the address,
# and telling somebody to wait an hour would waste it.
check("a 403 with budget left is not called a rate limit",
      "rate-limiting" in net.failure_message(
          {"status": 403, "rate_remaining": "57"}, "the thing"),
      False)
# The sentence is built by hand from two slices of `subject`, which is easy to
# get wrong in a way that reads almost right -- `%` binds tighter than `+`.
check("a 404 says what was not found, with the subject intact",
      net.failure_message({"status": 404}, "the latest release of xemu"),
      "The latest release of xemu was not found.")
check("and a caller with something better to say gets to say it",
      net.failure_message({"status": 404}, "x", not_found="Look for it by hand."),
      "Look for it by hand.")
# Empty rather than a sentence: no status means the request never reached
# anything, and only the caller knows what to say about its own subject.
check("no status is left to the caller", net.failure_message({}, "the thing"), "")


section("the emulator downloads -- what the xemu hard disk image reported")

_real_get_json = net.get_json
try:
    net.get_json = _answering(403, "0")

    _asset, _error = emu_install.resolve_release_asset(
        "xemu-project/xemu-hdd-image", r"^xbox_hdd\.qcow2\.zip$")
    check("a rate-limited fetch resolves nothing", _asset, None)
    check("and says the network is rate-limited", "rate-limiting" in _error, True)
    # The whole bug: a confident wrong answer about somebody else's repository.
    check("and does not claim the project moved away", "moved off" in _error, False)
    check("and names what was being looked up", "xemu-hdd-image" in _error, True)

    _builds, _error = emu_install.resolve_release_list(
        "xemu-project/xemu-hdd-image", r"^xbox_hdd\.qcow2\.zip$")
    check("the build list is rate-limited in the same words", "rate-limiting" in _error, True)
    check("and does not blame the project either", "moved off" in _error, False)

    # Both halves of the plugin now say the same thing for the same status,
    # which is the property that was missing rather than either wording.
    check("and the update check agrees with them",
          "rate-limiting" in releases._failure_message(
              {"status": 403, "rate_remaining": "0"}),
          True)

    # The case the old sentence was written for, which must survive: a request
    # that got no answer at all. 451 is what the Ryujinx mirrors return and it
    # has no branch of its own, so it lands here too.
    net.get_json = _answering(None)
    _asset, _error = emu_install.resolve_release_asset("someone/gone", r"^x$")
    check("a request that answered nothing still suspects the project",
          "moved off" in _error, True)
finally:
    # Restored, or every file that runs after this one gets the stub. That is
    # invisible until something asserts on a real lookup.
    net.get_json = _real_get_json

check("the real lookup is back in place", net.get_json is _real_get_json, True)


if __name__ == "__main__":
    summary()
