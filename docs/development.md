# Developing DeckyEmu

How the plugin is put together, how to build it, and how to run it against a
real Deck. None of this is needed to use it -- [getting-started.md](getting-started.md)
is the walkthrough, and the rest of [docs/](.) is the reference.

## How the pieces fit

**Core selection drives artwork lookup.** Every core installed through
RetroArch's Core Updater ships an `.info` file whose `database` field is the exact
libretro playlist name — which is also the exact directory name on
`thumbnails.libretro.com`. Choosing a core therefore says precisely which
system's artwork to search. Cores installed without their `.info` fall back to a
built-in table of common ones.

**Name and artwork matching**, cheapest step first:

| Step | Cost | Catches |
| --- | --- | --- |
| Filename tried verbatim | one HEAD request | Correctly named No-Intro dumps |
| De-tagged title + region suffixes (`(USA)`, `(Europe)`, …) | a few HEAD requests | ROMs with no region tag, or the wrong one |
| Fuzzy match against the system's full boxart index | one directory listing, cached 30 days | Renamed files, article-order mismatches |

If every step misses you still get a cleaned-up name from the filename, and can
type whatever you like before adding.

**Launching goes through a generated script.** Steam stores a shortcut's
arguments as one `LaunchOptions` string and re-splits it at launch, which breaks
on the spaces, apostrophes and brackets that ROM filenames are full of. Instead
each game gets a small `exec`'d shell script with every argument properly quoted.
For the Flatpak build of RetroArch the script also passes `--filesystem=` for the
ROM's directory, so games on an SD card work without opening the sandbox wider
than needed.

## Building

```sh
pnpm install
pnpm run build
```

## Developing against a Deck

This plugin has no compiled backend, so the Docker + Decky CLI path from the
template is unnecessary — only the runtime files need to reach the Deck.

One-time setup on the Deck:

1. Enable SSH: *Settings → System → Developer Mode*, then enable SSH in the
   Developer menu. In desktop mode run `passwd` to set the `deck` password.
2. Enable frontend debugging: turn on **Allow Remote CEF Debugging** in Decky's
   settings, or `touch ~/.steam/steam/.cef-enable-remote-debugging` and restart
   Steam. Two ports answer and only one is usable from another machine: `8080` is
   bound to `127.0.0.1`, while **`8081` listens on all interfaces**. Both serve
   the same browser.

Then, from this repo:

```sh
DECK_HOST=steamdeck.local pnpm run dev     # build + push
```

`pnpm run dev` builds and pushes; `pnpm run deploy` pushes without rebuilding.
Both accept `DECK_HOST`, `DECK_USER`, `DECK_PORT` and `PLUGIN_DIR`.

Decky's file watcher (`LIVE_RELOAD`, on by default) reloads the plugin, so no
service restart is normally needed. When something gets stuck:

```sh
# Backend log. Decky starts a new one on every reload, so follow the newest.
ssh deck@steamdeck.local 'tail -f "$(ls -t ~/homebrew/logs/deckyemu/*.log | head -1)"'

# Force a full reload of decky and every plugin
ssh deck@steamdeck.local 'sudo systemctl restart plugin_loader'
```

For frontend logs and React state, open `chrome://inspect` in a desktop Chrome,
add `<deck-ip>:8081` under *Discover network targets*, and inspect
**SharedJSContext**. The deployed sourcemap points stack traces at the original
`.tsx`.

Log lines carry one of two prefixes: most say `[retroarch]`, from when this was
named after the thing it drove, and newer files say `[deckyemu]`. The rename was
never finished, so filter on both.

### Backend logic tests

The riskiest logic — name cleanup and artwork matching — needs no Deck:

```sh
python scripts/test_backend.py            # includes live thumbnail lookups
python scripts/test_backend.py --offline  # pure logic, no network
```

The live checks are the valuable ones: they assert that real ROM filenames
resolve to real cover art, including the awkward cases. Run them before
deploying — they catch far more than poking at the UI does.

## Layout

