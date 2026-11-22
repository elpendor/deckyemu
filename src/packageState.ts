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
