# Adding an emulator DeckyEmu does not ship

DeckyEmu installs a fixed set of emulators. Anything outside that set can still
be *set up* for you — the system, file extensions, launch arguments and firmware
layout — by importing a small file that describes it. Nothing outside the set is
linked to or named as a download here; a definition is something you bring.

**Contents** — [Using one](#using-one) · [After importing](#after-importing) ·
[Writing one](#writing-one) · [Fields](#fields) ·
[Firmware and keys](#firmware-and-keys) · [Getting it right](#getting-it-right) ·
[What is refused](#what-is-refused) · [Updating and removing](#updating-and-removing) ·
[When it does not work](#when-it-does-not-work)

## Using one

1. Open **Transfer** in the Quick Access panel and send the `.deckyemu.json`
   from your phone or laptop. The suffix is what makes the panel offer
   **Import** instead of **Add**.
2. Press **Import**. A confirmation appears first, showing what the definition
   will install and every directory it may write to.
3. Read it, then confirm.
4. The emulator appears under **Emulators**, alongside the built-in ones.

The same thing is reachable from the other end: **Emulators → Import a
definition** lists every `.deckyemu.json` waiting in the transfer folder,
including one sent in an earlier session. That dialog also has its own
**Transfer to Deck** button, so a definition can be sent and imported without
leaving it.

Importing takes the file out of the transfer folder — the plugin keeps its own
copy, and a second one in the inbox would only be there to delete later. A
definition that is *refused* stays where it is: it is still the only copy on the
Deck, and the reasons it was refused are what tell its author what to change.

No Desktop Mode and no typing on the Deck: whatever device you sent the file
from does the typing.

## After importing

The row behaves like any other, with two differences. What it offers depends on
how the definition says the emulator is obtained:

| Button | When |
|---|---|
| **Download** | The definition names a source and the emulator is not installed |
| **Folder** | The definition is `byo` — pick the binary you already have |
| **Bin** | Uninstall what was installed, keeping the definition |
| **Eraser** | Remove the definition, uninstalling the emulator with it |

An imported entry is never marked *verified*. Nobody here has run it, and saying
so is the honest half of allowing imports at all.

## Writing one

A definition is JSON. A template, not a working setup for anything in
particular — the id, paths and arguments all depend on which emulator you have:

```json
{
  "format": 1,
  "id": "my-emulator",
  "name": "My Emulator",
  "summary": "Nintendo Switch.",
  "source": {
    "kind": "github",
    "repo": "owner/name",
    "asset": "^Thing-Linux-v[0-9][0-9A-Za-z.+-]*-steamdeck\\.AppImage$"
  },
  "root": [".config/my-emulator", ".local/share/my-emulator"],
  "platform": "Nintendo - Switch",
  "args": "-g {rom}",
  "fullscreen_args": "-f",
  "note": "Shown in the panel as a caveat.",
  "firmware": [
    {
      "name": "Console keys",
      "note": "Your own dump. Nothing decrypts without it.",
      "match": "(?i)^prod\\.keys$",
      "expects": "The file must be named exactly prod.keys.",
      "dest": ".local/share/my-emulator/keys"
    }
  ]
}
```

## Fields

Required: `id`, `name`, `summary`, `source`, `args`. Everything else is
optional. `py_modules/emulator_catalog/schema.py` is the authority; the importer
names every problem it finds, so the fastest way to get a definition right is to
import it and read what comes back.

| Field | |
|---|---|
| `id` | Lowercase letters, digits, `-` and `_`. Becomes a directory name. Do not change it after sharing one: it is what an installed emulator is recorded under. |
| `name` | What the panel shows. |
| `summary` | One line. Say which system it runs. |
| `source` | How the emulator is obtained — see below. |
| `args` | How to launch a game. `{rom}` is where the ROM path goes. |
| `fullscreen_args` | The switch that starts fullscreen. Omit if it has none. |
| `root` | The directory under your home the emulator owns, or a list. Everything the definition writes must sit inside one. A list because emulators following the XDG layout split them: settings under `~/.config/<name>`, saves and keys under `~/.local/share/<name>`. |
| `platform` **or** `databases` | What it plays. `databases` takes libretro system names, e.g. `["Sony - PlayStation"]`, and buys extensions, boxart and collection grouping at once. `platform` is for systems libretro has no database for. One or the other, never both. |
| `firmware` | Files you must supply — see [below](#firmware-and-keys). |
| `note` | A caveat shown in the panel. |
| `setup` | Configuration written once, just after installing — controller bindings, or skipping a first-run wizard. Every path it writes must sit inside a `root`. The formats it understands are in `py_modules/emu_config.py`; this is the most involved field and the one most worth checking against a real install, since it edits a file the emulator owns. |
| `installed_args` | How to start a title the emulator has already installed, when a file path will not do it. `{title}` is the title id. |
| `command`, `env` | The binary to run inside a flatpak when it is not the one the manifest names, and any environment it needs. |
| `aliases` | Extra names to match when suggesting arguments for a hand-registered binary. |
| `workarounds` | Corrections for bugs in the emulator itself, each one a switch. Unlike everything above, a workaround is *temporary*: it must name the upstream issue or pull request that will retire it, say what it costs in the user's terms, and it is off by default. Ordinary configuration that is simply how this emulator has to run is not a workaround — it belongs in `env`, `layout` or `setup`. The fields are in `py_modules/emulator_catalog/schema.py`; note that an imported definition may not use one that patches the emulator's files. |

### `source`

```jsonc
{ "kind": "byo" }                                  // you supply it and point at it
{ "kind": "flatpak", "id": "org.example.App" }     // installed from Flathub
{ "kind": "github", "repo": "owner/name",          // taken from the latest release
  "asset": "^…\\.AppImage$" }
```

Add `"host": "git.example.com"` to a `github` source for a project that left
GitHub and self-hosts the same releases API — its old repository answers HTTP
451 there, so no asset pattern reaches it. `host` is a host name, not a URL.

## Firmware and keys

`firmware` is a list of files the emulator needs and this plugin will never
supply. Each entry becomes a row under **BIOS & firmware** saying whether it is
present, and files you send over **Transfer** are matched to it by name.

| Key | |
|---|---|
| `name` | Required. What the row is called. |
| `note` | What it is and whether a game runs without it. |
| `match` | A regex the sent filename must match. |
| `expects` | What to tell someone whose file was rejected. Required whenever `match` is set — otherwise the only explanation is the pattern itself. |
| `optional` | The emulator runs without it, so its absence is not a warning. |
| `dest` | Where to copy it, relative to your home. Must sit inside a `root`. |
| `manual` | Instead of copying: what to tell the user to do themselves. |
| `detect` | `{"path": "…", "label": "installed"}` — a folder whose being non-empty means it is there. Use with `manual`. |
| `sizes`, `lower_ext` | Byte sizes a valid file may have; lowercase the extension before matching. |

An imported definition may use **`dest`** or **`manual`**, and not the routes
that drive an emulator's own installer. Some firmware cannot be copied into
place at all — a few hundred encrypted files registered into a content cache
under hashed names is not a file copy — and for those, `manual` plus `detect` is
the honest shape: report whether it is there and say where the menu is, rather
than claim to install it. A requirement that is reported but not installable is
worth more than silence, because its absence otherwise looks like a game simply
failing to boot.

## Getting it right

**`asset`** — anchor it. Releases carry `aarch64` builds beside `x86_64` ones
and `.zsync` delta files beside the real ones. The wrong pick installs happily
and dies at exec time with nothing naming the cause. Match the whole filename
with `^` and `$`, and leave room for the version to move.

**`args`** — the launch arguments and the fullscreen switch interact, so test
them together. The failure worth knowing about, seen on more than one emulator:
`<emu> -f <rom>` opens the game list instead of the game, because the flag
swallows the positional path, while `<emu> -f -g <rom>` works. Several emulators
ignore arguments they do not understand without complaint, so a wrong recipe
looks like nothing happening rather than like an error.

**`root` and `dest`** — run the emulator once and look at what it creates under
`~/.config`, `~/.local/share` and `~/.cache`. Do not take paths from its source:
what a program is written to do and what the build you have actually writes come
apart often enough that it is not worth the guess. The **BIOS & firmware**
section reports the destination it would use for each file, so a wrong one shows
itself rather than failing quietly.

## What is refused

A definition is not data DeckyEmu reads — it is a list of actions DeckyEmu
performs, with your user's privileges. One you import was written by whoever
gave it to you and reviewed by nobody here.

**It may install the emulator it describes.** Refusing that would be friction
rather than safety: the alternative is downloading a build by hand and
re-pointing at it on every update, which does not change who you trusted.

What is refused is everything that is not "install the emulator you asked for":

- **Deleting.** No `removes`, no `data`. Nothing about installing an emulator
  requires the power to delete directory trees.
- **A second binary.** No `helper` — that is arbitrary code beside the emulator,
  which the definition did not describe.
- **Editing the emulator.** A definition may carry *workarounds* — switchable
  corrections for bugs in the emulator, each naming the upstream fix that will
  retire it — but not one that patches the emulator's own files. That is the
  same power as `helper`, reached by rewriting a binary rather than fetching
  one.
- **Downloading firmware.** No `fetch`. Firmware is your own dump; an entry
  offering to fetch one is offering something it should not have.
- **Writing outside its `root`.** Not merely "somewhere under your home" — your
  home also holds Steam's data and your ssh keys.
- **Replacing a built-in emulator.** If the `id` matches one DeckyEmu ships, the
  built-in entry wins and the import is refused.

These bound what a definition can *reach*. They cannot tell you whether its
author meant well. **Read the file before importing it** — it is a few lines of
plain text.

## Updating and removing

Importing a definition whose `id` is already in use asks before replacing it,
because overwriting one you may not be able to obtain again is not recoverable.

The **eraser** button removes a definition and uninstalls whatever it installed.
Both, and in that order: once the definition is gone there is no row left to
uninstall from, and an emulator downloaded through it would sit on disk with
nothing able to reach it. Games already added to Steam keep their launcher
scripts, and re-importing brings everything back.

Definitions live in the plugin's settings directory, one file per emulator, and
survive a reset that clears emulators.

## When it does not work

| Symptom | Likely cause |
|---|---|
| No **Import** button on the sent file | The name must end `.deckyemu.json` |
| The import is refused with a list | Each line names one rule; the importer says which field and why |
| The emulator never appears | The definition failed to load — the Emulators tab lists refusals |
| No ROM matches it | `databases` or `platform` names a system with no known extensions |
| A game opens the emulator but no game | `args` — see *Getting it right* |
| It starts in a window | `fullscreen_args` is wrong, or the emulator uses a setting instead of a flag |
| Installed but dies immediately | The `asset` pattern took the wrong architecture |
| Firmware row says missing when it is not | `detect.path` or `dest` does not match where the emulator really keeps it |
