# Developing DeckyEmu

How DeckyEmu is put together, how to build it, and how to run it against a
real Deck. You need none of this to *use* it —
[getting started](getting-started.md) is the walkthrough, and the rest of these
pages are the reference.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## How the pieces fit

**DeckyEmu is a service, not a plugin.** A systemd user unit runs `launcher.py`,
which starts the installed version's `service.py` on SteamOS's own Python. The
service runs the backend (`main.py` and `py_modules/`), and keeps the panel
inside Steam's UI over Steam's remote-debugging port:

- `dist/preload.js` is registered to run before Steam's own UI code. It rewrites
  three of Steam's webpack module factories as they load -- the Quick Access tab
  list, the Game Mode route list and the game context menu -- each anchored on
  string literals and localization keys, never on minified names. Any doubt
  leaves Steam's code as it was.
- `dist/deckyemu.js` is the panel. It is evaluated once our Quick Access tab has
  rendered, and builds every control from Steam's own components, found in
  Steam's build by anchors (`src/steamui/`).
- The panel calls the backend through a `Runtime.addBinding` function on that
  same debugger session, so there is no port or token for anything else to find.

Updates install beside the running version and switch over only once whole;
`launcher.py` goes back to the previous version if a new one never reports
healthy. The library tile runs `rescue.sh`, which opens the rescue page in
Steam's browser even when nothing else of DeckyEmu works.

**Core selection drives artwork lookup.** Every core installed through
RetroArch's Core Updater ships an `.info` file whose `database` field is the
exact libretro playlist name — which is also the exact directory name on
`thumbnails.libretro.com`. So choosing a core says precisely which system's
artwork to search. Cores installed without their `.info` fall back to a built-in
table of common ones.

**Name and artwork matching** goes cheapest step first:

| Step | Cost | Catches |
| --- | --- | --- |
| Filename tried verbatim | one HEAD request | Correctly named No-Intro dumps |
| De-tagged title + region suffixes (`(USA)`, `(Europe)`, …) | a few HEAD requests | ROMs with no region tag, or the wrong one |
| Fuzzy match against the system's full boxart index | one directory listing, cached 30 days | Renamed files, article-order mismatches |

Miss every step and you still get a cleaned-up name from the filename, and you
can type whatever you like before adding.

**Launching goes through a generated script.** Steam stores a shortcut's
arguments as one `LaunchOptions` string and re-splits it at launch, which breaks
on the spaces, apostrophes and brackets that ROM filenames are full of. So each
game gets a small `exec`'d shell script with every argument properly quoted.

For the Flatpak build of RetroArch the script also passes `--filesystem=` for
the ROM's directory, so games on an SD card work without opening the sandbox
wider than needed.

## Building

```sh
pnpm install
pnpm run build
```

## Developing against a Deck

Only the runtime files have to reach the Deck, and nothing needs root.

Enable SSH once: *Settings → System → Developer Mode*, then enable SSH in the
Developer menu, and in desktop mode run `passwd` to set the `deck` password. The
service turns on Steam's debugging port itself (it creates
`~/.steam/steam/.cef-enable-remote-debugging`); that takes effect the next time
Steam starts.

> **Two ports answer and only one is usable from another machine.** `8080` is
> bound to `127.0.0.1`, while **`8081` listens on all interfaces**. Both serve
> the same browser.

Then, from this repo:

```sh
DECK_HOST=steamdeck.local pnpm run dev     # build + install + restart
```

`pnpm run dev` builds and deploys; `pnpm run deploy` deploys without
rebuilding. Both accept `DECK_HOST`, `DECK_USER` and `DECK_PORT`. Each deploy is
a new version under `~/.local/share/deckyemu/app/`, installed with
`service.py --install`; the service restarts into it and the panel in Steam is
replaced where it stands, without restarting Steam.

