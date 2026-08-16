# Artwork

Where cover art comes from, how a wrong match is avoided, and getting a
SteamGridDB key in without a keyboard.

Back to [the README](../README.md).

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
