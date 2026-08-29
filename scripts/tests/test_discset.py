#!/usr/bin/env python3
"""Recognising a multi-disc set from filenames, and writing its playlist.

    python scripts/tests/test_discset.py

The detection is name-based and cannot be anything else -- the disc number is
not inside the file -- so what is worth testing is the *shape* of the two ways
it can be wrong. They are not equally bad, and the rules are lopsided on
purpose:

* **Missing a set costs nothing.** The game is added a disc at a time, exactly
  as it was before this existed, and the panel offers to pick the discs by hand.
  Several checks below assert a miss, and each one is a deliberate miss.
* **Merging two games would write a playlist that runs the wrong thing.** So
  everything except the disc number has to match exactly, and a gap in the
  numbering is no set at all rather than a shorter one.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import REPO_ROOT, check, section  # noqa: E402  -- installs the decky stub

sys.path.insert(0, REPO_ROOT)

import discset  # noqa: E402


def touch(folder, *names):
    for name in names:
        with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
            handle.write("x")


def cue(folder, name, *tracks):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
        for track in tracks:
            handle.write('FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n' % track)
    touch(folder, *tracks)


section("reading a disc marker off a name")

check("Redump's own shape",
      discset.split_disc("Final Fantasy VII (USA) (Disc 1).cue"),
      ("Final Fantasy VII (USA)", 1, ".cue"))
check("with the count spelled out",
      discset.split_disc("Metal Gear Solid (USA) (Disc 2 of 2).chd"),
      ("Metal Gear Solid (USA)", 2, ".chd"))
# All three words are in real use: Redump writes Disc, older No-Intro sets write
# Disk, and European PlayStation releases were labelled CD often enough.
check("Disk", discset.split_disc("Game [Disk 3].cue"), ("Game", 3, ".cue"))
check("CD", discset.split_disc("Game (CD 1).cue"), ("Game", 1, ".cue"))
check("the marker takes its spacing with it",
      discset.split_disc("Game (Disc 1) (USA).cue")[0], "Game (USA)")

section("names that are deliberately not discs")

# A title ending in a number is not at risk and never was -- the pattern needs
# the literal word `disc`, `disk` or `cd`, and this title has none of them. Kept
# because it is worth having the harmless case pinned down, and because the
# comment that used to stand here claimed it was the reason for the brackets.
# See `discset._DISC_RE` for what the brackets actually buy, which is less than
# it was made to sound.
check("a title ending in a number", discset.split_disc("Star Wars Episode 1.cue"), None)
# The unbracketed forms are a deliberate miss rather than a danger: a rip named
# by hand reads `Game - Disc 2`, and the panel's answer is **Pick another
# disc**. If this is ever loosened it is `disc` and `disk` at the end of a name,
# never `cd` -- two letters that appear in real titles, `Sonic CD` among them.
check("an unbracketed marker", discset.split_disc("Game Disc 2.cue"), None)
check("and a hyphenated one", discset.split_disc("Final Fantasy VII - Disc 2.cue"), None)
check("a shorthand nobody standardised", discset.split_disc("FF7 d1.cue"), None)
check("two markers, so which is the disc is a guess",
      discset.split_disc("Game (Disc 1) (Disk 2).cue"), None)
check("disc zero", discset.split_disc("Game (Disc 0).cue"), None)
check("a number past any real set", discset.split_disc("Game (Disc 99).cue"), None)
check("nothing but a marker", discset.split_disc("(Disc 1).cue"), None)
check("no name at all", discset.split_disc(""), None)

section("finding the set on disk")

with tempfile.TemporaryDirectory() as folder:
    touch(folder,
          "Final Fantasy VII (USA) (Disc 1).cue",
          "Final Fantasy VII (USA) (Disc 2).cue",
          "Final Fantasy VII (USA) (Disc 3).cue")
    found = discset.find_set(os.path.join(folder, "Final Fantasy VII (USA) (Disc 2).cue"))
    check("all three, in order, from any one of them",
          found, ["Final Fantasy VII (USA) (Disc %d).cue" % n for n in (1, 2, 3)])
    check("and the playlist is named after the game",
          discset.playlist_name(found), "Final Fantasy VII (USA).m3u")

with tempfile.TemporaryDirectory() as folder:
    # A different game whose name happens to start the same way. This is the
    # merge that must not happen: everything except the number has to match.
    touch(folder, "Game (Disc 1).cue", "Game 2 (Disc 1).cue")
    check("a different game is not a disc of this one",
          discset.find_set(os.path.join(folder, "Game (Disc 1).cue")), [])

with tempfile.TemporaryDirectory() as folder:
    touch(folder, "Game (Disc 1).cue", "Game (Disc 3).cue")
    check("a gap is no set, not a shorter one",
          discset.find_set(os.path.join(folder, "Game (Disc 1).cue")), [])

with tempfile.TemporaryDirectory() as folder:
    touch(folder, "Game (Disc 2).cue", "Game (Disc 3).cue")
    check("a set that does not start at 1 is a set with disc 1 missing",
          discset.find_set(os.path.join(folder, "Game (Disc 2).cue")), [])

with tempfile.TemporaryDirectory() as folder:
    # Two formats of the same game side by side, which is a real folder: the
    # extension separates them, so each is its own two-disc set.
    touch(folder, "Game (Disc 1).cue", "Game (Disc 2).cue",
                  "Game (Disc 1).chd", "Game (Disc 2).chd")
    check("the .cue set is only the .cue files",
          discset.find_set(os.path.join(folder, "Game (Disc 1).cue")),
          ["Game (Disc 1).cue", "Game (Disc 2).cue"])
    check("and the .chd set only the .chd files",
          discset.find_set(os.path.join(folder, "Game (Disc 2).chd")),
          ["Game (Disc 1).chd", "Game (Disc 2).chd"])

with tempfile.TemporaryDirectory() as folder:
    touch(folder, "Game (Disc 1).cue")
    check("one disc is not a set", discset.find_set(os.path.join(folder, "Game (Disc 1).cue")), [])
    touch(folder, "Zelda.cue")
    check("a file with no marker is not a set",
          discset.find_set(os.path.join(folder, "Zelda.cue")), [])

check("a folder that is not there is not a crash",
      discset.find_set("/nowhere/at/all/Game (Disc 1).cue"), [])

section("shapes taken from a real Redump collection")

# Read off a 156-game PlayStation library rather than invented. Every one of
# these was a guess until it was checked, and two of them would have been easy
# to get wrong.

# **The marker is not always last.** Redump appends the revision after it, so a
# rule anchored to the end of the name would find nothing for four of the
# biggest multi-disc games in that collection.
check("a revision after the disc marker",
      discset.split_disc("Final Fantasy IX (USA) (Disc 1) (Rev 1).cue"),
      ("Final Fantasy IX (USA) (Rev 1)", 1, ".cue"))

with tempfile.TemporaryDirectory() as folder:
    for disc in (1, 2, 3, 4):
        cue(folder, "Final Fantasy IX (USA) (Disc %d) (Rev 1).cue" % disc,
            "Final Fantasy IX (USA) (Disc %d) (Rev 1).bin" % disc)
    found = discset.find_set(
        os.path.join(folder, "Final Fantasy IX (USA) (Disc 1) (Rev 1).cue"))
    check("all four discs are still one set", len(found), 4)
    # The revision belongs to the game, so it stays in the playlist's name.
    check("and the revision stays in the name",
          discset.playlist_name(found), "Final Fantasy IX (USA) (Rev 1).m3u")

# **A bonus disc is not disc three.** Lunar ships "(The Making of)" beside its
# two game discs, in the same shape and the same folder once transferred. It
# carries no disc marker, so it is a separate thing -- and merging it would put
# a documentary in the middle of the game.
with tempfile.TemporaryDirectory() as folder:
    for disc in (1, 2):
        cue(folder, "Lunar (USA) (Disc %d).cue" % disc,
            "Lunar (USA) (Disc %d) (Track 1).bin" % disc,
            "Lunar (USA) (Disc %d) (Track 2).bin" % disc)
    cue(folder, "Lunar (USA) (The Making of).cue",
        "Lunar (USA) (The Making of) (Track 1).bin")
    found = discset.find_set(os.path.join(folder, "Lunar (USA) (Disc 1).cue"))
    check("the bonus disc is not one of the game's",
          found, ["Lunar (USA) (Disc 1).cue", "Lunar (USA) (Disc 2).cue"])
    check("and offers no set of its own",
          discset.find_set(os.path.join(folder, "Lunar (USA) (The Making of).cue")), [])

# **A disc of its own per folder** is how a Redump download arrives, and it
# finds nothing -- deliberately. A playlist names files beside itself, and
# `romshelf` refuses to follow one out of its own directory, which is what keeps
# filing safe. The route that works is the one the plugin is built around:
# transferred files land flat, because `fileserver.safe_name` reduces every
# upload to its basename.
with tempfile.TemporaryDirectory() as folder:
    for disc in (1, 2):
        room = os.path.join(folder, "Fear Effect (USA) (Disc %d)" % disc)
        os.makedirs(room)
        cue(room, "Fear Effect (USA) (Disc %d).cue" % disc,
            "Fear Effect (USA) (Disc %d).bin" % disc)
    picked = os.path.join(folder, "Fear Effect (USA) (Disc 1)",
                          "Fear Effect (USA) (Disc 1).cue")
    check("one disc per folder is not a set the plugin can write",
          discset.find_set(picked), [])
    # But it is a thing the panel can *say*, which is the difference between a
    # limitation and a plugin that appears not to have noticed three discs
    # sitting next to the one you picked.
    check("though the folders beside it are found and counted",
          discset.discs_in_sibling_folders(picked),
          ["Fear Effect (USA) (Disc %d)" % n for n in (1, 2)])

section("discs in folders of their own")

with tempfile.TemporaryDirectory() as folder:
    for disc in (1, 2, 3, 4):
        room = os.path.join(folder, "Fear Effect (USA) (Disc %d)" % disc)
        os.makedirs(room)
        cue(room, "Fear Effect (USA) (Disc %d).cue" % disc,
            "Fear Effect (USA) (Disc %d).bin" % disc)
    picked = os.path.join(folder, "Fear Effect (USA) (Disc 2)",
                          "Fear Effect (USA) (Disc 2).cue")
    check("all four folders, from any of them",
          len(discset.discs_in_sibling_folders(picked)), 4)
    # Lenient where `find_set` is strict: this decides a sentence, not a file
    # that gets written, so a set missing a disc still earns the advice.
    import shutil  # noqa: E402  -- only this section needs it
    shutil.rmtree(os.path.join(folder, "Fear Effect (USA) (Disc 3)"))
    check("a gap does not silence the advice",
          len(discset.discs_in_sibling_folders(picked)), 3)

with tempfile.TemporaryDirectory() as folder:
    # An ordinary game in an ordinary folder says nothing, which is every game
    # anybody adds. A warning here would fire on the whole library.
    touch(folder, "Alundra (USA) (Rev 1).cue")
    check("a game that is not in a disc folder says nothing",
          discset.discs_in_sibling_folders(os.path.join(folder, "Alundra (USA) (Rev 1).cue")), [])

with tempfile.TemporaryDirectory() as folder:
    # One disc folder on its own is somebody who has a single disc, or has only
    # copied one across. Nothing to advise about a set that is not there.
    room = os.path.join(folder, "Fear Effect (USA) (Disc 1)")
    os.makedirs(room)
    touch(room, "Fear Effect (USA) (Disc 1).cue")
    check("a lone disc folder is not a set in folders",
          discset.discs_in_sibling_folders(
              os.path.join(room, "Fear Effect (USA) (Disc 1).cue")), [])

# A folder whose name carries a dot. `os.path.splitext` would take `.5 (Disc 1)`
# for an extension and lose the marker with it, which is why folders are split
# by a function of their own.
check("a version number in a folder name is not an extension",
      discset.split_disc_folder("Game v1.5 (Disc 1)"), ("Game v1.5", 1))
check("and a trailing separator is not part of the name",
      discset.split_disc_folder("Game (Disc 2)/"), ("Game", 2))

section("a track is not a disc")

# The layout this feature meets most often on a PlayStation game with audio:
# one `.cue` per disc, several `.bin` files under it, and **the tracks carry the
# disc marker too**. Read as names alone, `Game (Disc 2) (Track 01).bin` is disc
# 2 of something -- and the set built from that was track 1 of each disc: two
# files that are neither discs nor a game. The `.cue` naming them is what
# settles it.


with tempfile.TemporaryDirectory() as folder:
    for disc in (1, 2):
        cue(folder, "Game (Disc %d).cue" % disc,
            "Game (Disc %d) (Track 01).bin" % disc,
            "Game (Disc %d) (Track 02).bin" % disc)
    check("the .cue files are the discs",
          discset.find_set(os.path.join(folder, "Game (Disc 1).cue")),
          ["Game (Disc 1).cue", "Game (Disc 2).cue"])
    check("and a track offers nothing, however it is named",
          discset.find_set(os.path.join(folder, "Game (Disc 1) (Track 01).bin")), [])

with tempfile.TemporaryDirectory() as folder:
    # One track per disc, so the `.bin` shares its `.cue`'s whole name. Still a
    # track: what makes it one is being named by the sheet, not how it is named.
    for disc in (1, 2):
        cue(folder, "Game (Disc %d).cue" % disc, "Game (Disc %d).bin" % disc)
    check("a single-track .bin is still not a disc",
          discset.find_set(os.path.join(folder, "Game (Disc 1).bin")), [])

with tempfile.TemporaryDirectory() as folder:
    # No sheet anywhere, which is a real way to store a dump. Nothing says these
    # are tracks, so they are discs -- the guard is evidence-based and has none
    # here. Refusing them would break a layout that works.
    touch(folder, "Game (Disc 1).bin", "Game (Disc 2).bin")
    check("bare .bin discs with no sheet are a set",
          discset.find_set(os.path.join(folder, "Game (Disc 1).bin")),
          ["Game (Disc 1).bin", "Game (Disc 2).bin"])

with tempfile.TemporaryDirectory() as folder:
    # A `.cue` for disc 1 only, which is what a half-finished copy looks like.
    # Disc 2's `.bin` is not named by anything, but disc 1's is -- so the two
    # are not the same kind of file and are not a set.
    cue(folder, "Game (Disc 1).cue", "Game (Disc 1).bin")
    touch(folder, "Game (Disc 2).bin")
    check("a mixed folder offers nothing rather than half a set",
          discset.find_set(os.path.join(folder, "Game (Disc 2).bin")), [])

section("a track with no sheet at all")

# Breath of Fire III arrived as a 442MB data track and a 37MB audio track with
# no `.cue` anywhere, and the panel offered cores for it as happily as for a
# cartridge. The `.bin` files are raw sectors: nothing in them says where the
# tracks are or what mode they are in, so without the sheet the disc cannot be
# assembled -- and nothing on screen said so.

import romshelf  # noqa: E402  -- read after the harness stubbed decky

with tempfile.TemporaryDirectory() as folder:
    touch(folder,
          "Breath of Fire III (USA) (Track 1).bin",
          "Breath of Fire III (USA) (Track 2).bin")
    for track in (1, 2):
        check("track %d of a sheetless rip is flagged" % track,
              romshelf.track_without_a_sheet(
                  os.path.join(folder, "Breath of Fire III (USA) (Track %d).bin" % track)),
              True)
    # And it is not a disc set, which is the other half of what went wrong: two
    # tracks of one disc are not two discs.
    check("and two tracks are not two discs",
          discset.find_set(os.path.join(folder, "Breath of Fire III (USA) (Track 1).bin")),
          [])

with tempfile.TemporaryDirectory() as folder:
    # The same rip with its sheet. This is the ordinary case and by far the
    # commonest, so a warning here would be noise on every CD game.
    cue(folder, "Breath of Fire III (USA).cue",
        "Breath of Fire III (USA) (Track 1).bin",
        "Breath of Fire III (USA) (Track 2).bin")
    check("with the .cue there, nothing is said",
          romshelf.track_without_a_sheet(
              os.path.join(folder, "Breath of Fire III (USA) (Track 1).bin")),
          False)

with tempfile.TemporaryDirectory() as folder:
    # Naming the rippers actually write, none of which a game is called.
    touch(folder, "Game - Track 01.bin", "Track 01.bin", "Game [Track 3].bin")
    for name in ("Game - Track 01.bin", "Track 01.bin", "Game [Track 3].bin"):
        check("%s reads as a track" % name,
              romshelf.track_without_a_sheet(os.path.join(folder, name)), True)

with tempfile.TemporaryDirectory() as folder:
    # **A single-track dump is not this.** `Game (Disc 1).bin` with no sheet
    # works, is a real way to store a game, and is a set of its own -- warning
    # about it would be wrong, and would fire on the fixture folder that proves
    # bare .bin discs still form a set.
    touch(folder, "Game (Disc 1).bin", "Game.bin", "Game (Track 1).chd")
    for name in ("Game (Disc 1).bin", "Game.bin"):
        check("%s is a whole track and stays silent" % name,
              romshelf.track_without_a_sheet(os.path.join(folder, name)), False)
    # A `.chd` carries its own structure, tracks included, so the name means
    # nothing here.
    check("a .chd says nothing whatever it is called",
          romshelf.track_without_a_sheet(os.path.join(folder, "Game (Track 1).chd")), False)

section("writing the playlist")

with tempfile.TemporaryDirectory() as folder:
    discs = ["Game (Disc 1).cue", "Game (Disc 2).cue"]
    touch(folder, *discs)

    path, error = discset.write_playlist(folder, discs)
    check("it goes beside the discs", os.path.dirname(path), folder)
    check("named after the game", os.path.basename(path), "Game.m3u")
    check("no error", error, "")
    with open(path, "r", encoding="utf-8") as handle:
        body = handle.read()
    # Bare names, one per line. Every reader resolves them against the
    # playlist's own directory, and that is what keeps the set movable -- which
    # matters immediately, because romshelf files the whole group straight
    # after.
    check("one bare filename per line, in order",
          body, "Game (Disc 1).cue\nGame (Disc 2).cue\n")

    # Writing the same set again is what adding the same game twice does, and it
    # has nothing to do rather than something to refuse.
    again, error = discset.write_playlist(folder, discs)
    check("the same set again is a success", (again, error), (path, ""))

    # But a file already there saying something else may be the user's own,
    # hand-made and correct. Refuse, and say which file.
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("Something else.cue\n")
    written, error = discset.write_playlist(folder, discs)
    check("a different playlist already there is refused", written, "")
    check("and the message names the file", "Game.m3u" in error, True)

section("what write_playlist will not do")

with tempfile.TemporaryDirectory() as folder:
    touch(folder, "Game (Disc 1).cue", "Game (Disc 2).cue")
    check("fewer than two discs is not a playlist",
          discset.write_playlist(folder, ["Game (Disc 1).cue"])[0], "")
    check("nor is none", discset.write_playlist(folder, [])[0], "")
    check("a disc that is not in the folder is refused",
          discset.write_playlist(folder, ["Game (Disc 1).cue", "Nope.cue"])[0], "")
    # The list arrives from the frontend, so it is checked like anything else
    # that does. A name with a separator in it either escapes the folder or is
    # not a name.
    check("and so is a path",
          discset.write_playlist(folder, ["Game (Disc 1).cue", "../../etc/passwd"])[0], "")
    check("and an absolute one",
          discset.write_playlist(folder, ["Game (Disc 1).cue", "/etc/passwd"])[0], "")
    check("the same disc twice is refused",
          discset.write_playlist(folder, ["Game (Disc 1).cue", "Game (Disc 1).cue"])[0], "")
    check("nothing was written by any of that",
          sorted(os.listdir(folder)), ["Game (Disc 1).cue", "Game (Disc 2).cue"])

section("a hand-built set, which is the whole point of the fallback")

with tempfile.TemporaryDirectory() as folder:
    # Named the way the rules cannot read, which is why the user picked them.
    discs = ["FF7 d1.cue", "FF7 d2.cue"]
    touch(folder, *discs)
    check("nothing is detected, as expected",
          discset.find_set(os.path.join(folder, "FF7 d1.cue")), [])
    path, error = discset.write_playlist(folder, discs)
    check("but a playlist can still be written", error, "")
    # Falls back to the first disc's stem, since there is no shared base to take.
    # Not pretty, and never what the game is called in Steam -- the title comes
    # from the file the user picked.
    check("named after the first disc", os.path.basename(path), "FF7 d1.m3u")
