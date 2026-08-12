#!/usr/bin/env python3
"""Turn the commits in a release into the notes that ship with it.

    python scripts/changelog.py v0.3.0..HEAD

Fully generated: there is no CHANGELOG.md to keep in step, and the subject line
written at commit time *is* the changelog entry. A `feat:`/`fix:`/`perf:`/
`internal:` prefix only decides which heading it sits under.

Grouping rather than filtering is the point. Nothing is ever dropped, so a
forgotten prefix is not a silent omission -- the commit turns up under "Other",
which is visible and mildly annoying and therefore self-correcting. Filtering
would mean a changelog that is quietly wrong, which is worse than one that is
obviously untidy, and it would need CI to reject a release over a typo to be
trustworthy at all.

There is deliberately no attempt to guess a section from the files a commit
touched. That was measured and it does not work: `Drop the eslint directives`
touches only `src/` and is pure housekeeping, while `Probe thumbnail candidates
concurrently` touches only `py_modules/` and is the largest user-visible change
in its release. Whether a change is worth telling someone about is known when it
is written and nowhere else.
"""

import re
import subprocess
import sys

# Order is the order they appear in the notes: what someone reads first should be
# what they most likely came for.
SECTIONS = (
    ("feat", "New"),
    ("fix", "Fixed"),
    ("perf", "Faster"),
    ("internal", "Under the hood"),
)

# Where an unprefixed subject goes. Last, so it reads as the leftovers it is.
OTHER = "Other"

# `feat: x`, `fix(store): x`, `perf!: x` -- the scope and the breaking-change
# marker are accepted and ignored, so the convention degrades to plain
# conventional-commits if a tool is ever pointed at this history.
_PREFIX_RE = re.compile(
    r"^(%s)(\([^)]*\))?!?:\s*" % "|".join(name for name, _title in SECTIONS),
    re.IGNORECASE,
)

# CI writes this commit itself; it says nothing a reader wants.
_RELEASE_RE = re.compile(r"^Release v\d", re.IGNORECASE)


def classify(subject):
    """(section title, entry text) for one commit subject, or None to skip it."""
    subject = (subject or "").strip()
    if not subject or _RELEASE_RE.match(subject):
        return None

    match = _PREFIX_RE.match(subject)
    if not match:
        return OTHER, subject

    title = dict(SECTIONS)[match.group(1).lower()]
    text = subject[match.end():].strip()
    if not text:
        return None
    # The prefix eats the capital the subject would otherwise have started with.
    return title, text[0].upper() + text[1:]


def render(subjects):
    """Markdown for `subjects`, newest first within each section. '' if empty."""
    grouped = {}
    for subject in subjects:
        entry = classify(subject)
        if entry is None:
            continue
        title, text = entry
        # Deduplicated: a cherry-pick or a reworded retry of the same change
        # should not be listed twice.
        if text not in grouped.setdefault(title, []):
            grouped[title].append(text)

    order = [title for _name, title in SECTIONS] + [OTHER]
    blocks = []
    for title in order:
        entries = grouped.get(title)
        if not entries:
            continue
        blocks.append("## %s\n\n%s" % (title, "\n".join("- %s" % e for e in entries)))
    return "\n\n".join(blocks)


def subjects_in(range_spec):
    """Commit subjects in `range_spec`, newest first. Empty when git cannot say."""
    argv = ["git", "log", "--no-merges", "--format=%s"]
    if range_spec:
        argv.append(range_spec)
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        # A shallow clone has no tags and no range to walk. Notes are worth
        # having but not worth failing a release over, so this is reported and
        # the caller ships without them.
        print("changelog: could not read %r: %s" % (range_spec, error), file=sys.stderr)
        return []
    return [line for line in done.stdout.splitlines() if line.strip()]


def previous_tag():
    """The newest release tag, or '' when this is the first release."""
    try:
        done = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=-v:refname"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    tags = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    return tags[0] if tags else ""


def main(argv):
    if len(argv) > 1:
        range_spec = argv[1]
    else:
        tag = previous_tag()
        range_spec = "%s..HEAD" % tag if tag else ""
    sys.stdout.write(render(subjects_in(range_spec)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
