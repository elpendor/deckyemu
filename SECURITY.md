# Reporting a security problem

Please report it privately through GitHub's
[**Report a vulnerability**](https://github.com/elpendor/deckyemu/security/advisories/new)
form rather than opening an issue. That keeps the details out of public view
until there is a version to move to.

Only the newest release is supported. There is no store listing, so the fix
arrives through the plugin's own **Updates** tab.

## What is worth reporting

This plugin runs with your user's privileges, installs software, and briefly
listens on the network. The parts where that matters most:

- **The transfer server** (`py_modules/fileserver.py`). It listens on the local
  network while the Transfer window is open. Every path needs a random token;
  the only exception is the root page, which takes a six-digit code and stops
  accepting codes after eight wrong ones. Anything that reaches a file, escapes
  the upload folder, or gets past the code without the token is a bug.
- **Imported emulator definitions** (`docs/emulator-definitions.md`). A
  definition is a list of actions the plugin performs, so it is validated
  strictly: it may install the emulator it describes, and it may not delete
  anything, fetch firmware or a second binary, or write outside the directory it
  declares. Anything that gets past those bounds is a bug.
- **The updater** (`py_modules/releases.py`, `handoff.py`). Self-hosted
  distribution makes this the only way a fix reaches anyone, so it is worth more
  scrutiny than its size suggests. The download is checked against the digest
  published in the release, and offered to Decky over loopback.
- **Generated launchers** (`py_modules/launchers.py`). Every argument is quoted
  and nothing a filename or a game title carries may become a command.

## What is already known and is not a bug

- **The transfer server is plain HTTP.** It exists to move files around one
  home network. Treat the address as reachable by anything else on that network,
  which is why the token is required and the code is capped.
- **Remembering the transfer address** turns a bookmarked link into a standing
  credential for as long as the server runs. That is what the setting says, and
  it is off by default.
- **Removing a game deletes the ROM this plugin filed**, and clearing the
  library deletes all of them. There is no undo. A ROM the plugin never filed --
  on an SD card, or in a library laid out by something else -- is never touched.
