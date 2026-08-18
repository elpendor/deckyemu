"""Recommended settings written into an emulator's own config after installing.

Installing an emulator is not always enough to play it. Azahar ships keyboard
bindings and a windowed default, so a freshly installed one launched from Steam
shows a window nothing on the Deck can control -- which reads as a broken
install rather than as configuration nobody has done yet.

**This writes into a file the user owns, so the rule for when it may is strict.**
The RetroArch lesson is what this is written against: `--appendconfig` was not
sandboxed, RetroArch saved the merged configuration on exit, and a real Deck was
found carrying settings its owner never chose.

Qt's own config makes a safe rule possible. Azahar writes a companion
`<key>\\default` line beside every setting, and reads it back like this:

    if (qt_config->value(name + "/default", false).toBool()) {
        result = default_value;          // the stored value is IGNORED
    } else {
        result = qt_config->value(name, default_value);
    }

So `\\default=true` means "still the value Azahar itself chose", and the stored
value is not even read. That gives an exact, uninvented rule:

  * `\\default=true`, or the key is absent -> nothing of the user's is at stake,
    so the value may be written. Writing it also means clearing the flag to
    `false`, or Azahar would throw away what was just written.
  * `\\default=false` -> the value differs from Azahar's own default because
    somebody set it. Leave it alone, and say that it was left alone.

Everything else in the file is preserved byte for byte. This is a line editor,
not a parser that rewrites what it did not understand.
"""

import hashlib
import json
import os
import re

import decky

import sysenv

QT_INI = "qt-ini"

# Dolphin, PCSX2, DuckStation and friends: ordinary `key = value` INI with no
# marker saying whether a value is still the emulator's own. Qt's `\default`
# line is what made the Azahar rule exact, and without it a written `False` is
# indistinguishable from a `False` the user chose.
#
# So a key in this format states the default it is willing to replace:
#
#     "Fullscreen": {"value": "True", "default": "False"}
#
# and is written only when the key is absent, still holds that default, or holds
# what this plugin last wrote. A value that is none of those was set by somebody
# and is left alone. A bare string is shorthand for "write only if absent or
# ours", which is right for a key the emulator does not ship at all.
PLAIN_INI = "plain-ini"

# A section may carry this instead of relying on the per-key rule:
#
#     ANCHOR: {"key": "Device", "defaults": ("XInput2/0/Virtual core pointer",)}
#
# meaning "this whole section is one profile, and the anchor says whose it is".
# If the anchor is absent, still one of the emulator's own defaults, or the value
# this plugin last wrote, the entire section is rewritten; otherwise none of it
# is touched.
#
# An input profile needs this because it is all-or-nothing, and because the
# per-key rule cannot express it: Dolphin writes its own default bindings into
# WiimoteNew.ini the first time it runs, so every key existed with a value that
# was neither absent nor ours, and a complete Wiimote profile was skipped
# key by key while the GameCube one -- whose file did not exist yet -- went in
# fine. Listing every default binding as replaceable would be the alternative,
# and there are sixty of them per profile.
ANCHOR = "__anchor__"

# A file this plugin supplies whole, rather than keys edited inside one the
# emulator wrote. Cemu is the case it exists for: it ships no controller profile
# at all and writes no settings until you use it, so there is nothing to edit and
# nothing to parse -- `controllerProfiles/controller0.xml` either exists or does
# not, and until it does no pad works.
#
# That makes ownership simpler than anywhere else, and exact: write when the file
# is absent, or when its contents are byte for byte what this plugin last wrote.
# Anything else means somebody has been in there, and the file is theirs. The
# comparison is a digest rather than the text, so the state file stays small.
#
# `files` maps a path to its complete contents, not to sections.
WHOLE_FILE = "whole-file"

