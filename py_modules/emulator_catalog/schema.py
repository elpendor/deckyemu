"""What an emulator entry may contain, and a check that one is well formed.

This file is the reference. Adding an emulator means writing a module next to
this one whose `ENTRY` uses the fields below; nothing else in the package needs
to learn about it beyond one line in `__init__.py`.

The check exists because every one of these fields fails *quietly* when it is
wrong. A misspelt `fullscreen_arg` is not an error -- `entry.get` returns "" and
the emulator launches in a window. An `args` string with no `{rom}` placeholder
installs fine and then starts the emulator with no game. A `dest` that names an
absolute path escapes the sandbox the installer assumes. None of that surfaces
until someone runs the emulator on a Deck, which is the slowest possible place
to find out. `validate` turns each into a message at test time instead.

Deliberately not a JSON Schema or a dataclass. The entries stay plain dicts
because that is the shape `to_emulator` and `listing` read, because comments
between the keys are half of what the catalog is worth, and because an entry
loaded from a file later (see `__init__.py`) has to be checkable by exactly the
same function that checks a bundled one.
"""

import re

#: Fields every entry must carry.
REQUIRED = {
    "id": "Short lowercase identifier. Becomes a directory name for AppImages, "
          "so it must match `is_safe_id`. Never change one after release: it is "
          "what an installed emulator is recorded under.",
    "name": "Display name, shown in the emulator list.",
    "summary": "One line under the name. Say which system it runs.",
    "source": "How to install it: {'kind': 'flatpak', 'id': ...} or "
              "{'kind': 'appimage', ...}. See emu_install.",
    "args": "Launch arguments, with `{rom}` where the ROM path goes.",
}

#: Fields an entry may carry, with what each is for.
OPTIONAL = {
    "databases": "libretro system names this emulator runs, e.g. "
                 "['Sony - PlayStation']. Buys ROM extensions, boxart, name "
                 "cleanup and collection grouping at once -- extensions are "
                 "derived from these, never stored. Empty only for a system "
                 "libretro has no database for, which then needs `platform`.",
    "platform": "Platform label, for the systems libretro has no database for. "
                "Must appear in `platforms.NO_LIBRETRO_PLATFORMS`. Do not set "
                "it as well as `databases` -- that is two sources for one fact.",
    "fullscreen_args": "The switch that starts fullscreen, or omit when the "
                       "emulator has none and uses a config setting instead.",
    "installed_args": "How to start a title the emulator has already installed, "
                      "when a file path will not do it. `{title}` is the title "
                      "id. Vita3K only.",
    "splits_args": "True when the emulator's own launcher word-splits the "
                   "arguments it is given, so a path with a space in it "
                   "arrives as several. Every file path handed to it is then "
                   "replaced by a space-free link. Vita3K only -- its AppImage "
                   "runs `\"$APPDIR/usr/bin/Vita3K\" $@`, unquoted.",
    "command": "The binary to run inside the flatpak, when it is not the one "
               "the manifest names.",
    "env": "Environment variables the emulator needs, as a dict.",
    "changes_disc": "True when the other discs are reachable once the first is "
                    "running -- from the emulator's own menu, as PCSX2 does, or "
                    "because the game asks for them, as a split Xbox 360 game "
                    "does. Only consulted for an emulator that cannot read a "
                    "playlist, and it decides whether a set may be offered as "
                    "one entry -- see `discSet.ts`. Omit unless it has been "
                    "seen working: the cost of a wrong yes is one library entry "
                    "that can only ever play disc one.",
    "cannot_open": "Extensions to subtract from the derived list, as a tuple. "
                   "The derivation is about a *system* -- it is built from what "
                   "libretro cores declare -- so an emulator inherits anything "
                   "any core for its system reads. This is how an entry says "
                   "the two differ. See `extensions_for`.",
    "layout": "Steam Input layout template a game needs, as a `template://` url.",
    "workarounds": "Temporary corrections for bugs in the emulator itself, as "
                   "a list. Each is a delta over this entry that a user can "
                   "switch off, and that exists only until a named upstream "
                   "fix lands. Ordinary configuration does not belong here -- "
                   "see WORKAROUND_FIELDS for what separates the two.",
    "setup": "Configuration to seed on install -- controller bindings, skipping "
             "a first-run wizard. See `emu_config` for the formats.",
    "firmware": "BIOS or firmware the emulator needs. A list of specs; see "
                "FIRMWARE_REQUIRED below.",
    "data": "Paths this emulator owns, relative to home, for the reset tab to "
            "clear. The flatpak's own directory is already covered.",
    "saves": "Where this emulator keeps save data, relative to home, for the "
             "backup to carry off the device. Each path must sit inside one "
             "of the directories the entry already owns -- the flatpak's own, "
             "or one of `data`. Omit it and the whole of that directory is "
             "backed up instead, which is right for an emulator that only "
             "reads ROMs off the disk and wrong for one that installs games "
             "into itself. See `savedata`.",
    "seed": "Files the package ships that the application cannot find, as "
            "{source under the flatpak's `files` directory: destination "
            "relative to home}. Copied after installing and again at startup, "
            "and only where the destination has no file of that name. Flatpak "
            "sources only -- there is no deployed tree to copy out of "
            "otherwise. See `emu_install.seed_bundled_files` for the packaging "
            "fault this exists for.",
    "note": "A caveat shown in the UI, e.g. that a system needs firmware "
            "the user must supply.",
    "source_moved": "Set when `source` starts naming a different place, as "
                    "{'recipe': <number>, 'note': <sentence>}. An install whose "
                    "recorded recipe is below that number was downloaded from "
                    "somewhere this entry no longer names, and nothing moves it "
                    "on its own: `source` is read live, but the AppImage already "
                    "on disk is not re-fetched, and AppImage updates are not "
                    "offered. So the install is flagged, and the note is what "
                    "the user is told once.",
    "recipe": "Version of the launch arguments. Bump it when correcting `args` "
              "or `fullscreen_args` so the fix reaches an emulator already "
              "installed; see `to_emulator`.",
    "verified": "True once the launch recipe was confirmed against the "
                "emulator's own behaviour rather than reasoned from its help "
                "text. Several emulators ignore unknown arguments silently, so "
                "an unverified recipe can look fine and do nothing.",
    "aliases": "Extra names to match when suggesting arguments for an emulator "
               "the user registered by hand -- forks that take the same flags. "
               "Matched as substrings against the flatpak id or binary name.",
    "helper": "An extra binary the emulator needs, fetched separately. See "
              "`emu_install.helper_path`. shadPS4 only.",
    "motion": "How this emulator reaches the Deck's gyro, as "
              "{'server': {...}}.\n"
              "The server is fetched like a `helper` -- `name`, `label`, "
              "`repo`, `asset`, and `extract` when the release ships an "
              "archive -- and the launcher starts it beside the game and kills "
              "it afterwards.\n"
              "For emulators that read motion off a local socket rather than "
              "through SDL, which is what leaves Steam Input alone. Ryujinx "
              "only.",
    "root": "The directory under home this emulator owns, e.g. '.config/<name>', "
            "or a list of them. Required of an imported entry, where every path "
            "it writes must sit inside one. Optional for a bundled entry, which "
            "is trusted to name its own paths.\n"
            "A list because emulators that follow the XDG layout do not have a "
            "single directory: settings resolve under $XDG_CONFIG_HOME and keys "
            "and saves under $XDG_DATA_HOME, so a definition that seeds bindings "
            "and also declares where a key file goes needs both.",
}

