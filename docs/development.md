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
`.tsx` — deployed only: a published release ships without one, so traces there
are minified. Deploy from this repo when you need to read them.

The backend log carries no prefix of its own — decky writes the timestamp and
level, and the message follows. Every public method on `Plugin` is wrapped, so a
failing one appears as `<method>() failed` with its traceback, which is the first
thing to grep for:

```sh
ssh deck@steamdeck.local 'grep -A 20 "() failed" "$(ls -t ~/homebrew/logs/deckyemu/*.log | head -1)"'
```

Frontend `console` calls are prefixed `[deckyemu]`, but nothing in Game Mode can
see them — that is what the diagnostic report under *Updates → Report a problem*
is for.

### Backend logic tests

The riskiest logic — name cleanup and artwork matching — needs no Deck:

```sh
python scripts/test_backend.py            # includes live thumbnail lookups
python scripts/test_backend.py --offline  # pure logic, no network
```

The live checks are the valuable ones: they assert that real ROM filenames
resolve to real cover art, including the awkward cases. Run them before
deploying — they catch far more than poking at the UI does.

New backend checks go in `scripts/tests/`, one file per subject, each runnable on
its own. The frontend suite is vitest (`pnpm run test:ui`) and covers the pure
logic and the Steam calls that delete things; there is no DOM environment, so it
does not cover rendering.

## Before you commit

```sh
pnpm run check
```

That is the whole gate: typecheck, bundle, both test suites, mypy, and the
release-build guard. CI runs the same things, so a green `check` is a green CI.

**Prefix the commit subject** with one of `feat:`, `fix:`, `perf:`, `internal:`,
`docs:`, `chore:` or `refactor:`. Release notes are generated from these subjects
by `scripts/changelog.py` and the prefix decides which heading the line appears
under, so the subject should read as the sentence a user would want:

    fix: a renamed game takes back its own shortcut instead of making a second

A scope or a `!` is accepted and ignored (`fix(store):`, `perf!:`). `SECTIONS` in
that script is the list of prefixes that means anything — a prefix that is not in
it reaches the notes with the prefix still attached, which is not a tidy fallback
but machine syntax in front of a reader.

There is no changelog file to update and no release notes to write: they come
from the log. CI is dispatched by hand (`gh workflow run ci.yml -f publish=true
-f bump=patch`), which is what bumps the version, tags it and publishes the zip
the plugin's own updater reads.

## Layout

Every backend module is listed. The frontend is grouped by role instead, because
`src/` is mostly one file per panel or modal and naming each of them here would
be a second copy of the directory listing. What is worth knowing about `src/` is
which files are *not* a panel, and why they sit where they do.

