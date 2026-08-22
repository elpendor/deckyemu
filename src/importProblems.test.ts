import { describe, expect, it } from "vitest";

import { importProblems } from "./importProblems";

/**
 * Whether the Emulators tab says anything about a definition it refused, and
 * whether it says it in a shape anybody can act on.
 *
 * The backend has always collected a reason per fault and put them on separate
 * lines; nothing called for them, so every refusal was silent. Wiring it up was
 * not the whole job: rendered as one string in one element, HTML collapses
 * every newline to a space, and a definition missing three fields arrives as a
 * single run-on sentence. The split is checked here because that is the part
 * with a rule in it — the words themselves are the backend's and pass through.
 */

// What `imported.load` actually produces: the filename on its own line, then
// one line per fault from `schema.validate`.
const REAL = [
  "zz-clash.deckyemu.json was not loaded:",
  "rpcs3: missing required field 'summary' -- One line under the name.",
  "rpcs3: missing required field 'args' -- Launch arguments, with `{rom}`.",
  "rpcs3: needs 'root' -- the directory under home this emulator owns.",
].join("\n");

describe("importProblems", () => {
  it("says nothing when nothing was refused", () => {
    expect(importProblems([])).toBeNull();
  });

  // The two ways the backend can answer before it has an answer.
  it("says nothing before the call has come back", () => {
    expect(importProblems(null)).toBeNull();
    expect(importProblems(undefined)).toBeNull();
  });

  it("puts the filename on its own and each fault under it", () => {
    const result = importProblems([REAL]);
    expect(result?.refusals).toHaveLength(1);
    expect(result?.refusals[0].headline).toBe("zz-clash.deckyemu.json was not loaded:");
    expect(result?.refusals[0].details).toHaveLength(3);
    expect(result?.refusals[0].details[2]).toContain("needs 'root'");
  });

  it("passes the backend's words through untouched", () => {
    const detail = "rpcs3: missing required field 'summary' -- One line under the name.";
    expect(importProblems([`file.deckyemu.json was not loaded:\n${detail}`])
      ?.refusals[0].details[0]).toBe(detail);
  });

  // A refusal the backend states in one line: unreadable, or too large. There
  // is nothing under the headline and the row must not imply there is.
  it("leaves details empty for a single-line refusal", () => {
    const result = importProblems(["broken.deckyemu.json could not be read: no such file"]);
    expect(result?.refusals[0].headline).toBe(
      "broken.deckyemu.json could not be read: no such file",
    );
    expect(result?.refusals[0].details).toEqual([]);
  });

  // Counted in files rather than in faults: three missing fields in one
  // definition is one file to go and fix, and saying "3 definitions" would send
  // the reader looking for two that do not exist.
  it("counts files, not faults", () => {
    expect(importProblems([REAL])?.label).toBe("A definition was not loaded");
    expect(importProblems([REAL, REAL])?.label).toBe("2 definitions were not loaded");
  });

  it("keeps the order the backend found them in", () => {
    expect(importProblems(["first", "second"])?.refusals.map((r) => r.headline))
      .toEqual(["first", "second"]);
  });

  // A blank line renders as a gap in the middle of a list of faults, which
  // reads as the panel being broken rather than as a definition being refused.
  it("drops blank lines rather than rendering gaps", () => {
    const result = importProblems(["file.json was not loaded:\n\n  \nthe only fault\n"]);
    expect(result?.refusals[0].headline).toBe("file.json was not loaded:");
    expect(result?.refusals[0].details).toEqual(["the only fault"]);
  });

  it("says nothing when a problem was entirely blank", () => {
    expect(importProblems(["", "  \n \n"])).toBeNull();
  });

  it("keeps a real refusal even when a blank one arrives beside it", () => {
    const result = importProblems(["", "real.json was not loaded:\nbecause"]);
    expect(result?.label).toBe("A definition was not loaded");
    expect(result?.refusals).toHaveLength(1);
  });
});