# What this plugin last wrote, per emulator and key.
#
# Without it the rule above cannot tell its own previous work from the user's:
# writing a value *requires* clearing the `\default` flag, so every key we wrote
# looks edited on the next pass. Comparing against the current value is enough
# while the value is unchanged, but not when we need to *correct* it -- and the
# first Azahar bindings were wrong, so correcting them is exactly the case that
# matters. Keyed by what was written rather than a timestamp, so a user edit
# made after ours is still recognised as theirs.
#
# In the settings directory rather than the runtime one: decky wipes runtime on
# uninstall, and losing this makes the plugin conservative about settings that
# are genuinely its own.
STATE_PATH = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "emulator_setup.json")


# Which version of a setup block was last applied. Stored beside the written
# values rather than in its own file, so one read answers both "is this ours?"
# and "is it current?".
VERSION_KEY = "__version__"

#: What each config file looked like when this plugin last wrote it, as
#: {relative path: "<size>:<mtime_ns>"}. Bookkeeping, like the version.
#:
#: Here because an emulator can undo what was written. DuckStation had never run
#: when its settings were applied at install, so the file was created from
#: nothing -- and on its first real run it regenerated the file with its own
#: defaults, putting `SetupWizardIncomplete` back to true. The result was a setup
#: wizard in front of every game Steam launched, on an install the plugin had
#: correctly configured and correctly recorded configuring.
#:
#: A stamp rather than a per-key comparison because it needs no reader for the
#: five formats, and re-applying is safe by construction: the writers already
#: leave alone anything whose value differs from what was recorded, which is how
#: a setting the user changed themselves survives.
STAMP_KEY = "__files__"


def needs_setup(entry):
    """Whether `entry`'s recommended settings are missing or out of date.

    This is what makes the settings correctable at all. They are applied when an
    emulator is installed, and an emulator is installed once -- so without a
    version to compare, a fix to those settings would only ever reach people who
    had not installed the emulator yet.
    """
    setup = entry.get("setup")
    if not setup:
        return False
    stored = _read_state().get(entry["id"], {})
    if stored.get(VERSION_KEY) != setup.get("version", 1):
        return True
    # Or the emulator has written its config since, which may mean it threw away
    # what was put there. Cheaper to re-apply than to read five formats back and
    # decide, and re-applying costs nothing when nothing moved -- the writers
    # report "0 written" and the file is not touched.
    return _stamps(setup) != stored.get(STAMP_KEY, {})


#: The keys in a stored entry that are bookkeeping rather than values written
#: into somebody's config. Filtered wherever the recorded values are read back,
#: and kept as a set so adding a third cannot be remembered in one place and
#: forgotten in the other.
BOOKKEEPING = (VERSION_KEY, STAMP_KEY)


def _recorded_values(stored):
    """Just the values this plugin wrote, without the bookkeeping beside them."""
    return {key: value for key, value in stored.items() if key not in BOOKKEEPING}


def _stamps(setup):
    """{relative path: "<size>:<mtime_ns>"} for the files this setup writes.

    Missing files are recorded as "" rather than skipped: a config that has been
    deleted since is a config that no longer holds what was written, which is
    the same problem as one that was regenerated.
    """
    stamps = {}
    for relative, _sections, _prefix, _fmt in _files_of(setup):
        path = os.path.join(sysenv.user_home(), relative)
        try:
            info = os.stat(path)
            stamps[relative] = "%d:%d" % (info.st_size, info.st_mtime_ns)
        except OSError:
            stamps[relative] = ""
    return stamps


def _read_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except OSError as error:
        # Not fatal: the settings were still applied, and the only cost is that
        # the next run treats them as the user's and leaves them alone.
        decky.logger.warning("Could not record what was written: %s", error)


