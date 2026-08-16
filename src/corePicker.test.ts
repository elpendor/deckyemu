import { describe, expect, it } from "vitest";

import { type Core, type InstallableCore } from "./backend";
import {
  coreOptions,
  installableOptions,
  isEmulatorId,
  pinnedLabel,
  withCurrentCore,
} from "./corePicker";

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

  it("shortens inside the groups too", () => {
    // The grouped path builds its options separately, so it can drift from the
    // flat one -- which is the drift this module exists to prevent.
    const groups = coreOptions([
      core("emu:dolphin", "Dolphin", "GameCube/Wii"),
      core("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
    ]) as { label: string; options: { label: string }[] }[];
    expect(groups.map((g) => g.options.map((o) => o.label))).toEqual([
      ["Dolphin"],
      ["Gambatte"],
    ]);
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

  it("shows the core's own name, not libretro's system prefix", () => {
    // The system used to be appended here. It reads well until the dropdown
    // truncates the value to half a Quick Access row, at which point the half
    // that survives is the "Nintendo - ..." every option shares.
    // One kind at a time, so the list stays flat and these are options rather
    // than group headings.
    const [libretro] = coreOptions([
      core("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
    ]) as { label: string }[];
    expect(libretro.label).toBe("Gambatte");
    // A standalone emulator has no bracketed name to take, so it is untouched.
    const [emulator] = coreOptions([
      core("emu:dolphin", "Dolphin", "GameCube/Wii"),
    ]) as { label: string }[];
    expect(emulator.label).toBe("Dolphin");
  });
});

describe("installableOptions", () => {
  it("leads with the part that differs between the options", () => {
    // Every core for one system shares the system half of its name, and the
    // dropdown truncates the value to half the row -- so the shared half is
    // all that survives and every option reads the same until it is opened.
    const labels = (installableOptions([
      installable("DoubleCherryGB", "Nintendo - Game Boy / Color (DoubleCherryGB)", "Game Boy"),
      installable("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
      installable("mesen-s", "Nintendo - SNES / SFC / Game Boy / Color (Mesen-S)", "Game Boy"),
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

  it("stays flat when a core has no system to file it under", () => {
    // A blank heading is a row that says nothing and cannot be read as anything.
    const options = installableOptions([
      installable("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
      installable("mystery", "Mystery Core"),
    ]);
    expect(options.some((o) => "options" in o)).toBe(false);
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

  it("stays flat when every core is for the same system", () => {
    // A heading over a list where everything is the same kind is a row of noise.
    const options = installableOptions([
      installable("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
      installable("sameboy", "Nintendo - Game Boy / Color (SameBoy)", "Game Boy"),
    ]);
    expect(options.some((o) => "options" in o)).toBe(false);
  });

  it("groups by system when more than one is offered", () => {
    // Ten of the twenty cores offered for a .gbc ROM are SNES cores, which
    // claim the extension because they emulate the Super Game Boy. The short
    // name gives no hint of that; the heading is what puts it back.
    const options = installableOptions([
      installable("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
      installable("bsnes", "Nintendo - SNES / SFC (bsnes)", "Super Nintendo"),
    ]) as { label: string; options: { label: string }[] }[];
    expect(options.map((o) => o.label)).toEqual(["Game Boy", "Super Nintendo"]);
    expect(options[1].options.map((o) => o.label)).toEqual(["bsnes"]);
  });

  it("keeps the backend's order rather than sorting the headings", () => {
    // The catalog is already ordered by system, and that order is its answer to
    // which of these is most likely the right one for the file.
    const options = installableOptions([
      installable("bsnes", "Nintendo - SNES / SFC (bsnes)", "Super Nintendo"),
      installable("gambatte", "Nintendo - Game Boy / Color (Gambatte)", "Game Boy"),
    ]) as { label: string }[];
    expect(options.map((o) => o.label)).toEqual(["Super Nintendo", "Game Boy"]);
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

describe("withCurrentCore", () => {
  const c = (id: string) => ({ id });

  it("puts the game's core back when the filter dropped it", () => {
    // A Vita game's path is .../eboot.bin, so the extension is bin and the
    // matching cores are DuckStation, PCSX2 and RPCS3. Vita3K claims vpk, zip
    // and pkg -- installed, the thing the game runs on, and not in the list.
    // Something matched, so "show everything" stayed off, and the emulator was
    // hidden from its own game's editor.
    const matching = [c("duckstation"), c("pcsx2"), c("rpcs3")];
    const all = [...matching, c("emu:vita3k")];
    expect(withCurrentCore(matching, all, "emu:vita3k").map((x) => x.id)).toEqual([
      "emu:vita3k", "duckstation", "pcsx2", "rpcs3",
    ]);
  });

  it("leaves the list alone when the core is already in it", () => {
    const list = [c("gambatte"), c("sameboy")];
    expect(withCurrentCore(list, list, "gambatte")).toBe(list);
  });

  it("cannot invent a core that is not installed", () => {
    // An uninstalled core is in no list at all. Adding a fake entry would let
    // it be re-selected, which would write a launcher pointing at nothing.
    const list = [c("gambatte")];
    expect(withCurrentCore(list, list, "mupen64plus_next").map((x) => x.id)).toEqual([
      "gambatte",
    ]);
  });

  it("does nothing when no core is set", () => {
    const list = [c("gambatte")];
    expect(withCurrentCore(list, list, "")).toBe(list);
  });
});

describe("pinnedLabel", () => {
  const c = (id: string) => ({ id });

  it("names a core that is no longer installed", () => {
    // Uninstalling RetroArch takes its cores with it, and every game that ran
    // on one keeps a core_id naming something absent. Blank reads as a broken
    // editor; this reads as the thing that actually happened.
    expect(pinnedLabel([c("gambatte")], "mupen64plus_next"))
      .toBe("mupen64plus_next (not installed)");
  });

  it("drops the namespace from an emulator id, which is ours and not a name", () => {
    expect(pinnedLabel([c("gambatte")], "emu:vita3k")).toBe("vita3k (not installed)");
  });

  it("says nothing when the core is there", () => {
    // Steam shows this only when nothing is selected, so an unnecessary one
    // would sit where a real core name belongs.
    expect(pinnedLabel([c("gambatte")], "gambatte")).toBe("");
    expect(pinnedLabel([c("gambatte")], "")).toBe("");
  });
});
