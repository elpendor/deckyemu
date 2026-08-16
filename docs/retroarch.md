# RetroArch

Installing RetroArch and its cores, and the launch behaviour this plugin sets
for games that run on one.

Back to [the README](../README.md).

**Contents** — [Installing RetroArch and cores](#installing-retroarch-and-cores) ·
[Fullscreen and RetroArch's on-screen chatter](#fullscreen-and-retroarchs-on-screen-chatter) ·
[Getting into RetroArch's menu](#getting-into-retroarchs-menu) ·
[RetroAchievements](#retroachievements)

## Installing RetroArch and cores

Neither has to be set up beforehand.

**RetroArch** installs from Flathub in user scope (`flatpak install --user`), so
it needs no password, with progress streamed to a bar rather than one long
blocking call.

**Cores** come from the libretro buildbot, the same source RetroArch's own Core
Downloader uses. The catalog describes every core that exists rather than only
the installed ones, which enables the useful case: **pick a ROM that nothing
installed can run and the plugin offers the cores that could, then continues
straight into adding the game.**

Roughly a third of what the buildbot publishes is not a game system — media
players, image viewers, tech demos. A core is only offered if it declares both a
`database` and `supported_extensions` and is not in an excluded category.

**Uninstalling** is offered only when the plugin can honestly do it: a user-scope
flatpak, removed with `flatpak uninstall --user`. A system-wide flatpak (what
EmuDeck and Discover install) is root-owned, a native package would mean
unlocking SteamOS's read-only filesystem, and an AppImage is a file the plugin
never installed — each shows the reason rather than a disabled button with no
explanation. Configuration and saves are kept unless a separate toggle asks
otherwise, and games already added work again the moment RetroArch is reinstalled.

## Fullscreen and RetroArch's on-screen chatter

**Launch custom emulators fullscreen** applies each emulator's own fullscreen
switch. There is no flag common to all of them — Dolphin has none at all, PCSX2
uses `-fullscreen`, RPCS3 `--fullscreen` — so it is stored per emulator and suggested for
recognised ones. It stays an editable field because several emulators ignore
unknown arguments silently, which would make a wrong guess invisible.

RetroArch announces itself when content loads — a load animation, then notices
about controller autoconfig, refresh rate and config overrides. **RetroArch
notifications** suppresses that for games launched from this plugin:

| Mode | Effect |
| --- | --- |
| `Hide the startup banner` (default) | Disables the load animation and the notices that follow it |
| `Hide all on-screen messages` | Also sets `video_font_enable = false`, silencing save-state confirmations and errors too |
| `Keep RetroArch's notifications` | RetroArch behaves exactly as it does on its own |

These are passed per-launch rather than written into your own `retroarch.cfg`,
and the override turns RetroArch's save-on-exit off so they cannot settle into it
as permanent defaults. The trade-off is that changes made from RetroArch's own
menu during a game launched from here are not saved either; *Save Current
Configuration* still works if you want them kept.

Because launch behaviour is baked into each game's launcher script, changing this
rewrites the launchers of games already added.

## Getting into RetroArch's menu

**RetroArch menu shortcut** binds a controller combination that opens RetroArch's
menu mid-game, defaulting to **Select + Start**.

It is on by default because otherwise there is usually no way in. RetroArch sets
no combo of its own, and the Guide button its autoconfig binds never reaches it on
a Deck — Steam claims that button first. That leaves `F1` on a keyboard.

> **This applies to games run on a libretro core only.** A game launched through
> a custom emulator is unaffected: PCSX2, Dolphin and the rest each have
> their own menu binding, and nothing here can set it.

RetroArch takes a fixed list rather than a free-form binding, so the choices are
exactly what it supports:

| Setting | |
| --- | --- |
| `Select + Start` (default) | `L1 + R1 + Select + Start`, `L3 + R3`, `L1 + R1`, `L2 + R2`, `L3 + R` |
| `D-pad Down + Select` | `D-pad Down + Y + L1 + R1`, `Hold Start`, `Hold Select` |
| `Off` | Writes nothing, so whatever is in your `retroarch.cfg` applies |

Pick one your games do not use themselves. `Hold Start` and `Hold Select` fire on
a single button and are the most likely to interfere; the four-button combos are
safest.

Like the notification setting, this goes into the `--appendconfig` file and
changing it rewrites the launchers of games already added.

## RetroAchievements

RetroArch has achievement support built in; this turns it on for games launched
from here and signs you in.

Signing in asks for your retroachievements.org password **once**, and only the
Connect token it returns is stored; their API offers no way around that one
login. If RetroArch already has a login stored it is offered as a one-tap adopt
instead, with nothing to type.

**Hardcore mode is off by default, a deliberate disagreement with RetroArch**,
which defaults it on. Hardcore disables save states, rewind, slowdown and cheats
— most of how a handheld gets played, and switching achievements on is not a
request to lose it. Turn it on if you want unlocks to count on the hardcore
leaderboard.

**Not every core can take part.** Achievements work by watching emulated memory,
so a core publishing no memory map has nothing to read. Cores declare this in
their `.info` file, so the tab lists yours as supported, unsupported, or not
declared — the last meaning the core says neither, which older cores often do.

The token is treated like the SteamGridDB key: stored in the plugin's settings,
never sent to the frontend, and the launch override file carrying it is `0600`.
