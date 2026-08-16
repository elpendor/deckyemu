import { type DropdownOption } from "@decky/ui";

import { type Core, type InstallableCore } from "./backend";

/** Whether a picker entry is a standalone emulator rather than a libretro core. */
export const isEmulatorId = (id: string) => id.startsWith("emu:");

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
 * Names with no bracket at all -- "ROM Cleaner", and every standalone emulator
 * -- are already the core's name and come through untouched.
 */
const CORE_IN_BRACKETS = /^[^(]*\((.+)\)$/;

export const coreShortName = (displayName: string) =>
  displayName.match(CORE_IN_BRACKETS)?.[1] ?? displayName;

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
 *
 * Short names, the same as the installable list. This used to append the system
 * -- "Snes9x - Super Nintendo" -- which reads well until the dropdown truncates
 * it to the right-hand half of a Quick Access row, at which point the half that
 * survives is libretro's shared "Nintendo - ..." opening and every option looks
 * the same. A standalone emulator has no bracketed name to take, so "Dolphin"
 * and "PCSX2" come through as they are.
 */
export function coreOptions(cores: Core[]): DropdownOption[] {
  const option = (core: Core) => ({
    data: core.id,
    label: coreShortName(core.display_name),
  });

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
 * The same list, for cores that are not installed yet.
 *
 * Short names, because every core offered runs the one file being added: the
 * system is settled by the question rather than a thing to tell options apart
 * by, and libretro's full name spends its first half saying it.
 *
 * Grouped by system when more than one appears, and this is not the same
 * "system" the file belongs to. Ten of the twenty cores offered for a Game Boy
 * Color ROM are SNES cores -- bsnes and friends claim .gbc because they emulate
 * the Super Game Boy. They will run it; they are not what anyone means. The
 * short name alone gives no hint of that, so the heading is what puts it back.
 *
 * One heading over a list where everything is the same system is a row of noise,
 * which is the rule `coreOptions` follows for the same reason.
 */
export function installableOptions(cores: InstallableCore[]): DropdownOption[] {
  const option = (core: InstallableCore) => ({
    data: core.id,
    label: coreShortName(core.display_name),
  });

  // Nothing in today's catalog is missing a system, but a heading is only worth
  // having if every option can be filed under one -- otherwise the odd core out
  // lands under a blank heading, which is a row that says nothing and cannot be
  // read as anything. Flat is the honest answer then.
  if (cores.some((core) => !core.system_name.trim())) return cores.map(option);

  // First appearance, not sorted: the backend already ordered the catalog by
  // system, and its order is its answer to which of these is most likely right.
  const systems: string[] = [];
  for (const core of cores) {
    if (!systems.includes(core.system_name)) systems.push(core.system_name);
  }
  if (systems.length < 2) return cores.map(option);

  return systems.map((system) => ({
    label: system,
    options: cores.filter((core) => core.system_name === system).map(option),
  }));
}