#: How an entry says it can be installed.
#:
#: `byo` -- bring your own -- is the kind that can be described but not
#: installed: the user points at a binary they obtained themselves and the entry
#: supplies the launch recipe, the controller bindings and the firmware layout.
#: It exists for emulators this project will not distribute or link to.
#:
#: An imported entry may declare any of the three. Installing the emulator it
#: describes is the point of importing one, and refusing it would only send the
#: user to download the same build by hand -- see FORBIDDEN_WHEN_IMPORTED for
#: what is actually withheld, which is everything that is not that.
SOURCE_KINDS = ("flatpak", "github", "byo")

#: Keys a firmware spec may carry, as `emu_firmware` reads them.
FIRMWARE_REQUIRED = ("name",)

#: Ways a requirement can be satisfied. A spec needs at least one, or the panel
#: shows a requirement with no route to meeting it.
FIRMWARE_ROUTES = (
    "dest",         # copy the file here, relative to home. The plain case.
    "import",       # hand it to the emulator's own installer: {args, installed, ...}
    "gui_install",  # the emulator will only do it through its window: {prompt, ...}
    "manual",       # a string: what to tell the user to do themselves
)

FIRMWARE_OPTIONAL = FIRMWARE_ROUTES + (
    "note",         # shown under the name in the panel
    "match",        # regex the supplied filename must match
    "expects",      # what to tell the user when `match` rejects their file
    "lower_ext",    # lowercase the extension before matching
    "sizes",        # byte sizes a valid file may have
    "optional",     # the emulator runs without it, so do not warn
    "removes",      # paths to delete when uninstalling this firmware
    "detect",       # how to tell it is already installed, when a path will not
    "stub",         # how to recognise a placeholder the emulator wrote itself
    "configure",    # config keys to point at the file once it is in place
    "fetch",        # {url, name} when the file is ours to download
)

