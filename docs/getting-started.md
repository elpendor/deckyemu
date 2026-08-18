# Getting started with DeckyEmu

From a plugin you have just installed to a game running, in order, with nothing
that needs Desktop Mode or a keyboard.

The rest of [docs/](.) is the reference — every setting, every table, every
option, a page per subject. This is the walkthrough: what to do first, second
and third, and what to do when one of them does not work.

**Contents** — [Before you start](#before-you-start) ·
[1. Get a game onto the Deck](#1-get-a-game-onto-the-deck) ·
[Skipping the code next time](#skipping-the-code-next-time) ·
[2. Get something to run it](#2-get-something-to-run-it) ·
[3. Add the game to Steam](#3-add-the-game-to-steam) ·
[Everyday tasks](#everyday-tasks) ·
[When something does not work](#when-something-does-not-work) ·
[Where your files are](#where-your-files-are)

## Before you start

Open the Quick Access panel (the **…** button) and find **DeckyEmu**. The top row
tells you where you stand:

| It says | Meaning |
| --- | --- |
| **Setup needed** | Nothing can run a game yet — start at step 2 |
| **Ready to use** | At least one core or emulator is available |

Below it, a button reading **Set up emulators** or **Settings** opens the settings
page, which is where everything configured once lives. The panel itself stays
small on purpose: it is what you use while playing.

You do not need RetroArch, a core, or any emulator installed beforehand. All three
can be done from here.

## 1. Get a game onto the Deck

Skip this if your ROMs are already on the device or on an SD card — the picker in
step 3 can reach them where they are.

Otherwise, in **Add a game**, press **Transfer to Deck**. The Deck starts a small
web server on your local network and shows two ways in, because devices differ:

- **Scan the QR code** with a phone. It carries the full address, so scanning goes
  straight to the upload page.
- **Type the short address** shown, on a laptop or desktop, then enter the
  **six-digit code**. A desktop cannot scan a code, and a 22-character token is
  not something anyone will type.

Pick your files on that device and they upload. You will see each one arrive, with
a progress bar and a **Cancel** for anything you started by mistake.

Some things worth knowing:

- **You can close the dialog.** A transfer keeps going, and a **Receiving files**
  row appears in the Quick Access panel with a **Show transfer** button, so a
  running upload is never invisible.
- **The server stops itself** when you close the dialog, after 30 minutes idle,
  and when the plugin unloads.
- **BIOS files and keys go the same way.** They are recognised by name and offered
  to the emulator that needs them — see [step 2](#2-get-something-to-run-it).
- **Send whole games.** For a multi-disc or `.cue`/`.bin` game, send every file.
  The plugin will not file a game it cannot account for in full.

Everything lands in `~/deckyemu/transfer`, whatever it is. Each received file gets
an **Add** button that drops straight into step 3 with the name and artwork
already worked out.

### Skipping the code next time

By default the address, the token and the six-digit code are all new every
session, so nothing outlives one transfer and a saved link is worthless the next
day. That is the safe default, and it means typing the code every time.

Turn on **Remember trusted devices** and the address stays the same instead. Your
laptop or phone can bookmark the upload page and come straight back to it with
nothing to type at all — no address, no code. For a device you send games from
regularly, this is the single biggest thing you can do to make it painless.

The trade-off is worth understanding, which is why it is a choice rather than the
default: it changes what the link *is*. A bookmark stops being a one-off and
becomes a standing key that works whenever the server is running. That is the
right deal for your own laptop and the wrong one for a house guest who scanned
the QR code once.

**Reset link** appears while it is on and invalidates every bookmark at once. It
is all or nothing, because the link is the credential — there is no per-device
list to prune. It is refused while a transfer is running, so it cannot cut off an
upload halfway.

## 2. Get something to run it

There are two routes, and you can use both. Which one you want depends on the
system.

### RetroArch and cores — for most retro systems

Open **Settings → RetroArch**. If RetroArch is not installed, press **Install
RetroArch**: it installs from Flathub for your user only, so no password is asked
for.

Then, under **Install cores**, pick a system and pick a core. Cores come from
libretro's own buildbot, the same source RetroArch's Core Downloader uses.

You do not have to guess which core you need. If you pick a ROM in step 3 that
nothing installed can run, the panel offers the cores that could and carries on
into adding the game once one is installed.

### Standalone emulators — for the bigger consoles

Open **Settings → Emulators** for the systems RetroArch does not cover:
GameCube and Wii, PlayStation 1 through 4, PSP, PS Vita, Switch, Wii U, 3DS and
original Xbox. Press install on one and the emulator is downloaded and set up —
the system it plays, the file types it accepts and its launch arguments are all
filled in.

Two things to expect here:

- **Installing is not always enough to play.** Some systems need BIOS files, keys
  or firmware that are yours to dump and that this plugin will never download. The
  prompt says which before the download starts, and a **BIOS and firmware**
  section appears under the emulator list showing what is still missing. Send
  those files the same way as a ROM and press **Install** on the row.
- **Controller bindings and fullscreen are written for you**, because several of
  these emulators bind a keyboard and start windowed as they ship.

For an emulator not in that list, see
[docs/emulator-definitions.md](emulator-definitions.md).

## 3. Add the game to Steam

Back in the Quick Access panel, under **Add a game**:

1. **Press Choose a game** and pick the ROM. The picker opens on the transfer
   folder to begin with, so a game you have just sent is right there; after that
   it opens where you last picked one, and it goes back to the transfer folder
   whenever something new is waiting in it. A file that arrived in step 1 can
   also be added straight from its row in the transfer dialog.
2. **Pick what runs it.** Only cores and emulators that handle that file type are
   offered, with the one you used last for it first. A toggle reveals everything
   installed, for when the right answer is not in the short list.

   Most cores cover more than one system — Genesis Plus GX alone reads Genesis,
   Game Gear, Master System, Sega CD, SG-1000 and PICO — so a **System** row
   appears when the one you picked does. It starts on what the file says it is,
   and it decides the shelf the game goes on and where its cover comes from.
   A core that covers one system has nothing to ask, and gets no row.
3. **Check the name and the cover.** `Super Mario World (USA) [!].smc` becomes
   *Super Mario World*. If the cover is wrong, **Wrong game? Choose the right
   one** lets you say which game it is — that sets the name as well as the
   cover — or **Choose the right game**, when nothing was found at
   all. Worth a glance either way: title matching is fuzzy, and a wrong cover is
   easier to fix now than later.
4. **Press Add to Steam.** The shortcut is created, the artwork applied, and the
   game filed into a collection so it is findable in your library rather than
   lost among every other non-Steam shortcut.

The game is now in your Steam library and launches like anything else — with
gamescope, Steam Input and the overlay all behaving normally, because Steam is
what starts it.

**One game at a time.** You see the core, the name and the cover before anything
reaches your library. There is no bulk import.

### PlayStation and Vita packages

A `.pkg` is not a game yet. Pick one and the panel offers to unpack it first —
RPCS3, shadPS4 or Vita3K does the work, with a progress bar, and the add flow
carries on from whatever came out. You never have to know the product code or find
the executable inside.

## Everyday tasks

| You want to | Where |
| --- | --- |
| See what you have added | **Added games (n)** in the Quick Access panel |
| Rename a game, or change its core, system or artwork | The pencil on its row in **Added games**, or the cog on the game's own page → **DeckyEmu → Edit** |
| Remove a game | The bin on its row, or **DeckyEmu → Remove** on its page — **this deletes the ROM** if the plugin filed it |
| Move a game to the right system | Edit it and change **System**. Saving moves it to that system's collection |
| Update an emulator, or go back to an earlier build | **Settings → Emulators**, the branch button on its row |
| Update RetroArch, or go back | **Settings → RetroArch → RetroArch version** |
| Change how games are grouped | **Settings → Collections** |
| Improve artwork | **Settings → Artwork**, which sets up a SteamGridDB key |
| Turn on achievements | **Settings → RetroArch → Achievements** |
| Stop RetroArch's on-screen chatter | **Settings → RetroArch → Launching** |
| Reach RetroArch's menu with a controller | **Settings → RetroArch → Launching** |
| Update the plugin | **Settings → Updates** |
| Find entries that drifted out of sync | **Settings → Library** |

Editing a game keeps its Steam entry, so playtime and its place in a collection
survive the change.

## When something does not work

| Symptom | Likely cause |
| --- | --- |
| The panel says the backend is not responding | The plugin restarts when its files change, and calls in flight are dropped. Press **Try again**; it is expected right after an update |
| No cores are offered for a ROM | Nothing installed handles that file type — the panel offers the cores that do, and can install one for you |
| A core is installed but a ROM still matches nothing | The core may be missing its `.info` file, so nothing knows what it plays. Reinstall it from **Install cores** |
| An emulator says "installed, but not set up for adding games yet" | It was installed by something other than this plugin, so nothing knows what it plays. Press the chain-link button on its row to register it |
| A game launches the emulator but no game | Its launch arguments are wrong. Edit them under **All registered emulators** |
| A game starts in a window | The emulator's fullscreen switch is wrong, or it uses a setting rather than a flag |
| An emulator closes immediately | For a hand-supplied AppImage, the execute bit is usually missing; re-saving it in the editor repairs that |
| A game worked and stopped after an emulator update | Open that emulator's version dialog and pick an earlier build. Choosing one also holds it, so nothing moves it back |
| An emulator you held updated anyway | The hold was released, or the emulator is not the one you held — a held row says *held* under its name |
| A game will not boot and the system needs firmware | Check **BIOS and firmware** — a missing file looks exactly like a game failing |
| A bookmarked transfer link stopped working | Either **Remember trusted devices** is off, so every session issues a new one, or **Reset link** was pressed — which invalidates all of them at once |
| A ROM stayed in `transfer/` after adding | Something was unaccounted for: a disc a playlist names, or a different dump of the same name already filed |
| The cover or the name is wrong | **Wrong game? Choose the right one** on the add panel, or the pencil on an added game |
| A game is on the wrong system's shelf, with that system's cover | Its core covers several systems and the game was added before the **System** row existed. Edit it, set **System**, and look the artwork up again |
| A game opens with the sticks moving a pointer and no buttons | Steam picked a layout for it. It files controller layouts by the game's *name*, so a title it recognises can arrive with a browser layout attached. Games added now get a gamepad layout pinned; for an older one, open its controller settings and pick **Gamepad With Joystick Trackpad** |
| A collection is left holding nothing | **Settings → Collections** tidies stale ones |
| A game you removed is still in Steam | **Settings → Library** finds entries that drifted apart, and offers the fix for each |

If something is wrong that is not here, the plugin's log is the place to look:

```
~/homebrew/logs/deckyemu/
```

## Where your files are

Everything the plugin puts on the device that is yours to keep is under
`~/deckyemu`, and uninstalling the plugin does not touch any of it.

| Folder | What is in it |
| --- | --- |
| `transfer/` | The inbox. Everything sent from another device lands here |
| `roms/` | The library. A ROM moves to `roms/<system>/` when its game is added |
| `emulators/` | Emulators installed here that are not Flatpaks |
| `firmware/` | BIOS files, keys and firmware you supplied |

**The one rule worth knowing:** a ROM sent through Transfer is *moved* into the
library when you add its game, and a ROM you picked from anywhere else — an SD
card, your home folder, an existing library — is left exactly where it is. That
also decides what removing a game can delete: only ROMs the plugin filed itself.
Full detail under
[Where a ROM ends up](transfers.md#where-a-rom-ends-up).
