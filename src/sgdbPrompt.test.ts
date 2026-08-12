import { describe, expect, it, vi } from "vitest";

import { SGDB_PROMPT, shouldOfferSgdb } from "./sgdbPrompt";

/*
 * `sgdbKeyJustAppeared` remembers across calls at module scope, so every test
 * of it needs a module nobody has asked yet. A shared import would carry the
 * previous test's answer into the next one, and the first test to run would be
 * the only honest one.
 */
async function freshModule() {
  vi.resetModules();
  return await import("./sgdbPrompt");
}

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

describe("sgdbKeyJustAppeared", () => {
  const withKey = { sgdb_api_key_set: true };
  const without = { sgdb_api_key_set: false };

  /*
   * The whole point of this function. Following the prompt closes the Quick
   * Access panel and unmounts the panel, so the state before the trip has to
   * have been recorded somewhere that survives it. Two calls, an unmount in
   * between, and the transition is still seen.
   */
  it("reports a key arriving after one was missing", async () => {
    const { sgdbKeyJustAppeared } = await freshModule();
    expect(sgdbKeyJustAppeared(without)).toBe(false);
    expect(sgdbKeyJustAppeared(withKey)).toBe(true);
  });

  // A key that was there before the plugin loaded is not news, and looking the
  // artwork up again on the first open of every session would be wrong.
  it("says nothing on the first look, whatever it finds", async () => {
    const { sgdbKeyJustAppeared } = await freshModule();
    expect(sgdbKeyJustAppeared(withKey)).toBe(false);
  });

  /*
   * One shot. The caller re-runs the lookup on a true, so a second true for the
   * same key would run it twice -- and the effect this drives re-fires whenever
   * the ROM or the core changes.
   */
  it("reports the same arrival only once", async () => {
    const { sgdbKeyJustAppeared } = await freshModule();
    sgdbKeyJustAppeared(without);
    expect(sgdbKeyJustAppeared(withKey)).toBe(true);
    expect(sgdbKeyJustAppeared(withKey)).toBe(false);
    expect(sgdbKeyJustAppeared(withKey)).toBe(false);
  });

  // Removing a key and adding another is a real sequence -- an expired key
  // replaced -- and the second arrival matters as much as the first.
  it("reports a later arrival too", async () => {
    const { sgdbKeyJustAppeared } = await freshModule();
    sgdbKeyJustAppeared(without);
    expect(sgdbKeyJustAppeared(withKey)).toBe(true);
    expect(sgdbKeyJustAppeared(without)).toBe(false);
    expect(sgdbKeyJustAppeared(withKey)).toBe(true);
  });

  // Settings still loading tells us nothing, and must not be mistaken for
  // "there was no key" -- that would invent an arrival on the next read.
  it("does not treat a missing answer as no key", async () => {
    const { sgdbKeyJustAppeared } = await freshModule();
    expect(sgdbKeyJustAppeared(null)).toBe(false);
    expect(sgdbKeyJustAppeared(withKey)).toBe(false);
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