ALLOWED = set(REQUIRED) | set(OPTIONAL)

#: Fields an imported entry may not carry at all, and why each one is refused.
#:
#: An entry is not data the plugin reads -- it is a list of actions the plugin
#: performs, with the user's privileges. These four are the ones where the
#: action is destructive or fetches software, so a definition from outside this
#: repository does not get to ask for them.
#: An imported entry MAY install the emulator it describes. That is the point of
#: importing one: the alternative is the user downloading a build by hand and
#: pointing at it every time it updates, which is friction for no safety --
#: someone who imports a definition has already decided to trust it, and the
#: panel says so in as many words before anything is fetched.
#:
#: What stays refused is everything that is not "install the emulator you asked
#: for". Each of these is a capability an entry could ask for that has nothing
#: to do with running an emulator, and a definition wanting one is either
#: mistaken or hostile:
FORBIDDEN_WHEN_IMPORTED = {
    "removes": "deletes directory trees under the home directory -- an imported "
               "entry does not get to name what gets deleted, and nothing about "
               "installing an emulator requires it",
    "data": "is the list the reset tab wipes, which is the same power under "
            "another name",
    "helper": "downloads and runs a second binary beside the emulator, which is "
              "arbitrary code the definition did not describe",
    "fetch": "downloads a firmware file rather than the emulator. Firmware is "
             "the user's own dump; an entry that offers to fetch one is "
             "offering something it should not have",
}

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _escapes(path):
    """Whether a relative path would leave the directory it is resolved against."""
    if not isinstance(path, str) or not path:
        return True
    return path.startswith("/") or path.startswith("~") or ".." in path.split("/")


def _under(path, root):
    """Whether `path` sits inside `root`, both relative to the home directory."""
    if _escapes(path) or _escapes(root):
        return False
    parts, base = path.split("/"), root.strip("/").split("/")
    return parts[:len(base)] == base


def owned_roots(entry):
    """The directories under home this entry owns, as home-relative paths.

    A flatpak needs nothing declared: everything it can write is under its
    application id. Anything else writes where it likes and the catalog has to
    say so, which is what `data` is for.

    Public because three places need the same answer and had begun to differ:
    the reset tab clears these, the backup reads out of them, and validation
    checks that a `saves` path stays inside one. Deriving it from the config
    file's directory was tried in the reset and was quietly wrong -- see
    `devreset` for what that cost.
    """
    source = entry.get("source") or {}
    if source.get("kind") == "flatpak" and source.get("id"):
        return [".var/app/%s" % source["id"]]
    return [path for path in (entry.get("data") or ()) if isinstance(path, str)]



#: What one entry in `workarounds` carries.
#:
#: **The line this draws is the whole point of the field.** Nearly every catalog
#: entry corrects the emulator it describes in some way -- shadPS4 is told which
#: binary to run and which Vulkan driver to use, Vita3K is told its own AppImage
#: word-splits arguments. None of that belongs here. Those are how you launch the
#: thing correctly, they are permanent, and switching one off would only break
#: the emulator.
#:
#: A workaround is narrower: it compensates a bug **upstream has been told
#: about**, and it goes away when a **specific fix lands**. That gives two
#: properties nothing else here has -- a removal condition that can be checked,
#: and a cost worth letting somebody decline. Both are required, and `validate`
#: enforces them: an entry with no `upstream` is configuration wearing a
#: workaround's clothes, and one nobody can switch off is not a choice.
WORKAROUND_FIELDS = {
    "id": "Stable identifier, unique within the entry. Stored when a user turns "
          "this off, so renaming one silently re-enables it.",
    "name": "What the user sees, in their words rather than ours -- \"Motion "
            "controls\", not the name of the mechanism.",
    "because": "The bug being compensated, in one sentence.",
    "upstream": "URL of the issue or pull request that will make this "
                "unnecessary. Required: without it nobody can tell when to "
                "delete the workaround, which is how they become permanent.",
    "costs": "What switching it on gives up, in the user's terms. Shown beside "
             "the toggle, because a cost nobody sees is not a choice.",
    "default": "Whether it starts on. Optional, defaults to True.",
    "fixed_in": "The emulator build that made this unnecessary -- a version "
                "string or a build number, whichever that emulator publishes. "
                "Compared against the build actually installed, never announced "
                "on its own. This used to be a free-form sentence, and it was "
                "the one thing in the panel that was a *belief about upstream* "
                "rather than an *observation of this Deck*: it shipped with the "
                "plugin, so updating the plugin told somebody their emulator no "
                "longer needed a fix nobody had looked at, and acting on that "
                "broke the thing the message was about. "
                "**Set it rather than deleting the workaround.** The bug is "
                "still in the build somebody has not updated yet, so removing "
                "it the day upstream merges takes the fix from exactly the "
                "people who still need it. Deletion comes later, when it is "
                "safe.",
    "apply": "The delta, written in ordinary catalog keys -- `env`, `layout` "
             "and so on. Merged over the entry when enabled and absent when "
             "not, so a workaround can correct anything the catalog can "
             "already express. See WORKAROUND_APPLIES for the whole list and "
             "PATCH_FIELDS for the one that is not an ordinary key.",
}

