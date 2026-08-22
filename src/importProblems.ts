/**
 * The row shown when a definition file was refused rather than loaded.
 *
 * A definition this plugin will not load produces an emulator that simply never
 * appears, which from the outside is indistinguishable from having sent the
 * wrong file, or from the transfer not having worked at all. The backend has
 * always said why -- `reload_imported` collects a reason per refusal and
 * `imported_emulators` returns them -- and for a long time nothing in the
 * frontend called it, so every refusal was silent and the reasons went nowhere.
 *
 * The reasons themselves are written by the backend and are already sentences
 * naming the file: *"foo.deckyemu.json was not loaded: 'rpcs3' is already a
 * built-in emulator."* Nothing here rewrites them. What is decided here is only
 * whether there is a row at all and what its heading says, because a count is
 * the one thing the backend's per-file messages cannot state.
 */

export interface ImportProblems {
  label: string;
  /** One per refusal, in the order the backend found them. */
  reasons: string[];
}

/**
 * What to say about `problems`, or null to say nothing.
 *
 * Null rather than an empty row, for the reason `shortcutNudge` gives: an empty
 * heading in a panel this dense is worse than the thing it fails to describe.
 *
 * Blank strings are dropped rather than rendered. A reason that arrived empty
 * would otherwise be a bullet with nothing after it, which reads as the UI
 * being broken rather than as a definition being refused.
 */
export function importProblems(problems: string[] | null | undefined): ImportProblems | null {
  const reasons = (problems ?? []).filter((reason) => reason.trim() !== "");
  if (reasons.length === 0) return null;
  return {
    // Singular and plural spelled out rather than a "(s)": this is the sentence
    // that has to make somebody go and look at a file.
    label:
      reasons.length === 1
        ? "A definition was not loaded"
        : `${reasons.length} definitions were not loaded`,
    reasons,
  };
}
