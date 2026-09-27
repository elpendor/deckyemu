# Updates and problems

Keeping the plugin current, and what to send when something goes wrong.

Back to [the README](https://github.com/elpendor/deckyemu#readme).

## Updates and what changed

The **Updates** tab shows which build you're running, checks GitHub for a newer
one, and installs it.

It also shows you **what's new** — in the release being offered if there is one,
otherwise in the build you're already running.

Those notes are generated from commit subjects and grouped under New, Fixed,
Faster and Under the hood. They ship inside the build as well as on the release,
so you can read your running version's changelog with no network at all.

Installing goes through decky's own loader, which has permissions this plugin
doesn't. The download gets checked against the digest published with the
release.

### When it checks

A dot appears on the plugin's Quick Access icon when a newer release exists.
This plugin isn't in decky's store, so nothing else is ever going to tell you.

The panel then shows the new version at the top. Press **See what's new** and
you get its notes and an **Update** button in a dialog over the panel, so you
can install without going to the settings page. That works even when a Steam
update has left decky unable to open plugin pages.

**Opening the Quick Access panel is what checks**, and that's the one that
decides what you see. The answer is cached for an hour, so opening the panel
twenty times in an evening asks GitHub once. The cache survives a plugin reload,
so it doesn't start over every time decky restarts.

There's also a background check every six hours, for a Deck left on the library
screen with the panel never opened.

> **Don't rely on that one.** It counts time your Deck is *awake*, and a Deck
> suspends rather than shutting down. An hour of play a night reaches the second
> check nearly a week later. It does run once immediately whenever the plugin
> loads, which is why a reboot shows you a current answer straight away.

Nothing is downloaded by any of this — the check reads the releases page and
stops there. Press **Check for updates** on that tab to force one past the cache
whenever you want a definite answer.

## Which build you are running

The **Diagnostics** tab shows two versions, and they aren't the same thing:

| | |
| --- | --- |
| **Plugin on disk** | What got installed |
| **Interface Steam loaded** | The half Steam is actually drawing |

Steam keeps the interface it already evaluated, so after an update these two can
disagree. The tab tells you when they do, and to restart Steam.

That's the first question whenever anything here misbehaves, which is why it
sits next to the report rather than under Updates.

## Reporting a problem

Press **Diagnostics → Report a problem**. It gathers what a bug report needs and
puts it where you can read it:

1. Scan the QR code with your phone, or type the short address and six digits on
   anything with a keyboard.
2. Read it.
3. Copy the text and paste it into the issue.

It carries your plugin version and build, what RetroArch is and how it got
installed, which emulators you have registered, how many games are in your
library and under which systems, your settings, the last 200 lines of the log,
and **what the emulator said the last time you launched a game**.

That last one is why a game that starts and dies is no longer a dead end.
Launching from here hides the emulator's on-screen messages so a game looks like
a game rather than a frontend — which also took away the line that would have
told you a BIOS had moved or a ROM was gone. Now every launch keeps what the
emulator wrote, one file per game, overwritten each time it starts. The most
recent one travels with your report.

Nothing interrupts you about it. No notification, no badge. It's just there when
you go looking.

### What gets struck out

Your SteamGridDB key, your RetroAchievements token, the transfer token, your
RetroAchievements username, and the names and paths of your games.

They're removed by value, across the whole text rather than just the section
they belong to — the log names games as it works, so removing the library
listing alone wouldn't have been enough.

Settings are read through a list of what *may* be reported rather than a list of
what may not, so a setting added later stays out until somebody lists it.

> **Two things it can't catch**, since neither is a value it knows: a game you
> probed but never added, and a title too short to strike without mangling the
> rest of the report. Read the report before you paste it. That's why you're
> shown it first.

Your report lives in memory and goes when the transfer server stops — half an
hour idle, or when you press **Done, and stop sharing now**.
