#!/usr/bin/env python3
"""Three things a definition no longer has to repeat.

    python scripts/tests/test_definition_shorthands.py

Measured on a nine-entry set of ports somebody wrote outside this repository,
which is the first real evidence of what the format is like to author rather
than to read. Three kinds of repetition came out of it, and only these were
worth removing -- the rest is a checked redundancy the validator depends on, or
per-port fact that no shorthand can compress.

* `"args": ""` in all nine. Required, and structurally empty for every port:
  the ROM arrives through `game_config` or `game_beside`, never on the command
  line. Now omittable exactly when one of those is present.
* Sixteen `controllerPak_file_N.sav` lines in one entry. Now one pattern.
* A file named twice by `setup` and `game_config`, which usually write the same
  file under two different rules. Now named once.

What is deliberately *not* here: a shorthand for the root repeating inside each
`saves` path. Those stay written out, because the validator proves each one sits
inside a directory the entry declared it owns, and that check only exists when
the path is there to check.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import emu_config  # noqa: E402
import savedata  # noqa: E402
import sysenv  # noqa: E402
from emulator_catalog import schema  # noqa: E402


def port(**extra):
    """A port entry, minus whichever field the case is about."""
    entry = {
        "id": "zed",
        "name": "Zed",
        "summary": "Native port of a game. Needs your own ROM.",
        "port": True,
        "source": {"kind": "github", "repo": "someone/zed", "asset": "^zed\\.AppImage$"},
        "root": "deckyemu/emulators/zed",
        "platform": "Ports",
    }
    entry.update(extra)
    return entry


section("args may be left out when the ROM travels another way")

check("a port whose ROM sits beside it needs no args",
      schema.validate(port(game_beside=True), imported=True), [])
check("nor does one that writes the ROM into its own config",
      schema.validate(port(game_config={
          "format": "json-flat",
          "path": "deckyemu/emulators/zed/config.json",
          "keys": {"rom": "{rom}"},
      }), imported=True), [])
# The rule is "the ROM has another way in", not "args is optional". An entry
# with neither still has to say how the game reaches the program.
check("an ordinary emulator still must declare args",
      any("missing required field 'args'" in problem
          for problem in schema.validate(port(), imported=True)), True)
check("and an empty args is still accepted, for the definitions that wrote one",
      schema.validate(port(args="", game_beside=True), imported=True), [])


section("a saves path may be a pattern")

check("a pattern inside an owned directory validates",
      schema.validate(port(game_beside=True, saves=[
          "deckyemu/emulators/zed/controllerPak_file_*.sav",
      ]), imported=True), [])
# The containment check reads the literal prefix, so a pattern cannot be used
# to point at somewhere the entry does not own.
check("and one outside every owned directory is still refused",
      any("outside every directory this entry owns" in problem
          for problem in schema.validate(port(game_beside=True, saves=[
              ".local/share/somebody-else/*.sav",
          ]), imported=True)), True)

with tempfile.TemporaryDirectory() as home:
    folder = os.path.join(home, "deckyemu", "emulators", "zed")
    os.makedirs(folder)
    for name in ("controllerPak_file_0.sav", "controllerPak_file_1.sav",
                 "controllerPak_file_10.sav", "default.sav", "zed.AppImage"):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write("x")

    matched = savedata._matching(os.path.join(folder, "controllerPak_file_*.sav"))
    check("the pattern finds every numbered file",
          sorted(os.path.basename(one) for one in matched),
          ["controllerPak_file_0.sav", "controllerPak_file_1.sav",
           "controllerPak_file_10.sav"])
    # Not the binary sitting beside them, which is what declaring the whole
    # directory instead would have swept into the backup.
    check("and nothing else in the folder",
          any(one.endswith(".AppImage") or one.endswith("default.sav") for one in matched),
          False)
    check("a plain path is returned whether or not it exists, as before",
          savedata._matching(os.path.join(folder, "default.sav")),
          [os.path.join(folder, "default.sav")])
    check("a pattern matching nothing yields nothing, rather than itself",
          savedata._matching(os.path.join(folder, "nothing_*.sav")), [])
    # glob's own order is the filesystem's, and a backup whose contents are
    # listed differently each run reads as having changed.
    check("the order is stable", matched, sorted(matched))


section("game_config takes setup's file when setup names one")

shared = port(
    game_config={"keys": {"backend.isoPath": "{rom}"}},
    setup={
        "format": "json-flat",
        "path": "deckyemu/emulators/zed/config.json",
        "sections": {"video.fullscreen": True},
    },
)
check("a game_config with only keys validates",
      schema.validate(shared, imported=True), [])
check("and resolves to the setup's file", schema.one_file_setup(shared),
      ("json-flat", "deckyemu/emulators/zed/config.json"))

# The one that matters at runtime: the launcher writes what this returns, so
# inheriting in the validator and not here would validate and then do nothing.
_home = sysenv.user_home()
path, keys = emu_config.game_config_values(shared, "/roms/zed.iso")
# Joined to home exactly as the definition spells it, which is what the
# launcher puts on disk. Separators are not normalised here and never were.
check("the launcher writes it to the same file",
      path, os.path.join(_home, "deckyemu/emulators/zed/config.json"))
check("with the ROM substituted", keys, {"backend.isoPath": "/roms/zed.iso"})

# A setup writing several files means no single file to inherit, so saying
# nothing would be guessing which one.
several = port(
    game_config={"keys": {"backend.isoPath": "{rom}"}},
    setup={
        "format": "json-flat",
        "files": {"deckyemu/emulators/zed/a.json": {"x": 1},
                  "deckyemu/emulators/zed/b.json": {"y": 2}},
    },
)
check("a multi-file setup is not guessed at", schema.one_file_setup(several), ("", ""))
check("and the entry is refused rather than half-configured",
      any("game_config" in problem for problem in schema.validate(several, imported=True)),
      True)
check("and nothing is written at launch",
      emu_config.game_config_values(several, "/roms/zed.iso"), ("", {}))

# Still overridable: two programs, or one program with a second config, is why
# the field exists at all.
own = port(
    game_config={"format": "json-flat",
                 "path": "deckyemu/emulators/zed/other.json",
                 "keys": {"backend.isoPath": "{rom}"}},
    setup={"format": "json-flat",
           "path": "deckyemu/emulators/zed/config.json",
           "sections": {"video.fullscreen": True}},
)
check("a game_config naming its own file keeps it",
      emu_config.game_config_values(own, "/roms/zed.iso")[0],
      os.path.join(_home, "deckyemu/emulators/zed/other.json"))


if __name__ == "__main__":
    from harness import summary

    summary()
