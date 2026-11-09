# Installing DeckyEmu

How to install it, the plugin version and switching between the two, the
install for a Deck that can't reach GitHub, what lands on your device, and how
to take it off again.

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
browser. On the left, a status card marks each part of DeckyEmu with a tick or
a cross: the service, Steam's UI, the Quick Access tab and the panel, and below
them each change DeckyEmu makes to Steam's UI, so you can see which one a Steam
update broke. On the right are buttons to restart DeckyEmu, update it, go back
to the previous version, or refresh the page. The log is folded away at the
bottom.

It's there for the day something goes wrong. A Steam update that changes the
Quick Access menu can leave DeckyEmu's tab missing; the tile still works then,
because it doesn't depend on anything inside Steam's menus. If DeckyEmu isn't
answering at all, the tile restarts it, and if that doesn't help it goes back to
the version before.

An update that fails to start three times is rolled back on its own, and the
tile says so.

While the plugin version is the one in use, the tile says so and offers **Use
this version instead**, which switches back to the standalone version and
restarts Steam. That works even when a Steam update has broken Decky.

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

## The plugin version

DeckyEmu also comes as a plugin for
[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader), built from
the same code and released alongside the standalone version. The two do the
same things with the same games and settings, and both keep themselves up to
date. What differs is how they get into Steam. The standalone version needs
nothing else, and keeps working when a Steam update breaks Decky. The plugin
suits you if you already use Decky and want DeckyEmu in its menu with the rest.

To install the plugin, open the **Decky** menu in Quick Access, go to its
settings, find **Install from URL** and give it `https://get.deckyemu.xyz`. That
redirects to
`https://github.com/elpendor/deckyemu/releases/latest/download/deckyemu.zip`,
which you can paste instead if you'd rather see where it goes.

## Switching between them

You can have both installed. Only one runs at a time, and they share
everything: your games, settings, emulators and firmware are the same whichever
one you're using.

At the bottom of the tab of the one in use, **Other version** offers the other
one, once it's installed. Switching turns this one off and the other on, which
takes a couple of seconds, then asks to restart Steam so the right tab shows.
The standalone version, when it's not the one in use, is off entirely and
doesn't start at login.

The plugin offers the standalone version even before it's installed: switching
then downloads it, checks it against the digest published with the release,
installs it and starts it, all from the tab, with no trip to Desktop Mode.

The tab of the one not in use says which one is, and has a **Use this one
instead** button. That's your way back if a Steam update ever breaks the other
one's tab.

Running the install script makes the standalone version the one in use, even
if the plugin was.

Plugin releases from before the two shared a codebase kept their state under
`~/homebrew`. Either version moves it to `~/.local/share/deckyemu` the first
time it starts, and leaves a link where it was, so every game you already added
keeps launching without being touched. Update an old plugin, or remove it from
Decky's plugin list: it doesn't know how to share.

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

The plugin version uninstalls from Decky's plugin list, with the same result.

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
