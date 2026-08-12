import { describe, expect, it } from "vitest";

import { type CustomEmulator } from "./backend";
import { originLabel, registeredDescription, systemLabel } from "./registeredEmulator";

function emulator(overrides: Partial<CustomEmulator> = {}): CustomEmulator {
  return {
    id: "dolphin",
    name: "Dolphin",
    kind: "flatpak",
    target: "org.DolphinEmu.dolphin-emu",
    args: "{rom}",
    extensions: ["iso", "rvz"],
    databases: [],
    platform: "",
    platform_full: "",
    fullscreen_args: "",
    from_catalog: false,
    ...overrides,
  };
}

describe("systemLabel", () => {
  it("prefers the libretro database name", () => {
    expect(systemLabel(emulator({ databases: ["Nintendo - GameCube"] }))).toBe(
      "Nintendo - GameCube",
    );
  });

  /*
   * The regression this fallback exists for: libretro has no database for the
   * Switch, Wii U or PS3, so those store a label directly. Reading only
   * `databases` reported "No system set" for a Switch emulator that had Nintendo
   * Switch selected, which reads like the setting did not save.
   */
  it("falls back to the stored label for systems libretro does not cover", () => {
    expect(systemLabel(emulator({ platform_full: "Nintendo Switch" }))).toBe("Nintendo Switch");
    expect(systemLabel(emulator({ platform: "Switch" }))).toBe("Switch");
  });

  it("says so when there is genuinely nothing set", () => {
    expect(systemLabel(emulator())).toBe("No system set");
  });
});

describe("originLabel", () => {
  // The whole point of the field: it is what explains why an emulator appears
  // in this list and in the catalog list above it at the same time.
  it("distinguishes a catalog install from one described by hand", () => {
    expect(originLabel(emulator({ from_catalog: true }))).toBe("from the catalog");
    expect(originLabel(emulator({ from_catalog: false }))).toBe("added by hand");
  });
});

describe("registeredDescription", () => {
  it("reads as system then origin", () => {
    const row = registeredDescription(
      emulator({ databases: ["Nintendo - GameCube"], from_catalog: true }),
    );
    expect(row).toBe("Nintendo - GameCube · from the catalog");
  });

  /*
   * Every row the same shape. Extensions on some rows and not others was the
   * shape that got rejected -- a list whose rows differ structurally reads as
   * something being broken rather than as a distinction being drawn.
   */
  it("has the same shape whatever the emulator is", () => {
    const rows = [
      registeredDescription(emulator({ databases: ["Sony - PlayStation 2"], from_catalog: true })),
      registeredDescription(emulator({ platform_full: "Nintendo Switch" })),
      registeredDescription(emulator()),
    ];
    for (const row of rows) {
      expect(row.split(" · ")).toHaveLength(2);
    }
  });

  // The redundancy that started this: these are already on the catalog row
  // above, and repeating them made the second list look like a copy of the first.
  it("never repeats the file extensions", () => {
    const row = registeredDescription(emulator({ extensions: ["iso", "rvz", "gcm"] }));
    for (const extension of ["iso", "rvz", "gcm"]) {
      expect(row).not.toContain(extension);
    }
  });
});
