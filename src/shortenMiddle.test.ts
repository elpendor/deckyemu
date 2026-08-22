import { describe, expect, it } from "vitest";

import { shortenMiddle } from "./shortenMiddle";

/**
 * Cutting a filename down without throwing away the half that identifies it.
 *
 * The cases that matter are the two real filename shapes: a ROM whose region
 * and revision sit at the end, and a .pkg that does not say what the game is
 * until two thirds of the way in. A trailing ellipsis loses both, which is why
 * this exists rather than the CSS.
 */

describe("shortenMiddle", () => {
  it("leaves a name that already fits completely alone", () => {
    expect(shortenMiddle("Sonic 2.md", 44)).toBe("Sonic 2.md");
  });

  it("leaves a name of exactly the budget alone", () => {
    const exact = "a".repeat(20);
    expect(shortenMiddle(exact, 20)).toBe(exact);
  });

  it("keeps the region and revision a ROM carries at the end", () => {
    const name = "Legend of Zelda, The - Ocarina of Time (USA) (Rev 2).z64";
    const short = shortenMiddle(name, 44);
    expect(short).toHaveLength(44);
    expect(short.startsWith("Legend of Zelda")).toBe(true);
    expect(short.endsWith("(Rev 2).z64")).toBe(true);
  });

  // The shape that defeats a trailing ellipsis outright: everything before the
  // game's name is a product code.
  it("keeps the game a .pkg only names near its end", () => {
    const name = "UP4415-NPUB31749_00-GOATSIMULATORPS3_bg_1_fbd920a6.pkg";
    const short = shortenMiddle(name, 44);
    expect(short).toHaveLength(44);
    expect(short.startsWith("UP4415-NPUB")).toBe(true);
    expect(short.endsWith(".pkg")).toBe(true);
  });

  it("never returns more than the budget", () => {
    for (const length of [45, 60, 120, 400]) {
      expect(shortenMiddle("x".repeat(length), 44)).toHaveLength(44);
    }
  });

  it("marks the cut so a shortened name does not read as the real one", () => {
    expect(shortenMiddle("x".repeat(80), 44)).toContain("…");
  });

  // A name is only ever cut once, and in one place -- two ellipses would read
  // as part of the filename rather than as an edit to it.
  it("cuts in exactly one place", () => {
    expect([...shortenMiddle("y".repeat(200), 44)].filter((c) => c === "…")).toHaveLength(1);
  });

  it("has nothing to do with an empty name", () => {
    expect(shortenMiddle("", 44)).toBe("");
  });

  // Cutting one of these in half yields a replacement character, which reads as
  // a corrupted file rather than a shortened name.
  it("does not split a surrogate pair", () => {
    const name = `${"🎮".repeat(30)}.zip`;
    const short = shortenMiddle(name, 20);
    expect(short).not.toContain("�");
    expect(short).toContain("…");
    expect(short.endsWith(".zip")).toBe(true);
    // Counted in code points, which is what the budget means here.
    expect(Array.from(short)).toHaveLength(20);
  });

  // Degenerate budgets: nothing sensible to return, but nothing that throws or
  // hands back something longer than asked for either.
  it("gives back what it can from a budget too small to cut", () => {
    expect(shortenMiddle("abcdefgh", 3)).toBe("abc");
    expect(shortenMiddle("abcdefgh", 1)).toBe("a");
    expect(shortenMiddle("abcdefgh", 0)).toBe("");
    expect(shortenMiddle("abcdefgh", -5)).toBe("");
  });
});
