import { describe, expect, it } from "vitest";

import { splitTail, TAIL_CHARS } from "./filenameTail";

/**
 * Deciding how much of a filename's end must survive being cut.
 *
 * The width is the browser's problem -- the head shrinks in a flex row and
 * ellipsizes when it does. What is decided here is only which characters are
 * put out of reach of that, and the rule that matters is that head + tail is
 * always exactly the name: anything else silently renders a filename that is
 * not the file's name.
 */

describe("splitTail", () => {
  it("rejoins to exactly the original, whatever the name", () => {
    for (const name of [
      "",
      "a",
      "Sonic 2.md",
      "Legend of Zelda, The - Ocarina of Time (USA) (Rev 2).z64",
      "UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6.pkg",
      "x".repeat(400),
    ]) {
      expect(splitTail(name).join("")).toBe(name);
    }
  });

  it("keeps a ROM's region and revision out of the cuttable half", () => {
    const [head, tail] = splitTail("Legend of Zelda, The - Ocarina of Time (USA) (Rev 2).z64");
    expect(tail).toBe("(USA) (Rev 2).z64");
    expect(head).toBe("Legend of Zelda, The - Ocarina of Time ");
  });

  it("keeps the extension of a .pkg out of it too", () => {
    const [, tail] = splitTail("UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6.pkg");
    expect(tail.endsWith(".pkg")).toBe(true);
  });

  // Nothing to cut means nothing should be cuttable: an empty head renders as
  // an empty span and the name arrives whole, with no ellipsis anywhere.
  it("makes a short name entirely uncuttable", () => {
    expect(splitTail("Sonic 2.md")).toEqual(["", "Sonic 2.md"]);
    expect(splitTail("")).toEqual(["", ""]);
  });

  it("treats a name of exactly the tail length as short", () => {
    const exact = "a".repeat(TAIL_CHARS);
    expect(splitTail(exact)).toEqual(["", exact]);
  });

  it("splits one character past that", () => {
    const name = "b".repeat(TAIL_CHARS + 1);
    const [head, tail] = splitTail(name);
    expect(head).toBe("b");
    expect(Array.from(tail)).toHaveLength(TAIL_CHARS);
  });

  it("protects the same number of characters however long the name is", () => {
    for (const length of [20, 60, 200]) {
      const [, tail] = splitTail("c".repeat(length));
      expect(Array.from(tail)).toHaveLength(TAIL_CHARS);
    }
  });

  // Splitting between the halves of a surrogate pair puts a replacement
  // character at the end of the head and the start of the tail, which reads as
  // a corrupted filename rather than a shortened one.
  it("does not split a surrogate pair", () => {
    const name = `${"🎮".repeat(30)}.zip`;
    const [head, tail] = splitTail(name);
    expect(head + tail).toBe(name);
    expect(head).not.toContain("�");
    expect(tail).not.toContain("�");
    expect(Array.from(tail)).toHaveLength(TAIL_CHARS);
  });

  it("takes a different tail length when asked", () => {
    expect(splitTail("abcdefghij", 4)).toEqual(["abcdef", "ghij"]);
  });

  // A tail of zero would put the whole name in the shrinking half, which is
  // the plain trailing ellipsis this exists to avoid -- but it must still
  // rejoin correctly rather than throw.
  it("survives a degenerate tail length", () => {
    expect(splitTail("abcdef", 0)).toEqual(["abcdef", ""]);
    expect(splitTail("abcdef", -3).join("")).toBe("abcdef");
  });
});
