import { type DropdownOption } from "@decky/ui";

import { type Core, type InstallableCore, type RomProbe } from "./backend";

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
 * `visible`, with the game's own core in it whether or not it belongs there.
 *
 * A dropdown whose `selectedOption` is not among its options draws nothing at
 * all -- no name, no placeholder -- so the editor for a game showed an empty
 * control and no hint of what it was set to. Two ways in, both real:
 *
 * - The filtered list excludes it. A Vita game's path is `.../eboot.bin`, so
 *   the extension is `bin`, and the cores claiming `bin` are DuckStation,
 *   PCSX2 and RPCS3. Vita3K claims `vpk`, `zip` and `pkg` -- it is installed,
 *   it is what the game runs on, and it is not in the match list. Something
 *   matched, so "show everything" stayed off, and the emulator the game
 *   actually uses was hidden from its own editor.
 * - It is not installed any more. An uninstalled core is in no list at all,
 *   which `pinnedLabel` answers instead.
 *
 * Front, not sorted in: it is the current value, and a reader looking for what
 * this game runs on should not have to hunt for it.
 */
export function withCurrentCore<T extends { id: string }>(
  visible: T[], all: T[], coreId: string,
): T[] {
  if (!coreId || visible.some((core) => core.id === coreId)) return visible;
  const current = all.find((core) => core.id === coreId);
  return current ? [current, ...visible] : visible;
}

/**
 * What to show when the selected core is in no list, because it is not there.
 *
 * Uninstalling RetroArch takes its cores with it, and every game that ran on
 * one keeps a `core_id` naming something now absent. The editor cannot offer
 * it and must not pretend it is gone unnoticed: a blank control reads as a bug
 * in the editor, where "mupen64plus_next (not installed)" reads as the thing
 * that actually happened and can be acted on.
 *
 * "" when the core is present, since Steam only shows this when nothing is
 * selected and an unnecessary one would replace a real name.
 */
/**
 * What to call the thing a game runs on, in a sentence.
 *
 * `short_name` first, which the backend fills from the core's own `corename`
 * -- "bsnes", "BlastEm" -- or from a standalone emulator's name. Falling back
 * to trimming the display name the way the picker does, and then to the id,
 * which is all there is for a core that is no longer installed.
 *
 * Wanted because the editor's save toast said "now runs on Super Nintendo" when
 * somebody switched from snes9x to bsnes -- the note fires *because the core
 * changed* and was reporting the platform, which is exactly the thing that
 * usually stays the same when you change core.
 */
export function coreLabel<T extends { id: string; short_name?: string; display_name?: string }>(
  all: T[],
  coreId: string,
): string {
  if (!coreId) return "";
  const found = all.find((core) => core.id === coreId);
  if (found) {
    return found.short_name || coreShortName(found.display_name ?? "") || coreId;
  }
  // Not in the list at all: uninstalled, or an emulator removed since. The id
  // is the only name left, and `emu:` is machinery rather than a name.
  return isEmulatorId(coreId) ? coreId.slice("emu:".length) : coreId;
}

export function pinnedLabel<T extends { id: string }>(all: T[], coreId: string): string {
  if (!coreId || all.some((core) => core.id === coreId)) return "";
  const name = isEmulatorId(coreId) ? coreId.slice("emu:".length) : coreId;
  return `${name} (not installed)`;
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

/**
 * The systems a core covers, for the row that appears when it covers several.
 *
 * Most cores do. Of the seven with an info file on the device this was written
 * for, six declare between two and six systems, and libretro lists them
 * alphabetically -- so the core's *first* system is Game Gear for Genesis Plus
 * GX and Sega CD for clownmdemu, neither of which is the system anyone means.
 * Which one a game is decides its shelf, its folder and which thumbnail
 * directory its cover comes from, and until this row existed nothing asked: it
 * was inferred from whichever system's artwork happened to match the filename
 * first, which filed Mega Drive games under Game Gear.
 *
 * Labelled from `database_labels` rather than from the database name, whose own
 * last word is "Mark III" for the Master System and "Genesis" for a name that
 * begins "Sega - Mega Drive".
 *
 * Empty for a core covering one system, which is how the row knows not to draw:
 * a dropdown with a single entry is a question with one answer.
 */
export function systemOptions(core: Core | null | undefined): DropdownOption[] {
  const databases = core?.databases ?? [];
  if (databases.length < 2) return [];
  const labels = core?.database_labels ?? [];
  return databases.map((database, index) => ({
    data: database,
    // The full name when no label came with it -- a system the backend's table
    // has never heard of still has to be pickable.
    label: labels[index]?.trim() || database,
  }));
}

/**
 * Which system to start on: what the file says, else what the game already had.
 *
 * `suggested` is the backend's reading of the extension -- `.md` is a Mega
 * Drive cartridge whatever the core declares -- and is empty for a file that
 * names no system, `.cue` and `.iso` among them. `current` is for the editor,
 * where the game has already been filed somewhere and that answer should stand
 * until somebody changes it.
 *
 * Both are checked against what the core actually claims, so a system left over
 * from another core cannot survive a core change and leave the row showing an
 * option that is not in it -- a `selectedOption` in no option draws nothing.
 */
export function defaultSystem(
  core: Core | null | undefined,
  suggested: string,
  current = "",
): string {
  const databases = core?.databases ?? [];
  if (databases.length < 2) return "";
  for (const candidate of [current, suggested]) {
    if (candidate && databases.includes(candidate)) return candidate;
  }
  return databases[0];
}

/**
 * The system row's value for a core, straight from a probe.
 *
 * The probe holds both halves -- the cores themselves and what it made of the
 * file for each of them -- so this is the form every caller actually wants, and
 * the only place that has to know `system_for_core` is keyed by core id.
 */
export function chooseSystem(
  probe: RomProbe | null | undefined,
  coreId: string,
  current = "",
): string {
  const core = probe?.all_cores?.find((candidate) => candidate.id === coreId);
  return defaultSystem(core, probe?.system_for_core?.[coreId] ?? "", current);
}
