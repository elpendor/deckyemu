import { describe, expect, it } from "vitest";

import type { ReceivedFile } from "./backend";
import { addableGroups, groupReceived, ownedCount, ownedNoun } from "./receivedGroups";

/**
 * Folding a CD rip's tracks into the sheet that names them.
 *
 * Worth testing away from the dialog because the failure is silent in both
 * directions: a set that does not fold is thirteen rows offering to make Steam
 * entries out of raw sectors, and a file wrongly folded is a row the user can
 * no longer reach at all.
 */

function file(name: string, size: number, part_of = "", folder = "/inbox"): ReceivedFile {
  return { name, path: `${folder}/${name}`, size, at: 0, part_of };
}

describe("groupReceived", () => {
  it("folds a disc's tracks into its sheet and totals the set", () => {
    const groups = groupReceived([
      file("Sunset Circuit (USA).cue", 2_000),
      file("Sunset Circuit (USA) (Track 01).bin", 400_000, "Sunset Circuit (USA).cue"),
      file("Sunset Circuit (USA) (Track 02).bin", 30_000, "Sunset Circuit (USA).cue"),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].file.name).toBe("Sunset Circuit (USA).cue");
    expect(groups[0].tracks.map((one) => one.name)).toEqual([
      "Sunset Circuit (USA) (Track 01).bin",
      "Sunset Circuit (USA) (Track 02).bin",
    ]);
    // The row reports the game, not the two kilobytes of text naming it.
    expect(groups[0].size).toBe(432_000);
  });

  it("leaves a file nothing names as its own row", () => {
    const groups = groupReceived([file("Neon Harbor (USA).z64", 48_000)]);

    expect(groups).toHaveLength(1);
    expect(groups[0].tracks).toEqual([]);
    expect(groups[0].size).toBe(48_000);
  });

  it("keeps a track whose sheet has not arrived", () => {
    // The row the reader most needs: raw sectors with nothing to assemble them,
    // and nothing about the file says so. Hiding it would hide the problem.
    const groups = groupReceived([file("Sunset Circuit (USA) (Track 01).bin", 400_000)]);

    expect(groups.map((one) => one.file.name)).toEqual([
      "Sunset Circuit (USA) (Track 01).bin",
    ]);
  });

  it("does not fold a track onto a sheet in another folder", () => {
    // `part_of` is a bare filename, because that is what a playlist may hold.
    // Two folders each holding a Game.cue must stay two games.
    const groups = groupReceived([
      file("Game.cue", 2_000, "", "/inbox"),
      file("Game.bin", 400_000, "Game.cue", "/firmware"),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0].tracks).toEqual([]);
    expect(groups[1].file.name).toBe("Game.bin");
  });

  it("keeps the order the backend listed, which is newest first", () => {
    const groups = groupReceived([
      file("Neon Harbor (USA).z64", 48_000),
      file("Sunset Circuit (USA).cue", 2_000),
      file("Sunset Circuit (USA) (Track 01).bin", 400_000, "Sunset Circuit (USA).cue"),
    ]);

    expect(groups.map((one) => one.file.name)).toEqual([
      "Neon Harbor (USA).z64",
      "Sunset Circuit (USA).cue",
    ]);
  });

  it("folds the discs of one game into one row, in disc order", () => {
    const disc = (number: number, at: number) => ({
      ...file(`Harbor Dash (USA) (Disc ${number}).cue`, 1_000),
      at,
      disc_set: "Harbor Dash (USA).cue",
      disc_title: "Harbor Dash (USA)",
      disc_number: number,
    });
    const groups = groupReceived([
      disc(2, 2),
      file("Harbor Dash (USA) (Disc 2).bin", 500_000, "Harbor Dash (USA) (Disc 2).cue"),
      disc(1, 1),
      file("Harbor Dash (USA) (Disc 1).bin", 400_000, "Harbor Dash (USA) (Disc 1).cue"),
      file("Other.chd", 10),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0].title).toBe("Harbor Dash (USA)");
    expect(groups[0].discs?.map((one) => one.disc_number)).toEqual([1, 2]);
    expect(groups[0].size).toBe(902_000);
    expect(groups[1].file.name).toBe("Other.chd");
  });

  it("leaves a lone disc, or a disc of a game already added, as its own row", () => {
    const lone = { ...file("Harbor Dash (USA) (Disc 1).cue", 1), disc_set: "x", disc_number: 1 };
    expect(groupReceived([lone])[0].discs).toBeUndefined();
    const joining = { ...lone, disc_for: { app_id: 1, title: "Harbor Dash", disc: 2 } };
    const other = { ...file("Harbor Dash (USA) (Disc 2).cue", 1), disc_set: "x", disc_number: 2 };
    expect(groupReceived([joining, other] as ReceivedFile[]).map((one) => one.discs)).toEqual([undefined, undefined]);
  });

  it("is empty for an empty list, which is what hides the section", () => {
    expect(groupReceived([])).toEqual([]);
  });
});

describe("ownedNoun", () => {
  it("calls what a sheet names a track", () => {
    expect(ownedNoun("Sunset Circuit (USA).cue")).toBe("track");
    expect(ownedNoun("Sunset Circuit (USA).gdi")).toBe("track");
  });

  it("calls what a playlist names a file, because it is sheets and tracks both", () => {
    expect(ownedNoun("Sunset Circuit (USA).m3u")).toBe("file");
    expect(ownedNoun("SUNSET CIRCUIT.M3U")).toBe("file");
  });
});

describe("ownedCount", () => {
  it("counts in the words the row uses", () => {
    expect(ownedCount("Game.cue", 12)).toBe("12 tracks");
    expect(ownedCount("Game.cue", 1)).toBe("1 track");
    expect(ownedCount("Game.m3u", 26)).toBe("26 files");
  });
});

describe("addableGroups", () => {
  const groups = groupReceived([
    file("Sunset Circuit (USA).cue", 2_000),
    file("Sunset Circuit (USA) (Track 01).bin", 400_000, "Sunset Circuit (USA).cue"),
    file("Harbor Dash.sfc", 1_000),
    file("bios.bin", 512),
    file("Harbor Dash.ips", 64),
    file("Harbor Dash.rap", 16),
    file("ports.deckyemu.json", 8),
    { ...file("Sunset Circuit (Disc 2).cue", 2_000), disc_for: { app_id: 1, title: "Sunset Circuit", disc: 2 } },
  ]);
  const firmware = (name: string) => name === "bios.bin";

  it("takes only the rows whose button is plain Add", () => {
    expect(addableGroups(groups, "roms", firmware).map(({ file: one }) => one.name)).toEqual([
      "Sunset Circuit (USA).cue",
      "Harbor Dash.sfc",
    ]);
  });

  it("takes nothing from a firmware or backup send", () => {
    expect(addableGroups(groups, "firmware", firmware)).toEqual([]);
    expect(addableGroups(groups, "backup", firmware)).toEqual([]);
  });
});
