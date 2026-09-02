# Standalone emulators

The one-press catalog, moving between published builds, and registering an
emulator yourself.

Back to [the README](../README.md).

**Contents** — [Installing an emulator](#installing-an-emulator) ·
[Unpacking a PS4 package](#unpacking-a-ps4-package) ·
[Getting to the emulator's own menu](#getting-to-the-emulators-own-menu) ·
[Fixes](#fixes) · [Motion controls](#motion-controls) ·
[Xbox 360 files](#xbox-360-files) · [Arcade ROM sets](#arcade-rom-sets) ·
[Removing an emulator](#removing-an-emulator) ·
[Updating an emulator, or going back](#updating-an-emulator-or-going-back) ·
[Adding your own emulator](#adding-your-own-emulator)

## Installing an emulator

![The Emulators tab, listing ready-made emulators with the system and file types
each one handles.](images/installing-an-emulator.jpg)

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
| Vita3K | PS Vita | GitHub — [`Vita3K/Vita3K-builds`](https://github.com/Vita3K/Vita3K-builds) |
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

## Getting to the emulator's own menu

**DuckStation and PCSX2.** Both ship every hotkey bound to a key, and both put
**Change Disc** in a menu a controller can drive once it is open. Dolphin, the
other emulator here with multi-disc games, has no menu worth reaching this way:
its *Change Disc* opens a file browser rather than listing a playlist's discs,
so it is set to change disc by itself instead.

**Select + Start**, the same combo RetroArch uses — see
[getting into RetroArch's menu](retroarch.md#getting-into-retroarchs-menu). It opens DuckStation's pause
menu, where save states, settings, quitting and **Change Disc** live.

It is written for you when DuckStation is set up. Every hotkey DuckStation ships
is bound to a key — `Escape` for the pause menu — and on a Deck in Game Mode
there is no keyboard to press, so without this its menu cannot be reached at
all.

**A multi-disc game usually changes disc by itself.** DuckStation is set to
switch to the next disc when the game stops the CD-ROM motor, which is what a
game does when it asks you to insert the next one. Upstream is clear that this
does not work for every game, so the combo above is the way through when it does
not fire. See
[multi-disc games](getting-started.md#multi-disc-games) for how a set becomes
one entry in the first place.

## Fixes

Some emulators have bugs this plugin can correct, and those corrections appear
as **Fixes** when you edit an emulator on the **Emulators** tab. Motion
controls, below, is the only one today.

**A fix is temporary, by definition.** Every one names the upstream bug report
that will make it unnecessary, and it exists to be deleted rather than kept.
This is not where an emulator is configured: settings that are simply how an
emulator has to run on a Deck are applied for you and never appear here.

**They all start switched off**, because each one costs something. The ❓ beside
a fix says what it fixes and what that costs, which is the whole basis for
deciding. **The switch always works**, both ways, whatever else is going on.

**Set per emulator, or per game.** The emulator's switch is the default for its
games; edit any game and the same fixes appear there, set to *Follow the
emulator* until you say otherwise.

**A fix tells you when it is not doing its job**, and only then:

- *"The emulator does this itself now. You can switch this off."* — said only
  once the build you have actually contains the fix, never merely because
  DeckyEmu was updated. If yours is older, nothing is said and the fix goes on
  working.
- *"This build of the emulator would not take it, so it is not running."* — for
  a fix applied to the emulator's own files, when a build has changed too much
  to accept one. Nothing is altered; the emulator runs exactly as downloaded.

You do not have to go looking for either. Both appear under the emulator on the
**Emulators** tab, and a game that starts with one shows a dialog as it
launches — once per emulator, never while a fix is on and working. The dialog
only tells you; the switch lives on the Emulators tab and nowhere else.

## Motion controls

Four consoles here had a motion sensor and games that expect it: the **PS
Vita**, where Gravity Rush is unplayable without one, the **PS4**, whose
DualShock has a gyroscope, the **Switch**, and the **Wii U**, whose GamePad had
one that Wind Waker HD, Splatoon and Star Fox Zero all lean on. The Deck has one
too, and it can drive all four — but the PS Vita and the PS4 pay for it, so
there it is **off until you ask for it**.

**On the Switch and the Wii U it is simply on, and costs nothing.** Ryujinx and
Cemu can both take motion over a small local connection instead of reading the
controller, so your Steam layout is untouched and the back buttons keep working.
Nothing to switch on and no per-game choice to make: the piece that provides it
is fetched with the emulator, runs only while a game is open, and stops when you
close it.

**A Tools section on the Emulators tab shows where it stands.** The piece that
provides motion is a small download, listed there by name with the project it
came from, whether it is installed, and how big it is. It can be removed and
downloaded again from that row. The emulator's own row says **motion ready**
too, so it is visible without scrolling.

If it says it is waiting to retry, that is GitHub limiting how often one address
may ask; it clears on its own.

**If you have set up the emulator's controller yourself**, your settings are
kept and never overwritten — which means the emulator is not pointed at the
motion server and gyro will not work. The row says so rather than claiming it is
ready. To use it, add a motion source to the emulator's own controller settings:
in Cemu, a second controller with the **DSUController** API at `127.0.0.1` port
`26760`; in Ryujinx, set the motion backend to **CemuHook** at the same address.

**Tools are a separate list from BIOS and firmware on purpose.** Everything
under BIOS and firmware is yours, and none of it is ever downloaded. Everything
under Tools is fetched from the project that publishes it, and each row says
which. Installing Ryujinx or Cemu tells you the motion server is coming before
it is downloaded.

If a Switch or Wii U game still ignores the Deck's tilt, check the game's own
settings before anything else. Several ship with motion turned off — *Pokémon
Legends: Arceus* has gyro aiming but sets **Motion Sensitivity** to zero, and it
is not mentioned anywhere in the game.

The rest of this section is about the PS Vita and the PS4, where it does cost
something.

**Turning it on.** Edit the emulator on the **Emulators** tab and switch on
**Motion controls** under *Fixes* — see [Fixes](#fixes) above for how those
work. Vita3K and shadPS4 are set separately. Ryujinx and Cemu have no such
switch, because they have nothing to trade.

**Per game, if one differs.** That is the common shape of a PS4 library: one
game that wants motion and twenty that would rather keep their back buttons.
Set the emulator off and that one game on.

**What it costs, and why it is not simply on.** To reach the sensor the emulator
has to read the Deck's controller directly instead of through Steam Input. Your
Steam layout then stops shaping it: remapped buttons, stick curves and the
**back buttons** do nothing. The **STEAM button** opens the Steam menu and
nothing else. Sticks, triggers and face buttons behave as always, and the right
trackpad still works as a pointer.

That applies to **every** game of that system, including the ones with no motion
at all — it cannot be paid per game. So a PS4 library with one motion game
would lose its back buttons everywhere to gain a gyro in one place, which is a
choice worth making deliberately rather than one to inherit.

**Games are put on a controller layout called "Gamepad with Gyro (DeckyEmu)"**
while motion is on, because Steam switches the Deck's sensor off unless the
running game's layout uses the gyro. It is Valve's own gyro layout with the gyro
sent to a stick rather than the mouse, since both emulators read the mouse
pointer as a touch surface. Switching motion off puts those games back on an
ordinary gamepad layout — which matters, because a gyro layout left in place
would send your tilting to the right stick and drift the camera.

**If you picked a layout for a game yourself, yours is kept**, in both
directions: it is never replaced when motion goes on, and never taken away when
it goes off. So if motion does not work in one game, that is usually why — open
its **Controller Settings** and choose **Gamepad with Gyro (DeckyEmu)**.

Binding the gyro yourself works too, with one catch: a behaviour that activates
only while you hold or touch something — *Gyro To Mouse* defaults to right-stick
touch — leaves the sensor powered only while you do, so motion works under your
thumb and looks broken otherwise. Pick one that is always on, such as **Gyro To
Joystick Camera**.

**If Vita3K says its build came from a source no longer used**, update it once
from the **Emulators** tab. An emulator already on your Deck is never
re-downloaded on its own, so an older install stays where it is until you say.
You are told once as a game starts, and the **Emulators** tab keeps saying it
until you do.

### The two fixes underneath

Neither console works on a Deck without a correction, and they are different
ones.

**Vita3K gets four bytes changed in the copy on your Deck.** Motion is broken
in current builds, where the bundled SDL reports the Deck's sensor timings in the
wrong unit and the maths comes out a thousand times too small. Vita3K builds SDL
into itself, so unlike shadPS4 below there is nothing to correct from outside —
the change has to be in the file.

The emulator is still the authors' own build, downloaded from
[Vita3K/Vita3K-builds](https://github.com/Vita3K/Vita3K-builds/releases) and
updated like any other — that is their numbered build repository, so DeckyEmu
can tell you which build you have and offer you an older one.

The corrected copy is made when it installs and kept beside the original, and
turning the switch off runs the original, unaltered. If a future build no longer
matches what the correction describes, nothing is changed at all — the emulator
runs exactly as downloaded, and the panel says the fix is not running rather than
letting the switch imply otherwise. Asked for upstream as
[Vita3K#4100](https://github.com/Vita3K/Vita3K/pull/4100).

**shadPS4 gets a small correction at launch instead.** It reads the Deck's
sensor axes in the wrong order — SDL describes a gamepad's axes differently from
a handheld's, and shadPS4 passes them straight through — so tilting the Deck
worked while turning it did nothing. The plugin loads a tiny library alongside
the emulator that rotates the axes back. shadPS4 itself is the ordinary Flathub
build, untouched and still updating normally. Asked for upstream as
[shadPS4#3871](https://github.com/shadps4-emu/shadPS4/issues/3871), and this goes
away when it lands.

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

Every emulator installed from the panel can be moved between published builds
without leaving it, whether it came from Flathub or from the project's own
releases.

For an emulator, the branch button on its row under **Emulators**. For RetroArch,
**RetroArch version** on its own tab. Both open the same dialog: which build is
installed, an **Update** when a newer one is published, and every other build
that is published, listed by date. Each row opens to show the whole of its
description, the version, and **how much it would download** — switching build
re-fetches the entire application, which for RetroArch is around 400MB.

Nothing updates on its own. An emulator moves when you ask it to.

### The ones marked (GitHub)

RPCS3, Azahar, Vita3K and Xenia Canary publish no Flatpak, so the plugin
downloads them from the projects' own release pages — which is what the
**(GitHub)** beside their names on the Emulators tab means. They move between
builds like the rest, with two differences.

**Whether an update exists is not checked when the tab opens.** Finding out
means asking each project's repository directly, one request per emulator, and a
tab that did that every time you walked past it would be spending your
connection on a question nobody asked. So there is a **Check for emulator
updates** button at the foot of the Emulators tab. Press it and the rows say
*update available* where there is one, and the button says what it found.

Until you press it, the plugin does not claim either way. A row saying nothing
means nobody has looked — not that the emulator is current.

**They cannot be held.** A hold exists to stop something else moving an
emulator, and nothing else on the Deck updates an AppImage this plugin
downloaded. Staying on a build is simply not pressing update.

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
| A system-wide Flatpak | Root-owned, and the plugin has no way to answer a password prompt |
| RetroArch from a package or an AppImage | Neither was installed from here and neither has builds to move between |
| An emulator you registered yourself | The plugin did not install it and does not know where it publishes |

For a Flathub build, the note on each row describes its *packaging* — "Restrict
nvidia-cg-toolkit to x86_64" — not the emulator's own release notes, which live
on the project's site. For a release build the row is the tag the project gave
it, which is as much as a release listing carries.

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
