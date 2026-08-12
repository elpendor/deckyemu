import { describe, expect, it } from "vitest";

import { type AddedGame } from "./backend";
import { systemLabel } from "./systemLabel";

const game = (fields: Partial<AddedGame>): AddedGame =>
  ({ platform: "", system: "", core_id: "", ...fields } as AddedGame);

/**
 * The fallback chain that decides what a game says it runs on.
 *
 * Each step exists because the one before it can be empty, and the last one
 * exists because the alternative was showing `emu:xemu` to somebody.
 */
describe("systemLabel", () => {
  it("prefers the short platform label", () => {
    expect(systemLabel(game({ platform: "SNES", system: "Nintendo - SNES" }))).toBe("SNES");
  });

  it("falls back to the tail of the libretro database name", () => {
    expect(systemLabel(game({ system: "Nintendo - Super Nintendo Entertainment System" })))
      .toBe("Super Nintendo Entertainment System");
  });

  it("uses a database name with no manufacturer prefix as it stands", () => {
    expect(systemLabel(game({ system: "MAME" }))).toBe("MAME");
  });

  // The namespace is internal bookkeeping and was never meant to be read.
  it("strips the emulator namespace rather than showing it", () => {
    expect(systemLabel(game({ core_id: "emu:xemu" }))).toBe("xemu");
  });

  it("says something rather than nothing when everything is empty", () => {
    expect(systemLabel(game({}))).toBe("Unknown system");
  });
});
