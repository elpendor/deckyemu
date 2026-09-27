# DeckyEmu

**A complete emulation setup for the Steam Deck:** install emulators, transfer
ROMs, add games to Steam, back up saves — all with a controller.

![The Quick Access panel in Game Mode, showing a ROM identified as Tobu Tobu
Girl with its boxart, one press from being added to
Steam.](docs/images/adding-a-game.jpg)

**Install an emulator** in one press — RetroArch and its cores, or Dolphin,
PCSX2, DuckStation, PPSSPP, RPCS3, shadPS4, Vita3K, Ryujinx, Cemu, Azahar,
xemu, Xenia Canary, Supermodel and BigPEmu — along with the BIOS and firmware each
one needs.
Bring your own instead, if you would rather.

**Or a native port**, where a game has been rebuilt to run on the Deck with no
emulator at all — Dusklight, Ship of Harkinian, 2 Ship 2 Harkinian, Ghostship,
Starship, SpaghettiKart, Lighthouse, PaperBoat and DevilutionX. Each plays one
game: point it at the dump you already own and it lands in Steam like any other,
artwork and all, with its own menu on Select+Start.

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
and keep your save data safe: back it up to another device, or to cloud storage
of your own, where closing a game copies that emulator's saves up on their own.

![Steam's home screen. A game added from a ROM sits first under Recent Games
with its own wide artwork, beside games bought from
Steam.](docs/images/a-game-in-steam.jpg)

Everything happens with a controller, from the Quick Access panel. The one
exception is [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
itself, which you install from Desktop Mode — that's the only trip you make.
DeckyEmu's own install happens in Game Mode, and nothing after it needs a
keyboard, a desktop or a second device.

DeckyEmu ships no games, no BIOS files and no encryption keys, and downloads
none of them. It installs emulators from their own publishers and points them at
files you already have. It also fetches four helpers that aren't emulators:
[the PS4 package extractor](docs/emulators.md#unpacking-a-ps4-package) if you
add a PlayStation 4 `.pkg`,
[a motion server](docs/emulators.md#motion-controls) if you install an emulator
that uses one, a hotkey helper if you add a native port, and a copy of rclone if
you switch on cloud saves.

## Install it

In Decky's settings, give **Install from URL** this address:

```
https://get.deckyemu.xyz
```

Decky Loader is the only prerequisite. RetroArch and its cores install from the
plugin, and an existing RetroArch is found on its own.

[Installing](docs/installing.md) has the rest — an address you can verify before
pasting, the manual install for a Deck that can't reach GitHub, and what lands
where on your device.

Then [Getting started](docs/getting-started.md) walks from there to a game
running: send a ROM, pick what runs it, add it to Steam.

## Documentation

| | |
| --- | --- |
| [Getting started](docs/getting-started.md) | The walkthrough: install to first game, then everyday tasks and what to do when one misbehaves |
| [Installing](docs/installing.md) | Installing and uninstalling, the Desktop Mode fallback, and what the plugin puts on your Deck |
| [Getting files onto the Deck](docs/transfers.md) | Sending ROMs, BIOS files and keys from another device, and where each one ends up |
| [RetroArch](docs/retroarch.md) | Installing it and its cores, fullscreen, on-screen chatter, the menu combo, achievements |
| [Standalone emulators](docs/emulators.md) | The one-press catalog, moving between builds, registering your own |
| [Artwork](docs/artwork.md) | Where your cover art comes from, and getting a SteamGridDB key in without a keyboard |
| [Your library](docs/library.md) | Editing a game, ROM hacks and add-ons, collections, and putting things back in order |
| [Save data](docs/saves.md) | Backing saves up, copying them to cloud storage of your own, and putting them back |
| [Updates and problems](docs/updates.md) | Keeping it current, and what to send when something breaks |
| [Emulator definitions](docs/emulator-definitions.md) | The JSON format for setting up an emulator this plugin does not ship |
| [Development](docs/development.md) | Building it, running it against a real Deck, and the layout of the tree |
| [Contributing](CONTRIBUTING.md) | What is worth sending, and what to know before opening a pull request |

## Not implemented yet

- **Batch importing a folder of ROMs.** Needs an answer to what the
  one-at-a-time flow asks per game: no matching core, several possible cores,
  wrong artwork. Getting those wrong in bulk is what makes it tedious to undo.

## Credits

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
  motion server behind gyro in Cemu, Ryujinx, Azahar and any definition you
  import that asks for it. It reads the Deck's own sensors and
  serves them over the cemuhook protocol on `127.0.0.1:26760`, which is what
  lets those emulators have motion while the controller stays Steam's — no
  layout, back button or stick curve is given up for it. MIT, fetched from its
  own release page when you install an emulator that wants it.
- **[rclone](https://github.com/rclone/rclone)** is the transfer tool behind
  cloud saves. The storage is yours and so is the account — rclone talks to some
  seventy services and this plugin has an account with none of them, so nothing
  here ever holds your credentials. MIT, fetched from its own release
  page when you switch cloud saves on.
- **[gptokeyb2](https://github.com/PortsMaster/gptokeyb2)** for reaching a
  native port's own menu. A port opens its menu with a keyboard key and Game
  Mode has no keyboard; this turns Select+Start into that key, which is how
  PortMaster does it. GPL-2.0, fetched from its own release page when you add a
  port.
- **[unifideck](https://github.com/mubaraknumann/unifideck)** for the reason the
  update button works in Game Mode: the Quick Access panel is a popup window
  there, so Decky's global websocket sits on its opener rather than on `window`.
  A missing fallback shows up only in Game Mode, at the one moment a user is
  trying to update.

Built from the
[Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
