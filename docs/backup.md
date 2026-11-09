# Backing up everything

How to put all of DeckyEmu on an SD card or USB drive, and bring it back after
a reset or on another Deck.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Backing up

Insert an SD card or USB drive, then press **Back up DeckyEmu** under **Backup
and restore** on the Library tab.

Everything starts ticked: ROMs, saves, emulators, BIOS and firmware, settings
and games, and cloud sign-ins. Untick what you don't want. Emulators you leave
out are downloaded again when you restore, and the sign-ins are login tokens
for your cloud storage, so keep a backup holding them somewhere safe.

The backup is one uncompressed file. On a drive that can't hold files over 4 GB
it's written in pieces (`.zip.001`, `.zip.002`, …), which belong together. You
don't need to format anything first.

Your Deck stays awake while it copies. When it's done, it says **You can remove
the drive** once the drive is safe to pull. A USB drive is unmounted for you; an
SD card stays in, since it may hold your Steam games.

A drive keeps one DeckyEmu backup. The old one is deleted once the new one is
complete, so a backup that fails or that you cancel leaves the old one in place.
If the drive has no room for both, you're asked before the old one goes. Nothing
else on the drive is touched.

## Restoring

Insert the drive with your backup, then press **Restore DeckyEmu** under
**Backup and restore** and pick the backup by its date.

It replaces DeckyEmu's settings and games on this Deck with the backup's. Then
it finishes the job itself: it installs RetroArch, its cores and your emulators
if they're missing, rebuilds the launchers, and adds your games back to Steam
with their artwork and collections. That part downloads, so it needs a network
and takes a while. When it's done it says **Everything is back**, or lists what
didn't work.

> **Note:** the drive has to be one your Deck can read. If it says it can't
> read the drive, the card or stick is unformatted or encrypted, for example a
> card a phone adopted as internal storage. Format it in **Settings → Storage**,
> or use another.
