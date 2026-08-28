import { describe, expect, it } from "vitest";

/**
 * What each check is really asserting: the text of each item, and whether it was
 * written as a list entry. Comparing the full shape would make every one of
 * these a test of the span splitting as well, which has checks of its own.
 */
const plain = (sections: { heading: string; items: { spans: { text: string }[] }[] }[]) =>
  sections.map((section) => ({
    heading: section.heading,
    items: section.items.map((item) => item.spans.map((run) => run.text).join("")),
  }));

import { clampNotes, countItems, inlineSpans, parseNotes } from "./releaseNotes";

const NOTES = `## Added
- one
- two

## Fixed
- three
- four
- five`;

describe("parseNotes", () => {
  it("groups bullets under the heading above them", () => {
    expect(plain(parseNotes(NOTES))).toEqual([
      { heading: "Added", items: ["one", "two"] },
      { heading: "Fixed", items: ["three", "four", "five"] },
    ]);
  });

  it("keeps a line that is neither heading nor bullet", () => {
    // The notes are generated today, but a hand-edited release body should show
    // what it says rather than have most of it silently dropped.
    expect(plain(parseNotes("Some prose about the release."))).toEqual([
      { heading: "", items: ["Some prose about the release."] },
    ]);
  });

  it("drops a heading that has nothing under it", () => {
    expect(plain(parseNotes("## Empty\n\n## Real\n- a"))).toEqual([
      { heading: "Real", items: ["a"] },
    ]);
  });

  it("has nothing to show for empty notes", () => {
    expect(plain(parseNotes(""))).toEqual([]);
    expect(plain(parseNotes("\n\n  \n"))).toEqual([]);
  });
});

describe("clampNotes", () => {
  const sections = parseNotes(NOTES);

  it("counts every item across sections", () => {
    expect(countItems(sections)).toBe(5);
  });

  it("takes the first n, keeping them under their own heading", () => {
    expect(plain(clampNotes(sections, 3))).toEqual([
      { heading: "Added", items: ["one", "two"] },
      { heading: "Fixed", items: ["three"] },
    ]);
  });

  // A heading with nothing under it reads as a section that changed nothing,
  // which is worse than not showing the section at all.
  it("never leaves a bare heading", () => {
    expect(plain(clampNotes(sections, 2))).toEqual([
      { heading: "Added", items: ["one", "two"] },
    ]);
    for (let limit = 1; limit <= 6; limit++) {
      for (const section of clampNotes(sections, limit)) {
        expect(section.items.length).toBeGreaterThan(0);
      }
    }
  });

  it("shows everything when the limit is zero", () => {
    expect(plain(clampNotes(sections, 0))).toEqual(plain(sections));
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

describe("inlineSpans", () => {
  it("splits a bold run out of a line", () => {
    expect(inlineSpans("**Save data** can now leave the Deck")).toEqual([
      { text: "Save data", bold: true },
      { text: " can now leave the Deck", bold: false },
    ]);
  });

  it("handles a line that is entirely bold", () => {
    expect(inlineSpans("**All of it**")).toEqual([{ text: "All of it", bold: true }]);
  });

  it("leaves a line with no emphasis alone", () => {
    expect(inlineSpans("nothing special")).toEqual([
      { text: "nothing special", bold: false },
    ]);
  });

  // A stray asterisk in prose is likelier than an unclosed emphasis, and
  // swallowing the rest of the line to guess otherwise would lose the text.
  it("leaves an unpaired marker exactly as typed", () => {
    expect(inlineSpans("2 ** 8 is 256")).toEqual([{ text: "2 ** 8 is 256", bold: false }]);
  });

  it("takes more than one run", () => {
    expect(inlineSpans("**a** and **b**")).toEqual([
      { text: "a", bold: true },
      { text: " and ", bold: false },
      { text: "b", bold: true },
    ]);
  });
});
