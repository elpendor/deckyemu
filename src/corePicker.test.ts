import { describe, expect, it } from "vitest";

import { type Core } from "./backend";
import { coreOptions, isEmulatorId } from "./corePicker";

const core = (id: string, display_name: string, system_name = ""): Core =>
  ({ id, display_name, system_name } as Core);

/** Group headings only; a flat list has none. */
const headings = (options: ReturnType<typeof coreOptions>) =>
  options.filter((o) => "options" in o).map((o) => (o as { label: string }).label);

describe("coreOptions", () => {
  it("separates emulators from cores when both are present", () => {
    const options = coreOptions([
      core("snes9x", "Snes9x", "Super Nintendo"),
      core("emu:rpcs3", "RPCS3", "PlayStation 3"),
    ]);
    // Emulators first: an emulator is the specific answer for a system, where
    // the core list is long and mostly beside the point for any one file.
    expect(headings(options)).toEqual(["Emulators", "RetroArch cores"]);
  });

  // A heading over a list where everything is the same kind is a row of noise,
  // and with one emulator installed and no cores that is the normal case.
  it("stays flat when only one kind is present", () => {
    expect(headings(coreOptions([core("snes9x", "Snes9x")]))).toEqual([]);
    expect(headings(coreOptions([core("emu:rpcs3", "RPCS3")]))).toEqual([]);
    expect(headings(coreOptions([]))).toEqual([]);
  });

  it("loses nothing when it groups", () => {
    const cores = [
      core("snes9x", "Snes9x"),
      core("emu:rpcs3", "RPCS3"),
      core("genesis_plus_gx", "Genesis Plus GX"),
    ];
    const flat = coreOptions(cores).flatMap((o) =>
      "options" in o ? (o as { options: { data: unknown }[] }).options : [o],
    );
    expect(flat.map((o) => o.data).sort()).toEqual(
      ["emu:rpcs3", "genesis_plus_gx", "snes9x"],
    );
  });

  it("appends the system to the label only when there is one", () => {
    const [withSystem, without] = coreOptions([
      core("snes9x", "Snes9x", "Super Nintendo"),
      core("mame", "MAME"),
    ]) as { label: string }[];
    expect(withSystem.label).toBe("Snes9x - Super Nintendo");
    expect(without.label).toBe("MAME");
  });
});

describe("isEmulatorId", () => {
  it("keys on the namespace the backend applies", () => {
    expect(isEmulatorId("emu:rpcs3")).toBe(true);
    expect(isEmulatorId("snes9x")).toBe(false);
    // Not a substring test: a core whose name merely contains the prefix is a
    // core, and treating it as an emulator would file it under the wrong group.
    expect(isEmulatorId("nemu:thing")).toBe(false);
    expect(isEmulatorId("")).toBe(false);
  });
});