def _validate_source_moved(entry_id, spec):
    """Problems with `source_moved`."""
    if spec is None:
        return []
    if not isinstance(spec, dict):
        return ["%s: source_moved must be {'recipe': ..., 'note': ...}" % entry_id]
    problems = []
    if not isinstance(spec.get("recipe"), int) or spec.get("recipe", 0) < 1:
        problems.append("%s: source_moved needs the recipe number at which the "
                        "source changed" % entry_id)
    if not str(spec.get("note") or "").strip():
        problems.append("%s: source_moved needs a note -- it is the one thing "
                        "the user is told, and it is told once" % entry_id)
    return problems


def build_number(text):
    """`text` as a comparable tuple of integers, or () when it is not one.

    Emulators number their builds differently and both shapes have to work:
    Vita3K publishes `4074`, Flathub publishes `0.12.1`. Digits are what they
    have in common, so digits are what is compared.

    () is the answer that matters. A rolling tag like `continuous`, an install
    made before the build was recorded, or a flatpak whose version could not be
    read all land here -- and every caller reads that as "cannot tell", which is
    the only honest thing to do with it. Guessing would put the panel back to
    announcing things about builds nobody looked at.
    """
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(part) for part in parts) if parts else ()


def build_at_least(installed, wanted):
    """Whether `installed` is `wanted` or newer. False when either is unknown.

    False rather than an exception or a guess: not knowing is not the same as
    "no", but it leads to the same silence, and silence is what an unverifiable
    claim deserves.
    """
    left, right = build_number(installed), build_number(wanted)
    if not left or not right:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) >= right + (0,) * (width - len(right))


#: What `apply.patch` says, for a bug that is only reachable inside the
#: emulator's own binary.
#:
#: Every emulator here is upstream's own build. Where a fix can be handed to one
#: at launch it is -- shadPS4 takes its motion fix as an `LD_PRELOAD`, because it
#: links SDL dynamically. Vita3K compiles SDL in, so there is no launch-time
#: seam at all and the only reachable place is the file. Which of the two an
#: emulator gets is decided by how it was built, not by us.
#:
#: See `emu_patch` for how this is applied and, more importantly, for when it
#: refuses to be.
PATCH_FIELDS = {
    "file": "Path inside the package, e.g. 'usr/bin/Vita3K'. Relative, and "
            "never reaching outside it.",
    "within": "Symbol whose bounds the search is limited to. Required, and the "
              "single most important field here: Vita3K's four bytes occur nine "
              "times in its binary and once inside "
              "`HIDAPI_DriverSteamDeck_UpdateDevice`, so a patch without a "
              "symbol is a patch applied to a randomly chosen one of nine "
              "addresses.",
    "find": "Bytes to replace, as hex. Must occur exactly once inside `within`; "
            "anything else and nothing is patched.",
    "replace": "Bytes to write, as hex, the same length as `find`. Nothing is "
               "inserted or removed, so every address in the binary stays "
               "where it was.",
}

#: Required in a patch spec: all of them.
PATCH_REQUIRED = tuple(PATCH_FIELDS)

#: Required in every workaround. `default` is the only optional one.
WORKAROUND_REQUIRED = ("id", "name", "because", "upstream", "costs", "apply")

#: Keys a workaround's `apply` may set. Deliberately short: every one of these
#: can be turned on and off between one launch and the next.
#:
#: `patch` earns its place by not breaking that rule. It edits bytes in the
#: emulator's binary, which sounds like it decides what got installed -- but the
#: patched build is written *beside* the stock one and the launcher points at
#: whichever the user's choice names, so switching it off runs exactly what
#: upstream shipped. See `emu_patch`.
#:
#: `source` is still excluded, and that is the line: it decides which build was
#: downloaded, which no toggle can undo without a reinstall. A fork is not a
#: workaround in this sense however temporary it is.
WORKAROUND_APPLIES = ("env", "layout", "patch")


