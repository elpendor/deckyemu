# Standalone emulators

The one-press catalog, moving between published builds, and registering an
emulator yourself.

Back to [the README](../README.md).

**Contents** — [Installing an emulator](#installing-an-emulator) ·
[Updating an emulator, or going back](#updating-an-emulator-or-going-back) ·
[Adding your own emulator](#adding-your-own-emulator)

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
RPCS3, Azahar and Vita3K publish no Flatpak and are downloaded from their own
releases into `~/deckyemu/emulators`. Each row says which it is, in brackets
after the name, because the two behave differently when something goes wrong and
only one of them has builds you can move between.

Several emulators are not playable as they ship — a keyboard is bound instead of
a controller, or they start in a window — so installing one also writes a
controller configuration and turns fullscreen on. Those values are not guesses;
where they came from is under [Thanks](../README.md#thanks).

The same pass turns off whatever an emulator draws over the game. On a desktop a
menu bar that slides in, a notification in the corner or a mouse pointer are
harmless; on a handheld the game is the only thing on screen and there is no
pointer to dismiss any of it with. xemu is the clearest case — its menu bar, its
notifications and its cursor are all switched off on install.

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
JSON file that describes it: send the `.deckyemu.json` over **Transfer**, or
press **Import a definition** at the bottom of this tab to reach one already on
the Deck, and
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

See [emulator-definitions.md](emulator-definitions.md) for the format,
a worked example, and what to check when one does not work.

## Removing an emulator

**Remove** on its row uninstalls it and forgets its registration. Games you have
already added keep their shortcuts and launcher scripts and start working again
the moment the emulator is reinstalled, so removing one is not a decision about
your library.

For a Flathub emulator the dialog offers **Also delete its saves and
configuration**, off by default. Left off, everything the emulator owns stays
where it is — `flatpak uninstall` does not touch `~/.var/app/<id>` — so
reinstalling picks up exactly where you left off, memory cards and all. Turned
on, nothing is left behind, which is what a genuinely fresh install needs: an
emulator that keeps its old configuration is one that comes back with whatever
state it was in, including a setup wizard you have already answered once.

The switch is not offered for an emulator installed from a GitHub release or one
of your own, because their data lives in ordinary folders this does not remove.

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
