#!/usr/bin/env python3
"""A disc set in the transfer folder is one game, not thirteen files.

    python scripts/tests/test_received_sets.py

A CD rip arrives as one `.cue` and a dozen `.bin` tracks, and the transfer
dialog listed every one of them with its own **Add** -- which on a track offers
the add flow a file of raw sectors, and makes a Steam entry out of something
that cannot start. `romshelf.sheet_owners` is what folds them: it says, for a
whole listing at once, which playlist owns each file.

Two things are worth pinning down here and neither is obvious from the code.
The first is that ownership resolves to the *top*: in a multi-disc set the
`.bin` files belong to the `.m3u`, not to the `.cue` that literally lists them,
so the dialog is left with one row rather than three. The second is what happens
at the edges -- a track whose sheet has not arrived must stay visible, because
it is the file the reader has to act on.

Deleting is tested with it, since grouping is what makes deleting a set
possible: removing `Game.cue` and leaving its tracks behind is hundreds of
megabytes nothing will ever point at again.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import plugin_transfers  # noqa: E402
import romshelf  # noqa: E402


def write_cue(folder, sheet, tracks):
    """A real sheet naming `tracks`, because the parser is what is being read."""
    with open(os.path.join(folder, sheet), "w", encoding="utf-8", newline="\n") as handle:
        for index, name in enumerate(tracks, start=1):
            handle.write('FILE "%s" BINARY\n' % name)
            handle.write("  TRACK %02d %s\n"
                         % (index, "MODE2/2352" if index == 1 else "AUDIO"))
    for name in tracks:
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write("x")


section("one disc with audio tracks")

with tempfile.TemporaryDirectory() as folder:
    tracks = ["Zed (Track 01).bin", "Zed (Track 02).bin", "Zed (Track 03).bin"]
    write_cue(folder, "Zed.cue", tracks)
    # A game of its own beside it, which must be left entirely alone.
    with open(os.path.join(folder, "Ayeway.z64"), "w", encoding="utf-8") as handle:
        handle.write("x")

    owners = romshelf.sheet_owners(folder, sorted(os.listdir(folder)))
    check("every track is owned by the sheet",
          sorted(owners), sorted(tracks))
    check("and the sheet is what owns them",
          sorted(set(owners.values())), ["Zed.cue"])
    check("the sheet itself is owned by nothing", "Zed.cue" in owners, False)
    check("and so is a cartridge sitting beside it", "Ayeway.z64" in owners, False)


section("a multi-disc set resolves to the playlist, not the sheet above the track")

with tempfile.TemporaryDirectory() as folder:
    write_cue(folder, "Zed (Disc 1).cue", ["Zed (Disc 1) (Track 01).bin"])
    write_cue(folder, "Zed (Disc 2).cue", ["Zed (Disc 2) (Track 01).bin"])
    with open(os.path.join(folder, "Zed.m3u"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("Zed (Disc 1).cue\nZed (Disc 2).cue\n")

    owners = romshelf.sheet_owners(folder, sorted(os.listdir(folder)))
    # The whole point of resolving past the immediate parent: one game, one row.
    check("the sheets belong to the playlist",
          owners.get("Zed (Disc 1).cue"), "Zed.m3u")
    check("and so do the tracks under them",
          owners.get("Zed (Disc 1) (Track 01).bin"), "Zed.m3u")
    check("which leaves exactly one file unowned",
          [name for name in sorted(os.listdir(folder)) if name not in owners],
          ["Zed.m3u"])


section("edges -- what must keep its own row")

with tempfile.TemporaryDirectory() as folder:
    # Raw sectors with no sheet anywhere. Hiding this would hide the problem:
    # nothing about the file says it cannot be assembled.
    with open(os.path.join(folder, "Zed (Track 01).bin"), "w", encoding="utf-8") as handle:
        handle.write("x")
    owners = romshelf.sheet_owners(folder, sorted(os.listdir(folder)))
    check("a track whose sheet never arrived is owned by nothing", owners, {})

with tempfile.TemporaryDirectory() as folder:
    write_cue(folder, "Zed.cue", ["Zed (Track 01).bin"])
    # The sheet has arrived and the track has not been listed -- a half-finished
    # transfer, polled while the .bin is still coming.
    owners = romshelf.sheet_owners(folder, ["Zed.cue"])
    check("a sheet owns nothing it was not listed beside", owners, {})

with tempfile.TemporaryDirectory() as folder:
    # Two playlists naming each other. No ripper writes this and a hand-edited
    # .m3u can; the walk up the chain must stop rather than spin.
    for one, other in (("a.m3u", "b.m3u"), ("b.m3u", "a.m3u")):
        with open(os.path.join(folder, one), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(other + "\n")
    owners = romshelf.sheet_owners(folder, ["a.m3u", "b.m3u"])
    check("a cycle resolves rather than hanging", sorted(owners), ["a.m3u", "b.m3u"])


section("deleting a sheet takes its tracks with it")

with tempfile.TemporaryDirectory() as folder:
    tracks = ["Zed (Track 01).bin", "Zed (Track 02).bin"]
    write_cue(folder, "Zed.cue", tracks)
    with open(os.path.join(folder, "Ayeway.z64"), "w", encoding="utf-8") as handle:
        handle.write("x")

    group = plugin_transfers._owned_beside(os.path.join(folder, "Zed.cue"))
    check("the sheet's group is its tracks",
          sorted(os.path.basename(one) for one in group), sorted(tracks))

    # The row beside it is a game in its own right and owns nothing, so pressing
    # its delete must remain a one-file delete.
    alone = plugin_transfers._owned_beside(os.path.join(folder, "Ayeway.z64"))
    check("a file that is not a playlist takes nothing with it", alone, [])


section("the received list carries who owns what")

with tempfile.TemporaryDirectory() as folder:
    write_cue(folder, "Zed.cue", ["Zed (Track 01).bin"])
    received = [{"name": name, "path": os.path.join(folder, name), "size": 1, "at": 0}
                for name in sorted(os.listdir(folder))]

    owners = plugin_transfers._received_owners(received)
    check("the track is annotated with its sheet",
          owners.get(os.path.join(folder, "Zed (Track 01).bin")), "Zed.cue")
    check("and the sheet with nothing",
          os.path.join(folder, "Zed.cue") in owners, False)

# Two folders at once, which the received list can be: it follows the running
# server, and a firmware send saves somewhere else. A track must not be folded
# onto a same-named sheet in the other one.
with tempfile.TemporaryDirectory() as root:
    first = os.path.join(root, "roms")
    second = os.path.join(root, "firmware")
    os.makedirs(first)
    os.makedirs(second)
    write_cue(first, "Zed.cue", ["Zed (Track 01).bin"])
    with open(os.path.join(second, "Zed (Track 01).bin"), "w", encoding="utf-8") as handle:
        handle.write("x")

    received = []
    for folder in (first, second):
        received += [{"name": name, "path": os.path.join(folder, name), "size": 1, "at": 0}
                     for name in sorted(os.listdir(folder))]

    owners = plugin_transfers._received_owners(received)
    check("the track beside its sheet is owned",
          owners.get(os.path.join(first, "Zed (Track 01).bin")), "Zed.cue")
    check("the one in another folder is not",
          os.path.join(second, "Zed (Track 01).bin") in owners, False)


section("a disc of a game already added is offered to that game")

import discset  # noqa: E402  -- only this section needs it

with tempfile.TemporaryDirectory() as folder:
    library = {
        "111": {"title": "Zed", "rom_path": os.path.join(folder, "Zed (Disc 1).cue")},
        "222": {"title": "Ayeway", "rom_path": os.path.join(folder, "Ayeway.z64")},
    }
    homes = plugin_transfers._disc_homes(library)
    check("the added disc's set is known", sorted(homes), [("Zed", ".cue")])
    check("and the cartridge is not a set", ("Ayeway", ".z64") in homes, False)

    waiting = {"name": "Zed (Disc 2).cue", "path": "/inbox/Zed (Disc 2).cue"}
    check("disc 2 is offered to the game holding disc 1",
          plugin_transfers._disc_for(waiting, homes),
          {"app_id": 111, "title": "Zed", "disc": 2})

    # Already there: adding it would do nothing, and a button that does nothing
    # is worse than no button.
    check("a disc the game already has is not offered",
          plugin_transfers._disc_for(
              {"name": "Zed (Disc 1).cue", "path": "/inbox/Zed (Disc 1).cue"}, homes),
          None)
    check("nor is a different game",
          plugin_transfers._disc_for(
              {"name": "Wye (Disc 2).cue", "path": "/inbox/Wye (Disc 2).cue"}, homes),
          None)
    # Same base, different format: a core is chosen for one extension, and a
    # playlist mixing two is a set that will not load.
    check("nor the same disc in another format",
          plugin_transfers._disc_for(
              {"name": "Zed (Disc 2).chd", "path": "/inbox/Zed (Disc 2).chd"}, homes),
          None)
    # `part_of` says a sheet in the folder names it, which is the only evidence
    # there is that a file is a track rather than a disc.
    check("nor a track that merely reads like a disc",
          plugin_transfers._disc_for(
              {"name": "Zed (Disc 2).bin", "path": "/inbox/Zed (Disc 2).bin",
               "part_of": "Zed (Disc 2).cue"}, homes),
          None)

with tempfile.TemporaryDirectory() as folder:
    # A game already added as a set: its playlist names the discs, so all of
    # them count as held and the next one along is what gets offered.
    write_cue(folder, "Zed (Disc 1).cue", ["Zed (Disc 1) (Track 01).bin"])
    write_cue(folder, "Zed (Disc 2).cue", ["Zed (Disc 2) (Track 01).bin"])
    playlist, error = discset.write_playlist(
        folder, ["Zed (Disc 1).cue", "Zed (Disc 2).cue"])
    check("the set was written for the fixture", error, "")

    homes = plugin_transfers._disc_homes({"333": {"title": "Zed", "rom_path": playlist}})
    check("both discs in the playlist count as held",
          plugin_transfers._disc_for(
              {"name": "Zed (Disc 2).cue", "path": "/inbox/Zed (Disc 2).cue"}, homes),
          None)
    check("and disc 3 is offered",
          plugin_transfers._disc_for(
              {"name": "Zed (Disc 3).cue", "path": "/inbox/Zed (Disc 3).cue"}, homes),
          {"app_id": 333, "title": "Zed", "disc": 3})

# Two added games whose discs share a base name. Picking one to offer would be
# wrong half the time, so neither is offered and the ordinary Add stands.
homes = plugin_transfers._disc_homes({
    "444": {"title": "Zed", "rom_path": "/roms/ps1/Zed (Disc 1).cue"},
    "555": {"title": "Zed again", "rom_path": "/roms/ps1/Zed (Disc 3).cue"},
})
check("an ambiguous match is not guessed at",
      plugin_transfers._disc_for(
          {"name": "Zed (Disc 2).cue", "path": "/inbox/Zed (Disc 2).cue"}, homes),
      None)

# The status call this feeds runs every second or two while a transfer moves, so
# one bad record has to cost its own row rather than the whole dialog.
homes = plugin_transfers._disc_homes({
    "not-a-number": {"title": "Wat", "rom_path": "/roms/ps1/Wat (Disc 1).cue"},
    "nope": "this is not an entry",
    "666": {"title": "Zed", "rom_path": "/roms/ps1/Zed (Disc 1).cue"},
})
check("a malformed library record is skipped, not raised",
      sorted(homes), [("Zed", ".cue")])
check("and the good record beside it still answers",
      plugin_transfers._disc_for(
          {"name": "Zed (Disc 2).cue", "path": "/inbox/Zed (Disc 2).cue"}, homes),
      {"app_id": 666, "title": "Zed", "disc": 2})

check("an empty library answers nothing rather than failing",
      plugin_transfers._disc_homes({}), {})
check("and so does a missing one", plugin_transfers._disc_homes(None), {})
