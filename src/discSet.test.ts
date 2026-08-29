import { describe, expect, it } from "vitest";

import { coreById, discRow, readsPlaylist, withDisc } from "./discSet";
import type { Core, RomProbe } from "./backend";

/*
 * The judgement worth being sure about is `readsPlaylist`. Getting it wrong
 * writes an `.m3u`, adds it to Steam, and hands the user a game that will not
 * start -- with nothing on screen connecting the failure to the switch they
 * pressed. There is no DOM in this run, so this lives outside the panel.
 */

function core(id: string, extensions: string[], shortName = id): Core {
  return {
    id,
    path: `/cores/${id}.so`,
    display_name: shortName,
    short_name: shortName,
    system_name: "",
    databases: [],
    database_labels: [],
    extensions,
    has_info: true,
    cheevos: "unknown",
  };
}

// Both extension lists are real, copied off a Deck rather than invented:
// `supported_extensions` in duckstation_libretro.info and snes9x_libretro.info.
const DUCKSTATION = core(
  "duckstation",
  ["exe", "psexe", "cue", "bin", "img", "iso", "chd", "pbp", "ecm", "mds", "psf", "m3u"],
  "DuckStation",
);
const SNES9X = core("snes9x", ["smc", "sfc", "swc", "fig", "bs", "st"], "Snes9x");
// What the catalog reports for PCSX2 now that `cannot_open` subtracts `m3u`:
// its own file-type filter, read off the installed binary.
const PCSX2 = { ...core(
  "emu:pcsx2",
  ["bin", "iso", "cue", "mdf", "chd", "cso", "zso", "gz", "dump"],
  "PCSX2",
), changes_disc: true };
// Xenia reads the XEX header flags that say a game is multi-disc and offers
// nothing to act on them -- no playlist, no Change Disc. Read off the extracted
// AppImage, not assumed.
const XENIA = { ...core("emu:xenia", ["iso", "xex", "zar", "stfs"], "Xenia"),
                changes_disc: true };
// Nothing in the catalog claims neither, so a stand-in is needed to exercise the
// refusal at all.
const NO_DISCS = core("emu:none", ["iso"], "SomeEmu");

function probe(discSet: string[], cores: Core[]): RomProbe {
  return {
    disc_set: discSet,
    disc_playlist: discSet.length ? "Game.m3u" : "",
    all_cores: cores,
    matching_cores: cores,
  } as unknown as RomProbe;
}

describe("readsPlaylist", () => {
  it("believes the core's own info file", () => {
    expect(readsPlaylist(DUCKSTATION)).toBe(true);
    expect(readsPlaylist(SNES9X)).toBe(false);
  });

  // The panel asks before a core is chosen, and while the probe is still out.
  it("is false for no core rather than throwing", () => {
    expect(readsPlaylist(undefined)).toBe(false);
    expect(readsPlaylist({} as Core)).toBe(false);
  });
});

