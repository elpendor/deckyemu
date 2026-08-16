# Getting files onto the Deck

Sending ROMs, BIOS files and emulator definitions from another device, and
where each one ends up.

Back to [the README](../README.md).

**Contents** — [Sending files from another device](#sending-files-from-another-device) ·
[Where a ROM ends up](#where-a-rom-ends-up)

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
set up — see [Emulators this plugin does not ship](emulators.md#emulators-this-plugin-does-not-ship).

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
[Removing everything](library.md#removing-everything).
