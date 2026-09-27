# Save data

How to back your saves up, copy them to cloud storage of your own, and put them
back when something goes wrong.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Backing up save data

Press **Back up save data** on the Library tab. It gathers the saves of every
emulator on your Deck into one file and hands it to your phone or PC over your
network — the same QR code and six-digit code that [send files the other
way](transfers.md#sending-files-from-another-device).

Nothing on your Deck gets changed or removed by this.

> **Do this before anything that deletes.** Removing a game, removing
> everything, and uninstalling an emulator with its data all take saves with
> them, and you can't undo any of it.

Every emulator is a row you can untick. What each one contributes:

| | |
| --- | --- |
| **Most emulators** | Just the save folders. RPCS3's saves are 28 KB next to 367 MB of games and firmware in the same folder, and the games aren't in your backup |
| **Some emulators** | Everything they keep, configuration included. The row tells you, because it's the difference between a few megabytes and the whole emulator directory |

RetroArch gets asked where its saves are rather than assumed. So if something
has pointed it somewhere other than the default — another setup tool, or you —
you get backed up from the folder actually in use.

> **Download it before you press Done.** The file gets deleted from your Deck at
> that point. It also goes when the transfer server times out.

**Moved an emulator's saves to your SD card and linked them back?** Those aren't
included, and you'll be told. Nothing here follows a link — not the .zip, not
the copy to cloud storage. The emulator's row names the folders it skipped, and
so does the diagnostic report. Move the files back under the emulator's own
folder if you want them carried.

## Setting up cloud storage

Press **Set up cloud storage** under **Save data** to pick somewhere off your
Deck for saves to go. The storage is yours and so is the account — your Deck
just writes down how to reach it, and your password stays on the device.

You fill the form in from your phone or PC, using the same QR code and six
digits as everything else here, because it means typing an address, a username
and a password.

There are two kinds of storage on that page.

**Ones you type the details for:**

| | |
| --- | --- |
| **WebDAV** | Your WebDAV endpoint address, plus username and password |
| **SFTP or SSH** | Hostname, username and password — a NAS, or any box you can already log into. Leave the port empty for the usual one |
| **FTP** | Same again, for plain FTP servers. FTP offers no checksums, so copies there compare size and modification time |
| **S3 storage** | Your endpoint and an access key pair. You're not asked which S3 it is, because the generic settings are what save files need |

**Ones you sign in to** — Dropbox, OneDrive and pCloud:

1. Pick one and press **Sign in**.
2. Log in like you normally would.
3. Your browser lands on a page that won't load. **That's expected.**
4. Press **Paste the address and finish**.

That reads your clipboard, hands the address to your Deck and finishes the
sign-in in one press. If your browser won't share its clipboard, paste the
address into the box underneath instead.

Why that last step? Signing in sends the answer back to `localhost`, which from
your phone means *your phone*. The answer is sitting in the address of the page
that failed, so pasting it across is what gets it to your Deck. Either way, you
type nothing on the Deck.

> **Google Drive isn't offered.** The shared credentials rclone uses for it are
> being retired during 2026, and the alternative is registering your own
> application in Google's developer console.

**Using WebDAV?** Your address goes to the server exactly as you type it, so use
the full WebDAV endpoint your server documents — not the address you'd open in a
browser. Copies get compared by size and modification time, since WebDAV servers
rarely offer a checksum. Some servers report free space and some don't; if yours
doesn't, you just won't see a figure.

The page saves your settings and then checks the storage actually answers, so a
typo in the hostname gets caught right there instead of failing days later. If
it can't be reached, nothing is kept.

You're never asked to name anything. The service is what it's called, on the
page and on your Deck.

### Managing your storages

Once one is set up, the row reads **Change where saves go** and names the
service — "Saves go to Dropbox". Open it and you'll see every storage on this
Deck, with **In use** next to the one saves go to.

- **Pick another** to switch.
- **Add another** puts the code back on screen for a second account. It'll say
  it's waiting, and once you finish signing in on your phone the Deck comes back
  to the list with the new storage marked in use.
- **Sign out** removes a storage and its credentials. Sign out of the one saves
  currently go to and the job passes to the next storage on the list — the
  question tells you which: *Saves go to Dropbox after this*. Sign out of your
  last one and cloud saves is off until you set another up. There's no separate
  switch for it.

Got two accounts on the same service? They're numbered, here and in **Restore
save data**, so the storage you copy to and the storage you restore from are
named the same way.

Setting this up copies nothing. It only records where saves would go.

## Sending saves to the cloud

This happens from **Back up save data** too, because it's the same decision —
which emulators, and where to.

Tick what you want and you get two destinations:

- **Copy to a device** makes the .zip and hands it to your phone or PC.
- **Copy to Dropbox** (or whichever storage is in use) sends the same saves
  straight up.

What goes up is loose files, one folder per emulator, not a zip. So only what
actually changed gets sent.

You can open your own storage in its website or app and look around. It's laid
out as `DeckyEmu/saves/<emulator>/`, and you can delete an emulator's saves from
there without any tool.

> **Nothing is ever deleted from your storage by this plugin.** A save you remove
> from your Deck stays in the cloud, and uninstalling an emulator doesn't empty
> its folder up there.

Copying always sends your Deck's version. So if you restore an old save and then
press copy, the cloud now holds the old one.

### Earlier copies

Whatever a copy replaced is kept, in both directions — so taking the cloud's
copies keeps yours too.

Look under **Restore save data** for a row reading *Dropbox — earlier copies
(3)*. Each one tells you which saves it holds and when they were set aside:
*RetroArch — 3 Sep, 22:10*. Pick one and you see what's in it before anything
gets put back.

This is what stops an automatic copy destroying a save. Say a save gets
corrupted, or you restore an old one. Then you play for five minutes, quit, and
the automatic copy sends that state to the cloud on top of your good save.
Without this it'd be gone from both places.

Ten are kept and ten are offered, so nothing sits in your storage that you can't
reach from your Deck. One press is one of those ten, whether it covered one
emulator or fourteen. Older ones get removed after each copy.

Your actual saves are never deleted by any of this.

> **Note:** everything that removes or replaces something gets written down —
> copies ageing out, saves moved aside, a restore that overwrote, a storage you
> signed out of. One line each in `destructive.log`, next to your settings.
> Unlike the ordinary log, it's never rotated.

## Copying when a game closes

Once a storage is set up this just happens. Close a game and that emulator's
saves go up. Only that emulator, only the files that changed — closing a Mega
Drive game sends a few kilobytes.

Nothing to press, no dialog.

Want to check it's working? The switch under **Change where saves go** — *Copy
saves when a game closes* — tells you when saves last went up, and reads
*Copying saves now* while one is running. Turn it off if you're on a hotspot and
would rather choose when to spend the connection.

### Some of my saves haven't been copied

The last row of **Save data** says so: *Saves not copied yet: RetroArch and
DuckStation have saves newer than your storage*. Press **Copy them now** and
they go up there and then.

Worth using, because the copy after a game only covers the emulator you were
playing. One that failed while you were offline would otherwise sit there until
you next play *that* emulator, which might be never.

If something's still waiting after a later copy has come and gone, the plugin's
front panel tells you too, with the same button.

> **Note:** only one copy runs at a time. Press **Copy now** or start a restore
> while one is going and you'll be asked to try again in a moment.

Copying doesn't run from the launcher, which is why your library tile goes back
to "Stopped" the moment you quit instead of waiting for the network.

## Saves coming back before a game starts

The other half of the same idea. Start a game and your storage gets checked for
saves this Deck doesn't have, which come down before the emulator opens
anything.

Nothing gets overwritten — a file that isn't here can't replace one that is — so
it happens quietly and asks you nothing.

If it takes more than a moment you'll see *Getting your saves*, with a bar and a
**Start now** button. Nothing to fetch means you see nothing at all.

It's one request and it has a deadline. Your game starts within about six
seconds whatever your storage is doing. If the plugin can't answer at all — your
network's gone, decky is reloading — the launcher gives up and starts the game on
the saves already there.

**Its own switch** sits above the other one: *Check for newer saves when a game
starts*. On by default, because it's the half that makes a second device work —
without it your saves only ever go up.

Turn it off and games start straight away on whatever's on your Deck, while
copies still go up when you stop playing. Worth doing on a slow connection, or
if this Deck is the only place you play.

### I was asked to choose between two saves

That happens when a save exists both here and in your storage and the two are
different. Your game waits while you decide.

> **Note:** this is about the emulator, not the one game. Saves can't reliably be
> traced to a single game — RetroArch names them after the ROM, but RPCS3 files
> by title id and a PS1 memory card holds a dozen games in one file. So starting
> one RetroArch game can raise a question about a save belonging to a different
> one, and whichever button you press applies to all of them.

You get a date for each side — *This Deck: changed 2 hours ago* / *Cloud storage:
changed 20 minutes ago* — the files that differ, and three answers:

| | |
| --- | --- |
| **Play with this Deck's** | Nothing gets written. Your storage keeps its copy, and the next copy up replaces it — keeping what it replaced |
| **Play with the cloud's** | The cloud copies come down first, then your game starts |
| **Don't start** | Your game doesn't launch, so you can go and look before deciding |

Neither of the first two loses anything. You're asked because nothing here can
tell which copy you want.

You only get asked once. Whichever you pick is remembered, so the same
disagreement won't come back next time you play. If that other device writes
again, that's a new situation and you'll be asked about that one.

The dialog waits for you — your game is paused, not loading. Leave it long enough
that something has clearly gone wrong and it starts with this Deck's saves,
which writes nothing.

### I restored an old backup and my old saves came back

A restore from a .zip only writes to your Deck. Your storage still holds what it
held, so the next launch of that emulator brings down the files it has and your
Deck no longer does.

If you've deliberately gone back to an older set of saves, either turn *Check
for newer saves when a game starts* off, or copy the older set up first so the
two agree.

## When there is no network

None of this stops you playing.

Offline, the check before a game gives up in about a second and your game starts
on the saves it already has.

Closing a game still tries. A copy that can't reach your storage rides out a
short outage, and if it fails properly nothing gets written down as sent — so
that save goes up on the next copy instead, whether that's the next game you
close or **Copy now**.

## Restoring from the cloud

Press **Restore save data** and you'll see your signed-in storages listed next
to the backup files on your Deck, because from that screen they're the same
thing. The one saves are copied to comes first, marked **In use**.

Pick one and you get the same per-emulator rows and the same two buttons as a
.zip:

| | |
| --- | --- |
| **Restore missing** | Writes only what isn't already here |
| **Restore all** | Writes the lot, overwriting. Asks you to confirm, and can't be undone |

The list appears before it's finished. Emulator names come back in about a
second, then each row says what it holds as its own answer arrives — so the one
you came for is usually readable while the rest are still counting. The line
under the storage name reads *Reading what it holds - 6 to go*. Both buttons
wait for that.

> **Every account is offered**, not just the one saves currently go to. That's
> what makes switching storage cost nothing: move from Dropbox to pCloud and
> nothing is moved, copied across or stranded. Dropbox keeps what it had and is
> still one press away.

Uninstalled an emulator? Its saves still show in the list, marked, so you can
see your Vita saves are safe on a Deck with no Vita3K on it.

**Restoring everything from a storage gives you a way back.** Press **Keep a
copy first** and the saves about to be overwritten go up, appearing under earlier
copies as one more dated row — so a restore you pressed by mistake is one restore
away from being undone. **Replace without keeping** is the other button.

## Restoring a backup

Press **Restore save data** under **Save data** on the Library tab, right next to
the button that made the backup.

No backup on your Deck yet? Press **Send a backup to this Deck** in that dialog.
It opens the [same transfer
flow](transfers.md#sending-files-from-another-device) you use for everything
else.

It finds the file itself. You don't point at it, and it's recognised by what's
inside rather than by its name, so renaming changes nothing. With more than one
on your Deck, you pick which.

> **Note:** backups don't land in your transfer folder. They're recognised on
> arrival and filed under `~/deckyemu/backups/`, so they never show up in the ROM
> picker as something to add to Steam.

The choice that matters is which button you press:

| | |
| --- | --- |
| **Restore missing** | Writes only the saves you don't have. Anything already on your Deck is left alone, so a game you played since the backup can't lose progress |
| **Restore all** | The backup wins and whatever is on your Deck now is gone. What you want after wiping a Deck. It asks first and says how many files it'd overwrite |

Before you press anything, the screen tells you how many files are in the backup
and how many you already have.

> **Warning:** there is no undo for replacing.

Restoring everything from a storage also takes that storage's record of what it
holds, so the next game you close doesn't copy the same saves straight back up.

A restore that wouldn't fit gets refused before anything is written, telling you
what it needs and what's free. It counts what the restore would actually write,
so restoring what's missing isn't refused just because the whole backup wouldn't
fit twice.

Saves for an emulator you don't have installed get named and left in the archive
rather than written into a folder nothing reads. Install that emulator and
restore again.

**Your backup is deleted from the Deck once it's been read**, the same way
unpacking a zip consumes it. The copy you sent it from is untouched, so restore
again by sending it again. A restore that *fails* leaves the file, since that's
how you try again.