def _read_lines(path):
    """(lines, bom, error) for `path`, tolerating a byte order mark.

    PPSSPP writes its ini with a UTF-8 BOM. Read as plain utf-8 that mark stays
    glued to the first line, so `[General]` does not start with `[`, no section
    matches it, and a second `[General]` gets appended to the end of the file --
    a whole section silently duplicated. Stripping it here and putting it back on
    write keeps the file byte-identical apart from the values that changed.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except FileNotFoundError:
        # The emulator has not run yet, or has never been configured. Writing the
        # file is correct: these emulators read what they find and fill in the
        # rest themselves.
        return [], False, ""
    except OSError as error:
        return None, False, "Could not read %s: %s" % (path, error)

    try:
        with open(path, "rb") as handle:
            bom = handle.read(3) == b"\xef\xbb\xbf"
    except OSError:
        bom = False

    return text.splitlines(), bom, ""


def _write_lines(path, lines, bom):
    """Replace `path` with `lines`. Returns an error string, or ''."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".deckyemu-tmp"
        encoding = "utf-8-sig" if bom else "utf-8"
        with open(tmp, "w", encoding=encoding, newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except OSError as error:
        return "Could not write %s: %s" % (path, error)
    return ""


def _split_sections(lines):
    """[(header_or_None, start, end)] spans covering `lines`."""
    spans = []
    current = None
    start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            spans.append((current, start, index))
            current = stripped[1:-1]
            start = index + 1
    spans.append((current, start, len(lines)))
    return spans


def _find_key(lines, start, end, key):
    """Index of the line assigning `key` within a span, or -1."""
    prefix = key + "="
    for index in range(start, end):
        if lines[index].startswith(prefix):
            return index
    return -1


def _is_ours(current, key_name, previous, superseded):
    """Whether `current` is a value this plugin put there, not the user's."""
    if previous.get(key_name) == current:
        return True
    # Values written by earlier versions, before the state file existed. These
    # patterns match things only this plugin ever wrote, so they cannot claim a
    # user's own binding. Removable once no install can still carry them.
    return any(pattern.search(current) for pattern in superseded)


def _apply_qt_ini(path, sections, previous=None, superseded=()):
    """Write `sections` into a Qt INI, respecting each key's `\\default` flag.

    Returns (applied, skipped, written, error); `written` is what to record as
    this plugin's own work, so a later correction can tell it from a user edit.
    """
    previous = previous or {}
    # A missing file is fine here: Azahar has not run yet, and a partial file
    # works because it fills in whatever it does not find with its own defaults
    # and reads ours because they carry `\default=false`.
    lines, bom, error = _read_lines(path)
    if error:
        return [], [], {}, error

    applied = []
    skipped = []
    written = {}

    for section, values in sections.items():
        spans = _split_sections(lines)
        span = next((item for item in spans if item[0] == section), None)
        if span is None:
            # A trailing blank line keeps the file readable when several
            # sections are appended in a row.
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("[%s]" % section)
            spans = _split_sections(lines)
            span = next(item for item in spans if item[0] == section)

        _name, start, end = span
        # Applied one at a time because every insertion moves the span, and
        # recomputing is cheaper than tracking offsets by hand.
        for key, literal in values.items():
            spans = _split_sections(lines)
            _name, start, end = next(item for item in spans if item[0] == section)

            name = "%s/%s" % (section, key)
            default_key = key + "\\default"
            default_at = _find_key(lines, start, end, default_key)
            key_at = _find_key(lines, start, end, key)
            if default_at != -1:
                flag = lines[default_at].split("=", 1)[1].strip().lower()
                current = lines[key_at].split("=", 1)[1] if key_at != -1 else None
                # `false` means the value differs from the emulator's own
                # default because somebody set it -- unless that somebody was
                # us. Writing a value *requires* clearing this flag, so every key
                # we wrote looks edited on the next pass; without the tests below
                # this would refuse to correct its own mistakes, which is how a
                # wrong set of bindings became unfixable once.
                if (
                    flag == "false"
                    and current != literal
                    and not _is_ours(current, name, previous, superseded)
                ):
                    skipped.append(name)
                    continue

            written[name] = literal
            if key_at != -1:
                lines[key_at] = "%s=%s" % (key, literal)
            else:
                lines.insert(end, "%s=%s" % (key, literal))
                end += 1

            # Without this the value above is read and discarded.
            if default_at != -1:
                lines[default_at] = "%s=false" % default_key
            else:
                spans = _split_sections(lines)
                _name, start, end = next(item for item in spans if item[0] == section)
                insert_at = _find_key(lines, start, end, key)
                lines.insert(insert_at + 1, "%s=false" % default_key)

            applied.append(name)

    error = _write_lines(path, lines, bom)
    if error:
        return [], [], {}, error

    return applied, skipped, written, ""


_PLAIN_KEY_RE_CACHE: dict = {}


def _read_value(line, quoted=False):
    """The value assigned on `line`, in unquoted terms."""
    text = line.split("=", 1)[1].strip()
    return _toml_unquote(text) if quoted else text


def _plain_find(lines, start, end, key):
    """Index of `key = value` within a span, tolerating spacing. -1 if absent."""
    pattern = _PLAIN_KEY_RE_CACHE.get(key)
    if pattern is None:
        pattern = _PLAIN_KEY_RE_CACHE[key] = re.compile(r"^\s*%s\s*=" % re.escape(key))
    for index in range(start, end):
        if pattern.match(lines[index]):
            return index
    return -1


# xemu's `xemu.toml`, which is an INI as far as this file is concerned: `[table]`
# headers and `key = value` lines. The one difference that matters is that TOML
# strings are quoted, and an unquoted one is not a parse error there -- it is a
# *different type*, so `hdd_path = /home/deck/x.qcow2` makes xemu reject the file
# rather than ignore the key.
#
# So this is PLAIN_INI with quoting on the way out and unquoting on the way back
# in, rather than a second copy of the same eighty lines. Only string values are
# supported, which is all the paths xemu needs.
TOML_KEYS = "toml-keys"

_TOML_QUOTES = "'\""


def _toml_unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in _TOML_QUOTES:
        return text[1:-1]
    return text


def _toml_quote(value):
    # Single quotes are TOML's literal string: no escapes inside, which is
    # exactly right for a filesystem path and is what xemu writes itself.
    # A path containing a single quote cannot be represented this way, so it
    # falls back to a basic string with the two escapes that form requires.
    if "'" not in value:
        return "'%s'" % value
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def _apply_toml_keys(path, sections, previous=None, superseded=()):
    """Write `sections` into a TOML file. Same contract as _apply_plain_ini."""
    return _apply_plain_ini(path, sections, previous, superseded, quoted=True)


# Vita3K's `config.yml`: a flat list of `key: value` lines under a `---` marker,
# with no sections at all. Not YAML in general -- nothing here would survive a
# nested document or a list -- which is why it edits lines rather than parsing:
# the file is the emulator's and everything not addressed has to come back out
# untouched, including the ordering and the comments a future version adds.
#
# `files` maps a path to {key: spec}, with the same ownership rule as
# PLAIN_INI. There is no section, so keys are named alone.
YAML_KEYS = "yaml-keys"

_YAML_KEY_RE_CACHE: dict = {}


def _yaml_find(lines, key):
    pattern = _YAML_KEY_RE_CACHE.get(key)
    if pattern is None:
        pattern = _YAML_KEY_RE_CACHE[key] = re.compile(r"^\s*%s\s*:" % re.escape(key))
    for index, line in enumerate(lines):
        if pattern.match(line):
            return index
    return -1


def _apply_yaml_keys(path, keys, previous=None, superseded=()):
    """Set `keys` in a flat YAML file. Same contract as the other handlers.

    An absent file is refused rather than created, the same rule JSON_KEYS
    follows and for a worse reason. Vita3K reads its config as a whole
    document: handed one containing only the three keys this writes, it failed
    with `invalid node; first invalid key: "keyboard-button-select"`, fell back
    to an empty pref-path, and aborted in `create_directories`. A partial
    config did not degrade -- it stopped the emulator starting at all.

    Reported as an error rather than silently skipped, so `apply_setup` does
    not record the version and tries again once the emulator has written its
    own config.
    """
    previous = previous or {}
    if not os.path.exists(path):
        return [], [], {}, (
            "%s does not exist yet. Start the emulator once so it writes its "
            "own configuration." % path
        )

    lines, bom, error = _read_lines(path)
    if error:
        return [], [], {}, error

    applied = []
    skipped = []
    written = {}

    for key, spec in keys.items():
        if isinstance(spec, dict):
            literal = spec["value"]
            replaceable = spec.get("default")
        else:
            literal = spec
            replaceable = None

        at = _yaml_find(lines, key)
        if at != -1:
            current = lines[at].split(":", 1)[1].strip()
            if (
                current != literal
                and current != replaceable
                and not _is_ours(current, key, previous, superseded)
            ):
                skipped.append(key)
                continue
            lines[at] = "%s: %s" % (key, literal)
        else:
            lines.append("%s: %s" % (key, literal))

        written[key] = literal
        applied.append(key)

    error = _write_lines(path, lines, bom)
    if error:
        return [], [], {}, error
    return applied, skipped, written, ""


def _apply_plain_ini(path, sections, previous=None, superseded=(), quoted=False):
    """Write `sections` into an ordinary INI. Same contract as _apply_qt_ini.

    `quoted` renders values as TOML strings -- see TOML_KEYS. Everything either
    side of the file stays in unquoted terms, so what is compared, recorded and
    reported is the value itself rather than its spelling on disk.
    """
    previous = previous or {}
    lines, bom, error = _read_lines(path)
    if error:
        return [], [], {}, error

    applied = []
    skipped = []
    written = {}

    for section, values in sections.items():
        spans = _split_sections(lines)
        if not any(item[0] == section for item in spans):
            if lines and lines[-1].strip():
                lines.append("")
            lines.append("[%s]" % section)

        anchor = values.get(ANCHOR)
        forced = False
        if anchor:
            spans = _split_sections(lines)
            _name, start, end = next(item for item in spans if item[0] == section)
            at = _plain_find(lines, start, end, anchor["key"])
            current = _read_value(lines[at], quoted) if at != -1 else None
            name = "%s/%s" % (section, anchor["key"])
            forced = (
                current is None
                or current in anchor.get("defaults", ())
                or current == values.get(anchor["key"])
                or _is_ours(current, name, previous, superseded)
            )
            if not forced:
                # Somebody pointed this profile at a device we did not choose,
                # so the whole profile is theirs.
                skipped.extend(
                    "%s/%s" % (section, key) for key in values if key != ANCHOR
                )
                continue

        for key, spec in values.items():
            if key == ANCHOR:
                continue
            if isinstance(spec, dict):
                literal = spec["value"]
                replaceable = spec.get("default")
                # TOML types are not interchangeable: `show_menubar = 'false'`
                # is the string "false", which is true. A boolean or a number
                # has to go in bare, and only the entry knows which it is.
                bare = spec.get("raw", False)
            else:
                literal = spec
                replaceable = None
                bare = False

            name = "%s/%s" % (section, key)
            spans = _split_sections(lines)
            _name, start, end = next(item for item in spans if item[0] == section)

            rendered = _toml_quote(literal) if quoted and not bare else literal
            at = _plain_find(lines, start, end, key)
            if at != -1:
                current = _read_value(lines[at], quoted)
                if (
                    not forced
                    and current != literal
                    and current != replaceable
                    and not _is_ours(current, name, previous, superseded)
                ):
                    skipped.append(name)
                    continue
                lines[at] = "%s = %s" % (key, rendered)
            else:
                lines.insert(end, "%s = %s" % (key, rendered))

            written[name] = literal
            applied.append(name)

    error = _write_lines(path, lines, bom)
    if error:
        return [], [], {}, error

    return applied, skipped, written, ""


# Ryujinx and shadPS4 keep their whole configuration in JSON, which the emulator
# rewrites wholesale every time it saves. Line editing is neither possible nor
# needed: JSON carries no comments to preserve, so it can be parsed, changed and
# written back, and the emulator restores its own formatting on the next save.
#
# `files` maps a path to {key: spec}, where a spec is either a bare value ("write
# when absent or ours") or {"value": ..., "default": ...} stating the value it is
# willing to replace -- the same rule as PLAIN_INI.
#
# A list-valued key may instead say `replace_when_all`, which is the JSON form of
# ANCHOR: replace the whole list when every entry agrees on one field. Ryujinx
# needs it because its default `input_config` is a keyboard, and "nobody has set
# up a gamepad" is a far better test of whose config it is than matching the
# exact keyboard dict Ryujinx happens to ship this version.
JSON_KEYS = "json-keys"

_CONTENT_KEY = "content"


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _apply_whole_file(path, content, previous=None, superseded=()):
    """Supply `path` entirely. Same contract as the other handlers.

    `superseded` is accepted and unused: those patterns match values inside a
    config, and here there are no values -- a file either is what this plugin
    last wrote or it is the user's.
    """
    previous = previous or {}
    digest = _digest(content)

    try:
        with open(path, "r", encoding="utf-8") as handle:
            current = handle.read()
    except FileNotFoundError:
        current = None
    except OSError as error:
        return [], [], {}, "Could not read %s: %s" % (path, error)

    if current is not None:
        if _digest(current) == digest:
            # Already exactly this. Recorded anyway, so a corrected version can
            # still recognise it as ours and replace it.
            return [], [], {_CONTENT_KEY: digest}, ""
        if previous.get(_CONTENT_KEY) != _digest(current):
            return [], [_CONTENT_KEY], {}, ""

    # Not `error`: that name belongs to the `except OSError as error` above, and
    # Python unbinds it at the end of the block. Reusing it works and reads as
    # though the exception were still in hand.
    write_error = _write_lines(path, content.splitlines(), False)
    if write_error:
        return [], [], {}, write_error
    return [_CONTENT_KEY], [], {_CONTENT_KEY: digest}, ""


def _json_literal(value):
    """A stable string for a JSON value, so two of them can be compared."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _all_agree(current, rule):
    """Whether every entry of `current` has one of the expected field values.

    An absent or empty list counts: there is nothing of the user's in it.
    """
    if not isinstance(current, list):
        return False
    return all(
        isinstance(item, dict) and item.get(rule["key"]) in rule["values"]
        for item in current
    )


def _json_at(data, key):
    """(container, leaf name) for a dotted key, or (None, '') if it cannot be.

    `"General.install_dirs"` reaches inside a nested object, which shadPS4 needs
    and Ryujinx does not -- its settings are all at the top level, so an
    undotted key behaves exactly as before. Missing objects along the way are
    created: a config that has never held a section still has to be able to
    receive one.
    """
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if child is None:
            child = node[part] = {}
        elif not isinstance(child, dict):
            return None, ""
        node = child
    return node, parts[-1]


def _apply_json_keys(path, keys, previous=None, superseded=()):
    """Set `keys` in a JSON object file. Same contract as the other handlers."""
    previous = previous or {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        # Unlike the INI handlers, an absent file is not safe to invent here: a
        # config this emulator has never written has no version field, and
        # guessing the rest of the document is not something to do blind.
        return [], [], {}, ""
    except (OSError, ValueError) as error:
        return [], [], {}, "Could not read %s: %s" % (path, error)
    if not isinstance(data, dict):
        return [], [], {}, "%s is not a JSON object." % path

    applied = []
    skipped = []
    written = {}

    for key, spec in keys.items():
        if isinstance(spec, dict) and "value" in spec:
            value = spec["value"]
            replaceable = spec.get("default")
            rule = spec.get("replace_when_all")
        elif isinstance(spec, dict):
            # A dict with no `value` is a malformed spec, not a value somebody
            # wants written whole. Loud, because the alternative already
            # happened: shadPS4's nested sections were passed as if they were
            # values, every one was skipped as "the user's", and the setup
            # recorded itself as applied having written nothing -- which meant
            # it never ran again.
            return [], [], {}, (
                "%s: %r is a section, not a value. Address nested keys as "
                "\"section.key\"." % (path, key)
            )
        else:
            value, replaceable, rule = spec, None, None

        container, leaf = _json_at(data, key)
        if container is None:
            return [], [], {}, "%s: %s is not inside an object." % (path, key)

        literal = _json_literal(value)
        if leaf in container:
            current = _json_literal(container[leaf])
            ours = (
                current == literal
                or (replaceable is not None and current == _json_literal(replaceable))
                or (rule is not None and _all_agree(container[leaf], rule))
                or _is_ours(current, key, previous, superseded)
            )
            if not ours:
                skipped.append(key)
                continue

        container[leaf] = value
        written[key] = literal
        applied.append(key)

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".deckyemu-tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    except OSError as error:
        return [], [], {}, "Could not write %s: %s" % (path, error)

    return applied, skipped, written, ""


_HANDLERS = {
    QT_INI: _apply_qt_ini,
    PLAIN_INI: _apply_plain_ini,
    TOML_KEYS: _apply_toml_keys,
    YAML_KEYS: _apply_yaml_keys,
    WHOLE_FILE: _apply_whole_file,
    JSON_KEYS: _apply_json_keys,
}


def _files_of(setup):
    """[(relative path, sections, key prefix, format)] for either spec shape.

    A one-file setup keeps its bare "Section/key" state keys, because Azahar's
    are already recorded that way and renaming them would make its settings look
    like the user's and stop being correctable -- the exact trap the state file
    exists to avoid.

    `formats` overrides the setup's format for one file. One emulator's settings
    are not all in one shape: RPCS3 needs a pad file supplied whole *and* two
    keys set inside a Qt ini it already owns, and splitting those into separate
    setup blocks would give them separate versions to keep in step.
    """
    default = setup.get("format")
    formats = setup.get("formats") or {}
    if setup.get("files"):
        return [
            (path, sections, os.path.basename(path) + "/", formats.get(path, default))
            for path, sections in setup["files"].items()
        ]
    return [(setup["path"], setup["sections"], "", default)]


# Where the user's own dumps are collected. The catalog is evaluated at import
# and cannot know it -- the path depends on the home directory, which the tests
# move -- so entries write this token and it is resolved here instead.
#
# Kept in step with emu_install.firmware_dir() and fileserver.default_dir() by
# tests rather than by imports: emu_install imports emulator_catalog, which
# imports this module.
FIRMWARE_TOKEN = "{firmware}"
TRANSFER_TOKEN = "{transfer}"
PACKAGES_TOKEN = "{packages}"
PS4_GAMES_TOKEN = "{ps4games}"


def _firmware_dir():
    return sysenv.user_dir("firmware")


def _transfer_dir():
    return sysenv.user_dir("transfer")


def _packages_dir():
    return sysenv.user_dir("packages")


def _ps4_games_dir():
    # Kept in step with ps4_games.games_dir() by a test rather than an import:
    # ps4_games imports nothing from here, and importing it here would be a
    # cycle through the catalog.
    return sysenv.user_dir("games", "ps4")


def _expand(value):
    """Resolve tokens in a setup's values, whatever shape the value is.

    Substring replacement rather than str.format, so a config value that happens
    to contain a brace -- and several do -- is left exactly as written.
    """
    if isinstance(value, str):
        if FIRMWARE_TOKEN in value:
            value = value.replace(FIRMWARE_TOKEN, _firmware_dir())
        if TRANSFER_TOKEN in value:
            value = value.replace(TRANSFER_TOKEN, _transfer_dir())
        if PACKAGES_TOKEN in value:
            value = value.replace(PACKAGES_TOKEN, _packages_dir())
        if PS4_GAMES_TOKEN in value:
            value = value.replace(PS4_GAMES_TOKEN, _ps4_games_dir())
        return value
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_expand(item) for item in value]
    return value


def apply_file(path, fmt, sections, owner):
    """Write keys into one config file, outside any catalog setup block.

    For settings that are not part of an emulator's recommended setup but of
    something the user did: xemu's boot ROM, BIOS and disk image paths are only
    knowable once those files have been installed, so they cannot live in a
    table evaluated at import.

    `owner` namespaces the ownership record, so these and a setup block cannot
    overwrite each other's history of what was written. The same rule applies as
    everywhere else: a value the user changed is left alone.
    """
    handler = _HANDLERS.get(fmt)
    if handler is None:
        return {"ok": False, "error": "Unknown setup format %r." % fmt}

    state = _read_state()
    previous = _recorded_values(state.get(owner, {}))

    applied, skipped, written, error = handler(path, _expand(sections), previous, ())
    if error:
        return {"ok": False, "error": error}

    state[owner] = dict(previous, **written)
    _write_state(state)
    return {"ok": True, "applied": applied, "skipped": skipped}


def apply_setup(entry):
    """Apply a catalog entry's recommended settings. Returns a result dict.

    Never raises and never reports a hard failure for "there was nothing to do":
    an emulator with no setup block is not a problem, it just has sensible
    defaults already.
    """
    setup = entry.get("setup")
    if not setup:
        return {"ok": True, "applied": [], "skipped": [], "changed": False}

    state = _read_state()
    stored = state.get(entry["id"], {})
    # The version lives alongside the values; it is bookkeeping, not something
    # that was ever written into the emulator's config.
    previous = _recorded_values(stored)
    superseded = [re.compile(pattern) for pattern in setup.get("superseded", ())]

    applied = []
    skipped = []
    written = {}
    for relative, sections, prefix, fmt in _files_of(setup):
        handler = _HANDLERS.get(fmt)
        if handler is None:
            return {"ok": False, "error": "Unknown setup format %r." % fmt}
        path = os.path.join(sysenv.user_home(), relative)
        # Keys are prefixed per file so two files in one setup cannot collide on
        # the same section and key name.
        scoped = {key[len(prefix):]: value for key, value in previous.items()
                  if not prefix or key.startswith(prefix)}
        part_applied, part_skipped, part_written, error = handler(
            path, _expand(sections), scoped, superseded
        )
        if error:
            return {"ok": False, "error": error}
        applied.extend(prefix + name for name in part_applied)
        skipped.extend(prefix + name for name in part_skipped)
        written.update({prefix + name: value for name, value in part_written.items()})

    # Recorded even when nothing was written: every key having been left as the
    # user set them is still a complete answer for this version, and repeating
    # the attempt at every startup would achieve nothing.
    # Merged rather than replaced, so a key skipped this time keeps whatever was
    # last recorded for it.
    state[entry["id"]] = dict(previous, **written)
    state[entry["id"]][VERSION_KEY] = setup.get("version", 1)
    # Taken after the writes, so it describes the files as this plugin left
    # them. Anything that moves them afterwards is the emulator, and that is
    # what brings this round again.
    state[entry["id"]][STAMP_KEY] = _stamps(setup)
    _write_state(state)

    decky.logger.info(
        "Configured %s: %d written, %d left as the user set them",
        entry.get("id"),
        len(applied),
        len(skipped),
    )
    return {
        "ok": True,
        "applied": applied,
        "skipped": skipped,
        "changed": bool(applied),
        "label": setup.get("label", "recommended settings"),
    }