def _validate_patch(where, spec):
    """Problems with one `apply.patch`.

    Stricter than the other keys, because this one is the only place the catalog
    describes an edit to somebody else's binary. Everything checkable before the
    file exists is checked here; the rest -- that the symbol is present, and that
    the bytes occur exactly once inside it -- can only be checked against a real
    build, and `emu_patch` refuses there.
    """
    if spec is None:
        return []
    if not isinstance(spec, dict):
        return ["%s: apply.patch must be a dict -- %s"
                % (where, ", ".join(sorted(PATCH_FIELDS)))]

    problems = []
    for field in PATCH_REQUIRED:
        if not spec.get(field):
            problems.append("%s: patch is missing %r -- %s"
                            % (where, field, PATCH_FIELDS[field]))
    unknown = sorted(set(spec) - set(PATCH_FIELDS))
    if unknown:
        problems.append("%s: patch has unknown field(s) %s -- known fields "
                        "are: %s" % (where, ", ".join(repr(n) for n in unknown),
                                     ", ".join(sorted(PATCH_FIELDS))))

    member = str(spec.get("file") or "")
    if member and (member.startswith("/") or ".." in member.split("/")):
        problems.append("%s: patch file must be a path inside the package, "
                        "not %r" % (where, member))

    try:
        find = bytes.fromhex(str(spec.get("find") or ""))
        replace = bytes.fromhex(str(spec.get("replace") or ""))
    except ValueError:
        return problems + ["%s: patch find/replace must be hex" % where]
    if find and replace and len(find) != len(replace):
        # Same length or the file changes size, every later address moves, and
        # a binary that no longer matches its own relocations is not a binary.
        problems.append("%s: patch find is %d bytes and replace is %d -- they "
                        "must match, because nothing may move"
                        % (where, len(find), len(replace)))
    if find and find == replace:
        problems.append("%s: patch replaces bytes with themselves" % where)
    return problems


def _validate_workarounds(entry_id, workarounds):
    """Problems with an entry's `workarounds`.

    The two rules worth the code are `upstream` and `apply`. A workaround with
    no upstream reference has no removal condition, so nobody can tell when it
    stopped being needed and it quietly becomes permanent -- which is the exact
    failure this field exists to prevent. And an `apply` reaching keys outside
    `WORKAROUND_APPLIES` would be a workaround that cannot honestly be switched
    off, because the key it sets decides what got installed rather than how it
    launches.
    """
    problems = []
    if workarounds is None:
        return problems
    if not isinstance(workarounds, list):
        return ["%s: workarounds must be a list" % entry_id]

    seen = set()
    claimed = {}
    for item in workarounds:
        if not isinstance(item, dict):
            problems.append("%s: each workaround must be a dict" % entry_id)
            continue
        where = "%s workaround %r" % (entry_id, item.get("id") or "<no id>")

        for field in WORKAROUND_REQUIRED:
            if not item.get(field):
                problems.append("%s: missing %r -- %s"
                                % (where, field, WORKAROUND_FIELDS[field]))

        unknown = sorted(set(item) - set(WORKAROUND_FIELDS))
        if unknown:
            problems.append("%s: unknown field(s) %s -- known fields are: %s"
                            % (where, ", ".join(repr(n) for n in unknown),
                               ", ".join(sorted(WORKAROUND_FIELDS))))

        identifier = item.get("id")
        if identifier in seen:
            problems.append("%s: duplicate id -- ids are what a user's choice "
                            "is stored against" % where)
        seen.add(identifier)

        # A build nobody can compare against is the same as no answer, and
        # would put the panel back to announcing something it cannot check.
        fixed_in = item.get("fixed_in")
        if fixed_in is not None and not build_number(fixed_in):
            problems.append("%s: fixed_in must name a build that can be "
                            "compared -- a version or a build number, not %r"
                            % (where, fixed_in))

        upstream = str(item.get("upstream") or "")
        if upstream and not upstream.startswith(("http://", "https://")):
            problems.append("%s: upstream must be a URL naming the issue or "
                            "pull request that makes this unnecessary" % where)

        apply = item.get("apply")
        if apply is not None:
            if not isinstance(apply, dict):
                problems.append("%s: apply must be a dict of catalog keys" % where)
            else:
                outside = sorted(set(apply) - set(WORKAROUND_APPLIES))
                if outside:
                    problems.append(
                        "%s: apply may only set %s, not %s -- anything else "
                        "decides what was installed, which a toggle cannot undo"
                        % (where, ", ".join(WORKAROUND_APPLIES),
                           ", ".join(repr(n) for n in outside)))

                problems.extend(_validate_patch(where, apply.get("patch")))

                # Two workarounds writing the same thing is a trap rather than a
                # conflict to resolve: `resolve_workarounds` merges in order, so
                # the later one wins silently, and switching *that* one off would
                # change behaviour which looks like it belongs to the other. With
                # one workaround per entry it cannot happen yet, which is exactly
                # why it is worth catching before a second one exists.
                for key, value in apply.items():
                    names = [key] if key != "env" else [
                        "env.%s" % name for name in sorted(value or {})
                    ]
                    for name in names:
                        if name in claimed:
                            problems.append(
                                "%s: both this and %r set %s -- two workarounds "
                                "writing one key means turning either off "
                                "changes the other's behaviour"
                                % (where, claimed[name], name))
                        claimed[name] = item.get("id")
    return problems


