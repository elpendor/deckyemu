import { describe, expect, it } from "vitest";

import { buildDate } from "./buildDate";

describe("buildDate", () => {
  it("turns flatpak's timestamp into a date", () => {
    expect(buildDate("2026-07-26 20:53:49 +0000")).toBe("26/07/2026");
  });

  it("ignores the time, which never distinguishes two builds usefully", () => {
    expect(buildDate("2026-08-10 01:18:12 +0000")).toBe("10/08/2026");
    expect(buildDate("2026-08-10 23:59:59 +0000")).toBe("10/08/2026");
  });

  /*
   * The rollback list is chosen from by date, so a row whose date is blank is a
   * row nobody can tell apart from its neighbour. Anything unparseable is shown
   * as it came rather than dropped -- ugly beats absent when the alternative is
   * picking a build at random.
   */
  it("shows what it was given when the shape is not what flatpak prints", () => {
    expect(buildDate("last Tuesday")).toBe("last Tuesday");
    expect(buildDate("2026")).toBe("2026");
    expect(buildDate("26-07-2026")).toBe("26-07-2026");
  });

  it("never returns an empty string for a non-empty input", () => {
    for (const raw of ["x", "2026-07-26", " 2026-07-26 ", "?", "0000-00-00 00:00:00"]) {
      expect(buildDate(raw).length, `empty for ${JSON.stringify(raw)}`).toBeGreaterThan(0);
    }
  });

  it("has nothing to show for nothing", () => {
    expect(buildDate("")).toBe("");
    expect(buildDate("   ")).toBe("");
  });
});
