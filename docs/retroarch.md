# RetroArch

Installing RetroArch and its cores, the launch behaviour this plugin sets, the
menu combo, and achievements.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Installing RetroArch and cores

You don't need either of them set up beforehand.

**RetroArch** installs from Flathub for your user only
(`flatpak install --user`), so nothing asks for a password. You get a progress
bar rather than one long wait.

**Cores** come from the libretro buildbot — the same place RetroArch's own Core
Downloader uses.

The catalog knows about every core that exists, not just the ones you have
installed. That's what makes this work: pick a ROM nothing installed can run and
the plugin offers you the cores that could, then carries straight on into adding
the game.

> **Note:** about a third of what the buildbot publishes isn't a game system —
> media players, image viewers, tech demos. You're only offered cores that
> declare both a `database` and `supported_extensions` and aren't in an excluded
> category.

### Uninstalling RetroArch

You're only offered this when the plugin can honestly do it — a user-scope
flatpak, removed with `flatpak uninstall --user`.

You won't get the option for:

- **A system-wide flatpak**, which is root-owned. That's what you get if you
  installed it from Discover or from another setup tool.
- **A native package**, which would mean unlocking SteamOS's read-only
  filesystem.
- **An AppImage**, which is a file the plugin never installed.

Each of those tells you the reason rather than showing you a dead button.

Your configuration and saves are kept unless you tick the separate toggle, and
games you've already added work again the moment you reinstall RetroArch.

## Fullscreen and RetroArch's on-screen chatter

**Launch custom emulators fullscreen** applies each emulator's own fullscreen
switch. There's no flag they all share — Dolphin has none at all, PCSX2 uses
`-fullscreen`, RPCS3 uses `--fullscreen` — so it's stored per emulator and
suggested for the ones we recognise.

It stays an editable field because several emulators ignore arguments they don't
know without saying anything, which would make a wrong guess invisible to you.

RetroArch announces itself when content loads: a load animation, then notices
about controller autoconfig, refresh rate and config overrides. **RetroArch
notifications** shuts that up for games launched from this plugin.

| Mode | What you get |
| --- | --- |
| `Hide the startup banner` | No load animation, and none of the notices after it |
| `Hide all on-screen messages` (default) | Also sets `video_font_enable = false`, so save-state confirmations and errors go quiet too |
| `Keep RetroArch's notifications` | RetroArch behaves exactly like it does on its own |

These get passed per launch rather than written into your own `retroarch.cfg`,
and the override turns RetroArch's save-on-exit off so they can't settle in as
permanent defaults.

> **Trade-off:** changes you make from RetroArch's own menu during a game
> launched from here aren't saved either. Use *Save Current Configuration* if
> you want them kept.

Launch behaviour is baked into each game's launcher script, so changing this
rewrites the launchers of games you've already added.

## Getting into RetroArch's menu

**RetroArch menu shortcut** binds a controller combination that opens
RetroArch's menu mid-game. It defaults to **Select + Start**.

It's on by default because otherwise you usually have no way in. RetroArch sets
no combo of its own, and the Guide button its autoconfig binds never reaches it
on a Deck — Steam claims that button first. That leaves `F1` on a keyboard you
don't have.

> **This is for libretro cores only.** Games launched through a custom emulator
> aren't affected. PCSX2, Dolphin and the rest each have their own menu binding,
> and nothing here can set it.

RetroArch takes a fixed list rather than a free-form binding, so your choices
are exactly what it supports:

| Setting | Also available |
| --- | --- |
| `Select + Start` (default) | `L1 + R1 + Select + Start`, `L3 + R3`, `L1 + R1`, `L2 + R2`, `L3 + R` |
| `D-pad Down + Select` | `D-pad Down + Y + L1 + R1`, `Hold Start`, `Hold Select` |
| `Off` | Writes nothing, so whatever's in your `retroarch.cfg` applies |

Pick one your games don't use themselves. `Hold Start` and `Hold Select` fire on
a single button and are the most likely to get in the way. The four-button
combos are safest.

Like the notification setting, this goes into the `--appendconfig` file, so
changing it rewrites the launchers of games you've already added.

## RetroAchievements

RetroArch has achievement support built in. This turns it on for games launched
from here and signs you in.

Signing in asks for your retroachievements.org password **once**, and only the
Connect token it gives back is stored. Their API offers no way around that one
login.

Already have a login stored in RetroArch? You get a one-tap adopt instead, with
nothing to type.

**Hardcore mode is off by default**, which is a deliberate disagreement with
RetroArch — it defaults to on. Hardcore disables save states, rewind, slowdown
and cheats, which is most of how a handheld gets played. Turning achievements on
isn't a request to give that up. Switch it on yourself if you want unlocks to
count on the hardcore leaderboard.

### Why some of my cores can't do achievements

Achievements work by watching emulated memory, so a core that publishes no
memory map has nothing to read.

Cores declare this in their `.info` file, so the tab lists yours as supported,
unsupported, or not declared. That last one means the core says neither way,
which older cores often do.

> **Note:** your token is treated like your SteamGridDB key — stored in the
> plugin's settings, never sent to the frontend, and the launch override file
> carrying it is `0600`.
