import { describe, expect, it } from "vitest";

import { importProblems } from "./importProblems";

/**
 * Whether the Emulators tab says anything about a definition it refused.
 *
 * The backend has always collected a reason per refusal; nothing called for
 * them, so every refusal was silent — and a refused definition produces an
 * emulator that never appears, which looks exactly like having sent the wrong
 * file. The reasons are the backend's own sentences and are passed through
 * untouched; what is decided here is whether there is a row at all.
 */

describe("importProblems", () => {
  it("says nothing when nothing was refused", () => {
    expect(importProblems([])).toBeNull();
  });

  // The two ways the backend can answer before it has an answer.
  it("says nothing before the call has come back", () => {
    expect(importProblems(null)).toBeNull();
    expect(importProblems(undefined)).toBeNull();
  });

  it("passes the backend's reason through untouched", () => {
    const reason = "goat.deckyemu.json was not loaded: 'rpcs3' is already a built-in emulator.";
    expect(importProblems([reason])).toEqual({
      label: "A definition was not loaded",
      reasons: [reason],
    });
  });

  it("counts them when there is more than one", () => {
    const result = importProblems(["one broke", "two broke", "three broke"]);
    expect(result?.label).toBe("3 definitions were not loaded");
    expect(result?.reasons).toHaveLength(3);
  });

  it("keeps the order the backend found them in", () => {
    expect(importProblems(["first", "second"])?.reasons).toEqual(["first", "second"]);
  });

  // A blank reason renders as a bullet with nothing after it, which reads as
  // the panel being broken rather than as a definition being refused.
  it("drops a blank reason rather than rendering an empty line", () => {
    expect(importProblems(["real reason", "", "   "])).toEqual({
      label: "A definition was not loaded",
      reasons: ["real reason"],
    });
  });

  it("says nothing when every reason was blank", () => {
    expect(importProblems(["", "  "])).toBeNull();
  });
});
