import { describe, expect, it } from "vitest";

import { countStranded, unfileWarning } from "./unfileWarning";

/**
 * The sentence shown before collections are switched off.
 *
 * Tested for the same reason `clearWarning` is: it is the only thing between a
 * toggle and a change across the user's whole library. Unlike that one it
 * describes something reversible, and saying so is part of the job -- a dialog
 * that reads as dangerous when it is not teaches people to dismiss the ones
 * that are.
 */
describe("countStranded", () => {
  const out = (from: string) => ({ from, to: "" });

  it("counts the games and the collections they are spread across", () => {
    expect(
      countStranded([out("SNES"), out("SNES"), out("N64")]),
    ).toEqual({ games: 3, shelves: 2 });
  });

  it("ignores moves that are going somewhere", () => {
    // A plan can hold both when the name changed and the switch did not, and
    // only the ones leaving are what this dialog is about.
    expect(
      countStranded([out("SNES"), { from: "Old", to: "New" }]),
    ).toEqual({ games: 1, shelves: 1 });
  });

  it("counts a game whose old collection was never recorded", () => {
    // Added by a build before the collection was stored: it still has to be
    // taken out, but it names no shelf to count.
    expect(countStranded([out(""), out("SNES")])).toEqual({ games: 2, shelves: 1 });
  });

  it("is zero for an empty plan, which is what skips the dialog", () => {
    expect(countStranded([])).toEqual({ games: 0, shelves: 0 });
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
