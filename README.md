# DeckyEmu

**Add emulated games to your Steam library as real entries — clean name, boxart,
and a shelf of their own — without ever leaving Game Mode.**

![The Quick Access panel in Game Mode, showing a ROM identified as Tobu Tobu
Girl with its boxart, one press from being added to
Steam.](docs/images/adding-a-game.jpg)

Pick a ROM, pick a core or emulator, and the game appears in Big Picture like
anything else you own. Works with RetroArch's libretro cores and with standalone
emulators — Dolphin, PCSX2, DuckStation, PPSSPP, RPCS3, shadPS4, Vita3K,
Ryujinx, Cemu, Azahar and xemu — each installable in one press from the plugin,
or registered by hand.

Everything happens with a controller, from the Quick Access panel. There is no
step that needs Desktop Mode, a keyboard or a second device — including the
first install.

DeckyEmu ships no games, no BIOS files and no encryption keys, and downloads
none of them. It installs emulators from their own publishers and points them at
files you already have.

## Quick start

You need [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
Nothing else: RetroArch and its cores install from the plugin, and an existing
RetroArch is detected automatically.

1. Open the **Decky** menu in the Quick Access panel and go to its settings.
2. Find **Install from URL** and give it:

   ```
   https://get.deckyemu.workers.dev
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
| [Installing](docs/installing.md) | The manual install, and what the plugin puts on your Deck |
| [Getting files onto the Deck](docs/transfers.md) | Sending ROMs, BIOS files and keys from another device, and where each ends up |
| [RetroArch](docs/retroarch.md) | Installing it and its cores, fullscreen, on-screen chatter, the menu combo, achievements |
| [Standalone emulators](docs/emulators.md) | The one-press catalog, moving between builds, registering your own |
| [Artwork](docs/artwork.md) | Where cover art comes from, and getting a SteamGridDB key in without a keyboard |
| [Your library](docs/library.md) | Editing a game, collections, and putting things back in order |
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
and each of these saved a round of it.

- **[EmuDeck](https://github.com/EmuDeck)** and
  **[RetroDECK](https://github.com/RetroDECK/RetroDECK)** publish controller
  configurations tested on this hardware, and that is where the values written
  on install came from rather than a reading of a button table — which would
  have got several wrong, because face buttons match by position and not by
  letter. Both projects also cover far more systems than this one does.
- **[TabMaster](https://github.com/Tormak9970/TabMaster)** for the Quick Access
  header, which has a title class of its own and is what stopped this plugin's
  name sitting off-centre against Decky's back arrow.
- **[unifideck](https://github.com/mubaraknumann/unifideck)** for the reason the
  update button works in Game Mode: the Quick Access panel is a popup window
  there, so Decky's global websocket sits on its opener rather than on `window`.
  A missing fallback shows up only in Game Mode, at the one moment a user is
  trying to update.

Built from the
[Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
