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
    "layout": "Steam Input layout template a game needs, as a `template://` url.",
    "setup": "Configuration to seed on install -- controller bindings, skipping "
             "a first-run wizard. See `emu_config` for the formats.",
    "firmware": "BIOS or firmware the emulator needs. A list of specs; see "
                "FIRMWARE_REQUIRED below.",
    "data": "Paths this emulator owns, relative to home, for the reset tab to "
            "clear. The flatpak's own directory is already covered.",
    "seed": "Files the package ships that the application cannot find, as "
            "{source under the flatpak's `files` directory: destination "
            "relative to home}. Copied after installing and again at startup, "
            "and only where the destination has no file of that name. Flatpak "
            "sources only -- there is no deployed tree to copy out of "
            "otherwise. See `emu_install.seed_bundled_files` for the packaging "
            "fault this exists for.",
    "note": "A caveat shown in the UI, e.g. that a system needs firmware "
            "the user must supply.",
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
