# Artwork

Where your cover art comes from, how a wrong match gets avoided, and getting a
SteamGridDB key in without a keyboard.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Where the art comes from

You have two sources, and the setting defaults to **Auto** — SteamGridDB first,
falling back to libretro.

**libretro thumbnails** need no setup and no API key. They're scans of the
physical box, so their shape varies by console while Steam's capsule slot is
600x900 portrait. A scan far off that shape gets redrawn to fit rather than
stretched: whole, centred, at its true proportions, on a blurred copy of itself.
Art already made for the slot is passed through untouched, whichever source it
came from.

**SteamGridDB** is optional and gives you purpose-made Steam art — capsule, wide
header, hero and logo.

Until you save a key, Auto amounts to libretro every time. So the default costs
you nothing and starts using the better source the moment there is one.

### Why a wrong cover gets thrown away

SteamGridDB's search is fuzzy and confidently wrong. Search it for a platformer
and it'll happily hand you a sequel on a different console.

So candidates get scored on title and release era, and a weak winner is
discarded in favour of libretro's thumbnail. Below the threshold you get nothing
at all, because no artwork beats the wrong artwork.

The title it chose is shown next to the preview, so a bad match is visible
rather than silent.

## Getting a SteamGridDB key in

Typing a long API key on a touchscreen is miserable, so this is three steps and
none of them need the keyboard:

1. **Sign in to SteamGridDB.** Use the plugin's own sign-in button, not
   SteamGridDB's *Login via Steam* — Steam's in-app browser ignores that one.
   You'll end up on a blank page. That's the sign-in finishing, not an error.
2. **Open the API key page.** Hold on the key until Steam's context menu appears
   and choose Copy.
3. **Paste key and save.** Nothing else to press.

Two shortcuts sit next to those steps:

- **Import key from another plugin** appears when a key is already stored under
  `~/homebrew/settings`. Field names have to match exactly, so the wrong value
  is never imported behind your back.
- **Or type the key** is a plain field, saved when you tab away.

> **Note:** your key gets validated against SteamGridDB before it's saved, so a
> truncated paste is caught immediately. It's never sent back to the UI
> afterwards.