```sh
# The service's log, as systemd sees it
ssh deck@steamdeck.local 'journalctl --user -u deckyemu -f'

# The backend log the diagnostic report reads: one file per start
ssh deck@steamdeck.local 'tail -f "$(ls -t ~/.local/share/deckyemu/logs/*.log | head -1)"'

# Restart the service
ssh deck@steamdeck.local 'systemctl --user restart deckyemu'
```

For frontend logs and React state, open `chrome://inspect` in a desktop Chrome,
add `<deck-ip>:8081` under *Discover network targets*, and inspect
**SharedJSContext**.

The deployed sourcemap points stack traces at the original `.tsx` — deployed
only. A published release ships without one, so traces there are minified.
Deploy from this repo when you need to read them.

Each backend log line starts with the timestamp and level, and the message
follows. Every public method on `Plugin` is wrapped, so a
failing one appears as `<method>() failed` with its traceback. That's the first
thing to grep for:

```sh
ssh deck@steamdeck.local 'grep -A 20 "() failed" "$(ls -t ~/.local/share/deckyemu/logs/*.log | head -1)"'
```

Frontend `console` calls are prefixed `[deckyemu]`, but nothing in Game Mode can
see them. That's what the diagnostic report under *Diagnostics → Report a
problem* is for.

### Backend logic tests

The riskiest logic — name cleanup and artwork matching — needs no Deck:

```sh
python scripts/test_backend.py            # includes live thumbnail lookups
python scripts/test_backend.py --offline  # pure logic, no network
```

The live checks are the valuable ones. They assert that real ROM filenames
resolve to real cover art, including the awkward cases. Run them before
deploying — they catch far more than poking at the UI does.

New backend checks go in `scripts/tests/`, one file per subject, each runnable
on its own. The frontend suite is vitest (`pnpm run test:ui`) and covers the
pure logic and the Steam calls that delete things. There's no DOM environment,
so it doesn't cover rendering.

## Before you commit

```sh
pnpm run check
```

That's the whole gate: typecheck, lint, bundle, both test suites, mypy, and the
release-build guard. CI runs the same things, so a green `check` is a green CI.

One check is deliberately **not** in there, because it makes network calls and
downloads a whole emulator:

```sh
python scripts/check_workarounds.py                     # everything
python scripts/check_workarounds.py vita3k              # one entry
python scripts/check_workarounds.py vita3k --build 3829 # against one build
```

It asks whether each fix is still needed — reading the upstream issue it names,
and re-running the patch detection against a real build. `--build` names a
release tag instead of taking the newest, which answers "would the patch fit
that one" without installing it.

When upstream merges, it asks for a `fixed_in`. Which one depends on how much
the merge actually retired:

- `apply.patch.fixed_in` when only the binary patch is now unnecessary and the
  rest of the workaround still is.
- The workaround's own `fixed_in` when the whole thing is.

A patch with a ceiling isn't checked against newer builds — the bytes it looks
for are supposed to be gone.

Run it when you want to know; there's no schedule.
`.github/workflows/workarounds.yml` is the same check as a manual dispatch, with
the same two arguments, for when you'd rather not download an emulator over your
own connection.

Two things about reading its output. It needs `squashfs-tools` to unpack an
AppImage. And it distinguishes **needs a decision** from **could not be
checked** — an unauthenticated run hits GitHub's rate limit within a handful of
calls, and that's not a finding about a fix. Both fail the run, because a check
that didn't happen has no result:

```sh
GITHUB_TOKEN=$(gh auth token) python scripts/check_workarounds.py
```

It reports rather than editing the catalog. Choosing the first build that
carries a fix is a judgement call, and naming one too low tells people to switch
off a fix they still need.

The lint step is ESLint, and `react-hooks/exhaustive-deps` is why it's there: a
wrong dependency array is a stale closure, which you find by holding a Deck
rather than by reading a diff. `eslint.config.js` says which rules are off and
why. Warnings don't fail the gate; errors do.

