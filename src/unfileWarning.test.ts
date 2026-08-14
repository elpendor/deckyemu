import { describe, expect, it } from "vitest";

import { shouldConfirmUnfile, unfileWarning } from "./unfileWarning";

/**
 * The sentence shown before collections are switched off.
 *
 * Tested for the same reason `clearWarning` is: it is the only thing between a
 * toggle and a change across the user's whole library. Unlike that one it
 * describes something reversible, and saying so is part of the job -- a dialog
 * that reads as dangerous when it is not teaches people to dismiss the ones
 * that are.
 */
describe("shouldConfirmUnfile", () => {
  it("asks when there is something to take out", () => {
    expect(shouldConfirmUnfile(1)).toBe(true);
    expect(shouldConfirmUnfile(47)).toBe(true);
  });

  it("does not ask when nothing is filed", () => {
    // The setting only affects what happens from now on, so there would be
    // nothing for the user to agree to.
    expect(shouldConfirmUnfile(0)).toBe(false);
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
