# Your library

Starting and editing a game, how games are grouped in Big Picture, backing up
and restoring save data, and putting things back in order.

Back to [the README](../README.md).

**Contents** — [Starting a game](#starting-a-game) ·
[Editing a game](#editing-a-game) ·
[Collections](#collections) · [Orphaned entries](#orphaned-entries) ·
[Backing up save data](#backing-up-save-data) ·
[Restoring a backup](#restoring-a-backup) ·
[Removing everything](#removing-everything)

## Starting a game

The play button on each row in **Added games** starts that game, closing the
panel on the way so nothing is left over the top of it. It goes through Steam
rather than running the emulator directly, so gamescope, Steam Input and the
overlay all behave as they do when you launch from the library.

**A multi-disc game is one entry**, and most of them change disc by themselves.
When one does not, **Select + Start** opens the emulator's menu, where
**Change Disc** lists them — see
[multi-disc games](getting-started.md#multi-disc-games).

### Its page in your library

![A game added from a ROM, open on its own page in the Steam library, with hero
artwork, a logo and a Play button.](images/its-page-in-steam.jpg)

The ⓘ button beside play opens Steam's own page for that game — where the
artwork, the play time and the per-game controller and performance settings
live. The panel closes on the way, for the same reason play does: anything left
standing comes back on top of the page you asked for.

### If another game is already running

Steam normally warns you before starting a second game, but that warning never
appears for games added here — it only applies to Steam's own titles, and these
are non-Steam shortcuts. Running two at once is worth avoiding: they share the
Deck's memory and its heat budget, and the first one keeps doing so long after
you have forgotten it is there.

So the plugin does the warning itself. Start one of these games while another is
running — from anywhere, including the game's own page in Big Picture — and you
will see a flicker back to where you were, then:

> **You are currently running *Mina the Hollower*.** It is not recommended to
> run multiple games simultaneously as it can impact performance. How would you
> like to proceed?

with the same three choices Steam offers: close the running game and launch this
one, launch it anyway, or cancel. The emulator does not start until you pick.

**The flicker is the point, not a fault.** Nothing can stop a launch once Steam
has begun it, so the game's launcher script is what refuses — it is the first
thing that runs, and it stops before the emulator starts. That brief return to
the library is it deciding not to continue.

If anything about that check goes wrong, the game launches normally. It is built
to fail in that direction: a missing warning is a far smaller problem than a
game that will not start.

### Where a game's name comes from

Adding a game looks the name up rather than trusting the filename. If libretro
recognises it, that name is used. If nothing recognises it but **SteamGridDB**
identified the game while fetching artwork, its name is used instead — that
search is what found the artwork now on your game, so it identifies it better
than the filename does.

Only when nothing recognises it at all does the filename stand, tidied up. That
is when a ROM named `... , The (USA (Rev 1) Decrypted` becomes a game called
`Ocarina of Time 3D, The Decrypted`.

**The panel says which of the three named it**, under the name, whenever the
name is a guess — and the field is editable right there, so the moment to fix it
is before you press Add. It says so because SteamGridDB's search occasionally
answers with a different game in the same series, and a wrong name follows a
game around in a way a wrong picture does not.

### If the game or its emulator has gone

A shortcut keeps working after the things behind it have gone, and the two
ordinary ways that happens are an SD card that did not mount and an emulator
that is no longer installed. Either way the game used to start, fail, and put
you back in the library a second later with nothing on screen to explain it.

Now the launcher checks both before it starts anything, and if something is
missing it stops and says which:

- **The game file is not there** — usually a card that has not mounted, so
  reinsert it and try again. If the file was moved or deleted for good, remove
  the game and add it again.
- **The emulator is not installed** — the message names which one, so open the
  **Emulators** tab and install it. Saves and settings are kept, so this costs a
  download and nothing else. For a RetroArch game it names the *core*, since
  that is the piece that goes missing.

Same as the check above, this only ever stops a launch that was going to fail:
if it cannot tell, the game starts as usual.

![The Added games list, grouped by system, with play, details, edit and remove
buttons on each row.](images/added-games.jpg)

Each row carries the game's own artwork. A game whose artwork was never found —
the add flow says so at the time — gets a plain controller icon in its place, so
the titles still line up in one column.

### Grouped, or one tab per system

The list groups games under their system, all in one scroll, so what you own is
visible on the way past. **Settings → Library → One tab per system** swaps that
for a tab each, paged with L1 and R1.

Which reads better depends on your library rather than on taste. A few games
spread across many systems suit the grouped list — a tab holding one game is a
lot of chrome for one row. A lot of games on a few systems suit tabs, where a
system is one bumper press away instead of a scroll past everything above it.
The tab you were last on is remembered until the plugin restarts.

## Editing a game

The pencil on each row in **Added games** opens an editor for a game already in
Steam, so its playtime and its place in a collection survive. The game's own
page in Big Picture reaches the same editor: the cog menu carries a **DeckyEmu**
entry with **Edit** and **Remove**, for the games this plugin added and no
others.

- **Name** — renaming moves the launcher, since its filename embeds the title.
- **ROM file** — repoint an entry at a moved file, an SD card or a better dump.
  The launcher filename also embeds a hash of the ROM path, so this relocates the
  script too. A ROM the chosen core cannot read is refused.
- **Core or emulator** — changing it can change the system, so the platform label
  and the per-platform collection follow.
- **System** — only for a core covering more than one, which is most of them.
  It says which of that core's systems this game is, and that decides the shelf
  it is on, the folder its ROM was filed into and which thumbnail directory its
  cover comes from. It starts on where the game is filed now, so changing it is
  how a game that landed on the wrong shelf is moved — saving does the move.
  Worth running **Look up name and artwork again** afterwards, since the cover
  came from the old system.
- **Name and artwork** — **Choose the right game** is how you say which game
  this is when the automatic match got it wrong; it sets the name as well as
  the cover, unless you have written a name of your own. Artwork lands
  immediately; a name change waits for Save, like every other edit here.
  **Look up name and artwork again** is worth running after a core or system
  change, since the system decides which thumbnail directory is searched.
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

Which system a game is comes from the **System** row on the add panel, which
starts on what the file says: a `.md` is a Mega Drive cartridge whatever else
its core reads. Where the file says nothing — a `.cue` or an `.iso` names a
medium, not a system — the core's first system is used, and the row is there to
correct it before adding. Games added before that row existed had their system
inferred from whichever system's cover art matched the filename first, which is
worth knowing if one is on a shelf you did not expect; the editor's **System**
row moves it.

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

## Backing up save data

**Back up save data**, on the Library tab, collects the saves of every emulator
on this Deck into one file and offers it to a phone or PC on the same network —
the same QR code and six-digit code that [send files the other
way](transfers.md#sending-files-from-another-device). Nothing on the Deck is
changed or removed by it.

It is worth doing before anything on this page that deletes: removing a game,
removing everything, and uninstalling an emulator with its data all take saves
with them, and none of that can be undone.

Each emulator is a row you can untick, with what it would contribute:

| | |
| --- | --- |
| **Most emulators** | Only the save directories — RPCS3's saves are 28 KB beside 367 MB of games and firmware in the same folder, and the games are not in the backup |
| **Some emulators** | Everything they keep, including configuration. The row says so, because it is the difference between a few megabytes and the emulator's whole directory |

RetroArch is asked where its own saves are rather than assumed, so a Deck that
also has EmuDeck — which points RetroArch at `~/Emulation/saves` — is backed up
from the directory actually in use.

**The file is deleted from the Deck when you press Done**, so download it first.
It is a copy of your saves, and leaving one lying in the plugin's working
directory is a copy nobody asked to keep. It also goes when the transfer server
times out, as everything else there does.

**A save folder that is a link is not included, and says so.** Moving an
emulator's saves to the SD card and linking them back is a common trick, and
nothing here follows such a link — not the .zip and not the copy to a storage.
Rather than quietly leaving those saves out, the emulator's row on **Back up
save data** names the folders it skipped, and so does the diagnostic report.
Move the files themselves back under the emulator's own directory if you want
them carried.

## Setting up cloud storage

**Set up cloud storage**, under **Save data**, chooses somewhere off the Deck
for saves to be copied to. The storage is yours and the account is yours: the
Deck only writes down how to reach it, and the password stays on the device.

The form is filled in from a phone or PC — the same QR code and six digits as
everything else here — because it means typing an address, a username and a
password, and the on-screen keyboard is the wrong tool for that.

Two sorts of storage, on the same page.

**Ones you type the details for**, where the form is all there is:

| | |
| --- | --- |
| **WebDAV** | The address of the WebDAV endpoint, and the username and password you use for it |
| **SFTP or SSH** | A hostname, a username and a password — a NAS or any box you can already log into. The port is asked for and can be left empty, which means the usual one |
| **FTP** | The same, for a server that speaks plain FTP. FTP servers offer no checksums, so copies there compare size and modification time instead — which is what rclone does by default and what catches a save that changed without changing size |
| **S3 storage** | The endpoint and an access key pair — you are not asked which S3 it is, because the generic settings are what save files need |

**Ones you sign in to** — Dropbox, OneDrive and pCloud. Pick one and the
page gives you a **Sign in** link. Log in as you normally would, and the browser
will land on a page that does not load. **That is expected.** Copy the address
of that page and paste it into the box, and the Deck takes it from there.

The reason for that last step: signing in sends the answer back to
`localhost`, which from your phone means your phone. The answer is still sitting
in the address of the page that failed, so pasting it across is what gets it to
the Deck. Nothing is typed on the Deck either way.

Google Drive is not offered. The shared credentials rclone uses for it are being
retired during 2026, and the alternative is registering your own application in
Google's developer console — more work than this feature is worth.

For the storages you sign in to rather than type details for, the sign-in opens
in its own tab and ends on a page that will not load — that is expected, and the
address of that page is what carries the code. Copy it, come back to the setup
tab, and press **Paste the address and finish**: one press reads the clipboard,
hands the address to the Deck and completes the sign-in. Pasting it into the box
underneath does the same thing without a second press, for a browser that will
not share the clipboard.

**WebDAV is taken as typed.** The address goes to the server exactly as you
enter it, with nothing added and no assumptions about which software is behind
it — so it is the full WebDAV endpoint, the one your server documents, rather
than the address you would open in a browser. Copies there are compared by size
and modification time, because a WebDAV server rarely offers a checksum — which
is why the Deck asks it to store modification times, and why a server that
cannot is one where a save that changed without changing size could be missed. Some servers publish how much room
is left and some do not; where yours does not, the storage simply shows no
figure.

The page saves the settings and then **checks that the storage actually
answers**, so a mistyped hostname is a sentence on the screen you are looking at
rather than a backup that fails days later. If it cannot be reached, nothing is
kept.

**You are never asked to name anything.** The service is what it is called, on
the page and on the Deck. Something under the hood does need a name for its
config file, so one is picked for you and never shown.

Once a storage is set up, the row says so: it reads **Change where saves go**
and names the service — "Saves go to Dropbox". Where the service will say who you are
signed in as, that is shown too; most will not, and Dropbox is one of them, so
the service alone is often all there is to show.

Open it again and every storage set up on this Deck is listed, with **In use**
beside the one saves go to. Pick another to switch, or sign out of one to remove
it and its credentials. Signing out of the one saves currently go to hands that
job to the next storage on the list rather than to nothing, and the question asks
it that way — *Saves go to Dropbox after this* — because a Deck with three
storages signed in and no destination would stop copying without saying so. Sign
out of the last one and cloud saves is off: nothing is copied anywhere, and the
transfer tool stops being kept for it, until you set a storage up again. There
is no separate switch for that — the storages are what the feature is, and one
more toggle saying the same thing is one more thing to disagree with itself.
**Add another** puts the code back on screen for a
second account; it says it is waiting, and when the sign-in finishes on the
phone the Deck returns to the list by itself with the new storage marked in
use — the two screens take turns because the code and a list of storages do not
both fit on a Deck. Two accounts of the same service are numbered — here and
in **Restore save data**, so the storage you copy to and the storage you restore
from are named the same way — because that is the one case where the service
alone cannot tell two rows apart.

**That part stays on the Deck.** The web page exists because signing in needs a
browser and a keyboard; choosing between accounts needs neither, and it is a
decision about this device.

Setting this up copies nothing. It only records where saves would go.

## Sending saves to the cloud

**Back up save data** is where it happens, because it is the same decision — which
emulators, and where to. Tick what you want and the dialog offers two
destinations: **Copy to a device** makes the .zip and hands it to a phone or PC as
it always did, and **Copy to Dropbox** (or whichever storage is in use) sends the
same saves straight up. The two are named the same way on purpose — the same
saves are going somewhere either way, and where is the only difference.

What goes up is loose files, one folder per emulator, not a zip. That is what
makes a second copy cheap: only what actually changed is sent, rather than a
hundred megabytes to record a two-kilobyte change. They go up dozens at a time
rather than one after another, because a save is a small file and almost all of
the time is spent waiting for the storage to answer rather than sending
anything: sixty of them measured 50 seconds to Dropbox one way and 11 the other,
and 168 seconds to pCloud against 11. You can open your own storage
in its website or app and look at it — it is laid out as
`DeckyEmu/saves/<emulator>/` and you can delete an emulator's saves from there
without any tool.

**Everything that removes or replaces something is written down.** Safety copies
ageing out, saves moved aside by a copy, a restore that overwrote what was here,
a storage signed out of — each is one line in `destructive.log`, beside the
settings, with what it was and when. The ordinary log keeps only the last few
runs and rotates the rest away, which is fine for progress lines and useless for
the question "what removed this?" a week later. That file is never rotated.

**Nothing is ever deleted from your storage by this plugin.** A save removed from
the Deck stays in the cloud, and uninstalling an emulator does not empty its
folder there. That is deliberate: the alternative is one uninstall quietly taking
your backup with it.

**Copying always sends the Deck's version.** A file already in the cloud that is
different gets the Deck's copy — so if you restore an old save and then press
copy, the cloud now holds the old one.

**Nothing this plugin does automatically can destroy a save.** That is what the
replaced copies are for, and the case they exist for is an ordinary one: a save
gets corrupted, or you restore an old one, or a game overwrites a slot — then
you play for five minutes, quit, and the automatic copy sends that state to the
cloud on top of the good save. Without this it would be gone from both places.

Whatever a copy replaced is kept — in either direction, so taking the cloud's
copies keeps yours too — and **Restore save data** has it behind a row reading
*Dropbox — earlier copies (3)*. Open that and each one says which saves it holds
and when they were set aside: *RetroArch — 3 Sep, 22:10*. Choosing one shows what
it contains before anything is put back, exactly like choosing a backup: under each storage you will see rows like *Replaced 3 Sep,
14:51*, one per press that overwrote something, newest first. Choosing one shows
the same per-emulator rows as anything else and puts those saves back the same
way.

The list scrolls, showing about three at a time — with several emulators there
are more of these than of anything else on the screen, and the buttons have to
stay reachable. Every list in these dialogs is that shape: the emulators to back
up, the backups and storages to restore from, the storages themselves. Three
rows and the rest scrolled, so no list can push the buttons off the bottom.

Ten are kept, and ten are what you are offered — the same number on purpose, so
nothing sits in your storage that you cannot reach from the Deck. One press is
one of those ten, whether it covered one emulator or fourteen: a copy is a thing
that happened, so it is one row rather than fourteen rows sharing a timestamp. Older ones are removed after each copy, rather than
being left somewhere you would need a web browser and another device to reach.
Your saves themselves are never deleted by any of this; only these safety copies
age out.

## Copying when a game closes

Once a storage is set up this happens on its own: close a game, and that
emulator's saves are copied up. Only that emulator, and only the files that
changed — closing a Mega Drive game sends a few kilobytes.

There is nothing to press and no dialog appears. If you want to know it is
working, the switch under **Change where saves go** — *Copy saves when a game
closes* —
says when saves last went up, and reads *Copying saves now* while one is
actually running. Turning it off is worth doing if you are on a hotspot and
would rather choose when to spend the connection.

When something has not made it up yet, the last row of the **Save data**
section says so — *Saves not copied yet: RetroArch and DuckStation have saves
newer than your storage* — and pressing **Copy them now** sends those emulators
up there and then, with a bar under the button while it does. It is worth having because the copy after a game only covers the emulator
you were playing, so one that failed while you were offline waits for the next
time you play *that* emulator, which might be never.

**If saves stay uncopied, the plugin's own panel says so.** The row above is on
the Library tab, where you would have to go looking. When something is still
waiting after a later copy has been and gone — a storage that has stopped
accepting saves, or an emulator you have not opened since one failed — nothing
is going to pick it up on its own, so that one appears on the plugin's front
panel with the same button. It says nothing about the ordinary wait between
quitting a game and its copy landing, which would be a light on most of the time
and mean nothing.

Only one copy runs at a time. Press **Copy now** or start a restore while that
one is still going and you are asked to try again in a moment, rather than
having two of them writing the same saves in opposite directions.

It does not run from the launcher, which is why your library tile goes back to
"Stopped" the moment you quit rather than waiting for the network. The plugin
notices the game has ended and does the copying itself.

## Saves coming back before a game starts

The other half of the same idea. Starting a game checks your storage for saves
this Deck does not have, and brings them down before the emulator opens
anything. Nothing is overwritten by this — a file that is not here cannot
replace one that is — so it happens silently and asks nothing.

If a fetch takes more than a moment, a dialog says what is happening — *Getting
your saves* — with a bar and a **Start now** button, so you are never stuck
looking at a black screen wondering whether the game failed. A launch with
nothing to fetch shows nothing at all.

**It is one request, and it has a deadline.** The launch waits while it happens,
usually well under a second, and the game starts within about six seconds
whatever your storage is doing. If the plugin cannot answer at all — the network
is gone, decky is reloading — the launcher gives up on its own and starts the
game with the saves already on the Deck. A game that will not start is worse than
a game with an old save.

**One case does ask, the way Steam asks it.** If a save exists both here and in
your storage and the two are different, the game waits and you get a dialog.

**It has its own switch**, above the other one — *Check
for newer saves when a game starts*. On by default, because it is the half that
makes a second device work: without it saves only ever go up. Turn it off and a
game starts straight away and uses whatever is on the Deck, while copies still go
up when you stop playing. Worth doing on a slow connection, or if this Deck is
the only place you play and the copies are there as a backup rather than to be
read back.

**It is about the emulator, not the one game.** Saves cannot reliably be traced
to a single game — RetroArch names them after the ROM, but RPCS3 files by title
id and a PS1 memory card holds a dozen games in one file — so a conflict covers
everything that emulator keeps, and the dialog says so. Starting a RetroArch
game can therefore raise a question about a save belonging to a different one,
and whichever button you press applies to all of them.

The dialog gives you a date for each side — *This Deck: changed 2 hours ago* / *Cloud storage: changed
20 minutes ago* — the files that differ, and three answers:

| | |
| --- | --- |
| **Play with this Deck's** | Nothing is written. Your storage keeps its copy, and the next copy up replaces it — keeping what it replaced |
| **Play with the cloud's** | The cloud copies come down first, and the game starts with them |
| **Don't start** | The game does not launch at all, so you can go and look before deciding |

Neither of the first two loses anything. It is a question rather than a decision
because nothing here can tell which copy you want. And the plugin does not ask
your storage provider what it thinks: a small record is written beside your
saves each time they go up, and the only thing compared is whether that record
is the one this Deck wrote. That works the same on every service — Dropbox and
pCloud cannot even store a file's modification time without re-uploading it,
which is exactly the kind of difference this avoids depending on.

**You are only asked once.** Whichever you choose is remembered, so the same
disagreement is not put to you again next time you play. If that other device
writes again, that is a new situation and you will be asked about that one.

The dialog waits for you — the game is paused, not loading, and pausing costs
nothing. If it is left long enough that something has clearly gone wrong, the
game starts with this Deck's saves, which writes nothing.

**Restoring an old backup and then playing brings some of it back.** A restore
from a .zip only writes to this Deck; your storage still holds what it held, so
the next launch of that emulator brings down the files it has and this Deck no
longer does — that is the same rule as ever, since a file that is only up there
cannot overwrite anything here. If you have deliberately gone back to an older
set of saves, turn *Check saves before a game starts* off, or copy the older set
up first so the two agree.

## When there is no network

Nothing about cloud saves stops you playing. With the Deck offline, the check
before a game gives up in about a second and the game starts on the saves it
already has — which is what would have happened anyway.

Closing the game still tries. A copy that cannot reach your storage rides out a
short outage, and if it fails properly nothing is written down as having been
sent, so the save goes up on the next copy instead: the next game you close, or
**Copy now**. What you played is not lost by having been played somewhere with
no signal.

## Restoring from the cloud

**Restore save data** lists your signed-in storages beside the backup files on the
Deck, because from that screen they are the same thing — somewhere a backup is.
The one saves are being copied to comes first and is marked **In use**, the same
words the setup dialog uses, because it is the one a restore usually means.
Pick one and you get the same per-emulator rows and the same two buttons:
**Restore missing** writes only what is not already here, and **Restore all**
writes the lot, overwriting, exactly as with a .zip. The two are named the same
way on purpose — both put saves back, and how much of the backup they use is the
only difference. That the second one overwrites and cannot be undone is said on
the confirmation it asks for.

Either way, a restore that would not fit on the Deck is refused before anything
is written, saying what it needs and what is free. Half a save set is worse than
none of it, and the sizes are known before a byte moves. It counts what the
restore would actually write, so restoring what is missing is not refused
because the whole backup would not fit twice.

The list appears before it is finished. The emulator names come back in about a
second and each row then says what it holds as its own answer arrives, so the one
you came for is usually readable while the rest are still counting — the line
under the storage's name reads *Reading what it holds - 6 to go* until they have
all answered. Both buttons wait for that, because until then the totals are not
the totals.

**Every account is offered, not just the one saves currently go to.** This is what
makes changing storage cost nothing. If your saves are in Dropbox and you switch
to pCloud, nothing is moved, nothing is copied across and nothing is stranded —
Dropbox keeps exactly what it had, and it is still one press away on this screen
whenever you want it back. New saves simply start going to pCloud.

An emulator you no longer have installed still shows in the list, marked, rather
than being hidden — so you can see that your Vita saves are safe on a Deck with no
Vita3K on it right now.

## Restoring a backup

Press **Restore save data** under **Save data** on the Library tab, beside the
button that made it. With no backup on the Deck yet, **Send a backup to this
Deck** in that dialog opens the [same transfer
flow](transfers.md#sending-files-from-another-device) used for everything else —
you do not have to go and find it. It finds the file itself — you do not point at it, and it is recognised by what is
inside it rather than by its name, so renaming it changes nothing. With more than
one on the Deck, you pick which.

**A backup does not land in the transfer folder.** It is recognised as it
arrives and filed under `~/deckyemu/backups/` instead, so it never appears in the
ROM picker as something to add to Steam. Everything else you send — ROMs, BIOS
files, definitions — stays exactly where it lands.

The choice that matters is which of the two buttons you press:

| | |
| --- | --- |
| **Restore missing** | Writes only the saves that are **missing** here. Anything already on the Deck is left exactly as it is, so a game played since the backup cannot lose its progress |
| **Restore all** | The backup's copy wins and whatever is on the Deck now is gone. What you want after wiping a Deck, or when the saves here are the ones you are trying to get rid of. It asks first, and the question says how many files it would overwrite. Restoring everything from a storage also takes that storage's record of what it holds, so the next game to close does not copy the same saves straight back up |

Restoring everything **from a storage** offers a way back: **Keep a copy first**
uploads the saves it is about to overwrite, and they appear under earlier copies
as one more dated row — so a restore pressed by mistake is one more restore away
from being undone. **Replace without keeping** is the other button, for a Deck
with nothing on it worth keeping and no reason to wait for an upload. Restoring
from a .zip on the Deck has nowhere to put such a copy, so it asks the way it
always did.

The screen says how many files are in the backup and how many of them are
already on this Deck before you press anything, so which of the two you want is
a decision rather than a guess. **There is no undo for replacing** — take a
backup first if you are unsure.

Saves for an emulator that is not installed here are named and left in the
archive rather than written into a folder nothing reads. Install that emulator
and restore again.

**The backup is deleted from the Deck once it has been read**, the same way
unpacking a zip consumes it — a restored 75 MB archive left lying there is one
nothing in Game Mode could remove. The copy you sent it from is untouched, so
restore again by sending it again. A restore that *fails* leaves the file, since
then it is the way to try again.

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
