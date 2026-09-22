# Getting files onto the Deck

Sending ROMs, BIOS files and emulator definitions from another device, and
where each one ends up.

Back to [the README](../README.md).

**Contents** — [Sending files from another device](#sending-files-from-another-device) ·
[Unpacking a zip](#unpacking-a-zip) ·
[Unpacking a Switch .nsz](#unpacking-a-switch-nsz) ·
[Where a ROM ends up](#where-a-rom-ends-up)

## Sending files from another device

![The transfer dialog: a QR code, a short address and a six-digit code, with a
received file listed below it.](images/sending-a-game.jpg)

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
set up — see [Emulators this plugin does not ship](emulators.md#emulators-this-plugin-does-not-ship).

The list is the folder, not a record of what arrived while the dialog was open,
so a file sent last week is still there to act on. Anything you decide against
gets a **delete** button beside its action — a ROM you thought better of, a BIOS
for an emulator you removed, a definition that was refused. That is the only way
to clear the inbox from Game Mode, and it asks first, naming the size.

**A disc set is one row.** A CD rip is a `.cue` and a dozen `.bin` files, and a
multi-disc game adds an `.m3u` over the top of those — all of it one game, and
none of the tracks worth adding on their own. So the sheet gets the row, and what
it names folds into it: the row reports the size of the whole set and how many
files it speaks for, a **Tracks** button lists them by name, and **Add** and
**delete** both act on all of it. The count above the list still counts files, so
it still matches what you sent. A track whose `.cue` has not arrived stays a row
of its own, because that one is a game that cannot be assembled and you need to
see it.

Arriving files show a progress bar of bytes received against the declared total,
and each can be **cancelled**. That status also appears in the Quick Access
panel, so dismissing the dialog does not hide a transfer that is still running.

**Cancelling stops the transfer but keeps what arrived.** The sending page is
told to stop rather than retry, and its row gets a **Resume** button that
carries on from where it was cancelled instead of starting over — which matters
for a game of several gigabytes on a slow connection. A transfer that gave up on
a dead connection gets the same button. Once the page has been reloaded the
button is gone, but choosing the same file again carries on just the same.
Either way only while the transfer dialog stays open on the Deck: closing it
lets the server stop, and a cancelled transfer's half-file is cleared when the
server next starts.

Anything half-sent that nobody is sending — cancelled, or interrupted and not
picked up again — is listed under **Stopped**, with how far it got. Its bin
deletes what arrived, after asking; sending that file again then starts from the
beginning.

**An interrupted transfer carries on where it left off.** Wifi dropping, a phone
locking its screen or a tab left in the background all end an upload partway;
the Deck keeps what it has and the sending page reconnects and sends the rest,
so a 4 GB ROM that stopped at 90% resumes at 90%. A connection that stops
carrying anything without closing — which looks like a frozen progress bar — is
given up after twenty seconds and picked up the same way. Files are sent one at
a time rather than all at once, and the page asks the sending device to stay
awake while they are moving.

What has arrived is kept for as long as the transfer server is running. The
panel says **Paused** rather than **Waiting** while a transfer is between
attempts, and closing the dialog leaves the server running until it finishes or
goes idle. Once the server stops, anything half-sent is cleared the next time it
starts. Keep the page open; a tab that is closed cannot come back by itself, and
the browser will ask before letting you.

### The same server runs backwards

Two things travel the other way over it, and both are reached from the plugin
rather than from the upload page: the [diagnostic
report](updates.md#reporting-a-problem), and a [backup of your save
data](library.md#backing-up-save-data). Each starts the server if it is not
already running, and one started for either of them **accepts no files** — being
shown a report or a backup should not also hand somebody a writable folder on
your Deck, and they would have no way of telling they had been given one.

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

## Fetching a definition by link

The transfer page has a box for an address, under the file picker. Paste a link
and press **Fetch**: the Deck downloads it into the same folder your files land
in, and it appears with an **Import** button like anything else you sent. A
shortened link works — what it redirects to is what counts.

It is there because the page is open on a device with a keyboard, which the
Deck is not.

Two things it will not do. It **downloads, it does not import** — you still see
what the definition installs and where it may write, and you still confirm it on
the Deck. And it takes **definitions only**: what arrives is capped at a
definition's size and then has to be one, or it is deleted. A box that fetched
anything would be a downloader for games, which this plugin is not.

## Unpacking a zip

Pick the zip the way you would pick any game — **Add a game**, then the file
browser or the **Add** button in the received list. The panel then offers
**Unpack this zip**, in the same place a `.pkg` offers to unpack itself.

It is offered *beside* the usual core choice, not instead of it, because both
can be right. RetroArch reads a zip directly, so a zipped SNES ROM can just be
added. Standalone emulators mostly cannot: Xenia refuses one outright, and a zip
holding a `.cue` and its `.bin` files has to come apart before any of it works.

Pressing it extracts the contents **flat into the transfer folder**, beside the
zip, ignoring whatever folders the archive named them in. Xbox Live Arcade
titles are the reason — they arrive as a single file buried under
`58410954/000D0000/`, and the rest of the plugin only acts on files sitting
directly in the transfer folder. If exactly one file comes out, the panel
switches straight to it, so you carry on adding the game rather than going back
to a list.

**A single file with no extension is named after the zip.** An XBLA container is
called something like `DA78E477AA5E31A7D01AE8F84109FD4BF89E49E858`, which is no
use in a list and no use to the artwork search either, so it takes the zip's name
instead — `Banjo-Kazooie (World) (XBLA)`. A file that already has an extension
keeps its own name, since that is one somebody chose.

Only zips already in the transfer folder can be unpacked; that is the one folder
this plugin writes an archive's contents into, so a zip on an SD card is left
alone and the button is not offered for it.

Nothing is overwritten. If a name is already taken, or two files inside the zip
would come out with the same name, the whole thing is refused and says why —
these arrived over your network and there is no undo in Game Mode.

**The zip is deleted once its contents are out**, the same way importing a
definition consumes it and adding a ROM files it under its system. The transfer
folder is a waypoint: everything that uses a file takes it out of there. Only
after a clean extraction — if anything goes wrong the zip is still sitting where
it was.

Only `.zip`. Nothing on a stock SteamOS reads `.7z` or `.rar`, so the button is
not offered for those rather than failing after you press it.

## Unpacking a Switch .nsz

An `.nsz` is a Switch package compressed to save space, and Ryujinx cannot open
one. Pick it in the add panel and **Unpack this .nsz** is the only thing
offered: the rows for adding it wait until it is an `.nsp`. Pressing it writes
the `.nsp` into the transfer folder with a progress bar, then the panel switches
to it and adding carries on as usual.

It takes seconds rather than minutes: a 577 MB `.nsz` became its 1.34 GB `.nsp`
in under five seconds on a Deck. No keys are involved. An `.nsz` carries what it
needs to be put back together, and every part is checked against the original
before the `.nsz` is deleted, so what you get is the file it was made from, bit
for bit.

**It needs room for the `.nsp`.** When there is room for both files, the `.nsz`
is left untouched until the `.nsp` has checked out. When there is only room for
the `.nsp`, the `.nsz` is used up as it is read, so the peak is the `.nsp` alone
— and if that unpack then fails, the `.nsz` has to be sent again.

Updates and DLC sent as `.nsz` need no step of their own: they are unpacked as
they install. See [Switch updates and DLC](library.md#switch-updates-and-dlc).

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
[Removing everything](library.md#removing-everything).