**Prefix your commit subject** with one of `feat:`, `fix:`, `perf:`,
`internal:`, `docs:`, `chore:` or `refactor:`. Release notes are generated from
these subjects by `scripts/changelog.py`, and the prefix decides which heading
the line appears under — so the subject should read as the sentence a user would
want:

    fix: a renamed game takes back its own shortcut instead of making a second

A scope or a `!` is accepted and ignored (`fix(store):`, `perf!:`).

> **`SECTIONS` in that script is the list of prefixes that means anything.** A
> prefix that isn't in it reaches the notes with the prefix still attached, which
> isn't a tidy fallback but machine syntax in front of a reader.

There's no changelog file to update and no release notes to write — they come
from the log. CI is dispatched by hand (`gh workflow run ci.yml -f publish=true
-f bump=patch`), which is what bumps the version, tags it and publishes the zip
DeckyEmu's own updater reads.

## Layout

Every backend module is listed. The frontend is grouped by role instead, because
`src/` is mostly one file per panel or modal and naming each of them here would
be a second copy of the directory listing. What is worth knowing about `src/` is
which files are *not* a panel, and why they sit where they do.

```
main.py                     The Plugin class the service calls into. Mostly
                            thin wrappers, but the add and update flows are here.
py_modules/                 Backend logic. Plain Python, no third-party
                            dependencies -- it runs on SteamOS's own Python.
  appenv.py                 Where DeckyEmu lives on disk, its log, and the
                            events it sends the frontend
  ra_detect.py              Find RetroArch (flatpak/native/AppImage), build argv
  ra_cores.py               Scan cores, parse .info, match extensions, peek in zips
  unpack.py                 Extract a zip that arrived in the transfer folder
  libretro_meta.py          Name cleanup and libretro thumbnail resolution
  sgdb.py                   SteamGridDB search, scoring, era filtering
  vendored_difflib.py       CPython 3.11's difflib, pinned so name scores do not
                            move with the Python; the two above use it
  platforms.py              libretro database -> short name and folder name;
                            and which system a file extension names, for the
                            cores that cover several
  installer.py              Install RetroArch (flatpak) and cores (buildbot)
  launchers.py              One .sh per game; the RetroArch override files
  cheevos.py                RetroAchievements login, and the per-launch config
  store.py                  settings / library / emulators / collections records
  gameicon.py               A game's icon on disk: the one SteamGridDB had, or
                            the one that ships
  romshelf.py               File a ROM under roms/<system>, and delete it again
  rompatch.py               A game's ROM hacks: the list, our copies of them,
                            and the files RetroArch reads beside the ROM
  switch_content.py         What a Switch .nsp is -- game, update or DLC -- and
                            which game it is for, read without keys
  gamecontent.py            A Switch game's updates and DLC: our copies, and the
                            per-game lists Ryujinx reads at boot
  switch_nsz.py             Unpack a Switch .nsz into the .nsp Ryujinx can read,
                            checked against the original, in the room there is
  discset.py                Recognise a multi-disc game from the discs beside it,
                            and write the .m3u that makes it one game
  savedata.py               Where each emulator keeps its saves, and gathering
                            them into one archive to take off the device
  cloudsave.py              Talking to rclone: our own config file, and making
                            a remote from a form. Holds no credential itself
  cloudsync.py              The half that copies. Loose files per emulator, so a
                            second copy sends only what changed; `copy` and
                            never `sync`, so nothing on the remote is deleted.
                            Also the records that decide "did somebody else
                            write since we did", which is what a launch reads
  audit.py                  Append-only log of everything that removed or
                            replaced data, beside the settings. Trimmed by
                            halving, never rotated away, because the line you
                            want is the oldest one
  net.py                    stdlib-only HTTP, with a system-CA fallback
  jsonstore.py              Read and write DeckyEmu's own JSON, atomically
  procout.py                Read what a subprocess says while it is still saying it
  flatpak_progress.py       flatpak's install plan and percentages, read into
                            one named, size-weighted progress bar
  hardware.py               Which machine this is, and whether we claim to work on it
  sysenv.py                 Strip Steam's runtime; user_home(); user_dir();
                            where flatpak keeps applications and whether one is
                            deployed there or merely left behind
  fileserver.py             Upload from another device: QR, or short URL + code
  fileserver_page.py        The pages that server serves. Pure functions of what
                            they are handed; the server keeps state and sockets
  releases.py               Find newer releases on GitHub. Looks only.
  selfupdate.py             Install a release beside the running one; switch,
                            commit once healthy, roll back
  migrate.py                Carry an older install's state over, once
  claim.py                  The lock on the state and its format stamp; why
                            the backend stays off when either says no
  cdp.py                    Steam's remote-debugging port: list pages, talk to one
  injector.py               Keep the preload, the panel and the call channel in
                            Steam's UI across its restarts
  hostcalls.py              The service's own methods, called as `host.*`
  rescue.py                 The page the library tile opens: status and repairs
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
  ra_firmware.py            RetroArch's BIOS rows, read off each core's .info
  bios_dat.py               Recognise a BIOS by checksum, from libretro's list
  httpshim.py               http.server, or a stand-in built on socket and
                            threading where a Python lacks it
  findfiles.py              Listing files without glob
  emu_patch.py              Correct a bug inside an emulator's own binary, when
                            nothing else reaches it
  steam_layouts.py          The Steam Input layout an emulator needs, derived
                            from one Steam ships

  sfo.py                    PARAM.SFO, the container PS3, PS4 and Vita share
  ps3_games.py              RPCS3: .pkg headers, unpacked games, .rap licences
  ps4_games.py              shadPS4: CNT packages, unpacked games
  vita_games.py             Vita3K: PKG type 2, installed titles, zRIF keys
  vita_release.py           Recognise a NoNpDrm .zip by the param.sfo inside it
  xbox_disc.py              Read XDVDFS enough to say whether a disc can boot
  xbox360_content.py        Name an Xbox 360 file by its header, when it has no
                            name to go on
  model3_games.py           Name an arcade ROM set, for the files named by code

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
  plugin_probe.py           What a picked file is: what could run it, what to
                            call it, and its artwork. main.py keeps the add
                            flow it feeds
  plugin_retroarch.py       Installing RetroArch and its cores. Reading what is
                            already installed stays in main.py, with the state
                            it keeps
  plugin_startup.py         One-time migrations of data already on the device.
                            The sequence they run in stays in main.py's _main
  plugin_transfers.py       Sending files to the Deck, and reading a report back
  plugin_updates.py         What build this is, and finding + installing newer
                            ones. These twelve are mixins: the service exposes
                            the methods it finds on the Plugin object, so the
                            names must stay on Plugin while the code lives
                            somewhere findable.
                            None of them may be instantiated alone.

src/                        Frontend (React + TypeScript, bundled by rollup).
  main.tsx                  The bundle's entry: connects to the service and
                            fills the preload's tab, page and menu placeholders
  index.tsx                 Quick Access panel root; start() returns what
                            main.tsx registers
  preload/                  The script Steam runs before its own UI code, and
                            bridge.ts, the contract it shares with the bundle
  steamui/                  Steam's own controls, navigation and modals, found in
                            its build at runtime, each with a plain stand-in
  host/                     The channel to the service, toasts and the file
                            picker
  rescueTile.ts             The library tile that opens the rescue page
  ManagePage.tsx            The settings page. One route per tab -- Steam's
                            SidebarNavigation picks its tab from the URL.
  ErrorBoundary.tsx         One per surface. A throw during render is not
                            contained otherwise: it unmounts to whatever
                            boundary Steam happens to have, which is an empty
                            Game Mode screen.
  backend/                  Every callable() binding and its types, split by
                            subject and named after the backend module
                            each one talks to. index.ts re-exports, so importers
                            still write `from "./backend"` and a declaration can
                            move between them without touching a caller.
  steam/                    All undocumented SteamClient / appStore /
                            collectionStore / Steam Input use, split by subject.
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
  HandoffCode.tsx           The QR code, the short address and the six digits,
                            drawn once for the four dialogs that hand an address
                            to a phone or a PC. dialogStyle.ts, danger.ts and
                            iconButton.ts are the same idea for measurements
                            those dialogs otherwise restate.
  romDraft.ts               Module-scope draft state. Steam unmounts the panel
                            when a modal opens, so anything that must survive
                            that cannot live in component state.
  timeout.ts                withTimeout + callWithRetry, for calls lost when the
                            service restarts mid-flight
  version.ts                Build stamps compiled in by rollup; isStale()

service.py                  The service: backend, injector and rescue page.
                            `--install` makes its folder the running version.
launcher.py                 What the unit runs. Starts `current`, and goes back
                            to `previous` when a new version keeps failing.
rescue.sh                   What the library tile runs
assets/                     Files that ship with DeckyEmu as they are. Only
                            the game icon so far -- Steam records the path to a
                            shortcut's icon, so it has to be a real file.

scripts/
  harness.py                Points appenv at a scratch dir. Import it before
                            anything from py_modules.
  test_backend.py           The backend suite, and it runs scripts/tests/ too
  tests/                    One file per subject, each runnable on its own.
                            New backend tests go here.
  check_release_build.py    Assert a release bundle carries no development-only
                            code, and that a development one still does
  changelog.py              Release notes from commit subjects, grouped by prefix
  deploy.sh                 Install on a Deck over ssh as a new version
  diagnose.py               Read a diagnostic report off a device over the network
```

