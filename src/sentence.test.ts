import { describe, expect, it } from "vitest";

import { sentence } from "./sentence";

/**
 * Two toasts are assembled from fragments as things happen, and a fragment that
 * reads correctly in the middle of a list reads wrongly at the front of one.
 * Saving a renamed game said "renamed", with "Saved." as the fallback two lines
 * below it in the same call.
 */
describe("sentence", () => {
  it("capitalises a fragment that ended up first", () => {
    expect(sentence("renamed")).toBe("Renamed.");
    expect(sentence("renamed, moved to [DeckyEmu] Game Boy")).toBe(
      "Renamed, moved to [DeckyEmu] Game Boy.",
    );
  });

  it("leaves the fragments after it alone", () => {
    // They are a list, not sentences of their own.
    expect(sentence("no artwork found - could not add it to its collection")).toBe(
      "No artwork found - could not add it to its collection.",
    );
  });

  /*
   * A body opening with a count is already right, and one opening with a
   * filename must not be touched at all -- `tobudx.gb` is not `Tobudx.gb`, and
   * on a case-sensitive filesystem the difference is a file that does not
   * exist.
   */
  it("does not touch something that does not start with a letter", () => {
    expect(sentence("3 artwork image(s) applied")).toBe("3 artwork image(s) applied.");
    expect(sentence("[DeckyEmu] SNES was emptied")).toBe("[DeckyEmu] SNES was emptied.");
  });

  // The cost of the rule, written down rather than glossed: a fragment opening
  // with a deliberately lowercase name gets capitalised too. Worth it while the
  // fragments are the plugin's own words -- "renamed", "moved to", "no artwork
  // found" -- and worth revisiting if one ever starts with a game's title.
  it("capitalises even a name spelled lowercase, which the rule cannot know", () => {
    expect(sentence("iMUSE was enabled")).toBe("IMUSE was enabled.");
  });

  it("does not add a second full stop", () => {
    expect(sentence("Saved.")).toBe("Saved.");
    expect(sentence("Did that work?")).toBe("Did that work?");
    expect(sentence("Done!")).toBe("Done!");
  });

  it("says nothing when there is nothing to say", () => {
    // An empty body is better than a lone full stop.
    expect(sentence("")).toBe("");
    expect(sentence("   ")).toBe("");
  });
});
