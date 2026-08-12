#!/usr/bin/env python3
"""The controller profile handed to RetroArch for Steam Input's virtual pad.

    python scripts/tests/test_pad_profile.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import launchers  # noqa: E402

section("the pad Steam hands a game, which matches no shipped profile")
# RetroArch ships 1035 controller profiles and matches on vendor and product id.
# Steam Input's virtual pad calls itself "Microsoft X-Box 360 pad" and carries
# Valve's ids, so the profile whose bindings are exactly right is rejected
# before its name is considered, and an unconfigured pad has no bindings at all:
# the game runs and the controller does nothing.
#
#   [Autoconf] Microsoft X-Box 360 pad 0 (10462/4607) not configured.
#
# Found on a Deck after a reset deleted RetroArch's downloaded profiles, and the
# bindings below were confirmed working there before being written down.
_pad_dir = launchers.write_pad_profile()
_pad_file = os.path.join(_pad_dir, "udev", "Steam Virtual Gamepad.cfg")
check("the profile is written where RetroArch looks", os.path.isfile(_pad_file), True)
_pad = open(_pad_file, encoding="utf-8").read()
# The ids are the whole point: with the bundled profile's Microsoft ids this
# file would be rejected exactly as the bundled one is.
check("under Valve's ids, not Microsoft's",
      ('input_vendor_id = "10462"' in _pad, 'input_product_id = "4607"' in _pad),
      (True, True))
check("for the driver RetroArch actually chose", 'input_driver = "udev"' in _pad, True)
check("with the face buttons the hardware reported",
      [line for line in _pad.splitlines() if line.startswith("input_b_btn")],
      ['input_b_btn = "0"'])
check("and every launch is pointed at it",
      "joypad_autoconfig_dir" in
      open(launchers.write_override_config("startup", "off"), encoding="utf-8").read(),
      True)


if __name__ == "__main__":
    summary()