def validate(entry, known_platforms=(), imported=False):
    """Problems with one entry, as a list of strings. Empty means it is fine.

    `known_platforms` is the labels `platform` may take -- normally
    `platforms.NO_LIBRETRO_PLATFORMS`. Passed in rather than imported so this
    module stays free of the rest of the package.

    `imported` switches on the rules for an entry that did not come from this
    repository. A bundled entry is written by someone with commit access and
    reviewed as code; an imported one arrives as a file from anywhere, so it may
    not install software, may not delete anything, and may only write inside the
    one directory it declares as `root`. See FORBIDDEN_WHEN_IMPORTED.
    """
    problems = []
    say = problems.append
    entry_id = entry.get("id") or "<no id>"

    def bad(message):
        say("%s: %s" % (entry_id, message))

    for field in REQUIRED:
        if not entry.get(field):
            bad("missing required field %r -- %s" % (field, REQUIRED[field]))

    unknown = sorted(set(entry) - ALLOWED)
    if unknown:
        # The failure this check exists for. A misspelt key is not an error at
        # runtime; it is silently ignored, and the emulator behaves as if the
        # field had never been written.
        bad("unknown field(s) %s -- misspelt? known fields are: %s"
            % (", ".join(repr(name) for name in unknown),
               ", ".join(sorted(ALLOWED))))

    if entry.get("id") and not _SAFE_ID.match(entry["id"]):
        bad("id %r is not usable as a directory name (lowercase letters, "
            "digits, - and _; must not start with - or _)" % entry["id"])

    args = entry.get("args") or ""
    if args and "{rom}" not in args and not entry.get("installed_args"):
        bad("args %r has no {rom} -- the emulator would start with no game" % args)
    if "{rom}" in (entry.get("fullscreen_args") or ""):
        bad("fullscreen_args must not contain {rom}; it is appended to args")
    if "{title}" in args:
        bad("{title} belongs in installed_args, not args")

    source = entry.get("source") or {}
    kind = source.get("kind")
    if source and not kind:
        bad("source has no 'kind'")
    if kind and kind not in SOURCE_KINDS:
        bad("source kind %r is not one of %s"
            % (kind, ", ".join(repr(k) for k in SOURCE_KINDS)))
    if kind == "flatpak" and not source.get("id"):
        bad("a flatpak source needs the application id")
    if kind == "github":
        if not source.get("repo"):
            bad("a release source needs 'repo', as owner/name")
        if not source.get("asset"):
            bad("a release source needs 'asset' -- a regex for the file to take "
                "from the release. Anchor it: releases carry aarch64 builds "
                "beside x86_64 ones and .zsync files beside the real ones, and "
                "the wrong pick fails at exec time with nothing naming why")
        # Optional, and empty means GitHub. Present means a project that left
        # GitHub and self-hosts the same releases API.
        host = source.get("host") or ""
        if host and ("/" in host or ":" in host or host.startswith(".")):
            bad("source host %r must be a host name, not a URL" % host)

    problems.extend(_validate_imported(entry, entry_id) if imported else ())

    if not entry.get("databases") and not entry.get("platform"):
        bad("needs either 'databases' (a libretro system) or 'platform' "
            "(a system libretro has no database for) -- without one, no ROM "
            "will ever match this emulator")
    if entry.get("databases") and entry.get("platform"):
        bad("has both 'databases' and 'platform'; use one")
    platform = entry.get("platform")
    if platform and known_platforms and platform not in known_platforms:
        bad("platform %r is not in platforms.NO_LIBRETRO_PLATFORMS, so it will "
            "have no short label and games will group under the raw string"
            % platform)

    for path in entry.get("data") or ():
        if path.startswith("/") or ".." in path.split("/"):
            bad("data path %r must be relative to home and must not escape it"
                % path)

    # A `saves` path is read on backup and *written* on restore, so "relative to
    # home" is not enough of a fence -- home also holds Steam's data and the
    # user's ssh keys. It has to be inside something the entry already owns,
    # which for anything but a flatpak means declaring `data` first.
    roots = owned_roots(entry)
    for path in entry.get("saves") or ():
        if _escapes(path):
            bad("saves path %r must be relative to home and must not escape it"
                % path)
        elif not roots:
            bad("saves path %r has nothing to sit inside: the entry is not a "
                "flatpak and declares no 'data'" % path)
        elif not any(_under(path, root) for root in roots):
            bad("saves path %r is outside every directory this entry owns (%s)"
                % (path, ", ".join(roots)))

    seed = entry.get("seed")
    if seed:
        if not isinstance(seed, dict):
            bad("seed maps a source path to a destination, so it must be an "
                "object")
        elif kind and kind != "flatpak":
            bad("seed copies out of an installed flatpak's files, so it means "
                "nothing for a %r source" % kind)
        else:
            for source, destination in seed.items():
                if _escapes(source):
                    bad("seed source %r must be a plain relative path inside "
                        "the flatpak's files directory" % source)
                if _escapes(destination):
                    bad("seed destination %r must be relative to home and must "
                        "not escape it" % destination)

    problems.extend(_validate_setup(entry_id, entry.get("setup")))
    problems.extend(_validate_workarounds(entry_id, entry.get("workarounds")))
    problems.extend(_validate_source_moved(entry_id, entry.get("source_moved")))

    for item in entry.get("firmware") or ():
        problems.extend(_validate_firmware(entry_id, item))

    return problems


