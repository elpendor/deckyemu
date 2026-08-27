#!/usr/bin/env python3
"""Is every workaround still needed, and does every patch still fit?

    python scripts/check_workarounds.py                     # everything
    python scripts/check_workarounds.py vita3k              # one entry
    python scripts/check_workarounds.py vita3k --build 3829 # against one build

Exit 0 when nothing needs doing. Exit 1 when something does, *or* when
something could not be checked -- an unauthenticated run hits GitHub's rate
limit quickly, and reporting "all clear" for a question nobody managed to ask
would be the one answer worse than either. Pass a token to avoid it:

    GITHUB_TOKEN=$(gh auth token) python scripts/check_workarounds.py

`--build` names a release tag instead of taking the newest, which is how you
answer "would the patch fit that one" without installing it. It is also how the
one confusing case was pinned down: Vita3K 3829 refuses the patch, and it does so
because it *predates the bug*, not because anything is wrong.

A workaround exists to be deleted. The catalog says which upstream fix will
retire it, and `fixed_in` says which build carries that fix -- but somebody has
to notice the fix landed and write the build number in, and nobody watches an
issue tracker for a year. This is what watches it.

It asks two independent questions and expects them to agree:

* **Is the upstream fix still open?** The `upstream` URL, read through the
  GitHub API. Merged or closed means `fixed_in` is probably owed a value.
* **Does the patch still fit the current upstream build?** For a workaround
  that edits the emulator's binary, the newest release is downloaded and the
  signature re-checked. A signature that stops matching means either upstream
  fixed the bug or moved the code, and the file cannot tell those apart.

Agreement is what makes either safe to act on. A merged PR alone does not say
which *build* carries it, and a signature that stopped matching does not say
why -- Vita3K build 3829 predates the bug entirely and refuses the patch for
that reason alone. Two signals pointing the same way is a much better prompt
than either on its own, and it arrives before a user launches a game into it,
which matters because upstream ships a rolling release and a bad build reaches
everyone at once.

What this deliberately does *not* do is edit the catalog. Choosing the first
build that carries a fix is a judgement -- name one too low and the panel tells
people to switch off a fix they still need -- so it reports and a person
decides.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import REPO_ROOT  # noqa: E402  -- installs the decky stub

sys.path.insert(0, os.path.join(REPO_ROOT, "py_modules"))

import emu_install  # noqa: E402
import emu_patch  # noqa: E402
import emulator_catalog  # noqa: E402

#: Where a downloaded build is unpacked. Beside the script's own scratch, and
#: cleared between entries -- these are 60MB+ each and CI runners are small.
WORK = os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", "workaround-check")

_API = "https://api.github.com"

#: `https://github.com/<owner>/<repo>/(pull|issues)/<number>`, which is the only
#: shape `upstream` takes today. Anything else is reported rather than guessed
#: at: an unrecognised tracker is a thing to notice, not to silently skip.
_UPSTREAM_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+)/(pull|issues)/(\d+)/?$")

#: Things a person has to decide about.
_problems = []

#: Things that could not be checked at all. Separate because they are not
#: findings -- a rate limit is not a workaround needing attention -- but they
#: still fail the run, because a check that did not happen has no result.
_blocked = []

#: Things worth mentioning that stop nothing.
_notes = []


def _get(url):
    """Parsed JSON from `url`, or None. Never raises."""
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "deckyemu-workaround-check",
    })
    # CI passes a token purely for the rate limit; unauthenticated works too,
    # slowly, which is why its absence is not an error.
    token = os.environ.get("GITHUB_TOKEN") or ""
    if token:
        request.add_header("Authorization", "Bearer %s" % token)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError, OSError) as error:
        print("      could not read %s: %s" % (url, error))
        return None


def upstream_state(url):
    """('open'|'closed'|'merged'|'unknown', detail) for an `upstream` url."""
    match = _UPSTREAM_RE.match(url or "")
    if not match:
        return "unknown", "not a GitHub issue or pull request"
    owner, repo, kind, number = match.groups()
    # Issues and pull requests share a number space, and the issues endpoint
    # answers for both -- but only the pulls endpoint knows about `merged`.
    where = "pulls" if kind == "pull" else "issues"
    data = _get("%s/repos/%s/%s/%s/%s" % (_API, owner, repo, where, number))
    if not isinstance(data, dict):
        return "unknown", "could not be read"
    if data.get("merged"):
        return "merged", "merged %s" % (data.get("merged_at") or "")[:10]
    state = data.get("state") or "unknown"
    if state == "closed":
        return "closed", "closed %s" % (data.get("closed_at") or "")[:10]
    return "open", "still open"


def release_asset(entry, tag=""):
    """(tag, url, unreachable) for one release -- the newest, or `tag`.

    Being able to name one is why the source moved to `Vita3K/Vita3K-builds`:
    the main repo publishes a single rolling `continuous`, so there is nothing
    to ask for.

    `unreachable` separates "the API did not answer" from "no such release", and
    that distinction is not pedantry: a rate-limited lookup once reported itself
    as *there is no build 3829*, which is a confident claim about a release that
    exists, produced by a request nobody managed to make.
    """
    source = entry.get("source") or {}
    if source.get("kind") != "github" or source.get("host"):
        return "", "", ""
    if tag:
        one = _get("%s/repos/%s/releases/tags/%s" % (_API, source["repo"], tag))
        if one is None:
            return "", "", "could not read release %s of %s" % (tag, source["repo"])
        releases = [one] if isinstance(one, dict) else []
    else:
        data = _get("%s/repos/%s/releases?per_page=20" % (_API, source["repo"]))
        if data is None:
            return "", "", "could not read the releases of %s" % source["repo"]
        releases = data if isinstance(data, list) else []
    matcher = re.compile(source.get("asset") or "")
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        for asset in release.get("assets") or []:
            if matcher.match(asset.get("name") or ""):
                return (release.get("tag_name") or "",
                        asset.get("browser_download_url") or "", "")
    return "", "", ""


def patch_fits(spec, url):
    """(fits, detail) for `spec` against the build at `url`.

    Runs the real patcher against a real download, because the interesting
    failure is a build that changed shape and no amount of reasoning about the
    catalog can see one of those.
    """
    if not shutil.which("unsquashfs"):
        return None, "unsquashfs is not installed"
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    image = os.path.join(WORK, "build.AppImage")
    try:
        subprocess.run(["curl", "-sSfL", "-o", image, url], check=True, timeout=900)
    except (subprocess.SubprocessError, OSError) as error:
        return None, "could not download the build: %s" % error

    offset, error = emu_patch._payload_offset(image)
    if error:
        return None, error
    payload = os.path.join(WORK, "payload.sqfs")
    with open(image, "rb") as source:
        source.read(offset)
        with open(payload, "wb") as out:
            shutil.copyfileobj(source, out)
    tree = os.path.join(WORK, "root")
    result = subprocess.run(["unsquashfs", "-d", tree, "-no-progress", payload],
                            capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        return None, "could not unpack the build"

    member = os.path.join(tree, spec.get("file") or "")
    if not os.path.isfile(member):
        return False, "%s is not in this build" % spec.get("file")
    with open(member, "rb") as handle:
        buf = bytearray(handle.read())
    _, failure = emu_patch.patch_bytes(buf, spec)
    return (not failure), (failure or "one match inside %s" % spec.get("within"))


def check(entry, wanted_build=""):
    workarounds = emulator_catalog.workarounds_for(entry)
    if not workarounds:
        return
    print("")
    print(entry["id"])
    tag, url, unreachable = "", "", ""

    for item in workarounds:
        name = item.get("id") or "?"
        print("  %s" % name)

        state, detail = upstream_state(item.get("upstream"))
        print("    upstream: %-8s %s" % (state, detail))
        if state in ("merged", "closed"):
            _problems.append(
                "%s/%s: upstream is %s (%s). Find the first build carrying it "
                "and set `fixed_in`." % (entry["id"], name, state, detail))
        elif state == "unknown":
            _blocked.append("%s/%s: upstream %s" % (entry["id"], name, detail))

        spec = (item.get("apply") or {}).get("patch")
        if spec:
            if not url:
                tag, url, unreachable = release_asset(entry, wanted_build)
            if unreachable:
                _blocked.append("%s/%s: %s" % (entry["id"], name, unreachable))
            elif not url:
                _problems.append(
                    "%s/%s: no release to check the patch against%s"
                    % (entry["id"], name,
                       " -- there is no build %s" % wanted_build if wanted_build else ""))
            else:
                fits, detail = patch_fits(spec, url)
                print("    patch:    %-8s %s (build %s, %s)"
                      % ({True: "fits", False: "REFUSED"}.get(fits, "unknown"),
                         detail, tag, "asked for" if wanted_build else "newest"))
                if fits is False:
                    _problems.append(
                        "%s/%s: the patch no longer fits build %s -- %s. Either "
                        "upstream fixed it (set `fixed_in`) or the code moved "
                        "(update `find`/`within`)."
                        % (entry["id"], name, tag, detail))
                elif fits is None:
                    _blocked.append("%s/%s: the patch was not checked -- %s"
                                    % (entry["id"], name, detail))

        if item.get("fixed_in"):
            # A `fixed_in` nobody can reach yet is not wrong, but it is worth
            # saying out loud: until a build carries it, nothing is ever shown.
            reached = emulator_catalog.schema.build_at_least(tag, item["fixed_in"])
            print("    fixed_in: %s (build %s %s it)"
                  % (item["fixed_in"], tag, "reaches" if reached else "is below"))


def main():
    args = list(sys.argv[1:])
    build = ""
    if "--build" in args:
        at = args.index("--build")
        build = args[at + 1] if at + 1 < len(args) else ""
        del args[at:at + 2]
    for arg in list(args):
        if arg.startswith("--build="):
            build = arg.split("=", 1)[1]
            args.remove(arg)
    # A tag becomes part of a URL, and this one arrives from a command line or
    # a workflow input rather than from the catalog.
    if build and not emu_install.valid_tag(build):
        print("Not a release tag: %r" % build)
        return 2

    wanted = [name for name in args if not name.startswith("-")]
    for entry in emulator_catalog.CATALOG:
        if wanted and entry["id"] not in wanted:
            continue
        check(entry, build)
    shutil.rmtree(WORK, ignore_errors=True)

    print("")
    print("=" * 70)
    for note in _notes:
        print("note: %s" % note)
    if _problems:
        print("%d thing(s) need a decision:" % len(_problems))
        for problem in _problems:
            print("  - %s" % problem)
    if _blocked:
        print("%d thing(s) could not be checked:" % len(_blocked))
        for blocked in _blocked:
            print("  - %s" % blocked)
    if not _problems and not _blocked:
        print("Every workaround is still needed and every patch still fits.")
        return 0
    # Non-zero so the schedule mails somebody. There is nothing to do
    # automatically: naming the first build that carries a fix is a judgement,
    # and getting it wrong tells people to switch off a fix they still need.
    return 1


if __name__ == "__main__":
    sys.exit(main())
