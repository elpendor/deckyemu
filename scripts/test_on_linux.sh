#!/usr/bin/env bash
# Run the backend checks on Linux, because Windows does not fail the same way.
#
# **Two releases were pushed green from here and failed in CI on socket
# behaviour alone**, and neither was a test artefact: a listening socket closed
# under a blocked `accept()` keeps its port on Linux and frees it at once on
# Windows, and a socket closed with unread bytes in it sends RST on Linux and
# delivers the response on Windows. One broke the remembered transfer link, the
# other showed a refused upload as a dead connection.
#
#     scripts/test_on_linux.sh                          # everything CI runs
#     scripts/test_on_linux.sh scripts/tests/test_x.py  # one suite
#     scripts/test_on_linux.sh --deck [suite]           # on the Deck instead
#
# **Docker by default, because it is the CI image**: the same Python 3.11 on
# the same Debian base, so a pass here is the answer CI will give. The Deck is
# the fallback and a fine second opinion -- same kernel, same libc -- but it
# runs 3.13 inside a desktop session, so it is not the runner.
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="docker"
if [ "${1:-}" = "--deck" ]; then
  TARGET="deck"
  shift
fi
SUITE="${1:-}"

# What CI runs, in CI's order: the aggregate offline first, then every suite
# standalone -- a file can pass in the aggregate and fail alone, which is the
# thing running them one at a time exists to catch.
if [ -n "$SUITE" ]; then
  SCRIPT="python \"$SUITE\""
else
  SCRIPT='python scripts/test_backend.py --offline && for suite in scripts/tests/test_*.py; do echo "--- $suite"; python "$suite" > /tmp/suite.log 2>&1 || { tail -40 /tmp/suite.log; echo "FAILED: $suite"; exit 1; }; done && python -m compileall -q main.py py_modules && echo "ALL LINUX CHECKS PASSED"'
fi

if [ "$TARGET" = "docker" ] && docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
  # `pwd -W` because the daemon takes a Windows path and this script is run
  # from Git Bash, which would otherwise hand it an /e/... that does not exist
  # on the other side. MSYS_NO_PATHCONV stops the same translation being
  # applied to the container-side paths.
  HOST="$(pwd -W 2>/dev/null || pwd)"
  echo "==> python:3.11 in docker, as CI runs it"
  # No bytecode, or the tree fills with __pycache__ owned by root.
  MSYS_NO_PATHCONV=1 docker run --rm \
    -v "${HOST}:/src" -w /src -e PYTHONDONTWRITEBYTECODE=1 \
    python:3.11 bash -c "$SCRIPT"
  exit $?
fi

if [ "$TARGET" = "docker" ]; then
  echo "--> docker is not running; using the Deck instead" >&2
fi

REMOTE="${DECK_SSH:-deck@steamdeck.local}"
WHERE="/tmp/deckyemu-suite"
echo "==> copying the tree to ${REMOTE}:${WHERE}"
tar czf - --exclude=node_modules --exclude=.git --exclude=__pycache__ \
  --exclude=dist --exclude='*.pyc' . \
  | ssh "$REMOTE" "rm -rf '$WHERE' && mkdir -p '$WHERE' && tar xzf - -C '$WHERE'"
ssh "$REMOTE" "cd '$WHERE' && ${SCRIPT//python /python3 }"
