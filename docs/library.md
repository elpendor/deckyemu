# Your library

Editing a game after it is added, how games are grouped in Big Picture, and
putting things back in order.

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

The choice that matters is one switch:

| | |
| --- | --- |
| **Off** (default) | Writes only the saves that are **missing** here. Anything already on the Deck is left exactly as it is, so a game played since the backup cannot lose its progress |
| **On** | The backup's copy wins and whatever is on the Deck now is gone. What you want after wiping a Deck, or when the saves here are the ones you are trying to get rid of |

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
