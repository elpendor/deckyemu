# Installing DeckyEmu

The one-time install, the Desktop Mode fallback, and what the plugin puts on
your Deck.

Back to [the README](../README.md).

**Contents** — [Manual install](#manual-install) ·
[Where things live](#where-things-live)

## Manual install

The route above is the one to use; this is here for a Deck that cannot reach
GitHub, or a build you made yourself. It needs Desktop Mode once. Download
`deckyemu.zip` from the
[releases page](https://github.com/elpendor/deckyemu/releases) and unpack it into
`~/homebrew/plugins`, so that `~/homebrew/plugins/deckyemu/main.py` exists — the
zip already has the folder at its root.

**The folder must be named `deckyemu`.** Decky derives the settings, runtime and
log directories from the plugin's directory name, so renaming it orphans
everything the plugin has stored, including which games it added.

Some Decky installs root-own `~/homebrew/plugins` and some do not; if the unpack
is refused, it needs `sudo`. Restart Steam if the plugin does not appear.

## Where things live

The plugin has a Quick Access panel for what you do while playing — add a game,
see what has been added — and a settings page for everything configured once:

| Tab | What is there |
| --- | --- |
| **RetroArch** | What is installed, the installer, cores, launch behaviour, achievements, and uninstalling it |
| **Emulators** | One-click installs for Dolphin, PCSX2 and friends, plus any you register yourself |
| **Artwork** | Artwork source and the SteamGridDB key |
| **Collections** | How added games are grouped in Big Picture |
| **Library** | Orphan check, and removing every game the plugin added |
| **Updates** | Which build is installed, what changed in it, installing a newer one, and reporting a problem |

Anything the plugin puts on your device that is yours to keep lives under
`~/deckyemu`:

| Folder | What is in it |
| --- | --- |
| `transfer/` | The inbox. Everything sent from another device lands here, whatever it is |
| `roms/` | The library. A ROM is moved to `roms/<system>/` when its game is added |
| `emulators/` | Emulators installed from the Emulators tab that are not Flatpaks |
| `firmware/` | BIOS files, keys and firmware you supply |

Uninstalling the plugin does not touch any of it.