```
main.py                     The Plugin class decky calls into. Mostly thin
                            wrappers, but the add and update flows are here.
py_modules/                 Backend logic. Plain Python, stdlib only -- it runs
                            on decky's frozen interpreter and cannot grow deps.
  ra_detect.py              Find RetroArch (flatpak/native/AppImage), build argv
  ra_cores.py               Scan cores, parse .info, match extensions, peek in zips
  libretro_meta.py          Name cleanup and libretro thumbnail resolution
  sgdb.py                   SteamGridDB search, scoring, era filtering, key discovery
  platforms.py              libretro database -> short name and folder name;
                            and which system a file extension names, for the
                            cores that cover several
  installer.py              Install RetroArch (flatpak) and cores (buildbot)
  launchers.py              One .sh per game; the RetroArch override files
  cheevos.py                RetroAchievements login, and the per-launch config
  store.py                  settings / library / emulators / collections records
  romshelf.py               File a ROM under roms/<system>, and delete it again
  net.py                    stdlib-only HTTP, with a system-CA fallback
  sysenv.py                 Strip Steam's runtime; user_home(); user_dir();
                            where flatpak keeps applications and whether one is
                            deployed there or merely left behind
  fileserver.py             Upload from another device: QR, or short URL + code
  fileserver_page.py        The pages that server serves. Pure functions of what
                            they are handed; the server keeps state and sockets
  releases.py               Find newer releases on GitHub. Looks only.
  handoff.py                Serve one staged update to decky over loopback
  diagnostics.py            The redacted report behind Report a problem
  devreset.py               Development-only resets. Gated twice; absent from a
                            release build and refused by the backend in one.
  steam_shortcuts.py        Read Steam's shortcuts.vdf (records outlive ours)

  emulators.py              Registered standalone emulators: CRUD, launch argv
  emulator_catalog/         The one-click catalog: one module per emulator, each
                            exporting ENTRY. schema.py is the reference when
                            adding one; imported.py loads user-supplied
                            definitions, which are validated far more strictly.
  emu_install.py            Install a catalog emulator (flatpak, GitHub AppImage)
  emu_config.py             Recommended settings written into the emulator's own
                            config, and the rule for when that is allowed
  emu_firmware.py           Match a BIOS or key file by name and put it where the
                            emulator reads it

  sfo.py                    PARAM.SFO, the container PS3, PS4 and Vita share
  ps3_games.py              RPCS3: .pkg headers, unpacked games, .rap licences
  ps4_games.py              shadPS4: CNT packages, unpacked games
  vita_games.py             Vita3K: PKG type 2, installed titles, zRIF keys
  vita_release.py           Recognise a NoNpDrm .zip by the param.sfo inside it
  xbox_disc.py              Read XDVDFS enough to say whether a disc can boot

  plugin_base.py            What every mixin may assume about the composed
                            Plugin -- declarations only, no implementations.
  plugin_accounts.py        Signing in to somebody else's service
  plugin_audit.py           Drift between records, launchers, ROMs and shortcuts
  plugin_collections.py     What system a game is, what shelf that makes, and the
                            repairs when the naming changes
  plugin_devreset.py        Development-only resets. Gated twice; never in a release
  plugin_emulators.py       Installing and registering emulators
  plugin_firmware.py        Putting BIOS files and keys where they are read
  plugin_library.py         The record of what was added, and taking things out
                            of it. clear_library deletes the games
  plugin_packages.py        Games that arrive as a .pkg
  plugin_retroarch.py       Installing RetroArch and its cores. Reading what is
                            already installed stays in main.py, with the state
                            it keeps
  plugin_startup.py         One-time migrations of data already on the device.
                            The sequence they run in stays in main.py's _main
  plugin_transfers.py       Sending files to the Deck, and reading a report back
  plugin_updates.py         What build this is, and finding + staging newer ones
                            These twelve are mixins: decky exposes the methods it
                            finds on the plugin object, so the names must stay
                            on Plugin while the code lives somewhere findable.
                            None of them may be instantiated alone.

src/                        Frontend (React + TypeScript, bundled by rollup).
  index.tsx                 Quick Access panel root, and route registration
  ManagePage.tsx            The settings page. One route per tab -- Steam's
                            SidebarNavigation picks its tab from the URL.
  ErrorBoundary.tsx         One per surface. A throw during render is not
                            contained otherwise: it unmounts to whatever
                            boundary Steam happens to have, which is an empty
                            Game Mode screen.
  backend/                  Every callable() binding and its types, in seven
                            files by subject, named after the backend module
                            each one talks to. index.ts re-exports, so importers
                            still write `from "./backend"` and a declaration can
                            move between them without touching a caller.
  steam/                    All undocumented SteamClient / appStore /
                            collectionStore / Steam Input use, in five files by
                            subject.
                            Kept free of backend imports so the Node tests can
                            load it -- anything needing both halves lives one
                            level up (addGame.ts, collections.ts,
                            reuseShortcut.ts, setupShortcut.ts).
  *Panel.tsx                One per Quick Access row or settings tab
  *Modal.tsx                Transient flows. Preferred over a tab: a modal opens
                            over the panel, a tab costs a navigation out and back.
  <name>.ts + <name>.test.ts
                            Pure logic pulled out of a component so it can be
                            tested -- there is no DOM environment, deliberately.
                            capsuleFit/fitArtwork is the pattern: the geometry
                            is testable, the canvas next door is not.
  romDraft.ts               Module-scope draft state. Steam unmounts the panel
                            when a modal opens, so anything that must survive
                            that cannot live in component state.
  timeout.ts                withTimeout + callWithRetry, for calls lost when the
                            plugin reloads mid-flight
  version.ts                Build stamps compiled in by rollup; isStale()
  updater.ts                Hand an update to decky's own installer

scripts/
  harness.py                The stub decky and the scratch dir. Import it before
                            anything from py_modules.
  test_backend.py           The backend suite, and it runs scripts/tests/ too
  tests/                    One file per subject, each runnable on its own.
                            New backend tests go here.
  check_release_build.py    Assert a release bundle carries no development-only
                            code, and that a development one still does
  changelog.py              Release notes from commit subjects, grouped by prefix
  deploy.sh                 Push to a Deck over ssh (no Docker, no rsync)
  loaded_frontend.py        Ask Steam how old the bundle it is running is
  diagnose.py               Read a diagnostic report off a device over the network
```

`scripts/tests/test_docs_layout.py` checks that every path named above exists.
That block spent several releases pointing at `src/steam.ts` and `src/backend.ts`
after both became directories, which is worse than an omission: a gap is
something to look up, a wrong path is something to go looking for.

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
  `appStore` — hence the overview poll in `src/steam/shortcuts.ts`.
- `SetCustomArtworkForApp` wants bare base64, not a data URI; the image type is a
  separate argument. Asset types are `Capsule=0, Hero=1, Logo=2, Header=3,
  Icon=4, HeroBlur=5`; this plugin writes the first four.
- Collections are managed through the `collectionStore` global. Every call there
  is guarded, and failing to file a game into a collection never fails the add.