#: Keys a setup block may carry -- exactly what `emu_config` reads out of one.
#: Anything else is a misspelling that would be ignored in silence, which is the
#: failure this whole module exists to convert into a message.
SETUP_OPTIONAL = ("format", "formats", "label", "version", "superseded")


def _validate_setup(entry_id, setup):
    """A setup block has to name the files it writes, in one of the two shapes.

    `emu_config._files_of` reads `files`, or else `path` and `sections`, and
    subscripts the second pair directly -- so a block with neither raises
    KeyError part-way through an install rather than being reported. For a
    bundled entry that is a test failure; for an imported one it is a file from
    outside crashing the install of an emulator somebody asked for, and the
    error names a private function rather than the definition that caused it.
    """
    if not setup:
        return []

    problems = []

    def bad(message):
        problems.append("%s setup: %s" % (entry_id, message))

    if not isinstance(setup, dict):
        bad("must be an object, not a %s" % type(setup).__name__)
        return problems

    if setup.get("files"):
        if not isinstance(setup["files"], dict):
            bad("'files' maps each path to its sections, so it must be an object")
    elif setup.get("path"):
        if not setup.get("sections"):
            bad("has a 'path' but no 'sections', so there is nothing to write into it")
    else:
        bad("needs either 'files' -- {path: sections} -- or 'path' and 'sections' "
            "together. Without one the install fails part-way through instead of "
            "here")

    unknown = sorted(set(setup) - {"files", "path", "sections"} - set(SETUP_OPTIONAL))
    if unknown:
        bad("unknown key(s) %s -- misspelt? known keys are: %s"
            % (", ".join(repr(name) for name in unknown),
               ", ".join(sorted({"files", "path", "sections"} | set(SETUP_OPTIONAL)))))

    return problems


