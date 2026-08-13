#!/usr/bin/env python3
"""What the update path accepts from the outside.

    python scripts/tests/test_update_path.py

Self-hosted distribution makes this the only channel there is, so the values it
takes on trust are worth naming: a URL out of a releases API, a filename out of
the same, and a token off the loopback socket.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary, TMP  # noqa: E402

import fileserver  # noqa: E402
import handoff  # noqa: E402
import net  # noqa: E402

section("only HTTP addresses are fetched")

# urllib understands file: and ftp: too, so an asset whose download URL is not
# ours would otherwise choose which handler runs.
check("a plain https url is fetchable", net.is_web_url("https://example.com/a.zip"), True)
check("and http, since the loopback handoff is one",
      net.is_web_url("http://127.0.0.1:8000/x/deckyemu.zip"), True)
for _bad in ("file:///etc/passwd", "ftp://example.com/a.zip", "javascript:0",
             "https://", "", None):
    check("%r is not fetched" % (_bad,), net.is_web_url(_bad), False)

# The readers, not just the predicate: this is what would actually have copied a
# local file into the emulator folder.
check("get_bytes refuses one outright", net.get_bytes("file:///etc/passwd"), (None, None))
_ok, _error = net.download("file:///etc/passwd", os.path.join(TMP, "stolen"))
check("and download says so rather than writing it", (_ok, bool(_error)), (False, True))
check("nothing was written", os.path.exists(os.path.join(TMP, "stolen")), False)

section("a token off the network cannot raise inside the handler")

# compare_digest refuses a str holding a non-ASCII character, and
# BaseHTTPRequestHandler decodes the request line as latin-1 -- so a raw high
# byte in the path becomes one. handoff compared with compare_digest directly
# and would have raised where fileserver answers 404; both now share this.
check("a matching secret still matches", fileserver.same_secret("abc", "abc"), True)
check("a wrong one does not", fileserver.same_secret("abd", "abc"), False)
check("and an accented path is a mismatch, not an exception",
      fileserver.same_secret("töken", "token"), False)
check("nothing matches when there is no secret to match",
      fileserver.same_secret("anything", ""), False)
check("handoff uses that comparison rather than its own",
      handoff.same_secret is fileserver.same_secret, True)

section("the update is written under a name that cannot leave the runtime dir")

# The name arrives from the releases API and decides a path. Asserted against
# main.py's own line rather than by staging a release, which would need the
# network: what matters is that the value is reduced to a basename first.
with open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "main.py"), encoding="utf-8") as _handle:
    _main = _handle.read()
check("stage_update takes the basename of the asset name",
      'os.path.basename(release.get("asset_name") or "") or "deckyemu.zip"' in _main,
      True)


if __name__ == "__main__":
    summary()
