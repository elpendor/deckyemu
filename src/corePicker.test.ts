import { describe, expect, it } from "vitest";

import { type Core, type InstallableCore } from "./backend";
import { coreOptions, installableOptions, isEmulatorId } from "./corePicker";

const core = (id: string, display_name: string, system_name = ""): Core =>
  ({ id, display_name, system_name } as Core);

const installable = (id: string, display_name: string, system_name = ""): InstallableCore =>
  ({ id, display_name, system_name } as InstallableCore);

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

describe("installableOptions", () => {
  it("leads with the part that differs between the options", () => {
    // Every core for one system shares the system half of its name, and the
    // dropdown truncates the value to half the row -- so the shared half is
    // all that survives and every option reads the same until it is opened.
    const labels = (installableOptions([
      installable("DoubleCherryGB", "Nintendo - Game Boy / Color (DoubleCherryGB)",
        "Game Boy/Game Boy Color"),
      installable("gambatte", "Nintendo - Game Boy / Color (Gambatte)"),
      installable("mesen-s", "Nintendo - SNES / SFC / Game Boy / Color (Mesen-S)"),
    ]) as { label: string }[]).map((o) => o.label);
    expect(labels).toEqual(["DoubleCherryGB", "Gambatte", "Mesen-S"]);
  });

  it("offers every suggestion, in the order the backend ranked them", () => {
    // The buttons this replaced showed only the first four, silently. A
    // dropdown has room for all of them, and the backend's order is its answer
    // to "which of these is most likely right".
    const options = installableOptions([
      installable("a", "A"),
      installable("b", "B"),
      installable("c", "C"),
      installable("d", "D"),
      installable("e", "E"),
    ]);
    expect(options.map((o) => o.data)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("keeps brackets that belong to the core's own name", () => {
    // One core called "bsnes C++98 (v085)". Matching the innermost bracket
    // would label it "v085", which names a version and no core at all.
    const [a] = installableOptions([
      installable("bsnes_cplusplus98", "Nintendo - SNES / SFC (bsnes C++98 (v085))"),
    ]) as { label: string }[];
    expect(a.label).toBe("bsnes C++98 (v085)");
  });

  it("leaves a name that has no system prefix alone", () => {
    const [a] = installableOptions([installable("romcleaner", "ROM Cleaner")]) as { label: string }[];
    expect(a.label).toBe("ROM Cleaner");
  });

  it("stays flat, since everything installable is a libretro core", () => {
    const options = installableOptions([installable("snes9x", "Snes9x")]);
    expect(options.some((o) => "options" in o)).toBe(false);
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
