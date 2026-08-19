# Contributing

## Bug reports

These are the most useful thing you can send, and the plugin builds one for you.

**Updates → Report a problem** gathers the versions, what RetroArch is, which
emulators are registered, your library by system, the settings and the last of
the log — then puts it somewhere you can read it off the device: scan the QR
code with a phone, or type the short address and six digits on anything with a
keyboard. Copy the text into the issue.

It is redacted before you ever see it. Settings go through an allowlist rather
than a blocklist, keys and tokens are struck out by value, and filenames are
removed — so it is safe to paste in public. See
[docs/updates.md](docs/updates.md).

If you cannot reach the panel at all, say which Deck, which plugin version, and
what you did; that is enough to start.

## Asking for something

Open an issue with **Ask for something**. Say what you are trying to get done
rather than the button you imagine doing it — the first is a problem to solve,
the second is one answer to it, and often not the one that fits the rest of the
panel. Say what you do about it today as well, however ugly the workaround is;
that is what separates a papercut from the reason somebody stops using the
plugin.

**There is no promise that a request is acted on**, the same as for pull
requests below. One maintainer, no store listing, and nothing here is anybody's
job. A request can be a good idea and still be closed — usually against Game
Mode or the stdlib-only backend, and the reason is always given rather than
left to be inferred from silence.

Before filing one for an emulator, read the next section: that case needs no
code, no permission and no waiting.

## Emulators this project does not ship

You do not need code or permission for these. A `.deckyemu.json` definition
describes an emulator's system, extensions, launch arguments and firmware
layout, and is imported from the Quick Access panel — no Desktop Mode, no
typing on the Deck. See
[docs/emulator-definitions.md](docs/emulator-definitions.md), which is also the
list of what a definition is not allowed to do and why.

Definitions are welcome as issues. Whether one is ever bundled is a separate
question — a bundled entry is reviewed as code, because an entry is not data
the plugin reads but a list of actions it performs.

## Pull requests

Open an issue first. This is a small project with one maintainer and no store
listing, so a patch can be perfectly good and still not land — usually because
it solves a problem differently from how the rest of the plugin solves it, and
that is a conversation worth having before you spend an evening rather than
after. **There is no promise of review**, and that is worth knowing before you
start rather than discovering from silence.

If you do send one:

```sh
pnpm run check
```

is the whole gate — typecheck, bundle, both test suites, mypy, and the
release-build guard. CI runs the same things, so a green `check` is a green CI.

**Prefix the commit subject** with one of `feat:`, `fix:`, `perf:`, `internal:`,
`docs:`, `chore:` or `refactor:`. Release notes are generated from these
subjects, and the prefix decides which heading a line appears under — so the
subject should read as the sentence a user would want:

    fix: a renamed game takes back its own shortcut instead of making a second

[docs/development.md](docs/development.md) has the rest: building, running
against a real Deck, the layout of the tree, and what the tests cover.

Two constraints that are not style preferences, and that shape most of what
gets accepted:

- **Everything works in Game Mode.** No Desktop Mode, no keyboard, no second
  device, no SSH — including the first install. It is why this plugin exists
  next to tools that already do more. A change that ends at a shell command
  needs an in-panel alternative instead.
- **The backend is stdlib only.** It runs on decky's frozen Python, so there is
  nothing to install and no dependency to add. The frontend takes new runtime
  dependencies only with a reason.

## Security

Do not open an issue. Report it privately through GitHub's
[Report a vulnerability](https://github.com/elpendor/deckyemu/security/advisories/new)
form, so the details stay out of public view until there is a version to move
to. [SECURITY.md](SECURITY.md) says what is most worth looking at.

## Distribution

This plugin is not in decky's store and is not going to be; it is self-hosted
permanently, and the in-plugin **Updates** tab is the only channel there is.
Please do not spend effort on store-submission requirements.
