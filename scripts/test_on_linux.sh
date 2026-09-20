#!/usr/bin/env bash
# Run the backend suite on Linux, because Windows does not fail the same way.
#
# **Two releases were pushed green and failed in CI on socket behaviour alone.**
# A socket closed with unread bytes in it sends RST on Linux and delivers the
# response on Windows; a listening socket closed under a blocked `accept()`
# keeps its port on Linux and frees it on Windows. Both passed every check on
# the development machine and both broke a feature on the Deck.
#
# The Deck is the Linux box this project always has. It is not the CI image --
# Python 3.13 rather than 3.11, and a desktop session with a D-Bus bus of its
# own, so the bus checks report the real one and fail here -- but it is the same
# kernel and the same libc as the runner, which is where this class of bug
# lives.
#
#     scripts/test_on_linux.sh              # the whole backend suite
#     scripts/test_on_linux.sh scripts/tests/test_httpshim.py
#
# The tree is copied to /tmp on the Deck and run there. Nothing is installed and
# the deployed plugin is untouched.
set -euo pipefail

REMOTE="${DECK_SSH:-deck@steamdeck.local}"
WHERE="/tmp/deckyemu-suite"
SUITE="${1:-scripts/test_backend.py}"

cd "$(dirname "$0")/.."

echo "==> copying the tree to ${REMOTE}:${WHERE}"
tar czf - --exclude=node_modules --exclude=.git --exclude=__pycache__ \
  --exclude=dist --exclude='*.pyc' . \
  | ssh "$REMOTE" "rm -rf '$WHERE' && mkdir -p '$WHERE' && tar xzf - -C '$WHERE'"

echo "==> ${SUITE}"
# The D-Bus checks are the known difference and they are named rather than
# filtered: a run here is read, not gated on.
ssh "$REMOTE" "cd '$WHERE' && python3 '$SUITE'"
