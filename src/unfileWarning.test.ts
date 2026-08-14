import { describe, expect, it } from "vitest";

import { countFiled, strandedSummary, unfileWarning } from "./unfileWarning";

/**
 * The sentence shown before collections are switched off.
 *
 * Tested for the same reason `clearWarning` is: it is the only thing between a
 * toggle and a change across the user's whole library. Unlike that one it
 * describes something reversible, and saying so is part of the job -- a dialog
 * that reads as dangerous when it is not teaches people to dismiss the ones
 * that are.
 */
describe("countFiled", () => {
  it("counts the games and the collections they are spread across", () => {
    expect(countFiled(["SNES", "SNES", "N64"])).toEqual({ games: 3, shelves: 2 });
  });

  it("ignores games that record no collection", () => {
    // Added before the collection was stored, or never filed: there is no shelf
    // to name and nothing the dialog can promise about them.
    expect(countFiled(["SNES", "", undefined])).toEqual({ games: 1, shelves: 1 });
  });

  it("is zero for an empty library, which is what skips the dialog", () => {
    expect(countFiled([])).toEqual({ games: 0, shelves: 0 });
  });

  it("counts one collection holding many games as one", () => {
    expect(countFiled(["DeckyEmu", "DeckyEmu", "DeckyEmu"])).toEqual({
      games: 3,
      shelves: 1,
    });
  });
});

describe("strandedSummary", () => {
  it("says what is there without calling it a problem", () => {
    const text = strandedSummary(47, 12);
    expect(text).toContain("47 games");
    expect(text).toContain("12 collections");
    // Leaving them is a legitimate choice, so the row states a fact rather than
    // reporting an error to be cleared.
    expect(text.toLowerCase()).not.toMatch(/error|wrong|should|problem/);
  });

  it("reads correctly for one of each", () => {
    const text = strandedSummary(1, 1);
    expect(text).toContain("1 game added");
    expect(text).toContain("1 collection.");
    expect(text).not.toContain("1 games");
  });

  it("does not name a count it does not have", () => {
    // Games added before the collection was recorded name no shelf, so the
    // count can legitimately be zero while games are still filed.
    expect(strandedSummary(2, 0)).toContain("still in collections");
    expect(strandedSummary(2, 0)).not.toContain("0 collections");
  });
});

describe("unfileWarning", () => {
  it("names both counts, so the user can recognise a wrong one", () => {
    expect(unfileWarning(47, 12)).toContain("47 games out of 12 collections");
  });

  it("reads correctly for one of each", () => {
    const text = unfileWarning(1, 1);
    expect(text).toContain("1 game out of 1 collection");
    expect(text).not.toContain("1 games");
    expect(text).not.toContain("1 collections");
  });

  it("says what survives, since a collection may hold the user's own games", () => {
    const text = unfileWarning(3, 2);
    expect(text).toContain("left empty is removed");
    expect(text).toContain("games you put there yourself is kept");
  });

  it("says it is reversible, because it is", () => {
    expect(unfileWarning(3, 2)).toContain("switching this back on files them again");
  });

  it("does not claim anything is deleted, because nothing is", () => {
    const text = unfileWarning(9, 3).toLowerCase();
    expect(text).toContain("nothing is deleted from your library");
    expect(text).not.toContain("permanently");
  });
});
