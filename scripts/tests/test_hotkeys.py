#!/usr/bin/env python3
"""A port's own menu, reached from the pad.

    python scripts/tests/test_hotkeys.py

A port is a PC program whose menu opens with a key, and Game Mode has no
keyboard. `gptokeyb2` turns hold-Select-press-Start into that key, which is the
gesture RetroArch already uses and the mechanism PortMaster already ships.

The config below is the one that was run on a Deck: holding Select and pressing
Start opened Ship of Harkinian's menubar, and the pad kept playing the game.

Every port here is made up.
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check, section, summary  # noqa: E402

import decky  # noqa: E402
import emu_install  # noqa: E402
import emulator_catalog  # noqa: E402
import launchers  # noqa: E402
from emulator_catalog import hotkeys, schema  # noqa: E402

_PORT = {
    "id": "keyed-port",
    "name": "Keyed Port",
    "summary": "A native port of one game.",
    "source": {"kind": "github", "repo": "someone/keyed", "asset": "^Keyed\\.AppImage$"},
    "args": "{rom}",
    "port": True,
    "root": ".local/share/SomeStudio/Keyed",
    "platform": "Nintendo GameCube",
    "menu_key": "esc",
}


section("what the helper is told")

check("the menu key goes on Start", hotkeys.bindings_for(_PORT), {"start": "esc"})
check("an entry that declares none asks for nothing",
      hotkeys.bindings_for({"id": "plain"}), {})
check("and further keys join it",
      hotkeys.bindings_for(dict(_PORT, hotkeys={"y": "f5"})),
      {"start": "esc", "y": "f5"})

_text = hotkeys.config_text({"start": "esc"})
# Exactly the file that was run on the Deck. `overlay = clear` leaves every
# button unbound outside the held state, so the game still sees the whole pad.
check("Select is what reaches the second set of bindings",
      "back = hold_state hotkey" in _text, True)
check("and Start sends the key only while it is held",
      _text.split("[controls:hotkey]")[1].strip().endswith("start = esc"), True)
check("nothing is bound outside that state", "overlay = clear" in _text, True)


section("the button held is the port's to choose")

# While the chord is held the pad is taken from the game, so a port of a console
# that uses Select must hold something else. N64 and GameCube have no such
# button, which is why Select is the default rather than the only answer.
check("Select unless the entry says otherwise", hotkeys.modifier_for(_PORT), "back")
check("and whatever it does say", hotkeys.modifier_for(dict(_PORT, menu_modifier="l3")), "l3")
check("which is what the config holds",
      "l3 = hold_state hotkey" in hotkeys.config_text({"start": "esc"}, "l3"), True)
check("a modifier that is not a button is refused",
      any("not a button name" in problem
          for problem in schema.validate(dict(_PORT, menu_modifier="Select Button"),
                                         known_platforms=(), imported=True)),
      True)
# An EVIOCGRAB on the pad the game was given. Where that is the physical one,
# Steam loses its own buttons and does not get them back when the grab goes --
# the Steam button stayed dead until the machine was restarted.
check("nothing is ever grabbed",
      "exclusive" in hotkeys.config_text({"start": "esc"}), False)


section("the launcher runs it beside the game")

check("a port with no helper fetched yet gets an ordinary launcher",
      launchers.hotkey_helper(_PORT, path="/tmp/game.sh"), "")

_tools = emu_install.tools_dir(hotkeys.KEYBOARD_SERVER["name"])
_binary = os.path.join(_tools, "gptokeyb2.x86_64")
with io.open(_binary, "w", encoding="utf-8") as _handle:
    _handle.write("#!/bin/sh\nexit 0\n")
os.chmod(_binary, 0o755)

_shell = launchers.hotkey_helper(_PORT, path="/tmp/the-game.sh")
check("with the helper present it is started", "gptokeyb2.x86_64" in _shell, True)
check("told where its library is", "LD_LIBRARY_PATH" in _shell, True)
check("handed this port's config", "keyed-port.ini" in _shell, True)
# Steam's reaper waits for every descendant, so a helper still alive when the
# game exits keeps the library entry on "Running" with nothing to stop.
check("and stopped with the game", "trap 'kill" in _shell, True)
# The gesture is Select+Start, and gptokeyb2 quits on Start plus *its* hotkey
# button -- Select by default, hardcoded past any config. Moving that onto the
# Steam button, which Steam never delivers, is what leaves the gesture usable:
# without it the first press sent the key and stopped the helper.
check("with its own quit chord moved out of the way", "-H guide" in _shell, True)
check("an entry that declares no keys is left alone",
      launchers.hotkey_helper({"id": "plain"}, path="/tmp/game.sh"), "")

_written = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR,
                        "hotkeys", "keyed-port.ini")
check("the config is written where the launcher names it", os.path.isfile(_written), True)


section("a corrected key reaches a game already added")

# The config is written when a launcher is, and nothing rewrites launchers. So
# a key found to be wrong -- Starship's menu is F1, and it was first given Esc
# -- would have reached only games added afterwards. The file is rewritten from
# the catalog instead, which the launcher already names.
_corrected = dict(_PORT, menu_key="f1")
_real_catalog = emulator_catalog.CATALOG
emulator_catalog.CATALOG = (_corrected,)
try:
    launchers.refresh_hotkey_configs()
finally:
    emulator_catalog.CATALOG = _real_catalog
with io.open(_written, encoding="utf-8") as _handle:
    _after = _handle.read()
check("the file the launcher reads holds the new key",
      "start = f1" in _after, True)


section("a helper that outlived its game")

# The trap in the launcher covers every ending a script can see. SIGKILL runs
# nothing, and what survives reads the pad and types into whatever opens next.
# Measured on the Deck: TERM left nothing behind, KILL left it running.
check("the launcher clears a stray before starting its own",
      "pkill -f" in _shell, True)

# Both helpers, because both are started the same way and leak the same way.
_gyro = os.path.join(emu_install.tools_dir(
    emulator_catalog.deck_gyro.DSU_SERVER["name"]), "sdgyrodsu")
with io.open(_gyro, "w", encoding="utf-8") as _handle:
    _handle.write("#!/bin/sh\nexit 0\n")

_calls = []
_real_run = launchers.subprocess.run


def _fake_run(args, **kwargs):
    _calls.append(args)

    class Result:
        stdout = "2"
    return Result()


launchers.subprocess.run = _fake_run
try:
    check("and the sweep reports what it stopped", launchers.stop_stray_helpers(), 4)
    check("asking only about our own binary",
          any("gptokeyb2" in part for part in _calls[0]), True)
    # The motion server is started the same way and leaks the same way, and a
    # survivor holds the DSU port so the next game gets no gyro at all.
    check("and about the motion server, which has the same hole",
          any(any("gyro" in part for part in call) for call in _calls), True)
finally:
    launchers.subprocess.run = _real_run
    # **Put the fake server back where it was: absent.** These suites share one
    # temporary tree and run in one process under `test_backend`, so a file left
    # here is a file the next suite finds. This one stood in for a fetched
    # motion server, and two checks further on assert that a server nobody
    # fetched is simply not there.
    os.remove(_gyro)


section("only a port puts keys on the pad")

_emulator = dict(_PORT)
del _emulator["port"]
check("an emulator declaring a menu key is refused",
      any("binds its menu itself" in problem
          for problem in schema.validate(_emulator, known_platforms=(), imported=True)),
      True)
check("a key that is not a key name is refused",
      any("not a key name" in problem
          for problem in schema.validate(dict(_PORT, menu_key="Ctrl+Shift+M"),
                                         known_platforms=(), imported=True)),
      True)


if __name__ == "__main__":
    summary()
