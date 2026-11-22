/**
 * What the panel says about a multi-disc game, decided outside the component.
 *
 * Here rather than inline for the reason `packageState.ts` is: there is no DOM
 * in the test run, so anything only reachable by rendering the panel is
 * untested — and the one decision worth being sure about is whether the core
 * the user has chosen can actually load a playlist. Getting that wrong writes
 * an `.m3u`, adds it to Steam, and produces a game that will not start.
 */

import type { Core, RomProbe } from "./backend";

/**
 * Whether a core can be handed an `.m3u`, read from the core's own info file.
 *
 * `supported_extensions` is the only honest source for this and it is already
 * parsed into `extensions`. Measured on a Deck: 44 of 295 installed cores
 * declare `m3u` — DuckStation, SwanStation, Beetle Saturn, Flycast, Genesis
 * Plus GX, the Mednafen family. So this is a per-core fact, not a per-system
 * one, and there is no list here to fall out of date.
 *
 * A registered standalone emulator answers the same way: the catalog gives it
 * the extensions of the systems it covers, and `m3u` is among the PlayStation
 * ones.
 */
export function readsPlaylist(core: Core | undefined): boolean {
  return Boolean(core?.extensions?.includes("m3u"));
}

export function coreById(probe: RomProbe | null, coreId: string): Core | undefined {
  if (!probe || !coreId) return undefined;
  return (
    probe.all_cores.find((core) => core.id === coreId) ??
    probe.matching_cores.find((core) => core.id === coreId)
  );
}

/**
 * The set after a hand-picked disc is added, or `null` when it changes nothing.
 *
 * Seeds itself with the file already chosen, so a set built from scratch has
 * the disc the user started from as its first entry rather than only the ones
 * added afterwards. Order is the order they arrive in, which is the order they
 * go into the playlist — a `.m3u` has no other way to say which disc is which.
 */
export function withDisc(discs: string[], romName: string, name: string): string[] | null {
  if (!name) return null;
  const current = discs.length > 0 ? discs : romName ? [romName] : [];
  if (current.includes(name)) return null;
  return [...current, name];
}

/**
 * Whether a set's discs must go in one entry each: the emulator can neither
 * read a playlist nor change disc from its own menu, so one entry would be
 * stuck on disc one. PCSX2 and Xenia change disc themselves, so a set can be
 * one entry there; the discs are filed side by side either way.
 */
export function discsMustSplit(probe: RomProbe | null, coreId: string, discs: string[]): boolean {
  if (discs.length < 2) return false;
  const core = coreById(probe, coreId);
  return !readsPlaylist(core) && !core?.changes_disc;
}