def _validate_imported(entry, entry_id):
    """The extra rules for an entry that did not come from this repository.

    Refusals, not warnings. Everything here is a capability rather than a
    preference, and a definition that wants one is either mistaken or hostile;
    in both cases the answer is the same and the entry does not load.
    """
    problems = []

    def bad(message):
        problems.append("%s: %s" % (entry_id, message))

    for field, why in FORBIDDEN_WHEN_IMPORTED.items():
        if entry.get(field):
            bad("%r is not allowed in an imported entry: it %s" % (field, why))

    roots = entry.get("root")
    roots = [roots] if isinstance(roots, str) else list(roots or ())
    if not roots:
        bad("needs 'root' -- the directory under home this emulator owns, e.g. "
            "'.config/<name>', or a list of them. Everything it writes has to "
            "sit inside one.")
    for root in roots:
        if _escapes(root):
            bad("root %r must be a plain relative path under the home directory"
                % root)

    # Every path the entry can cause a write to, checked against those roots.
    # The bundled rule is only "somewhere under home", which is far too wide
    # when the home directory also holds Steam's data and the user's ssh keys.
    for where, path in _written_paths(entry):
        if not isinstance(path, str) or not path:
            bad("%s is not a path" % where)
        elif roots and not any(_under(path, root) for root in roots):
            bad("%s writes to %r, which is outside this entry's root%s (%s)"
                % (where, path, "s" if len(roots) > 1 else "",
                   ", ".join(repr(root) for root in roots)))

    # **`motion` is allowed, but only as a flag.**
    #
    # A bundled entry names the server it wants -- repo, asset pattern, the file
    # to keep out of the archive -- and that is the power `helper` is refused
    # for: a binary to download and run, chosen by the file. An imported entry
    # gets to say *that it speaks the protocol* and nothing more; the plugin
    # answers with `deck_gyro.DSU_SERVER`, which this project vetted. So there
    # is no path from a definition to an arbitrary download, and an emulator
    # somebody imported can still have gyro.
    #
    # The blanket refusal that came before this got the population backwards.
    # The emulators that arrive as definitions are the ones this project does
    # not carry, and several of them speak the protocol perfectly well -- so
    # refusing the field outright meant the emulators most likely to be
    # imported were exactly the ones that could never have motion.
    motion = entry.get("motion")
    if motion is not None:
        if not isinstance(motion, dict):
            bad("motion must be an object")
        elif set(motion) != {"dsu"} or motion.get("dsu") is not True:
            bad("an imported entry's motion may only be {\"dsu\": true} -- "
                "naming a server is the power `helper` is refused for, and the "
                "plugin supplies its own")

    # A patch rewrites bytes inside an executable the same entry chose to
    # download, and `find`/`replace` have no length limit -- so it is the power
    # `helper` is refused for, reached by rewriting rather than by fetching. A
    # bundled entry earns it by being read here; a file from outside does not.
    #
    # Only `patch`. `env` and `layout` are already settable at the top level of
    # an imported entry, so offering them inside a workaround adds no reach --
    # it only makes them switchable, which is the point of a workaround.
    for item in entry.get("workarounds") or ():
        if isinstance(item, dict) and (item.get("apply") or {}).get("patch"):
            bad("workaround %r may not carry a patch: it rewrites bytes inside "
                "the emulator's own binary, which is arbitrary code the "
                "definition did not describe"
                % (item.get("id") or "<no id>"))

    for item in entry.get("firmware") or ():
        for field, why in FORBIDDEN_WHEN_IMPORTED.items():
            if item.get(field):
                bad("firmware %r may not use %r: it %s"
                    % (item.get("name", "<unnamed>"), field, why))
        if item.get("gui_install") or item.get("import"):
            # Both hand a file to the emulator and let it run. That is fine for
            # an emulator this project ships a recipe for and has tested; it is
            # not something to accept on the word of a file.
            bad("firmware %r may not use an installer route -- an imported "
                "entry can say where a file goes, not run something to place it"
                % item.get("name", "<unnamed>"))
    return problems


def _written_paths(entry):
    """(description, path) for everywhere an entry can cause a write."""
    found = []
    for item in entry.get("firmware") or ():
        if item.get("dest"):
            found.append(("firmware %r dest" % item.get("name", "<unnamed>"),
                          item["dest"]))
    for _source, destination in (entry.get("seed") or {}).items():
        found.append(("seed destination", destination))
    setup = entry.get("setup") or {}
    if setup.get("path"):
        found.append(("setup path", setup["path"]))
    for path in (setup.get("files") or {}):
        found.append(("setup file", path))
    return found


def _validate_firmware(entry_id, item):
    problems = []

    def bad(message):
        problems.append("%s firmware %r: %s"
                        % (entry_id, item.get("name", "<unnamed>"), message))

    for field in FIRMWARE_REQUIRED:
        if not item.get(field):
            bad("missing required field %r" % field)
    unknown = sorted(set(item) - set(FIRMWARE_REQUIRED) - set(FIRMWARE_OPTIONAL))
    if unknown:
        bad("unknown field(s) %s" % ", ".join(repr(name) for name in unknown))

    if not any(item.get(route) for route in FIRMWARE_ROUTES):
        bad("has no way to be satisfied -- needs one of %s, or the panel lists "
            "a requirement the user cannot meet"
            % ", ".join(repr(route) for route in FIRMWARE_ROUTES))

    path = item.get("dest")
    if isinstance(path, str) and (path.startswith("/") or ".." in path.split("/")):
        bad("dest %r must be relative to home and must not escape it" % path)
    for path in item.get("removes") or ():
        if path.startswith("/") or ".." in path.split("/"):
            bad("removes %r must be relative to home and must not escape it" % path)

    pattern = item.get("match")
    if pattern:
        try:
            re.compile(pattern)
        except re.error as error:
            bad("match is not a valid regex: %s" % error)
        # A pattern with nothing to tell the user is a dead end: the file is
        # rejected and the message is the pattern itself.
        if not item.get("expects"):
            bad("has a 'match' but no 'expects', so a rejected file gets no "
                "explanation of what was wanted")
    return problems
