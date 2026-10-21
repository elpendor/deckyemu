"""Turning `flatpak install` output into something a progress bar can say.

Run with `-y` and without `--noninteractive`, flatpak prints its plan first --
one numbered row per ref, with its download size -- and then a line per step
with a percentage. A first install on a fresh Deck pulls five or more shared
runtimes before the app, so "Installing runtime/org.freedesktop.Platform.GL..."
for minutes read as stuck. This names each part, counts it against the plan,
and fills one bar across all of them, weighted by size.

The `--noninteractive` shape (a bare "Installing <ref>" per step, no plan, no
percentages) is understood too, since update and downgrade still use it.
"""

import re

# " 1.\t   \tio.github.example.App\tstable\ti\tflathub\t< 2.8 MB"
_PLAN_ROW = re.compile(r"^\s*(\d+)\.\s")
_STEP = re.compile(r"^(Installing|Updating)\b\s*(?:(\d+)/(\d+))?")
_BARE_REF = re.compile(r"^(?:Installing|Updating)\s+(?:app|runtime)/([^/\s]+)/")
_PERCENT = re.compile(r"(?<!\d)(\d{1,3})\s*%")
_SIZE = re.compile(r"([\d.,]+)\s*([kMG]?)B\b")
_UNITS = {"": 1, "k": 1e3, "M": 1e6, "G": 1e9}

# Most specific first: the base runtime's id is a prefix of every extension's.
_NAMES = (
    (".GL32.", "32-bit graphics drivers"),
    (".GL.", "graphics drivers"),
    (".VAAPI", "video decoding"),
    (".amd.", "AMD video support"),
    ("codecs", "video codecs"),
    ("ffmpeg", "video codecs"),
    (".Locale", "translations"),
    ("org.kde.Platform", "KDE runtime"),
    ("org.gnome.Platform", "GNOME runtime"),
    ("org.freedesktop.Platform", "base runtime"),
    (".Sdk", "SDK"),
)


def describe(ref_id, app_id="", app_name=""):
    """A name a person can read for one flatpak id."""
    if app_id and ref_id == app_id:
        return app_name or ref_id
    for needle, name in _NAMES:
        if needle in ref_id:
            return name
    return ref_id.rsplit(".", 1)[-1]


def _bytes(cell):
    match = _SIZE.search(cell.replace(" ", " ").replace("\xa0", " "))
    if not match:
        return 0
    return float(match.group(1).replace(",", "")) * _UNITS[match.group(2)]


class Progress:
    """Feed it flatpak's lines; it answers (text, percent) or None to skip."""

    def __init__(self, app_id="", app_name=""):
        self.app_id = app_id
        self.app_name = app_name
        self.plan = []  # [(id, bytes)] in the order flatpak will run them
        self.step = 0
        self.index = 0  # the part under way, when flatpak does not number them
        self.last = -1

    def _label(self, index, total):
        ref_id = self.plan[index][0] if index < len(self.plan) else ""
        name = describe(ref_id, self.app_id, self.app_name) if ref_id else (
            self.app_name or "the app")
        if total > 1:
            return "Downloading %s (%d of %d)" % (name, index + 1, total)
        return "Downloading %s" % name

    def _overall(self, index, percent):
        sizes = [size for _id, size in self.plan]
        if len(sizes) > 1 and all(sizes):
            done = sum(sizes[:index]) + sizes[index] * percent / 100.0
            return int(done * 100 / sum(sizes))
        if self.plan:
            return int((index + percent / 100.0) * 100 / len(self.plan))
        return percent

    def feed(self, line):
        text = line.strip()
        if _PLAN_ROW.match(text) and "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
            ids = [cell for cell in cells[1:] if re.match(r"^[A-Za-z][\w-]*(\.[\w-]+)+$", cell)]
            if ids:
                self.plan.append((ids[0], _bytes(cells[-1])))
            return None

        bare = _BARE_REF.match(text)
        if bare:
            self.step += 1
            name = describe(bare.group(1), self.app_id, self.app_name)
            return ("Downloading %s (part %d)" % (name, self.step), -1)

        step = _STEP.match(text)
        if not step:
            return None
        percents = [int(p) for p in _PERCENT.findall(text) if int(p) <= 100]
        if step.group(2):
            index, total = int(step.group(2)) - 1, int(step.group(3))
        else:
            # Unnumbered: a percentage falling back means the next part began.
            if percents and percents[-1] < self.last:
                self.index = min(self.index + 1, max(0, len(self.plan) - 1))
            index, total = self.index, max(1, len(self.plan))
        if percents:
            self.last = percents[-1]
        if not percents:
            return (self._label(index, total), self._overall(index, 0) if self.plan else -1)
        return (self._label(index, total), self._overall(index, percents[-1]))
