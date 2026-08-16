import { type DropdownOption } from "@decky/ui";

import { type Core, type InstallableCore } from "./backend";

/**
 * How a core reads in a picker: its name, and the system it is for when known.
 *
 * One function because the two lists that show cores must not disagree about
 * what a core is called -- which is the same reason this module exists.
 */
const coreLabel = (core: { display_name: string; system_name: string }) =>
  core.system_name ? `${core.display_name} - ${core.system_name}` : core.display_name;

/** Whether a picker entry is a standalone emulator rather than a libretro core. */
export const isEmulatorId = (id: string) => id.startsWith("emu:");

/**
 * The "run with" list, with cores and standalone emulators told apart.
 *
 * They are not the same kind of thing and the picker used to say they were: a
 * libretro core runs inside RetroArch and shares its settings, its controller
 * setup and its firmware folder, while a standalone emulator is its own program
 * with its own everything. Reading "RPCS3" between Snes9x and Genesis Plus GX
 * gave no hint that choosing it meant a different program entirely.
 *
 * Grouped only when both kinds are present. One heading over a list where
 * everything is the same kind is a row of noise, and with a single emulator
 * installed and no cores that is the normal case.
 *
 * Shared by the add panel and the game editor rather than written twice. The
 * two had already drifted once -- the editor kept the flat list after the panel
 * was grouped -- and a rule about what things *are* should not have two
 * implementations to disagree with each other.
 */
export function coreOptions(cores: Core[]): DropdownOption[] {
  const option = (core: Core) => ({ data: core.id, label: coreLabel(core) });

  const emulators = cores.filter((core) => isEmulatorId(core.id));
  const libretro = cores.filter((core) => !isEmulatorId(core.id));

  if (emulators.length === 0 || libretro.length === 0) return cores.map(option);

  // Emulators first: an emulator is the specific answer for a system, where the
  // core list is long and mostly beside the point for any one file.
  return [
    { label: "Emulators", options: emulators.map(option) },
    { label: "RetroArch cores", options: libretro.map(option) },
  ];
}

/**
 * The core's own name, out of libretro's "<system> (<core>)" display name.
 *
 * Every core for one system shares the system half, so a list of them is a
 * column of the same words -- and `DropdownItem` gives the value the right-hand
 * half of the row, where it is truncated. Collapsed, all twenty Game Boy cores
 * read "Nintendo - Game Boy / C...", which is every option looking identical
 * until the list is opened. The parenthetical is the only part that differs, so
 * it is the part worth showing.
 *
 * Greedy to the last bracket, because the name itself can contain brackets:
 * "Nintendo - SNES / SFC (bsnes C++98 (v085))" is one core called
 * "bsnes C++98 (v085)", and taking the innermost match would call it "v085".
 * Names with no bracket at all -- "ROM Cleaner" -- are already the core's name.
 */
const CORE_IN_BRACKETS = /^[^(]*\((.+)\)$/;

export const coreShortName = (displayName: string) =>
  displayName.match(CORE_IN_BRACKETS)?.[1] ?? displayName;

/**
 * The same list, for cores that are not installed yet.
 *
 * Flat, with no grouping: everything here comes from the libretro buildbot, so
 * the distinction the list above draws does not exist among these. And short
 * names rather than the rule above: every core offered runs the one file being
 * added, so the system is settled by the question rather than a thing to tell
 * options apart by.
 */
export function installableOptions(cores: InstallableCore[]): DropdownOption[] {
  return cores.map((core) => ({ data: core.id, label: coreShortName(core.display_name) }));
}
