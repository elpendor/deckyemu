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

## Reporting a problem

**Updates → Report a problem** gathers what a bug report needs and puts it where
you can read it: scan the QR code with a phone, or type the short address and the
six digits on anything with a keyboard. Copy the text, paste it into the issue.

It carries the plugin version and build, what RetroArch is and how it was
installed, which emulators are registered, how many games are in the library and
under which systems, your settings, and the last 200 lines of the log.

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
