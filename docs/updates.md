# Updates and problems

Keeping the plugin current, and what to send when something goes wrong.

Back to [the README](../README.md).

**Contents** — [Updates and what changed](#updates-and-what-changed) ·
[Reporting a problem](#reporting-a-problem)

## Updates and what changed

The **Updates** tab shows which build is running, checks GitHub for a newer one,
and installs it. It also shows **what's new** for both the release being offered
and the build already installed.

The notes are generated from commit subjects, grouped under New, Fixed, Faster
and Under the hood. They ship inside the build as well as on the release, so the
tab shows the running version's changelog with no network at all.

Installing goes through decky's own loader, which has permissions this plugin
does not. The download is checked against the digest published with the release.

### When it checks

A dot appears on the plugin's Quick Access icon when a newer release exists.
This plugin is not in decky's store, so nothing else will ever tell you.

**Opening the Quick Access panel checks**, and that is the one that decides what
you see. The answer is cached for an hour, so opening the panel twenty times in
an evening asks GitHub once — and the cache survives a plugin reload, so it does
not start again every time decky restarts.

There is also a background check every six hours, for a Deck left on the library
screen with the panel never opened. Do not rely on it for anything else: it
counts time the Deck is **awake**, and a Deck suspends rather than shutting down,
so an hour of play a night reaches the second check nearly a week later. It also
runs once immediately whenever the plugin loads, which is why a reboot shows a
current answer straight away.

Nothing is downloaded by any of this — the check reads the releases page and
nothing more. **Check for updates** on that tab forces one past the cache
whenever you want a definite answer.

## Which build you are running

The **Diagnostics** tab shows two versions, and they are not the same thing.
*Plugin on disk* is what was installed; *Interface Steam loaded* is the half
Steam is drawing. Steam keeps the interface it already evaluated, so after an
update the two can disagree, and the tab says so and tells you to restart Steam.

That is the first question whenever anything here misbehaves, which is why it
sits beside the report rather than under Updates.

## Reporting a problem

**Diagnostics → Report a problem** gathers what a bug report needs and puts it where
you can read it: scan the QR code with a phone, or type the short address and the
six digits on anything with a keyboard. Copy the text, paste it into the issue.

It carries the plugin version and build, what RetroArch is and how it was
installed, which emulators are registered, how many games are in the library and
under which systems, your settings, the last 200 lines of the log, and **what
the emulator said the last time you launched a game**.

That last one is why a game that starts and dies is no longer a dead end.
Launching from here suppresses the emulator's on-screen messages so a game looks
like a game rather than a frontend — which also took away the line that would
have told you a BIOS had moved or a ROM was gone. Each launch now keeps what the
emulator wrote, one file per game, overwritten every time it starts, and the most
recent one travels with this report. Nothing interrupts you: there is no
notification and no badge, it is simply there when you go looking.

Your SteamGridDB key, your RetroAchievements token, the transfer token, your
RetroAchievements username and the names and paths of your games are struck out
of it. By value, across the whole text rather than only the section they belong
to — the log names games as it works, so removing the library listing alone
would not have been enough. Settings are read through a list of what may be
reported rather than a list of what may not, so a setting added later is absent
until somebody lists it.

Two things it cannot catch, since neither is a value it knows: a game you probed
but never added, and a title too short to strike without mangling the rest of
the report. Read it before you paste it — it is shown to you first for that
reason.

The report lives in memory and goes when the transfer server stops — half an
hour idle, or **Done, and stop sharing now**.
