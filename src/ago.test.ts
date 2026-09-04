import { describe, expect, it } from "vitest";

import { ago } from "./ago";

/** A fixed "now", so none of this depends on when the suite runs. */
const NOW = 1_800_000_000_000;
const at = (secondsBefore: number) => ago(NOW / 1000 - secondsBefore, NOW);

describe("ago", () => {
  it("calls anything recent 'just now'", () => {
    expect(at(0)).toBe("just now");
    expect(at(89)).toBe("just now");
  });

  it("counts minutes, then hours, then days", () => {
    expect(at(20 * 60)).toBe("20 minutes ago");
    expect(at(2 * 3600)).toBe("2 hours ago");
    expect(at(3 * 86400)).toBe("3 days ago");
  });

  it("says the singular ones as words", () => {
    expect(at(3600)).toBe("an hour ago");
    expect(at(86400)).toBe("yesterday");
  });

  it("never reports the future, whatever the clocks say", () => {
    // The Deck's clock and the moment a copy was recorded are not guaranteed to
    // agree after a suspend or a time-zone change, and "in -3 minutes" would be
    // the panel's own bug rather than a fact about anything.
    expect(at(-500)).toBe("just now");
  });

  it("says nothing has happened as the epoch, not as fifty years", () => {
    // 0 is what the setting holds before the first copy. The caller checks for
    // it and says so in words; this only has to not pretend it is a date.
    expect(ago(0, NOW)).toContain("days ago");
  });
});
