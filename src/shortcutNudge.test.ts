import { describe, expect, it } from "vitest";

import { shortcutNudge, type ShortcutCounts } from "./shortcutNudge";

const counts = (over: Partial<ShortcutCounts> = {}): ShortcutCounts => ({
  unknown: 0,
  dead: 0,
  duplicate: 0,
  orphan: 0,
  ...over,
});

describe("when it says nothing", () => {
  // The normal state, and by far the most common one. A row that is always
  // there saying everything is fine is a row in the way of adding a game.
  it("says nothing when the registry accounts for everything", () => {
    expect(shortcutNudge(counts())).toBeNull();
  });

  // The panel opens before the backend answers, and a line that appears a
  // moment later and then vanishes reads as a glitch.
  it("says nothing before the counts arrive", () => {
    expect(shortcutNudge(null)).toBeNull();
    expect(shortcutNudge(undefined)).toBeNull();
  });
});

describe("what it says", () => {
  it("leads with how many there are", () => {
    const nudge = shortcutNudge(counts({ unknown: 21, dead: 20, duplicate: 1 }));
    expect(nudge?.label).toContain("21");
  });

  /*
   * Each kind wants a different decision, so each is counted separately. A bare
   * total would put "cannot start" and "still plays" behind the same sentence,
   * and only one of those is safe to sweep up without reading.
   */
  it("breaks the total down by what can be done about it", () => {
    const nudge = shortcutNudge(counts({ unknown: 23, dead: 20, duplicate: 1, orphan: 2 }));
    expect(nudge?.description).toContain("20 cannot start");
    expect(nudge?.description).toContain("1 is a duplicate");
    expect(nudge?.description).toContain("2 still play");
  });

  it("mentions only the kinds that are actually present", () => {
    const nudge = shortcutNudge(counts({ unknown: 2, duplicate: 2 }));
    expect(nudge?.description).toContain("2 are duplicates");
    expect(nudge?.description).not.toContain("cannot start");
    expect(nudge?.description).not.toContain("no longer tracked");
  });

  it("says where to go", () => {
    const nudge = shortcutNudge(counts({ unknown: 1, dead: 1 }));
    expect(nudge?.description).toContain("Library");
  });
});

describe("the grammar", () => {
  /*
   * One of these is the single most likely count -- a duplicate appears the
   * first time a game is re-added -- so "1 shortcuts needs attention" would be
   * the version most people see.
   */
  it("reads correctly for exactly one", () => {
    const nudge = shortcutNudge(counts({ unknown: 1, duplicate: 1 }));
    expect(nudge?.label).toBe("1 Steam shortcut needs attention");
    expect(nudge?.description).toContain("1 is a duplicate of a game");
  });

  it("reads correctly for more than one", () => {
    const nudge = shortcutNudge(counts({ unknown: 3, dead: 3 }));
    expect(nudge?.label).toBe("3 Steam shortcuts need attention");
    expect(nudge?.description).toContain("launcher scripts are gone");
  });

  it("uses the singular for one of a kind", () => {
    expect(shortcutNudge(counts({ unknown: 1, dead: 1 }))?.description).toContain(
      "launcher script is gone",
    );
    expect(shortcutNudge(counts({ unknown: 1, orphan: 1 }))?.description).toContain(
      "1 still plays but is no longer tracked",
    );
  });
});
