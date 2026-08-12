import { describe, expect, it } from "vitest";

import { SGDB_PROMPT, shouldOfferSgdb } from "./sgdbPrompt";

describe("shouldOfferSgdb", () => {
  it("offers when no key is stored", () => {
    expect(shouldOfferSgdb({ sgdb_api_key_set: false })).toBe(true);
  });

  /*
   * The prompt has to remove itself the moment a key exists. There is no
   * dismissal flag anywhere and no need for one: the row asks for exactly one
   * thing, so having done it is the only signal required.
   */
  it("goes away once there is one", () => {
    expect(shouldOfferSgdb({ sgdb_api_key_set: true })).toBe(false);
  });

  // A prompt that flashes up while settings load and then disappears looks like
  // a bug, and the answer is unknown until they arrive.
  it("says nothing until settings have loaded", () => {
    expect(shouldOfferSgdb(null)).toBe(false);
    expect(shouldOfferSgdb(undefined)).toBe(false);
  });
});

describe("the wording", () => {
  /*
   * The claim has to be the one that is true. libretro's thumbnails are box
   * scans and can be the better picture; what they cannot be is four images.
   * "Sharper" or "better quality" would be a promise this cannot keep, so the
   * copy is checked for it rather than left to drift back in later.
   */
  it("promises coverage rather than quality", () => {
    const copy = `${SGDB_PROMPT.label} ${SGDB_PROMPT.description}`.toLowerCase();
    for (const claim of ["sharper", "higher quality", "better quality", "crisp", "hd"]) {
      expect(copy).not.toContain(claim);
    }
    expect(copy).toContain("banner");
    expect(copy).toContain("logo");
  });

  it("says the key costs nothing, because that is the objection", () => {
    expect(SGDB_PROMPT.description.toLowerCase()).toContain("free");
  });
});
