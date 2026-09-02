# DeckyEmu

**A complete emulation setup for the Steam Deck:** install emulators, transfer
ROMs, add games to Steam, back up saves — all with a controller.

![The Quick Access panel in Game Mode, showing a ROM identified as Tobu Tobu
Girl with its boxart, one press from being added to
Steam.](docs/images/adding-a-game.jpg)

**Install an emulator** in one press — RetroArch and its cores, or Dolphin,
PCSX2, DuckStation, PPSSPP, RPCS3, shadPS4, Vita3K, Ryujinx, Cemu, Azahar,
xemu, Xenia Canary and Supermodel — along with the BIOS and firmware each one needs.
Bring your own instead, if you would rather.

![The Emulators tab in the settings page, listing Azahar, Cemu, Dolphin and
DuckStation with the system and file types each one
handles.](docs/images/installing-an-emulator.jpg)

**Get your games onto the Deck** from a phone or a laptop over your own network.
ROMs, disc sets, zipped archives and PlayStation 3, PS4 and Vita packages all
arrive, unpack and are filed under their system.

![The transfer dialog in Game Mode: a QR code beside a short address and a
six-digit code, with a received Game Boy ROM listed underneath and an Add button
next to it.](docs/images/sending-a-game.jpg)

**Play them from Steam**, with a clean name, boxart and a shelf of their own —
and back your save data up to another device, or put it back from one.

![Steam's home screen. A game added from a ROM sits first under Recent Games
with its own wide artwork, beside games bought from
Steam.](docs/images/a-game-in-steam.jpg)

Everything happens with a controller, from the Quick Access panel. The one
exception is [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
itself, which is installed from Desktop Mode: that is the only trip you make.
DeckyEmu's own install happens in Game Mode, and nothing after it needs a
keyboard, a desktop or a second device.

DeckyEmu ships no games, no BIOS files and no encryption keys, and downloads
none of them. It installs emulators from their own publishers and points them at
files you already have. It also fetches two helpers that are not emulators:
[the PS4 package extractor](docs/emulators.md#unpacking-a-ps4-package), if you
add a PlayStation 4 `.pkg`, and
[a motion server](docs/emulators.md#motion-controls), if you install an emulator
that uses one.

## Quick start

You need [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader),
which is the one thing installed from Desktop Mode. Everything below happens in
Game Mode with a controller, DeckyEmu's own install included — and nothing else
is needed first: RetroArch and its cores install from the plugin, and an
existing RetroArch is detected automatically.

1. Open the **Decky** menu in the Quick Access panel and go to its settings.
2. Find **Install from URL** and give it:

   ```
   https://get.deckyemu.xyz
   ```

3. Confirm Decky's prompt. DeckyEmu appears in the Quick Access panel.

That short address redirects to the latest release, and is kept short because it
is typed on an on-screen keyboard. To paste an address you can verify instead —
reasonable, for a URL that installs software — use
`https://github.com/elpendor/deckyemu/releases/latest/download/deckyemu.zip`.

For a Deck that cannot reach GitHub, see
[the manual install](docs/installing.md#manual-install).

## Adding your first game

1. **Send the ROM.** *Send files from another device* in the Quick Access panel
   shows a QR code, or a short address and a six-digit code. The file lands ready
   to add.
2. **Pick a core.** Only cores that can run that file are offered, the one you
   used last for it first — and for a core covering several systems, which one
   this game is, starting on what the file says. If nothing installed can run it,
   the cores that could are offered there and then.
3. **Add to Steam.** `Super Mario World (USA) [!].smc` becomes *Super Mario
   World*, boxart is applied, and the game is filed under a collection so it is
   findable rather than lost among every other non-Steam shortcut.

One ROM at a time, so you see the core, the name and the boxart before anything
reaches your library. Games added this way are tracked, so the plugin can remove
a shortcut and its launcher later without touching your ROM.

**[docs/getting-started.md](docs/getting-started.md) walks through it properly**
— install to first game in three steps, then the everyday tasks and a
symptom-by-symptom list for when one of them misbehaves.

## Documentation

| | |
| --- | --- |
| [Getting started](docs/getting-started.md) | The walkthrough: install to first game, then everyday tasks and what to do when one misbehaves |
| [Installing](docs/installing.md) | Installing and uninstalling, the Desktop Mode fallback, and what the plugin puts on your Deck |
| [Getting files onto the Deck](docs/transfers.md) | Sending ROMs, BIOS files and keys from another device, and where each ends up |
| [RetroArch](docs/retroarch.md) | Installing it and its cores, fullscreen, on-screen chatter, the menu combo, achievements |
| [Standalone emulators](docs/emulators.md) | The one-press catalog, moving between builds, registering your own |
| [Artwork](docs/artwork.md) | Where cover art comes from, and getting a SteamGridDB key in without a keyboard |
| [Your library](docs/library.md) | Editing a game, collections, backing up and restoring save data, and putting things back in order |
| [Updates and problems](docs/updates.md) | Keeping it current, and what to send when something breaks |
| [Emulator definitions](docs/emulator-definitions.md) | The JSON format for setting up an emulator this plugin does not ship |
| [Development](docs/development.md) | Building it, running it against a real Deck, and the layout of the tree |
| [Contributing](CONTRIBUTING.md) | What is worth sending, and what to know before opening a pull request |

## Not implemented yet

- **Batch importing a folder of ROMs.** Needs an answer to what the
  one-at-a-time flow asks per game: no matching core, several possible cores,
  wrong artwork. Getting those wrong in bulk is what makes it tedious to undo.

## Thanks

Parts of this were settled by reading other people's work instead of guessing,
and each of those saved a round of it. Two are not readings at all — they are
software this plugin downloads and runs.

- **[EmuDeck](https://github.com/EmuDeck)** and
  **[RetroDECK](https://github.com/RetroDECK/RetroDECK)** publish controller
  configurations tested on this hardware, and that is where the values written
  on install came from rather than a reading of a button table — which would
  have got several wrong, because face buttons match by position and not by
  letter. Both projects also cover far more systems than this one does.
- **[TabMaster](https://github.com/Tormak9970/TabMaster)** for the Quick Access
  header, which has a title class of its own and is what stopped this plugin's
  name sitting off-centre against Decky's back arrow.
- **[shadPS4Plus](https://github.com/AzaharPlus/shadPS4Plus)** for the PS4
  package extractor. shadPS4 cannot unpack a `.pkg` and no fork of it can
  either — the code that did was taken out and published as a command-line
  tool, descended from shadPS4's own extractor, so what comes out is what
  shadPS4 expects. GPL-2.0, fetched from its own release page the first time a
  PS4 package is added.
- **[SteamDeckGyroDSU](https://github.com/kmicki/SteamDeckGyroDSU)** is the
  other one: the motion server behind gyro in Cemu, Ryujinx, Azahar and any
  definition you import that asks for it. It reads the Deck's own sensors and
  serves them over the cemuhook protocol on `127.0.0.1:26760`, which is what
  lets those emulators have motion while the controller stays Steam's — no
  layout, back button or stick curve is given up for it. MIT, fetched from its
  own release page when you install an emulator that wants it.
- **[unifideck](https://github.com/mubaraknumann/unifideck)** for the reason the
  update button works in Game Mode: the Quick Access panel is a popup window
  there, so Decky's global websocket sits on its opener rather than on `window`.
  A missing fallback shows up only in Game Mode, at the one moment a user is
  trying to update.

Built from the
[Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
