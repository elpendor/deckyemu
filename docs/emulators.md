# Standalone emulators

The one-press catalog, moving between published builds, and registering an
emulator yourself.

Back to [the README](../README.md).

**Contents** — [Installing an emulator](#installing-an-emulator) ·
[Unpacking a PS4 package](#unpacking-a-ps4-package) ·
[Updating an emulator, or going back](#updating-an-emulator-or-going-back) ·
[Adding your own emulator](#adding-your-own-emulator)

## Installing an emulator

The **Emulators** tab lists emulators for the systems RetroArch does not cover.
Press install and the emulator is downloaded and set up: the system, the file
types it accepts and its launch arguments are all filled in for you.

| Emulator | System | Installed from |
| --- | --- | --- |
| Dolphin | GameCube, Wii | Flathub — [`org.DolphinEmu.dolphin-emu`](https://flathub.org/apps/org.DolphinEmu.dolphin-emu) |
| PCSX2 | PlayStation 2 | Flathub — [`net.pcsx2.PCSX2`](https://flathub.org/apps/net.pcsx2.PCSX2) |
| RPCS3 | PlayStation 3 | GitHub — [`RPCS3/rpcs3-binaries-linux`](https://github.com/RPCS3/rpcs3-binaries-linux) |
| shadPS4 | PlayStation 4 | Flathub — [`net.shadps4.shadPS4`](https://flathub.org/apps/net.shadps4.shadPS4) |
| DuckStation | PlayStation 1 | Flathub — [`org.duckstation.DuckStation`](https://flathub.org/apps/org.duckstation.DuckStation) |
| PPSSPP | PSP | Flathub — [`org.ppsspp.PPSSPP`](https://flathub.org/apps/org.ppsspp.PPSSPP) |
| Vita3K | PS Vita | GitHub — [`elpendor/Vita3K`](https://github.com/elpendor/Vita3K), upstream plus a motion fix ([why](#motion-controls-in-vita-games)) |
| Ryujinx | Switch | Flathub — [`io.github.ryubing.Ryujinx`](https://flathub.org/apps/io.github.ryubing.Ryujinx) |
| Cemu | Wii U | Flathub — [`info.cemu.Cemu`](https://flathub.org/apps/info.cemu.Cemu) |
| Azahar | 3DS | GitHub — [`azahar-emu/azahar`](https://github.com/azahar-emu/azahar) |
| xemu | Xbox | Flathub — [`app.xemu.xemu`](https://flathub.org/apps/app.xemu.xemu) |
| Xenia Canary | Xbox 360 | GitHub — [`xenia-canary/xenia-canary`](https://github.com/xenia-canary/xenia-canary) |
| Supermodel | Sega Model 3 arcade | Flathub — [`com.supermodel3.Supermodel`](https://flathub.org/apps/com.supermodel3.Supermodel) |

Nothing here is a mirror or a repack: the application id or the repository above
is where the build comes from, and following one takes you to the publisher's
own page. That is the whole of what this plugin adds — it downloads what those
projects publish and fills in the system, the file types and the launch
arguments.

Most come from Flathub and install for your user, so no password is asked for.
RPCS3, Azahar, Vita3K and Xenia Canary publish no Flatpak and are downloaded
from their own releases into `~/deckyemu/emulators`. The panel says which is
which in brackets after the name, because the two behave differently when
something goes wrong and only one of them has builds you can move between.

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

## Unpacking a PS4 package

A PlayStation 4 game arrives as a `.pkg`, and shadPS4 cannot unpack one — the
code that used to do it was taken out of the emulator and published separately.
So the first time you add a `.pkg`, the plugin downloads a small command-line
tool to do it: the **PS4 package extractor** from
[shadPS4Plus](https://github.com/AzaharPlus/shadPS4Plus), GPL-2.0, taken from
that project's own release page.

It is fetched then rather than with the emulator, because most people never add
a `.pkg` at all. It lands in `~/deckyemu/tools/`, kept apart from
`~/deckyemu/emulators/` on purpose — it plays nothing, it turns a `.pkg` into a
folder shadPS4 can run — and it is not listed as an emulator anywhere. A plugin
reinstall does not delete it.

It is descended from shadPS4's own extractor, which is why it was chosen over
anything else that reads the format: what comes out is what shadPS4 expects,
rather than another project's reading of the same file.

The other two consoles need nothing extra. RPCS3 unpacks its own packages, and
Vita3K installs from a `.pkg` directly once it has the licence key.

## Motion controls in Vita games

The Vita had a gyroscope and games like Gravity Rush expect it, and the Deck has
one too. This plugin hands Vita3K the Deck's own controller so it can see that
gyro, and it works.

**Why the Vita3K it installs is not the stock one.** Motion is broken in current
upstream builds: the emulator's bundled SDL reports the Deck's sensor timings in
microseconds where nanoseconds are expected, so Vita3K's motion maths comes out a
thousand times too small and games read a gyro that never turns. SDL fixed its
side and the fix has not reached the release Vita3K bundles. So this plugin
installs a build that is upstream plus the one commit that corrects it, published
at [elpendor/Vita3K](https://github.com/elpendor/Vita3K/releases) and built by
GitHub Actions from public source. It is a fixed version rather than a channel,
so Vita3K stops following upstream's rolling builds until the fix lands there.

That commit is offered upstream as
[Vita3K#4100](https://github.com/Vita3K/Vita3K/pull/4100). **When it is merged
this plugin goes back to installing Vita3K's own builds** and the fork stops
being used — the fork exists to keep motion working in the meantime, not to
become a fixture.

**The setting, which is normally made for you.** Steam powers the Deck's gyro
down unless the running game's controller layout uses it, so a Vita game on an
ordinary layout reads a sensor that never moves. Adding a Vita game therefore
puts it on **Gamepad with Gyro (DeckyEmu)**, which is there to switch the sensor
on — what that layout does with the gyro never reaches the game, because the
emulator reads the Deck's controller directly.

That layout is Valve's own "Gamepad with Gyro" with one thing changed: the gyro
goes to the right stick instead of the mouse. Steam's version drags a mouse
pointer around, and Vita3K treats the pointer as the Vita's touchscreen, so it
would be both visible and in the way. It is written on your Deck from the copy
Steam installed rather than shipped with the plugin, so a Steam update that
retunes the layout is inherited rather than frozen.

**If you have chosen a layout for that game yourself, yours is kept**, and then
the gyro is yours to bind: **Controller Settings → Edit Layout → Gyro →
Behavior**, anything other than **None**. Same if motion stops working after you
change layouts — check that first, before suspecting the game.

**One trap if you do it by hand.** Some behaviours are only active while you hold
or touch something — *Gyro To Mouse* defaults to activating on right-stick touch
— and the Deck's sensor is only powered while that activation is on, so motion in
the game works only while your thumb is on the stick and looks broken the rest of
the time. Either pick a behaviour that is always on, such as **Gyro To Joystick
Camera**, or set that binding's activation to always. The layout this plugin
applies has no such gate.

Games added before this was in place are given the layout too, on the next
restart — there is nothing to re-add and nothing to switch on.

**Unless you had already picked a layout for that game.** A layout you chose is
never replaced, so a Vita game you had set up yourself keeps what it has, and if
what it has does not use the gyro then motion in that game will not work. The fix
is one selection: open the game's **Controller Settings** and pick
**Gamepad with Gyro (DeckyEmu)** from the layout list. Steam files layouts under
the game's *name*, so this also applies to a game you once configured, removed,
and added again.

**What changes for the buttons.** To reach the sensor, Vita3K reads the Deck's
controller directly rather than through Steam Input, and that applies to every
Vita game. A custom Steam layout stops shaping them: remapped buttons, stick
curves and the **back buttons** do nothing. The **STEAM button** still opens the
Steam menu and nothing else — the emulator is told the Deck has no such button,
because Vita3K treats it as the Vita's PS button and pauses the game with it,
which left the emulator paused after the menu closed. The sticks,
triggers and face buttons work as they always did, and the right trackpad still
drives the Vita's touchscreen. If you would rather have your layout back than
have motion, there is nothing to switch off — tell us, and it can become a
choice.

## Xbox 360 files

Xenia works out what a file is by reading it, not by its name, so the extension
matters less than it does elsewhere. It runs:

- `.iso` — a game disc image
- `.xex` — an extracted executable
- `.zar` — Xenia's own compressed disc image, which it can also create
- Xbox Live Arcade titles, DLC and title updates, which are **content packages
  with no extension at all** — the filename is a long string of hex

That last one used to have nowhere to go: everything here matches a game to an
emulator by its extension, and these files have none. The plugin now reads the
first few bytes instead, so an XBLA container can be added like any other game
even though its name says nothing.

**Unzip first.** Xenia refuses `.zip`, `.7z`, `.rar`, `.tar` and `.gz` outright,
and XBLA titles are almost always distributed zipped. Send the zip to the Deck,
start adding it, and press **Unpack this zip** in the panel: inside is a folder
like `58410954/000D0000/` holding one long-named file, and that file — the game —
comes out named after the zip, ready to add. See
[Unpacking a zip](transfers.md#unpacking-a-zip).

## Arcade ROM sets

Supermodel runs the Sega Model 3 board, and an arcade game for it is not one
file — it is a set of forty-odd chip dumps, kept together in a `.zip` named
after the game (`scud.zip`, `daytona2.zip`). Supermodel opens the zip and reads
the dumps out of it by name, exactly as MAME does.

**Leave it zipped.** This is the one archive on the Deck that is not a wrapper
around a game: unpacking it produces a folder of files nothing can load, and
takes away the one file that could be played. The panel knows the difference and
does not offer **Unpack this zip** for a ROM set.

It also stops guessing. A ROM set used to be matched on whatever the first chip
dump inside was called, which meant `scud.zip` looked like a PlayStation image
and was offered PlayStation cores. It is now matched on `.zip` itself, which is
what Supermodel, MAME and FinalBurn Neo all declare — and since plenty of other
cores claim `.zip` only because they unpack archives, the ones that read a ROM
set *as* the cartridge are sorted to the front and preselected. The rest are
still in the list if you want them.

Names come from Supermodel's own game list, so `daytona2.zip` is added as
*Daytona USA 2: Battle on the Edge* rather than as `daytona2` — which also gives
the artwork search something it can find.

**Test and Service are the stick buttons.** Push the **left stick straight down
until it clicks** — the button usually called L3 — and that is Test. The right
stick clicked in (R3) is Service. This is pressing the sticks *in*, not moving
them; nothing happens if you tilt them.

Those two are the buttons inside a real cabinet's coin door, and on this board
they are not an operator's convenience: they are the only way into a game's own
settings, and some games do not start without going there.

Daytona USA 2 is one. It arrives configured as a linked cabinet and stops at
*CANCELLED / NETWORK BOARD NOT PRESENT*. To fix it:

1. Press the **left stick in** (Test). The test menu opens.
2. Go to **Game System** — the **right stick in** (Service) moves through the
   menu.
3. Change **Link ID** from Master to **Single**.
4. Exit the menu.

**Once per game, and then never again.** The setting goes into the game's
emulated NVRAM — `daytona2.nv` and friends, under the emulator's own data —
which is written when Supermodel exits and read at every start. There is no
launch argument or shortcut setting that can do it instead: Link ID is a
setting on the arcade board, not an emulator option, and Supermodel models it
as one. The only way to lose it is to clear the emulator's data from **Reset**,
which deletes the NVRAM along with everything else; the menu steps are then the
way back.

Only 63 games were ever made for the board, and it is demanding hardware to
emulate; the racers are the heaviest of them.

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
