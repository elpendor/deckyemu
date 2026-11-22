import { describe, expect, it } from "vitest";

import { coreById, discSetLabel, discsMustSplit, readsPlaylist, withDisc, withoutDiscTag } from "./discSet";
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

describe("discsMustSplit", () => {
  const discs = ["Game (Disc 1).iso", "Game (Disc 2).iso"];
  it("keeps a set as one game for a core that reads a playlist", () => {
    expect(discsMustSplit(probe(discs, [DUCKSTATION]), DUCKSTATION.id, discs)).toBe(false);
  });
  it("keeps a set as one game for an emulator that changes disc itself", () => {
    expect(discsMustSplit(probe(discs, [PCSX2]), PCSX2.id, discs)).toBe(false);
    expect(discsMustSplit(probe(discs, [XENIA]), XENIA.id, discs)).toBe(false);
  });
  it("splits a set for an emulator that can do neither", () => {
    expect(discsMustSplit(probe(discs, [NO_DISCS]), NO_DISCS.id, discs)).toBe(true);
  });
  it("has nothing to split with fewer than two discs", () => {
    expect(discsMustSplit(probe([], [NO_DISCS]), NO_DISCS.id, ["Game.iso"])).toBe(false);
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

describe("a set's name", () => {
  it("is the game without its disc number", () => {
    expect(withoutDiscTag("Harbor Dash (USA) (Disc 1)")).toBe("Harbor Dash (USA)");
    expect(withoutDiscTag("Harbor Dash [Disc 2 of 3]")).toBe("Harbor Dash");
    expect(withoutDiscTag("Harbor Dash (USA)")).toBe("Harbor Dash (USA)");
  });

  it("says which discs are here", () => {
    expect(discSetLabel(["Harbor Dash (USA) (Disc 1).cue", "Harbor Dash (USA) (Disc 2).cue"]))
      .toBe("Harbor Dash (USA) · Discs 1–2");
    expect(discSetLabel(["Harbor Dash (A).chd", "Harbor Dash (B).chd"]))
      .toBe("Harbor Dash (A) · 2 discs");
  });
});
