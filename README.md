# DeckyEmu

A Decky plugin that adds emulated games to your Steam library as proper entries:
pick a ROM, pick a core or emulator, and the game shows up in Big Picture with a
clean name and boxart.

Works with RetroArch's libretro cores and with standalone emulators — Dolphin,
PCSX2, Cemu, RPCS3 and so on, installable in one press from the plugin, or
registered by hand. Everything happens in Game Mode.

DeckyEmu ships no games, no BIOS files and no encryption keys, and downloads
none of them. It installs emulators from their own publishers and points them at
files you already have.

## Contents

**Start here** — [What it does](#what-it-does) · [Requirements](#requirements) ·
[Installing](#installing) · [Where things live](#where-things-live)

New to it? [docs/getting-started.md](docs/getting-started.md) is the walkthrough —
install to first game in three steps, then the everyday tasks and a
symptom-by-symptom list for when one of them misbehaves. What follows here is the
reference.

**Getting games in** —
[Sending files from another device](#sending-files-from-another-device) ·
[Where a ROM ends up](#where-a-rom-ends-up) ·
[Installing RetroArch and cores](#installing-retroarch-and-cores) ·
[Installing an emulator](#installing-an-emulator) ·
[Updating an emulator](#updating-an-emulator-or-going-back) ·
[Adding your own emulator](#adding-your-own-emulator) · [Editing a game](#editing-a-game)

**How the library looks** — [Collections](#collections) ·
[Artwork sources](#artwork-sources)

**RetroArch behaviour** —
[Fullscreen and on-screen chatter](#fullscreen-and-retroarchs-on-screen-chatter) ·
[Getting into RetroArch's menu](#getting-into-retroarchs-menu) ·
[RetroAchievements](#retroachievements)

**Keeping it tidy** — [Orphaned entries](#orphaned-entries) ·
[Removing everything](#removing-everything) ·
[Updates](#updates-and-what-changed) · [TODO](#todo)

**Building on it** — [docs/development.md](docs/development.md) covers how the
pieces fit, building, running it against a real Deck, the layout of the tree,
and the Steam APIs it leans on. [Thanks](#thanks)

## What it does

1. **Pick a ROM** through Decky's file picker. It opens where you last picked one.
2. **Pick a core.** Only cores that support that extension are offered, the one
   you used last for it first. A toggle reveals every installed core.
3. **Get a real name and boxart.** `Super Mario World (USA) [!].smc` becomes
   *Super Mario World*, and `Legend of Zelda, The - A Link to the Past` becomes
   *The Legend of Zelda: A Link to the Past*.
4. **Add to Steam.** The shortcut is created, artwork applied, and the game filed
   under a collection so it is findable rather than lost among every other
   non-Steam shortcut.

Games added this way are tracked, so the plugin can remove a shortcut and its
launcher later without touching your ROM.

**One ROM at a time.** You see the core, the name and the boxart before anything
reaches your library — the matching is fuzzy enough that a wrong cover is easy to
produce and tedious to undo across a whole shelf. Bulk import is not implemented;
see [TODO](#todo).

## Requirements

Nothing, in practice. RetroArch and cores can both be installed from the plugin.
If RetroArch is already present it is detected automatically — the Flathub build
(user or system install), a native package, or an AppImage in `~/Applications`.

[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) has to be there
first, since this is a plugin for it.

## Installing

Decky's own settings take a URL, so no Desktop Mode is needed:

1. Open the **Decky** menu in the Quick Access panel and go to its settings.
2. Find **Install from URL** and give it:

   ```
   https://get.deckyemu.workers.dev
   ```

   That redirects to the latest release, and is kept short because this is typed
   on an on-screen keyboard. If you would rather paste an address you can verify
   — reasonable, for a URL that installs software — it is
   `https://github.com/elpendor/deckyemu/releases/latest/download/deckyemu.zip`.
   You can also skip typing entirely: open the releases page in Steam's own
   browser, copy the asset link, and use the keyboard's paste key.
3. Confirm Decky's prompt. DeckyEmu appears in the Quick Access panel.

### Manual install

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

## Sending files from another device

Getting a ROM onto a Deck otherwise means Desktop Mode or a shell. **Send files
from another device** in the Quick Access panel starts a small HTTP server on the
local network and offers two ways in, because the devices differ:

- **A QR code**, for anything with a camera. It carries the full token URL, so
  scanning goes straight to the upload page.
- **A short address and a six-digit code**, for anything with a keyboard. A
  desktop cannot scan, and will not have a 22-character token typed into it.

Files land in `~/deckyemu/transfer` by default — an inbox of its own, since
uploads arrive unsorted and of unknown system. Each received file gets an **Add**
button that drops straight into the add flow with the name and artwork already
resolved. Adding a game moves its ROM out of the inbox and into
`roms/<system>/`, which is the first moment anything knows what the file was, so
the inbox empties itself as you use it. See
[Where a ROM ends up](#where-a-rom-ends-up).

One kind of file is not a ROM: a `.deckyemu.json` **emulator definition** gets an
**Import** button instead. That is how an emulator this plugin does not ship gets
set up — see [Emulators this plugin does not ship](#emulators-this-plugin-does-not-ship).

Arriving files show a progress bar of bytes received against the declared total,
and each can be **cancelled**, which deletes the partial rather than leaving it
behind. That status also appears in the Quick Access panel, so dismissing the
dialog does not hide a transfer that is still running.

### Keeping the same address

By default the port, token and code all rotate per session, so nothing outlives a
transfer and a saved link is worthless. **Remember trusted devices** reuses the
port and token instead, so a device that bookmarked the link lands on the upload
page with nothing to type.

It is off by default because it changes what the link *is*: a bookmark becomes a
standing credential that works whenever the server runs. That is the right trade
for your own laptop and the wrong one for a house guest. **Reset link** is
therefore all or nothing — the link is the credential — and is refused while a
transfer is running.

### Since this listens on the network

- **A random token is required in every path**, carried by the QR code. Without
  it every request is refused, so a port scan finds nothing usable.
- **The root path is the one exception**, serving the code form. Wrong codes are
  counted and none is accepted after eight, bounding anyone already on the
  network to roughly 1-in-125,000 over the server's 30-minute life. The code
  rotates every session even when the address is remembered.
- **Writes are confined to the chosen folder.** Path segments are decoded
  individually and reduced to a basename, so an encoded slash cannot climb out.
- **It stops** when you close the dialog, after 30 minutes idle, and when the
  plugin unloads. A transfer in progress survives a dismissed dialog and stops
  the server once idle.
- It is plain HTTP on a local network: fine for moving ROMs around a house, not
  something to expose beyond one.

## Where a ROM ends up

Whether a ROM is moved when you add it, and whether it is deleted when you remove
the game, both depend on one thing: where the file was when you picked it.

**A file in the `transfer/` inbox is moved** into `~/deckyemu/roms/<system>/`. The
system comes from the core or emulator you chose, which is the first point at
which anything can know it — `.iso` alone is GameCube, PS2, PSP or Xbox. The move
happens before the launcher is written, so nothing is ever left pointing at the
old path.

It moves the whole game or none of it. Companion files are found by name
(`Game.cue` beside `Game.bin`) and by reading playlists, since a `.cue`, `.m3u` or
`.gdi` names files that do not share its name. If a disc a playlist expects is
missing, nothing is moved — an untidy inbox beats a game that will not start.

Send the same ROM twice and the second copy is recognised as identical and
discarded, with the game pointed at the one already filed. A *different* dump of
the same name is never overwritten; it stays in the inbox and the row says so.

**A file anywhere else is left exactly where it is.** An SD card, your home
folder, a library some other tool laid out, even a subfolder inside `transfer/` —
the launcher points at it in place and nothing is moved.

That determines what removing a game can delete:

| Where the ROM is | Moved when added | Deleted when the game is removed |
| --- | --- | --- |
| `transfer/` | Yes, into `roms/<system>/` | Yes |
| `roms/<system>/` | Already filed | Yes |
| `roms/` itself | No | No |
| SD card, home, anywhere else | No | No |

Only ROMs sitting one level under `~/deckyemu/roms` count as the plugin's, which
is exactly the set it put there. Anything else is reported as not its to delete
rather than quietly skipped. See also
[Removing everything](#removing-everything).

## Installing RetroArch and cores

Neither has to be set up beforehand.

**RetroArch** installs from Flathub in user scope (`flatpak install --user`), so
it needs no password, with progress streamed to a bar rather than one long
blocking call.

**Cores** come from the libretro buildbot, the same source RetroArch's own Core
Downloader uses. The catalog describes every core that exists rather than only
the installed ones, which enables the useful case: **pick a ROM that nothing
installed can run and the plugin offers the cores that could, then continues
straight into adding the game.**

Roughly a third of what the buildbot publishes is not a game system — media
players, image viewers, tech demos. A core is only offered if it declares both a
`database` and `supported_extensions` and is not in an excluded category.

**Uninstalling** is offered only when the plugin can honestly do it: a user-scope
flatpak, removed with `flatpak uninstall --user`. A system-wide flatpak (what
EmuDeck and Discover install) is root-owned, a native package would mean
unlocking SteamOS's read-only filesystem, and an AppImage is a file the plugin
never installed — each shows the reason rather than a disabled button with no
explanation. Configuration and saves are kept unless a separate toggle asks
otherwise, and games already added work again the moment RetroArch is reinstalled.

## Installing an emulator

The **Emulators** tab lists emulators for the systems RetroArch does not cover.
Press install and the emulator is downloaded and set up: the system, the file
types it accepts and its launch arguments are all filled in for you.

| Emulator | System |
| --- | --- |
| Dolphin | GameCube, Wii |
| PCSX2 | PlayStation 2 |
| RPCS3 | PlayStation 3 |
| shadPS4 | PlayStation 4 |
| DuckStation | PlayStation 1 |
| PPSSPP | PSP |
| Vita3K | PS Vita |
| Ryujinx | Switch |
| Cemu | Wii U |
| Azahar | 3DS |
| xemu | Xbox |

Most come from Flathub and install for your user, so no password is asked for.
Azahar and Vita3K publish no Flatpak and are downloaded from their own releases
into `~/deckyemu/emulators`.

Several emulators are not playable as they ship — a keyboard is bound instead of
a controller, or they start in a window — so installing one also writes a
controller configuration and turns fullscreen on. Those values are not guesses;
where they came from is under [Thanks](#thanks).

**Installing the emulator is not always enough to play.** Some systems need BIOS
files, keys or firmware that are yours to dump and that this plugin will never
download — PCSX2 and xemu will not boot without them. The install prompt says
which ones before it starts.

A **BIOS and firmware** section appears under the emulator list once you have
installed something that needs files. Send them from another device and they are
recognised by name and put where the emulator reads them — press **Install** and
that is the whole step. Anything already in place is never overwritten: a dump
you put there by hand is left alone, and only a placeholder the emulator wrote
for you to fill in is replaced.

Installing **moves** the file rather than copying it, so `~/deckyemu/firmware`
does not accumulate a second copy of every BIOS you have ever sent — a PS3
firmware update is a couple of hundred megabytes. Removing a requirement moves
the file back there, so installing it again needs no second trip to a PC. The
one thing to know is that after installing, the transfer folder is empty: your
only copy is the one the emulator is now using.

A few cannot be installed for you, because the emulator unpacks them itself:
RPCS3's `PS3UPDAT.PUP`, a Switch firmware archive, and xemu's BIOS files. Those
are still detected, and the row tells you the one step left.

A few emulators are marked as having unconfirmed launch arguments. They install
the same way, but if a game opens the emulator without loading the game, edit the
arguments under **All registered emulators** below.

Removing an emulator here leaves your saves and configuration alone, and games
already added to Steam start working again the moment you reinstall it.

### Emulators this plugin does not ship

The list above is fixed, and nothing outside it is linked to or named as a
download here. Anything else can still be set up for you by importing a small
JSON file that describes it: send the `.deckyemu.json` over **Transfer** and
press **Import**. It then behaves like any other entry — right system, right
file extensions, working launch arguments, firmware rows that say what is
missing.

A definition says how the emulator is obtained. It can name a Flathub
application or a release to download, or say that you will supply the binary
yourself and point at it.

**Which means you are trusting whoever wrote it.** Before storing anything, the
panel shows what the definition will install and every directory it may write
to, and asks you to confirm. A definition cannot delete anything, download
firmware, run a second binary, write outside the directories it declares, or
replace a built-in emulator — but those bound what it can reach, not whether its
author meant well. Read the file first; it is a few lines of plain text.

See [docs/emulator-definitions.md](docs/emulator-definitions.md) for the format,
a worked example, and what to check when one does not work.

## Updating an emulator, or going back

Anything installed from Flathub — most of the list above, and RetroArch itself —
can be moved between published builds without leaving the panel.

For an emulator, the branch button on its row under **Emulators**. For RetroArch,
**RetroArch version** on its own tab. Both open the same dialog: which build is
installed, an **Update** when a newer one is published, and every other build
Flathub carries, listed by date. Each row opens to show the whole of its
description, the version, and **how much it would download** — switching build
re-fetches the entire application, which for RetroArch is around 400MB.

Nothing updates on its own. An emulator moves when you ask it to.

**Choosing a build also holds it there**, and that is the part worth
understanding. Holding stops *anything* moving it, not only this plugin — any
`flatpak update` on the device does, including whatever you press when you update
your Deck from Desktop Mode. Without a hold the sequence is: a build breaks a
game, you go back to one that works, you update your Deck a fortnight later, and
the game breaks again with nothing connecting the two. The hold is what prevents
that. It shows on the row as *held*, and is released from the same dialog
whenever you want updates again.

A held emulator receives no updates at all until you release it, security fixes
included. That is the trade, and it is why the state is stated on the row rather
than hidden in a dialog.

Not offered for:

| | Why |
| --- | --- |
| RPCS3, Azahar, Vita3K | Downloaded from the projects' own releases rather than Flathub, which publishes no build history to choose from |
| A system-wide Flatpak | Root-owned, and the plugin has no way to answer a password prompt |
| RetroArch from a package or an AppImage | Neither was installed from here and neither has builds to move between |

The note on each build describes its *packaging* — "Restrict nvidia-cg-toolkit to
x86_64" — not the emulator's own release notes, which live on the project's site.

## Adding your own emulator

The Emulators tab has two lists. **Ready-made emulators** is the catalog: what
the plugin knows how to install and set up. **All registered emulators** below it
is everything wired up for adding games — whichever list it came from, since
installing from the catalog registers it too — and it is where each one's
system, file types and launch arguments are edited.

For anything the catalog does not cover, a standalone emulator can be
registered by hand with **Add an emulator**. Either a Flatpak application id or
an executable/AppImage path, plus the file extensions it handles and an argument
template where `{rom}` is substituted.

**The System field is the one that matters for artwork.** Boxart lookup and the
SteamGridDB release-era check both key on the libretro system name, so declaring
it makes a custom emulator behave exactly like a core: same name cleanup, same
boxart, same collection grouping. Registering Dolphin against
`Nintendo - GameCube` turns `Metroid Prime (USA).rvz` into *Metroid Prime* with
real cover art.

Leaving the system unset still launches games, but artwork then depends entirely
on SteamGridDB matching by title, with no era sanity check.

With at least one emulator registered the plugin is fully usable **without
RetroArch installed at all**.

## Editing a game

The pencil on each row in **Added games** opens an editor for a game already in
Steam, so its playtime and its place in a collection survive.

- **Name** — renaming moves the launcher, since its filename embeds the title.
- **ROM file** — repoint an entry at a moved file, an SD card or a better dump.
  The launcher filename also embeds a hash of the ROM path, so this relocates the
  script too. A ROM the chosen core cannot read is refused.
- **Core or emulator** — changing it changes the system, so the platform label
  and the per-platform collection follow.
- **Artwork** — the picker applies immediately, with no need to save.
  **Re-fetch name and artwork** is worth running after a core change, since the
  core decides the system and the system decides which thumbnail directory is
  searched.
- **Launch options** — override the global fullscreen or notification setting for
  one game, and append extra arguments. They are appended rather than inserted,
  because several argument templates end in the ROM path. An override left on
  *follow the global setting* still picks up later changes to it.
- **Save and test launch** — starts the game through Steam, so gamescope, Steam
  Input and the overlay behave as they do in normal play. It saves first, since
  the launcher on disk is what Steam runs.

## Collections

Added games are filed under a Steam collection so they are findable in Big
Picture. The collection is called `DeckyEmu` unless you rename it.

**One collection per system** is on by default: each system gets its own shelf,
named by a selectable format. Turn it off and every system shares the one
collection.

| Format | Result |
| --- | --- |
| `[{name}] {platform}` (default) | `[DeckyEmu] SNES` |
| `{platform}` | `SNES` |
| `{name}: {platform}` | `DeckyEmu: SNES` |
| `{name} · {platform}` | `DeckyEmu · SNES` |
| `{name} - {platform}` | `DeckyEmu - SNES` |
| `{platform} ({name})` | `SNES (DeckyEmu)` |
| `{name}\n{platform}` | two lines — but Steam renders collection titles on one line, so expect a space |

An install that already has games keeps whichever layout those games were filed
under, so an upgrade never moves them. Only a new install takes the default.

**Platform names** are short by default: `SNES` rather than `Super Nintendo
Entertainment System`, which is 46 characters of shelf header. Unlisted systems
fall back to dropping the manufacturer prefix (`Acme - Wonder Machine` →
`Wonder Machine`).

Renaming the collection, or toggling per-platform naming, **moves games that were
already added** rather than only affecting the next one. An old collection is
deleted only once it is empty, never while it still holds games dragged in by
hand.

## Artwork sources

**libretro thumbnails** need no setup and no API key. They are scans of the
physical box, so their shape varies by console while Steam's capsule is 600x900
portrait. A scan far off that shape is redrawn to fit rather than stretched —
whole, centred, at its true proportions, on a blurred copy of itself. Art already
made for the slot is passed through untouched, whichever source it came from.

**SteamGridDB** (optional) gives purpose-made Steam art — capsule, wide header,
hero and logo.

The setting defaults to **Auto**, which tries SteamGridDB first and falls back to
libretro. Until a key is saved that amounts to libretro every time, so the
default costs nothing and starts using the better source the moment there is one.

SteamGridDB's search is fuzzy and confidently wrong — *Super Mario Brothers*
returns **Super Mario Galaxy 2** ahead of the NES game — so candidates are scored
on title and release era, and a weak winner is discarded in favour of libretro's
thumbnail. Below the threshold nothing is returned at all, since no artwork beats
the wrong artwork. The chosen title is shown next to the preview, so a bad match
is visible rather than silent.

Typing a long API key on a touchscreen is unpleasant, so getting one in is three
steps, none of them needing the keyboard:

1. **Sign in to SteamGridDB.** Use the plugin's own sign-in button rather than
   SteamGridDB's *Login via Steam*, which Steam's in-app browser ignores. It ends
   on a blank page; that is the sign-in finishing, not an error.
2. **Open the API key page.** Hold on the key until Steam's context menu appears
   and choose Copy.
3. **Paste key and save.** Nothing else to press.

Two shortcuts sit beside those steps. **Import key from another plugin** appears
when a key is already stored under `~/homebrew/settings`, with strict field-name
matching so the wrong value is never imported silently. **Or type the key** is a
plain field, saved on blur.

The key is validated against SteamGridDB before being saved, so a truncated paste
is caught immediately, and it is never sent back to the UI afterwards.

## Fullscreen and RetroArch's on-screen chatter

**Launch custom emulators fullscreen** applies each emulator's own fullscreen
switch. There is no flag common to all of them — Dolphin has none at all, PCSX2
uses `-fullscreen`, RPCS3 `--fullscreen` — so it is stored per emulator and suggested for
recognised ones. It stays an editable field because several emulators ignore
unknown arguments silently, which would make a wrong guess invisible.

RetroArch announces itself when content loads — a load animation, then notices
about controller autoconfig, refresh rate and config overrides. **RetroArch
notifications** suppresses that for games launched from this plugin:

| Mode | Effect |
| --- | --- |
| `Hide the startup banner` (default) | Disables the load animation and the notices that follow it |
| `Hide all on-screen messages` | Also sets `video_font_enable = false`, silencing save-state confirmations and errors too |
| `Keep RetroArch's notifications` | RetroArch behaves exactly as it does on its own |

These are passed per-launch rather than written into your own `retroarch.cfg`,
and the override turns RetroArch's save-on-exit off so they cannot settle into it
as permanent defaults. The trade-off is that changes made from RetroArch's own
menu during a game launched from here are not saved either; *Save Current
Configuration* still works if you want them kept.

Because launch behaviour is baked into each game's launcher script, changing this
rewrites the launchers of games already added.

## Getting into RetroArch's menu

**RetroArch menu shortcut** binds a controller combination that opens RetroArch's
menu mid-game, defaulting to **Select + Start**.

It is on by default because otherwise there is usually no way in. RetroArch sets
no combo of its own, and the Guide button its autoconfig binds never reaches it on
a Deck — Steam claims that button first. That leaves `F1` on a keyboard.

> **This applies to games run on a libretro core only.** A game launched through
> a custom emulator is unaffected: PCSX2, Dolphin and the rest each have
> their own menu binding, and nothing here can set it.

RetroArch takes a fixed list rather than a free-form binding, so the choices are
exactly what it supports:

| Setting | |
| --- | --- |
| `Select + Start` (default) | `L1 + R1 + Select + Start`, `L3 + R3`, `L1 + R1`, `L2 + R2`, `L3 + R` |
| `D-pad Down + Select` | `D-pad Down + Y + L1 + R1`, `Hold Start`, `Hold Select` |
| `Off` | Writes nothing, so whatever is in your `retroarch.cfg` applies |

Pick one your games do not use themselves. `Hold Start` and `Hold Select` fire on
a single button and are the most likely to interfere; the four-button combos are
safest.

Like the notification setting, this goes into the `--appendconfig` file and
changing it rewrites the launchers of games already added.

## RetroAchievements

RetroArch has achievement support built in; this turns it on for games launched
from here and signs you in.

Signing in asks for your retroachievements.org password **once**, and only the
Connect token it returns is stored; their API offers no way around that one
login. If RetroArch already has a login stored it is offered as a one-tap adopt
instead, with nothing to type.

**Hardcore mode is off by default, a deliberate disagreement with RetroArch**,
which defaults it on. Hardcore disables save states, rewind, slowdown and cheats
— most of how a handheld gets played, and switching achievements on is not a
request to lose it. Turn it on if you want unlocks to count on the hardcore
leaderboard.

**Not every core can take part.** Achievements work by watching emulated memory,
so a core publishing no memory map has nothing to read. Cores declare this in
their `.info` file, so the tab lists yours as supported, unsupported, or not
declared — the last meaning the core says neither, which older cores often do.

The token is treated like the SteamGridDB key: stored in the plugin's settings,
never sent to the frontend, and the launch override file carrying it is `0600`.

## Orphaned entries

**Check for orphaned entries** on the Library tab reports everything that has
drifted out of sync — a ROM or launcher that has gone, a record whose Steam
shortcut was deleted, launcher scripts nothing references, and games left behind
by a previous install under a different plugin name.

It also reports the other direction: shortcuts **Steam** has that the plugin's
records do not account for, read from Steam's own `shortcuts.vdf`. They are split
by what can be done about each:

| | |
| --- | --- |
| **Cannot start** | The launcher script is gone, so the entry does nothing when launched. Removing it is all there is to do |
| **Duplicate** | A tracked game already runs this same launcher, so it appears twice in Steam. Removing it keeps the tracked copy |
| **Untracked** | It still plays, but the plugin has no record of it, so editing and removing from the plugin will not work |

Ownership is decided by the executable being one of the plugin's launcher
scripts, never by the name — two shortcuts called *Super Mario 3D World* could be
one of these and one a real Steam game.

When any are found, the Quick Access panel says so and offers the way through,
since none of this is visible by looking at your library: an entry whose launcher
was deleted looks like an ordinary game that happens to do nothing.

Forgetting a record also takes the game out of the collection it was filed into,
deleting that collection once it is empty.

Collections are checked here too, in all three directions — games **missing**
from the shelf they belong to, games still on one they have **left**, and shelves
left **empty**. None of the three is answerable from the plugin's own records: a
game recorded as filed can simply not be there, because the collection was
deleted in Steam or because filing it failed as it was added. Each is reported
before anything is done about it, and the list is rebuilt after every fix.

A previous install can be **discarded** as well as adopted. Games with no
surviving shortcut are not offered for adoption at all, and discarding deletes
only the old record — the launcher scripts stay, because they are why any
still-working shortcut works.

## Removing everything

**Remove all DeckyEmu games from Steam**, at the bottom of the Library tab,
undoes everything the plugin has added: every shortcut, every launcher script,
and any collection it created that ends up empty. It also deletes **the games it
put on this Deck** — ROMs filed under a system, and games unpacked into an
emulator — for the same reason removing a single game does. A ROM you keep
somewhere of your own was never the plugin's to move and is left alone.

A collection is deleted only once it is empty, so one holding games dragged in by
hand survives. Shelves left empty by anything else — a shortcut deleted in Steam,
an earlier reset — are swept at the end.

It can take a while, so it reports what it is deleting as it goes.

## Reporting a problem

**Updates → Report a problem** gathers what a bug report needs and puts it where
you can read it: scan the QR code with a phone, or type the short address and the
six digits on anything with a keyboard. Copy the text, paste it into the issue.

It carries the plugin version and build, what RetroArch is and how it was
installed, which emulators are registered, how many games are in the library and
under which systems, your settings, and the last 200 lines of the log.

Your SteamGridDB key, your RetroAchievements token, the transfer token, your
RetroAchievements username and the names and paths of your games are struck out
of it. By value, across the whole text rather than only the section they belong
to — the log names games as it works, so removing the library listing alone
would not have been enough. Settings are read through a list of what may be
reported rather than a list of what may not, so a setting added later is absent
until somebody lists it.

Two things it cannot catch, since neither is a value it knows: a game you probed
but never added, and a title too short to strike without mangling the rest of
the report. Read it before you paste it — it is shown to you first for that
reason.

The report lives in memory and goes when the transfer server stops — half an
hour idle, or **Done, and stop sharing now**.

## Updates and what changed

The **Updates** tab shows which build is running, checks GitHub for a newer one,
and installs it. It also shows **what's new** for both the release being offered
and the build already installed.

The notes are generated from commit subjects, grouped under New, Fixed, Faster
and Under the hood. They ship inside the build as well as on the release, so the
tab shows the running version's changelog with no network at all.

Installing goes through decky's own loader, which has permissions this plugin
does not. The download is checked against the digest published with the release.

## TODO

- **Batch importing a folder of ROMs.** Needs an answer to what the
  one-at-a-time flow asks per game: no matching core, several possible cores,
  wrong artwork. Getting those wrong in bulk is what makes it tedious to undo.

---

## Thanks

Parts of this were settled by reading other people's work instead of guessing,
and each of these saved a round of it.

- **[EmuDeck](https://github.com/EmuDeck)** and
  **[RetroDECK](https://github.com/RetroDECK/RetroDECK)** publish controller
  configurations tested on this hardware. Where one existed for an emulator in the
  list above, that is what the values written on install were taken from, rather
  than a reading of a button table — and a button table would have got several of
  them wrong, because face buttons have to be matched by position and not by
  letter. Both projects also cover far more systems than this one does.
- **[TabMaster](https://github.com/Tormak9970/TabMaster)** for the Quick Access
  header. It has a title class of its own, separate from the generic one, and
  matching it is what stopped this plugin's name sitting off-centre against
  decky's back arrow.
- **[unifideck](https://github.com/mubaraknumann/unifideck)** for the reason the
  update button works in Game Mode. Installing an update goes through decky's
  global websocket, but the Quick Access panel is a popup window there, so the
  global sits on its opener rather than on `window`. Reading their source is why
  that worked here the first time it was tried: it behaves either way in Desktop
  Mode, so a missing fallback shows up only in Game Mode, on a Deck, at the one
  moment a user is trying to update.

Built from the
[Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template);
see its README and the [wiki](https://wiki.deckbrew.xyz/en/user-guide/home#plugin-development)
for CI, backend binaries and plugin submission.
