# Installing DeckyEmu

How to install it with a controller, the Desktop Mode fallback if your Deck
can't reach GitHub, and what lands on your device.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Installing

You need [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
first. That's the one thing you install from Desktop Mode, and the only trip you
make — everything below happens on the couch.

1. Open the **Decky** menu in the Quick Access panel and go to its settings.
2. Find **Install from URL** and give it:

   ```
   https://get.deckyemu.xyz
   ```

3. Confirm Decky's prompt.

DeckyEmu shows up in the Quick Access panel.

That address is short because you're typing it on an on-screen keyboard. It
redirects to the latest release. Want to paste something you can check first —
fair enough, for a URL that installs software? Use
`https://github.com/elpendor/deckyemu/releases/latest/download/deckyemu.zip`.

> **Note:** you never need any of this again. Updates happen from **Settings →
> Updates**.

## Manual install

Only do this if your Deck can't reach GitHub, or you're installing a build you
made yourself. Everyone else wants the route above. This one needs Desktop Mode.

1. Download `deckyemu.zip` from the
   [releases page](https://github.com/elpendor/deckyemu/releases).
2. Unpack it into `~/homebrew/plugins`, so that
   `~/homebrew/plugins/deckyemu/main.py` exists. The zip already has the folder
   at its root.
3. Restart Steam if the plugin doesn't appear.

> **Warning:** the folder must be named `deckyemu`. Decky works out the
> settings, runtime and log directories from the plugin's folder name, so
> renaming it orphans everything the plugin has stored — including which games
> it added.

Some Decky installs root-own `~/homebrew/plugins` and some don't. If the unpack
gets refused, you need `sudo`.

## Where things live

The plugin has two halves. The Quick Access panel is for what you do while
playing — add a game, see what you've added. The settings page is for everything
you configure once:

| Tab | What's there |
| --- | --- |
| **RetroArch** | What's installed, the installer, cores, launch behaviour, achievements, uninstalling |
| **Emulators** | One-press installs for Dolphin, PCSX2 and friends, plus any you register yourself |
| **Artwork** | Artwork source and your SteamGridDB key |
| **Collections** | How your added games get grouped in Big Picture |
| **Library** | Orphan check, and removing every game the plugin added |
| **Updates** | Which build you have, what changed, installing a newer one, reporting a problem |

Anything the plugin puts on your device that's yours to keep lives under
`~/deckyemu`:

| Folder | What's in it |
| --- | --- |
| `transfer/` | Your inbox. Everything sent from another device lands here |
| `roms/` | Your library. ROMs move to `roms/<system>/` when you add the game |
| `emulators/` | Emulators from the Emulators tab that aren't Flatpaks |
| `firmware/` | BIOS files, keys and firmware you supplied |

Uninstalling the plugin doesn't touch any of it.

## Uninstalling

**Your games keep working.** Decky removes `~/homebrew/plugins/deckyemu` — the
plugin's own code — and nothing else. Your records, launcher scripts, ROMs and
Steam shortcuts all live somewhere else and all survive, so everything in your
library launches exactly like before. You just lose the panel that manages them.

Which also means reinstalling picks up where you left off: same games, same
collections, same emulator setup, same firmware state, nothing to redo.

Uninstalling Decky itself is safe for the same reason. Its uninstaller removes
its service and its own binary, and leaves the plugins, settings and data
folders underneath alone.

### Removing it for good

Nothing gets cleaned up for you, so a permanent removal takes a few steps. Do
them **before** you uninstall — afterwards there's no panel to do them from.

1. **Library → Remove all DeckyEmu games from Steam**, if you want them gone.
   This takes the shortcuts and collections as well as the records. Skip it if
   you want to keep playing them.
2. **Library → Check the library**, and take any **Remove** it offers. One of
   them is an entry called *DeckyEmu setup* — the shortcut used to open an
   emulator's own window for firmware installs. It's hidden from your library,
   so it's the one thing here you can't find and remove yourself afterwards.
3. Uninstall.
4. Delete `~/homebrew/settings/deckyemu` and `~/homebrew/data/deckyemu` if you
   want the records and launcher scripts gone too. Leaving them costs a few
   hundred kilobytes, and it's what makes a later reinstall seamless.

**Already uninstalled and want that hidden entry gone?** Install the plugin
again and run the library check. That check is the only thing that can find it.

Your emulators, ROMs, saves and firmware are untouched by all of this. They're
under `~/deckyemu` and in each emulator's own folder.