`scripts/tests/test_docs_layout.py` checks that every path named above exists.
That block spent several releases pointing at `src/steam.ts` and `src/backend.ts`
after both became directories, which is worse than an omission: a gap is
something to look up, a wrong path is something to go looking for.

## Steam's runtime breaks system binaries

Steam runs the game launchers inside its own environment, where
`LD_LIBRARY_PATH` points at the Steam Runtime. So any system executable they
start resolves its libraries from there instead of from the OS:

    flatpak: libcrypto.so.3: version `OPENSSL_3.4.0' not found

The binary dies in milliseconds with nothing resembling a normal error, which
makes it look like the command itself is wrong. It isn't — the same command
works from a shell.

The generated launcher scripts `unset` those variables, and
`py_modules/sysenv.py` clears them for every subprocess the backend starts, in
case the service is ever started from inside that environment.

## Notes on the Steam APIs used

These are undocumented internal client APIs, so a few behaviours are worth
recording:

- `AddShortcut(name, exe, dir, launchOptions)` accepts four arguments but only
  reliably acts on the first two. Re-apply the rest with `SetShortcut*`, and
  those only stick once Steam has registered the app in `appStore` — hence the
  overview poll in `src/steam/shortcuts.ts`.
- `SetCustomArtworkForApp` wants bare base64, not a data URI; the image type is
  a separate argument. Asset types are `Capsule=0, Hero=1, Logo=2, Header=3,
  Icon=4, HeroBlur=5`; DeckyEmu writes the first four.
- Collections are managed through the `collectionStore` global. Every call there
  is guarded, and failing to file a game into a collection never fails the add.
- Steam's `TextField` lays its label beside a fixed-width input unless given
  `layout: "below"`. In the 300px Quick Access panel that input ran 120px past
  the edge, and focusing it scrolled the whole tab sideways, so the wrapper in
  `src/steamui/components.tsx` defaults to `below`.
- A Quick Access tab's title is rendered beside its focusable panel, not inside
  it, and the panel's Up handler always consumes the move. The `title focus`
  patch in `src/preload/index.ts` lets Up through for our tab, so the cog is
  reachable by pad; the title only accepts focus from inside the tab, so
  entering the tab still lands on the panel.
