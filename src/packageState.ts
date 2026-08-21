import { type PackageState, type RomProbe } from "./backend";

/**
 * What the add panel knows about a game that arrived as a package, derived.
 *
 * Three consoles hand over a `.pkg` rather than a ROM and the panel has to
 * answer the same three questions for each: is this still a package, is there a
 * licence for it, and can the install button be pressed. That was inline in
 * `AddGamePanel`, which meant the one decision here that spends a gigabyte and a
 * half -- which key a Vita package is installed under -- was reachable only by
 * rendering the panel, and there is no DOM in the test environment. It is a pure
 * function of the probe, so it is here and tested next door.
 */

export type PackageSystem = "ps3" | "ps4" | "vita";

export interface PackagedGame {
  system: PackageSystem;
  state: PackageState;
}

/**
 * The package still waiting to be installed, or null.
 *
 * Null once it has been: the draft then points at the game inside it, so the
 * panel only ever shows one of the two states. Order matters only in that a
 * probe carries at most one of these -- the extension is the same `.pkg` for
 * all three and the backend has already told them apart by their headers.
 */
export function pendingPackage(probe?: RomProbe | null): PackagedGame | null {
  const packaged: PackagedGame | null = probe?.ps4_package
    ? { system: "ps4", state: probe.ps4_package }
    : probe?.vita_package
      ? { system: "vita", state: probe.vita_package }
      : probe?.ps3_package
        ? { system: "ps3", state: probe.ps3_package }
        : null;
  return packaged && !packaged.state.installed ? packaged : null;
}

/**
 * The emulator a pending package needs, when it is not installed yet.
 *
 * Null when there is nothing to say — no package, or the emulator is already
 * here. Derived rather than asked separately because the probe already carries
 * the answer, and the alternative was finding out by pressing Install: the two
 * consoles whose emulator does its own unpacking refused straight away, and the
 * third spent gigabytes first and then had nowhere to put the result.
 */
export interface MissingEmulator {
  id: string;
  name: string;
  /** Installing it is necessary but not sufficient — firmware comes next. */
  needsFirmware: boolean;
}

export function missingEmulator(packaged: PackagedGame | null): MissingEmulator | null {
  if (!packaged || packaged.state.emulator_ready) return null;
  return {
    id: packaged.state.emulator_id,
    name: packaged.state.emulator_name,
    needsFirmware: Boolean(packaged.state.needs_firmware),
  };
}

export interface LicenceChoice {
  /**
   * Key files in the folder that nothing ties to this package by name. Present
   * only while the backend could not match one itself, which is what makes an
   * empty list mean "no choice to make" rather than "no key".
   */
  candidates: string[];
  /**
   * The key to install under, or "" for none. Empty for every console but Vita,
   * and for Vita whenever the backend matched the key by name itself -- which is
   * the case where it must stay empty, because a name the user did not choose is
   * not one to send back as though they had.
   */
  chosen: string;
  /** Vita with no key: installing would report a corrupt package. */
  blocked: boolean;
}

/**
 * Which licence a pending Vita package would be installed under.
 *
 * `chosen` is derived from what is on offer rather than kept in step with it. A
 * choice that is no longer among the candidates -- another ROM picked, or the
 * key sent under its proper name since -- falls back to the first rather than
 * lingering as a name the backend would reject.
 *
 * `keyChoice` comes from the draft rather than component state on purpose:
 * picking one opens a ContextMenu, Steam unmounts the panel behind it, and a
 * choice held in `useState` was discarded on the way back. The row's own
 * description says the wrong key installs the game and then fails to decrypt
 * it, so a silently reverted choice is one the user made and did not get.
 */
export function licenceChoice(
  packaged: PackagedGame | null,
  keyChoice: string,
): LicenceChoice {
  const needsKey = packaged?.system === "vita" && packaged.state.licence === false;
  const candidates = needsKey ? (packaged.state.licence_candidates ?? []) : [];
  const chosen = candidates.includes(keyChoice) ? keyChoice : (candidates[0] ?? "");
  return { candidates, chosen, blocked: Boolean(needsKey) && !chosen };
}