```
main.py                     Plugin class; thin async wrapper over py_modules
py_modules/
  ra_detect.py              Find RetroArch (flatpak/native/AppImage), build argv
  ra_cores.py               Enumerate cores, parse .info, look inside archives
  libretro_meta.py          Name cleanup + boxart matching
  emulators.py              User-registered standalone emulators
  platforms.py              Short system names (SNES, N64, ...)
  installer.py              Install RetroArch and cores from the buildbot
  sgdb.py                   Optional SteamGridDB lookups
  cheevos.py                RetroAchievements login and per-launch config
  launchers.py              Per-game launch scripts + the --appendconfig override
  store.py                  Settings + added-games registry
  net.py                    stdlib-only HTTP helpers
  fileserver.py             Upload server for other devices (token-scoped)
  sysenv.py                 Strip Steam's runtime libs from subprocesses
  releases.py               Find newer releases on GitHub (looks only)
  handoff.py                Serve one staged update to decky over loopback
  steam_shortcuts.py        Read Steam's shortcuts.vdf (the records outlive ours)
src/
  index.tsx                 Quick Access panel root (status, add, added games)
  ManagePage.tsx            Full-screen setup page; one route per tab
  AddGamePanel.tsx          The pick-ROM / pick-core / add flow
  AddedGamesPanel.tsx       Added games, with removal
  CoreInstallPanel.tsx      Browse and install cores by system
  EmulatorsPanel.tsx        Register standalone emulators
  EmulatorEditorModal.tsx   Add/edit an emulator, including its system
  ArtPickerModal.tsx        Correct a wrong artwork match
  GameEditorModal.tsx       Rename, change core, or re-pick artwork
  OrphanModal.tsx           Entries that drifted out of sync, and the fix for each
  TransferModal.tsx         QR code, arriving files, received files
  TransferStatusPanel.tsx   Transfer state in the panel, once the dialog is gone
  addFlow.ts                Shared ROM selection, picker and transfer
  romDraft.ts               Module-scope draft; survives Steam unmounting the panel
  timeout.ts                withTimeout + callWithRetry, for calls lost to a reload
  InstallRetroArchPanel.tsx First-run install, with streamed progress
  ArtworkPanel.tsx          Artwork source and the SteamGridDB key flow
  CollectionsPanel.tsx      Collection naming and the per-system split
  RetroArchPanel.tsx        RetroArch status, install/uninstall, cores, launching
  AchievementsPanel.tsx     RetroAchievements sign-in and per-launch settings
  LibraryPanel.tsx          Orphan check and removing every added game
  UpdatePanel.tsx           Installed build, its changelog, and installing a newer
  updater.ts                Hand an update to decky's installer (frontend half)
  version.ts                Build stamps compiled in by rollup; isStale()
  danger.ts                 Shared styling for destructive controls
  steam.ts                  SteamClient shortcut + artwork + collection calls
  backend.ts                Typed callables into main.py
scripts/
  deploy.sh                 Push to a Deck over ssh (no Docker, no rsync)
  test_backend.py           Backend tests with a stubbed decky module
  changelog.py              Release notes from commit subjects, grouped by prefix
  loaded_frontend.py        Ask Steam how old the bundle it is running is
```

## Steam's runtime breaks system binaries

Decky loads plugins inside Steam's environment, where `LD_LIBRARY_PATH` points at
the Steam Runtime, so any system executable resolves its libraries from there
instead of from the OS:

    flatpak: libcrypto.so.3: version `OPENSSL_3.4.0' not found

The binary dies in milliseconds with nothing resembling a normal error, which
makes it look like the command itself is wrong. It is not — the same command
works from a shell. `py_modules/sysenv.py` clears those variables for every
subprocess, and the generated launcher scripts `unset` them too, since Steam runs
those as well.

## Notes on the Steam APIs used

These are undocumented internal client APIs, so a few behaviours are worth
recording:

- `AddShortcut(name, exe, dir, launchOptions)` accepts four arguments but only
  reliably acts on the first two. The rest have to be re-applied with
  `SetShortcut*`, and those only stick once Steam has registered the app in
  `appStore` — hence the overview poll in `steam.ts`.
- `SetCustomArtworkForApp` wants bare base64, not a data URI; the image type is a
  separate argument. Asset types are `Capsule=0, Hero=1, Logo=2, Header=3,
  Icon=4, HeroBlur=5`; this plugin writes the first four.
- Collections are managed through the `collectionStore` global. Every call there
  is guarded, and failing to file a game into a collection never fails the add.
