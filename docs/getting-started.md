# Getting started with DeckyEmu

From a freshly installed plugin to a game running, in order, with nothing that
needs Desktop Mode or a keyboard.

The rest of these pages are reference — every setting, every option, a page per
subject. This one is the walkthrough: what to do first, second and third, and
what to do when one of them doesn't work.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Before you start

Open the Quick Access panel (the **…** button) and find **DeckyEmu**. The top
row tells you where you stand:

| It says | What it means |
| --- | --- |
| **Setup needed** | Nothing can run a game yet — start at step 2 |
| **Ready to use** | You have at least one core or emulator available |

Underneath, a button reading **Set up emulators** or **Settings** opens the
settings page, where everything you configure once lives. The panel itself stays
small on purpose — it's what you use while playing.

You don't need RetroArch, a core, or any emulator installed beforehand. You can
do all three from here.

## 1. Get a game onto the Deck

Already have your ROMs on the device or on an SD card? Skip this — the picker in
step 3 can reach them where they are.

Otherwise, press **Transfer to Deck** under **Add a game**. Your Deck starts a
small web server on your local network and shows you two ways in:

- **Scan the QR code** with your phone. It carries the full address, so you go
  straight to the upload page.
- **Type the short address** on a laptop or desktop, then enter the **six-digit
  code**. Desktops can't scan a QR code, and nobody is going to type a
  22-character token.

Pick your files on that device and they upload. You'll see each one arrive with
a progress bar, and a **Cancel** for anything you started by mistake.

Worth knowing:

- **You can close the dialog.** Transfers keep going, and a **Receiving files**
  row appears in the Quick Access panel with a **Show transfer** button.
- **The server stops itself** when you close the dialog, after 30 minutes idle,
  and when the plugin unloads.