describe("discRow", () => {
  it("says nothing for an ordinary single-file game", () => {
    expect(discRow(probe([], [SNES9X]), [], SNES9X).show).toBe(false);
  });

  it("offers the set when the core can read one", () => {
    const row = discRow(
      probe(["Game (Disc 1).cue", "Game (Disc 2).cue"],
            [DUCKSTATION]),
      ["Game (Disc 1).cue", "Game (Disc 2).cue"],
      DUCKSTATION,
    );
    expect(row.show).toBe(true);
    expect(row.on).toBe(true);
    expect(row.disabled).toBe(false);
    expect(row.label).toContain("2 discs");
  });

  /*
   * The case that would otherwise be silent: a set was found, but the core
   * chosen cannot load a playlist. Offering the switch here produces a game
   * that will not start, so the row stays and the switch does not.
   */
  /*
   * **Not being able to read a playlist does not make it two games.** That is a
   * statement about what gets launched, not about what the discs are: PCSX2
   * changes disc from its own menu, and what makes that bearable is disc two
   * being in the same folder as disc one rather than wherever it was sent from.
   *
   * So the switch stays on, the playlist is still written -- it is what filing
   * and deleting follow -- and `playlistRuns` is what tells the panel to start
   * a disc instead of it.
   */
  it("keeps a set together for an emulator that cannot read a playlist", () => {
    const row = discRow(
      probe(["Game (Disc 1).cue", "Game (Disc 2).cue"], [PCSX2]),
      ["Game (Disc 1).cue", "Game (Disc 2).cue"],
      PCSX2,
    );
    expect(row.show).toBe(true);
    expect(row.on).toBe(true);
    expect(row.disabled).toBe(false);
    // The one flag the add flow acts on.
    expect(row.playlistRuns).toBe(false);
    // Says where the discs went and where to change them, and names the
    // emulator because that is where you would go to do it.
    expect(row.description).toContain("PCSX2");
    expect(row.description).toContain("one folder");
  });

  it("runs the playlist itself when the core can read one", () => {
    const row = discRow(
      probe(["Game (Disc 1).cue", "Game (Disc 2).cue"], [DUCKSTATION]),
      ["Game (Disc 1).cue", "Game (Disc 2).cue"],
      DUCKSTATION,
    );
    expect(row.playlistRuns).toBe(true);
  });

  /*
   * Xenia takes the same shape as PCSX2, by a different mechanism: it
   * implements `XamLoaderLaunchTitleOnDvd`, so a game split across its discs
   * asks the console for the next one and Xenia serves it from the folder.
   *
   * This was briefly a refusal, on the grounds that Xbox 360 sets are not all
   * the same shape and merging suits only one of them. That is true and was the
   * wrong conclusion: refusing means four library entries under one name, of
   * which three start nothing — the exact thing this feature removes. The
   * switch is the answer to the ambiguity, not a refusal.
   */
  it("keeps a set together for an emulator whose games ask for the next disc", () => {
    const row = discRow(
      probe(["Game (Disc 1).iso", "Game (Disc 2).iso"], [XENIA]),
      ["Game (Disc 1).iso", "Game (Disc 2).iso"],
      XENIA,
    );
    expect(row.on).toBe(true);
    expect(row.disabled).toBe(false);
    expect(row.playlistRuns).toBe(false);
    expect(row.description).toContain("Xenia");
  });

  /*
   * The refusal still has to exist: an emulator that can neither be handed a
   * playlist nor reach the other discs would otherwise get one entry that can
   * only ever play disc one, under a sentence promising otherwise.
   */
  it("refuses the set when the other discs would be unreachable", () => {
    const row = discRow(
      probe(["Game (Disc 1).iso", "Game (Disc 2).iso"], [NO_DISCS]),
      ["Game (Disc 1).iso", "Game (Disc 2).iso"],
      NO_DISCS,
    );
    expect(row.show).toBe(true);
    expect(row.on).toBe(false);
    expect(row.disabled).toBe(true);
    expect(row.description).toContain("each disc on its own");
    expect(row.description).toContain("side by side");
  });

  it("offers the set switched off, whichever kind of emulator it is", () => {
    for (const runner of [DUCKSTATION, PCSX2]) {
      const row = discRow(
        probe(["Game (Disc 1).cue", "Game (Disc 2).cue"], [runner]),
        [],
        runner,
      );
      expect(row.show).toBe(true);
      expect(row.on).toBe(false);
      // Never refused now: a set is always offerable, and what differs is only
      // what starts when you press play.
      expect(row.disabled).toBe(false);
      expect(row.label).toContain("2 discs");
    }
  });

  it("still shows the row when the set is switched off", () => {
    const row = discRow(
      probe(["Game (Disc 1).cue", "Game (Disc 2).cue"], [DUCKSTATION]),
      [],
      DUCKSTATION,
    );
    expect(row.show).toBe(true);
    expect(row.on).toBe(false);
    // Counts what is on disk, not the empty list.
    expect(row.label).toContain("2 discs");
  });

  // The fallback's whole purpose: nothing was detected, the user picked the
  // discs by hand, and the row has to appear for a probe that found nothing.
  it("appears for a hand-built set the rules never saw", () => {
    const row = discRow(
      probe([], [DUCKSTATION]),
      ["FF7 d1.cue", "FF7 d2.cue"],
      DUCKSTATION,
    );
    expect(row.show).toBe(true);
    expect(row.on).toBe(true);
    expect(row.description).toContain("FF7 d2.cue");
  });

  it("says nothing when one disc has been picked and no set was found", () => {
    expect(discRow(probe([], [DUCKSTATION]), ["FF7 d1.cue"], DUCKSTATION).show).toBe(false);
  });
});

describe("withDisc", () => {
  it("seeds the set with the file already chosen", () => {
    expect(withDisc([], "FF7 d1.cue", "FF7 d2.cue")).toEqual(["FF7 d1.cue", "FF7 d2.cue"]);
  });

  it("appends in the order they are picked, which is playlist order", () => {
    expect(withDisc(["a.cue", "b.cue"], "a.cue", "c.cue")).toEqual(["a.cue", "b.cue", "c.cue"]);
  });

  // Null rather than a duplicate: the list already shows it, so there is
  // nothing to report and nothing to change.
  it("is null for a disc already in the set", () => {
    expect(withDisc(["a.cue", "b.cue"], "a.cue", "b.cue")).toBeNull();
    expect(withDisc([], "a.cue", "a.cue")).toBeNull();
  });

  it("is null for nothing", () => {
    expect(withDisc(["a.cue"], "a.cue", "")).toBeNull();
  });
});

describe("coreById", () => {
  it("finds the chosen core, and is undefined before one is chosen", () => {
    const info = probe([], [DUCKSTATION, SNES9X]);
    expect(coreById(info, "snes9x")).toBe(SNES9X);
    expect(coreById(info, "")).toBeUndefined();
    expect(coreById(null, "snes9x")).toBeUndefined();
    expect(coreById(info, "nothing")).toBeUndefined();
  });
});
