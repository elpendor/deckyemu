import { describe, expect, it } from "vitest";

import { clampNotes, countItems, parseNotes } from "./releaseNotes";

const NOTES = `## Added
- one
- two

## Fixed
- three
- four
- five`;

describe("parseNotes", () => {
  it("groups bullets under the heading above them", () => {
    expect(parseNotes(NOTES)).toEqual([
      { heading: "Added", items: ["one", "two"] },
      { heading: "Fixed", items: ["three", "four", "five"] },
    ]);
  });

  it("keeps a line that is neither heading nor bullet", () => {
    // The notes are generated today, but a hand-edited release body should show
    // what it says rather than have most of it silently dropped.
    expect(parseNotes("Some prose about the release.")).toEqual([
      { heading: "", items: ["Some prose about the release."] },
    ]);
  });

  it("drops a heading that has nothing under it", () => {
    expect(parseNotes("## Empty\n\n## Real\n- a")).toEqual([
      { heading: "Real", items: ["a"] },
    ]);
  });

  it("has nothing to show for empty notes", () => {
    expect(parseNotes("")).toEqual([]);
    expect(parseNotes("\n\n  \n")).toEqual([]);
  });
});

describe("clampNotes", () => {
  const sections = parseNotes(NOTES);

  it("counts every item across sections", () => {
    expect(countItems(sections)).toBe(5);
  });

  it("takes the first n, keeping them under their own heading", () => {
    expect(clampNotes(sections, 3)).toEqual([
      { heading: "Added", items: ["one", "two"] },
      { heading: "Fixed", items: ["three"] },
    ]);
  });

  // A heading with nothing under it reads as a section that changed nothing,
  // which is worse than not showing the section at all.
  it("never leaves a bare heading", () => {
    expect(clampNotes(sections, 2)).toEqual([
      { heading: "Added", items: ["one", "two"] },
    ]);
    for (let limit = 1; limit <= 6; limit++) {
      for (const section of clampNotes(sections, limit)) {
        expect(section.items.length).toBeGreaterThan(0);
      }
    }
  });

  it("shows everything when the limit is zero", () => {
    expect(clampNotes(sections, 0)).toEqual(sections);
  });

  it("shows everything when the limit exceeds what there is", () => {
    expect(countItems(clampNotes(sections, 99))).toBe(5);
  });

  // The property that matters: clamping must never invent or reorder entries,
  // only stop early.
  it("is a prefix of the full list at every limit", () => {
    const flat = sections.flatMap((s) => s.items);
    for (let limit = 1; limit <= 7; limit++) {
      const got = clampNotes(sections, limit).flatMap((s) => s.items);
      expect(got).toEqual(flat.slice(0, Math.min(limit, flat.length)));
    }
  });
});