- **BIOS files and keys go the same way.** They're recognised by name and
  offered to the emulator that needs them — see
  [step 2](#2-get-something-to-run-it). xemu's two files are the exception:
  they're told apart by size rather than name, so send those from their own row
  under **BIOS and firmware**.
- **Send whole games.** For a multi-disc or `.cue`/`.bin` game, send every file.
  The plugin won't file a game it can't account for in full.

Everything lands in `~/deckyemu/transfer`. Each file you receive gets an **Add**
button that drops straight into step 3 with the name and artwork already worked
out.

### Skipping the code next time

By default your address, token and six-digit code are all new every session, so
nothing outlives one transfer and a saved link is worthless the next day. Safe,
but it means typing the code every time.

Set **Trusted devices** to keep the address and it stays the same instead. Your
laptop or phone can bookmark the upload page and come straight back to it with
nothing to type — no address, no code. If you send games regularly, this is the
single biggest thing you can do to make it painless.

> **Understand the trade-off**, which is why it's a choice rather than the
> default. It changes what the link *is*. A bookmark stops being a one-off and
> becomes a standing key that works whenever the server is running. That's the
> right deal for your own laptop and the wrong one for a house guest who scanned
> the QR code once.

**Reset link** shows up while it's on and invalidates every bookmark at once.
It's all or nothing, because the link *is* the credential — there's no
per-device list to prune. It's refused while a transfer is running, so it can't
cut off an upload halfway.

## 2. Get something to run it

Three routes, and you can use all of them. Which one you want depends on the
game.

### RetroArch and cores — for most retro systems

1. Open **Settings → RetroArch**.
2. Press **Install RetroArch** if it isn't installed. It installs from Flathub
   for your user only, so nothing asks for a password.
3. Under **Install cores**, pick a system and pick a core.

Cores come from libretro's own buildbot, the same source RetroArch's Core
Downloader uses.

> **You don't have to guess which core you need.** Pick a ROM in step 3 that
> nothing installed can run and the panel offers you the cores that could, then
> carries on into adding the game once one is installed.

### Standalone emulators — for the bigger consoles

Open **Settings → Emulators** for the systems RetroArch doesn't cover: GameCube
and Wii, PlayStation 1 through 4, PSP, PS Vita, Switch, Wii U, 3DS and original
Xbox.

Press install on one and it's downloaded and set up for you — the system it
plays, the file types it accepts and its launch arguments all filled in.

Two things to expect:

- **Installing isn't always enough to play.** Some systems need BIOS files, keys
  or firmware that are yours to dump and that this plugin will never download.
  You're told which before the download starts, and a **BIOS and firmware**
  section appears under the emulator list showing what's still missing. Send
  those files the same way as a ROM and press **Install** on the row.
- **Controller bindings and fullscreen get written for you**, because several of
  these emulators bind a keyboard and start windowed as they ship.

Emulator not in the list? See
[emulator definitions](emulator-definitions.md).

### Native ports — for a handful of specific games

Open **Settings → Ports**. A few games have been rebuilt to run on the Deck
directly, with no emulator between them and the hardware, and the plugin ships
nine of them.

Each row names the game it plays, because that's the only thing that tells you
what to supply. You still need your own dump of that game, and the port builds
its own copy of the assets from it the first time it runs.

Install one the same way as an emulator. It then appears under **Run with** in
step 3 for a file it recognises — and only for that game's file, so there's
nothing to choose between. [More on ports](emulators.md#native-ports).

## 3. Add the game to Steam

Back in the Quick Access panel, under **Add a game**:

1. **Press Choose an existing file** and pick your ROM. The picker opens on your
   home folder the first time and wherever you last picked one after that. A
   file you just sent doesn't need this at all — it has its own row in the
   transfer dialog with a button to add it.
2. **Pick what runs it.** You're only offered cores and emulators that handle
   that file type, with the one you used last for it first. A toggle reveals
   everything installed, for when the right answer isn't in the short list.

   Most cores cover more than one system, so a **System** row appears when the
   one you picked does. It starts on what the file says it is, and it decides
   the shelf your game goes on and where its cover comes from. A core that
   covers one system has nothing to ask and gets no row.
3. **Check the name and the cover.** `Some Game (USA) [!].smc` becomes *Some
   Game*. If the cover is wrong, press **Wrong game? Choose the right one** —
   that sets the name as well as the cover — or **Choose the right game** if
   nothing was found at all. Worth a glance either way: title matching is fuzzy,
   and a wrong cover is easier to fix now than later.
4. **Press Add to Steam.** You get the shortcut, the artwork, and the game filed
   into a collection so it's findable rather than lost among every other
   non-Steam shortcut.

Your game is now in Steam and launches like anything else, with gamescope, Steam
Input and the overlay all behaving normally, because Steam is what starts it.

> **One game at a time.** You see the core, the name and the cover before
> anything reaches your library. There's no bulk import.

**Multi-disc game?** Pick any disc and the panel offers to add the whole set as
one game, so disc two is a menu away rather than a second shortcut. See
[multi-disc games](#multi-disc-games).

### PlayStation and Vita packages

A `.pkg` isn't a game yet. Pick one and the panel offers to unpack it first,
with a progress bar, then carries on from whatever came out. You never have to
know the product code or find the executable inside.

RPCS3 and Vita3K do that themselves. shadPS4 can't, so the first PS4 `.pkg` you
add downloads a small tool to do it — see
[Unpacking a PS4 package](emulators.md#unpacking-a-ps4-package).

## Everyday tasks

| You want to | Where |
| --- | --- |
| See what you've added | **Added games (n)** in the Quick Access panel |
| Start a game without leaving the panel | The play button on its row in **Added games** |
| Rename a game, or change its core, system or artwork | The pencil on its row, or the cog on the game's own page → **DeckyEmu → Edit** |
| Remove a game | The bin on its row, or **DeckyEmu → Remove** on its page — **this deletes the ROM** if the plugin filed it |
| Move a game to the right system | Edit it and change **System**. Saving moves it to that system's collection |
| Update an emulator, or go back to an earlier build | **Settings → Emulators**, the branch button on its row |
| Update RetroArch, or go back | **Settings → RetroArch → RetroArch version** |
| Change how games are grouped | **Settings → Collections** |
| Improve artwork | **Settings → Artwork**, which sets up a SteamGridDB key |
| Turn on achievements | **Settings → RetroArch → Achievements** |
| Stop RetroArch's on-screen chatter | **Settings → RetroArch → Launching** |
| Reach RetroArch's menu with a controller | **Settings → RetroArch → Launching** |
| Update the plugin | **Settings → Updates** |
| Find entries that drifted out of sync | **Settings → Library** |
| Change disc in a multi-disc game | **Select + Start** in game, if it hasn't switched by itself |

Editing a game keeps its Steam entry, so your playtime and its place in a
collection survive the change.

### Multi-disc games

Pick any disc of a set and the panel offers to **add all of them as one game**.
One entry in your library, every disc filed into one folder. The switch is on by
default — turn it off to add the single disc instead.

**You're asked first, however you got here.** Choose a disc — with **Add** in the
transfer dialog, or from the file browser — and a question names every disc it
found, in the order they'd go into the playlist: **One game**, **This disc
only**, or **Cancel** to add nothing.

Merging never just happens to you. The discs are recognised by their filenames
and nothing else can recognise them, so the guess gets put to you rather than
acted on. Whichever you answer, the panel then shows no row about discs at all —
it was asked and answered. To change your mind, pick the file again.

**A disc that turns up later joins the game you already added.** Send it and its
row in the transfer dialog reads *disc 2 of ‹game›*, offering **Add to game**
rather than **Add**. Pressing it asks once, then files the disc with the others,
extends the playlist and repoints the shortcut. Your game keeps its entry along
with its play time and controller layout. Answer *Its own entry* to add it
separately instead.

**What runs the game decides the rest:**

| Runs it | Shortcut starts | Changing disc |
| --- | --- | --- |
| A libretro core that reads playlists | the playlist | By itself. Otherwise **Select + Start** → **Disc Control** |
| DuckStation | the playlist | By itself. Otherwise **Select + Start** → **Change Disc** |
| Dolphin | the playlist | By itself, and only that — its own *Change Disc* opens a file browser no controller can drive |
| PCSX2 | the **first disc** | **Select + Start** → **Change Disc**, which finds disc 2 next to disc 1 |
| Xenia | the **first disc** | By itself — a split game asks for its next disc and gets it from the folder |

Every row is one library entry with its discs kept together. The last two can't
read a playlist, so their shortcut starts a disc — and having the rest in one
folder is exactly what lets them reach the others.

**Xbox 360 works like PlayStation 2**, by a different route: a game split across
discs asks the console for the next one and Xenia serves it from the folder, so
there's nothing to press.

> **Not every Xbox 360 set is split that way.** On some, disc 1 is the whole game
> and disc 2 holds extra content that's fairly its own entry. Turn the switch off
> for those.

PlayStation 3 never had a multi-disc game to begin with.

**Select + Start is the same combo everywhere it works**, including
[RetroArch's own menu](retroarch.md#getting-into-retroarchs-menu).

**About naming.** Discs are recognised by their filenames, because the disc
number isn't inside the file. Every emulation tool works this way.

| Recognised | Not recognised |
| --- | --- |
| `Game (Disc 1).cue` | `Game Disc 1.cue` — the marker has to be bracketed |
| `Game (Disc 1 of 2).chd` | `Game d1.cue` |
| `Game [Disk 1].cue` | `Game - Disc 1.cue` |
| `Game (CD 1).bin` | |
| `Game (Disc 1) (Rev 1).cue` | |

Anything else isn't spotted. **Pick another disc** under the switch lets you
choose the rest by hand — they have to be in the same folder. Everything except
the disc number has to match exactly, so `Game` and `Game 2` never get merged,
and a set missing a disc isn't offered at all.

**Three layouts the panel will warn you about:**

| What you picked | What it says |
| --- | --- |
| A disc when the others are in folders of their own — how a Redump download arrives | Send every disc's files together; they arrive in one folder, which is all it takes |
| A `.bin` whose `.cue` never arrived | Send the `.cue` too — without it the audio track is invisible and the game may not start |
| One `.bin` track of a disc | Pick the `.cue` that names it; tracks aren't discs, even though they're usually numbered like them |

## When something does not work

| Symptom | Likely cause |
| --- | --- |
| The panel says the backend is not responding | The plugin restarts when its files change, and calls in flight get dropped. Press **Try again** — it's expected right after an update |
| No cores are offered for a ROM | Nothing installed handles that file type. The panel offers the cores that do, and can install one for you |
| A core is installed but a ROM still matches nothing | The core may be missing its `.info` file, so nothing knows what it plays. Reinstall it from **Install cores** |
| An emulator says "installed, but not set up for adding games yet" | Something other than this plugin installed it, so nothing knows what it plays. Press the chain-link button on its row to register it |
| A game launches the emulator but no game | Its launch arguments are wrong. Edit them under **All registered emulators** |
| A game starts in a window | The emulator's fullscreen switch is wrong, or it uses a setting rather than a flag |
| An emulator closes immediately | For a hand-supplied AppImage, the execute bit is usually missing. Re-saving it in the editor repairs that |
| A game worked and stopped after an emulator update | Open that emulator's version dialog and pick an earlier build. Choosing one also holds it, so nothing moves it back |
| An emulator you held updated anyway | The hold was released, or it isn't the one you held — a held row says *held* under its name |
| A game won't boot and the system needs firmware | Check **BIOS and firmware**. A missing file looks exactly like a game failing |
| A bookmarked transfer link stopped working | Either **Trusted devices** is set to a new link each session, or **Reset link** was pressed |
| A ROM stayed in `transfer/` after adding | Something was unaccounted for: a disc the playlist names, or a different dump of the same name already filed |
| The cover or the name is wrong | **Wrong game? Choose the right one** on the add panel, or the pencil on an added game |
| A game is on the wrong system's shelf, with that system's cover | Its core covers several systems and you added it before the **System** row existed. Edit it, set **System**, and look the artwork up again |
| A game opens with the sticks moving a pointer and no buttons | Steam picked a layout for it, filing layouts by the game's *name* — so a title it recognises can arrive with a browser layout attached. Games added now get a gamepad layout pinned; for an older one, open its controller settings and pick **Gamepad With Joystick Trackpad** |
| A collection is left holding nothing | **Settings → Collections** tidies stale ones |
| A game you removed is still in Steam | **Settings → Library** finds entries that drifted apart and offers a fix for each |

Something wrong that isn't here? The plugin's log is the place to look:

```
~/homebrew/logs/deckyemu/
```

## Where your files are

Everything the plugin puts on your device that's yours to keep lives under
`~/deckyemu`, and uninstalling the plugin doesn't touch any of it.

| Folder | What's in it |
| --- | --- |
| `transfer/` | Your inbox. Everything sent from another device lands here |
| `roms/` | Your library. ROMs move to `roms/<system>/` when you add the game |
| `emulators/` | Emulators installed here that aren't Flatpaks |
| `firmware/` | BIOS files, keys and firmware you supplied |

> **The one rule worth knowing:** a ROM sent through Transfer is *moved* into
> your library when you add its game. A ROM you picked from anywhere else — an SD
> card, your home folder, an existing library — is left exactly where it is. That
> also decides what removing a game can delete: only ROMs the plugin filed
> itself. Full detail under [where a ROM ends up](transfers.md#where-a-rom-ends-up).
