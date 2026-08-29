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

export interface DiscRow {
  /** Whether to draw the row at all. */
  show: boolean;
  label: string;
  description: string;
  /** Whether the switch is on: two or more discs means a playlist gets written. */
  on: boolean;
  /** Never set now: a set is always offerable. Kept so the panel reads the same. */
  disabled: boolean;
  /**
   * Whether the playlist is what the shortcut runs.
   *
   * False for an emulator that cannot read one — PCSX2 — where the set is still
   * one entry and still filed together, but the launcher starts the first disc
   * and the emulator's own menu does the swapping. The panel passes this on so
   * the backend knows which of the two to put on the command line.
   */
  playlistRuns: boolean;
}

/**
 * The disc row, or `show: false`.
 *
 * Three states worth telling apart, and the third is the one that would
 * otherwise be silent:
 *
 * * a set was **found** — say how many, offer to make it one game;
 * * a set is being **built by hand** — the naming rules reached nothing, so
 *   what is on screen is whatever the user has picked;
 * * the chosen core **cannot read a playlist** — say so rather than offering a
 *   switch that produces a game which will not start.
 *
 * The row appears whenever the file looks like a disc, even with the switch
 * off, because "add the other discs" is not discoverable from a panel that says
 * nothing about them.
 */
export function discRow(
  probe: RomProbe | null,
  discs: string[],
  core: Core | undefined,
): DiscRow {
  const found = probe?.disc_set ?? [];
  const picked = discs.length >= 2;
  if (!probe || (found.length === 0 && !picked)) {
    return { show: false, label: "", description: "", on: false, disabled: false,
             playlistRuns: false };
  }

  if (!readsPlaylist(core)) {
    const name = core?.short_name || "This core";
    // **Still one game, and still filed together.** Not being able to read a
    // playlist is a statement about what gets launched, not about what the
    // discs are: PCSX2 changes disc from its own menu, and the thing that makes
    // that bearable is disc two sitting in the same folder as disc one rather
    // than in whatever folder it was sent from. So the switch stays, the
    // playlist is still written -- it is what filing and deleting follow, and
    // it costs a few bytes -- and the launcher runs disc one instead of it.
    // **Only when merging is right, which is not implied by anything.** PCSX2
    // has `Change Disc` in the menu Select + Start opens, so one entry works.
    // Xenia is the counter-example and the reason this is a catalog field
    // rather than a rule: a game split across its discs asks the console for
    // the next one and Xenia serves it, so a set is worth merging -- but not
    // every Xbox 360 set is split that way. On some, disc one is the whole game
    // and the rest hold extra content that is fairly its own entry, and nothing
    // in a filename separates the two shapes.
    //
    // Adding them separately costs nothing anyway: every ROM is filed into
    // `roms/<system>` whatever it is added as, so the discs sit side by side
    // and Xenia's prompt finds them regardless.
    if (!core?.changes_disc) {
      return {
        show: true,
        label: "Multi-disc game",
        description: `${name} cannot be given a playlist, so add each disc on its own. They are filed side by side either way, so ${name} can find the next one when it asks.`,
        on: false,
        disabled: true,
        playlistRuns: false,
      };
    }

    if (picked) {
      return {
        show: true,
        label: `Add ${discs.length} discs as one game`,
        description: `${name} cannot read a playlist, so the shortcut starts the first disc and all ${discs.length} are kept in one folder — which is how ${name} reaches the next one.`,
        on: true,
        disabled: false,
        playlistRuns: false,
      };
    }
    return {
      show: true,
      label: `Add ${found.length} discs as one game`,
      // Says what turning it back on would do, which differs from the playlist
      // case: there the emulator swaps discs itself, here you do it from its
      // menu. Naming the emulator matters because that is where you would go.
      description: `${found.length} discs of this game are in that folder. On, they are filed together and the shortcut starts the first, which is what lets ${name} reach the rest. Off, each one is added on its own.`,
      on: false,
      disabled: false,
      playlistRuns: false,
    };
  }

  if (picked) {
    return {
      show: true,
      label: `Add ${discs.length} discs as one game`,
      description: `${discs.join(", ")} — a playlist naming them in this order is written beside them, and one game goes into your library. The emulator's disc-swap menu does the rest.`,
      on: true,
      disabled: false,
      playlistRuns: true,
    };
  }

  // Found but switched off. `found.length` rather than `discs.length`, which is
  // zero here — the sentence is about what is on disk, not about the empty list.
  return {
    show: true,
    label: `Add ${found.length} discs as one game`,
    description: `${found.length} discs of this game are in that folder. Off, each one has to be added on its own and they arrive in your library with the same name.`,
    on: false,
    disabled: false,
    playlistRuns: true,
  };
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
