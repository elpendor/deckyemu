# Installing DeckyEmu

How to install it, the install for a Deck that can't reach GitHub, what lands on
your device, and how to take it off again.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Installing

This is the one thing you do in Desktop Mode, and the only trip you make —
everything after it happens on the couch.

1. Switch to Desktop Mode and open **Konsole**.
2. Run:

   ```
   curl -fsSL https://github.com/elpendor/deckyemu/releases/latest/download/install.sh | sh
   ```

3. Switch back to Game Mode.

DeckyEmu shows up as its own tab in the Quick Access menu, and as a **DeckyEmu**
tile in your library.

The script is short and worth reading before you run it — it's
[`install.sh`](https://github.com/elpendor/deckyemu/blob/main/install.sh) in the
repository. It downloads the newest release and lets that release install
itself: its files go under `~/.local/share/deckyemu`, and it starts as a
background service for your user. Nothing is installed system-wide and it never
asks for a password.

If Steam was already running with its debugging port off, DeckyEmu turns the
port on and its tab appears the next time Steam starts — switching back to Game
Mode does that.

> **Note:** you never need any of this again. Updates happen from **Settings →
> Updates**, or from the library tile.

## Installing without GitHub

Only do this if your Deck can't reach GitHub, or you're installing a build you
made yourself.

1. Download `deckyemu-service.tar.gz` from the
   [releases page](https://github.com/elpendor/deckyemu/releases) on another
   machine and copy it to the Deck.
2. Unpack it anywhere, and run the `install.sh` inside:

   ```
   tar xzf deckyemu-service.tar.gz
   sh deckyemu/install.sh
   ```

## The library tile

The **DeckyEmu** tile in your library opens a page of its own in Steam's
browser: which version is running, whether its tab is showing, and buttons to
update, go back to the previous version, or restart DeckyEmu.

It's there for the day something goes wrong. A Steam update that changes the
Quick Access menu can leave DeckyEmu's tab missing; the tile still works then,
because it doesn't depend on anything inside Steam's menus. If DeckyEmu isn't
answering at all, the tile restarts it, and if that doesn't help it goes back to
the version before.

An update that fails to start three times is rolled back on its own, and the
tile says so.

## Where things live

DeckyEmu has two halves inside Steam. The Quick Access tab is for what you do
while playing — add a game, see what you've added. The settings page is for
everything you configure once:

| Tab | What's there |
| --- | --- |
| **RetroArch** | What's installed, the installer, cores, launch behaviour, achievements, uninstalling |
| **Emulators** | One-press installs for Dolphin, PCSX2 and friends, plus any you register yourself |
| **Artwork** | Artwork source and your SteamGridDB key |
| **Collections** | How your added games get grouped in Big Picture |
| **Library** | Orphan check, and removing every game DeckyEmu added |
| **Updates** | Which build you have, what changed, installing a newer one, reporting a problem |

DeckyEmu itself lives under `~/.local/share/deckyemu`: the installed versions,
your settings and records, the launcher scripts your games start through, and
its logs.

Anything that's yours to keep lives under `~/deckyemu`:

| Folder | What's in it |
| --- | --- |
| `transfer/` | Your inbox. Everything sent from another device lands here |
| `roms/` | Your library. ROMs move to `roms/<system>/` when you add the game |
| `emulators/` | Emulators from the Emulators tab that aren't Flatpaks |
| `firmware/` | BIOS files, keys and firmware you supplied |

Uninstalling DeckyEmu doesn't touch any of it.

## Moving from the Decky Loader plugin

Earlier releases of DeckyEmu were a plugin for Decky Loader. The first time this
version starts it moves that install's settings, records and logs to
`~/.local/share/deckyemu`, and leaves a link where they were, so every game you
already added keeps launching without being touched.

Then remove the old plugin, so the two don't run side by side — from Decky's own
plugin list, or in Konsole:

```
sudo rm -rf ~/homebrew/plugins/deckyemu
```

## Uninstalling

In Konsole:

```
python3 ~/.local/share/deckyemu/current/service.py --uninstall
```

**Your games keep working.** That removes the service and DeckyEmu's own code,
and nothing else. Your records, launcher scripts, ROMs and Steam shortcuts all
survive, so everything in your library launches exactly like before. You just
lose the tab that manages them. Its tab leaves the Quick Access menu the next
time Steam starts.

Which also means reinstalling picks up where you left off: same games, same
collections, same emulator setup, same firmware state, nothing to redo.

### Removing it for good

Nothing gets cleaned up for you, so a permanent removal takes a few steps. Do
them **before** you uninstall — afterwards there's no tab to do them from.

1. **Library → Remove all DeckyEmu games from Steam**, if you want them gone.
   This takes the shortcuts and collections as well as the records. Skip it if
   you want to keep playing them.
2. **Library → Check the library**, and take any **Remove** it offers. One of
   them is an entry called *DeckyEmu setup* — the shortcut used to open an
   emulator's own window for firmware installs. It's hidden from your library,
   so it's the one thing here you can't find and remove yourself afterwards.
3. Uninstall, as above, and delete the **DeckyEmu** tile from your library.
4. Delete `~/.local/share/deckyemu` if you want the records and launcher scripts
   gone too. Leaving it costs a few hundred kilobytes, and it's what makes a
   later reinstall seamless.

**Already uninstalled and want that hidden entry gone?** Install DeckyEmu again
and run the library check. That check is the only thing that can find it.

Your emulators, ROMs, saves and firmware are untouched by all of this. They're
under `~/deckyemu` and in each emulator's own folder.
