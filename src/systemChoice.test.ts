import { describe, expect, it } from "vitest";

import { adoptedSystemId, initialSystemId, systemFields } from "./systemChoice";
import type { CustomEmulator, SystemOption } from "./backend";

/**
 * The Vita is the case that broke, and it is not a corner.
 *
 * `list_systems` offers a synthetic `~short` row only for a system libretro
 * does *not* know, so the two are never listed twice. The Vita is in both
 * lists, so only the libretro row survives — and a Vita3K record says
 * `platform: "Vita"`, which asks for the row that was dropped.
 */
const VITA_LIBRETRO: SystemOption = {
  id: "Sony - PlayStation Vita",
  database: "Sony - PlayStation Vita",
  label: "Sony - PlayStation Vita",
  short: "Vita",
  full: "PlayStation Vita",
  libretro: true,
};

const SWITCH_SYNTHETIC: SystemOption = {
  id: "~Switch",
  database: "",
  label: "Nintendo - Switch",
  short: "Switch",
  full: "Nintendo Switch",
  libretro: false,
};

const SYSTEMS = [VITA_LIBRETRO, SWITCH_SYNTHETIC];

const VITA3K = {
  id: "vita3k",
  databases: [],
  platform: "Vita",
  platform_full: "PlayStation Vita",
} as unknown as CustomEmulator;

describe("initialSystemId", () => {
  it("prefers a libretro database when the record has one", () => {
    expect(
      initialSystemId({ databases: ["Sony - PlayStation 2"] } as unknown as CustomEmulator),
    ).toBe("Sony - PlayStation 2");
  });

  it("falls back to the synthetic id for a platform-only record", () => {
    expect(initialSystemId(VITA3K)).toBe("~Vita");
  });

  it("is empty for a record with neither", () => {
    expect(initialSystemId({} as CustomEmulator)).toBe("");
  });
});

describe("adoptedSystemId", () => {
  // The bug: "~Vita" names no row, so the picker showed "None" for an emulator
  // whose system was set.
  it("finds the libretro row when the synthetic one was dropped", () => {
    expect(adoptedSystemId(SYSTEMS, "~Vita", VITA3K)).toBe("Sony - PlayStation Vita");
  });

  it("leaves an id that already names a row alone", () => {
    expect(adoptedSystemId(SYSTEMS, "~Switch", VITA3K)).toBe("");
  });

  it("adopts nothing before the list has loaded", () => {
    expect(adoptedSystemId(null, "~Vita", VITA3K)).toBe("");
  });

  // Guessing would be worse than showing nothing: a wrong system silently
  // changes the collection a game is filed into and where its artwork comes
  // from.
  it("adopts nothing when no row matches the record", () => {
    expect(
      adoptedSystemId(SYSTEMS, "~Dreamcast", {
        platform: "Dreamcast",
        platform_full: "Sega Dreamcast",
      } as unknown as CustomEmulator),
    ).toBe("");
  });
});

describe("systemFields", () => {
  // The data loss. Opening Vita3K's editor and pressing Save wrote this back,
  // and the record lost the system it had.
  it("keeps what the record had when the id resolves to nothing", () => {
    expect(systemFields("~Vita", undefined, VITA3K)).toEqual({
      databases: [],
      platform: "Vita",
      platform_full: "PlayStation Vita",
    });
  });

  it("clears the system when None was actually chosen", () => {
    expect(systemFields("", undefined, VITA3K)).toEqual({
      databases: [],
      platform: "",
      platform_full: "",
    });
  });

  it("stores the database for a libretro system and no label", () => {
    expect(systemFields(VITA_LIBRETRO.id, VITA_LIBRETRO, VITA3K)).toEqual({
      databases: ["Sony - PlayStation Vita"],
      platform: "",
      platform_full: "",
    });
  });

  // The other direction: libretro has no database to derive a label from, so
  // the label is what gets stored.
  it("stores the label for a system libretro does not know", () => {
    expect(systemFields(SWITCH_SYNTHETIC.id, SWITCH_SYNTHETIC, VITA3K)).toEqual({
      databases: [],
      platform: "Switch",
      platform_full: "Nintendo Switch",
    });
  });
});
