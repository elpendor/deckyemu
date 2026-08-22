/**
 * The row shown when a definition file was refused rather than loaded.
 *
 * A definition this plugin will not load produces an emulator that simply never
 * appears, which from the outside is indistinguishable from having sent the
 * wrong file, or from the transfer not having worked at all. The backend has
 * always said why -- `schema.validate` returns one problem per fault,
 * `imported.parse` joins them with newlines and `imported.load` puts the
 * filename on a line of its own above them -- and for a long time nothing in
 * the frontend called for any of it.
 *
 * **The newlines are the message, and HTML eats them.** Rendered as one string
 * in one element, the first version of this collapsed every one to a space, so
 * a definition missing three fields arrived as a single run-on sentence with
 * the reasons welded together:
 *
 *     ...was not loaded: rpcs3: missing required field 'summary' -- One line
 *     under the name. Say which system it runs. rpcs3: missing required field
 *     'args' -- Launch arguments, with `{rom}`...
 *
 * That reads as one broken thought rather than three separate faults, and the
 * list of what is actually missing is the part that gets lost. So the split
 * happens here, where it can be checked, and the component renders a line per
 * fault. Nothing rewrites the backend's words -- it was already saying the
 * right thing to nobody.
 */

export interface Refusal {
  /** Which file, and that it was not loaded. Always present. */
  headline: string;
  /**
   * Why, one entry per fault. Empty for a refusal the backend states in a
   * single line -- an unreadable file, or one too large to be a definition.
   */
  details: string[];
}

export interface ImportProblems {
  label: string;
  refusals: Refusal[];
}

/** Split one backend message into its headline and the faults under it. */
function refusal(problem: string): Refusal | null {
  const lines = problem
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  if (lines.length === 0) return null;
  return { headline: lines[0], details: lines.slice(1) };
}

/**
 * What to say about `problems`, or null to say nothing.
 *
 * Null rather than an empty row, for the reason `shortcutNudge` gives: an empty
 * heading in a panel this dense is worse than the thing it fails to describe.
 *
 * Blank lines are dropped rather than rendered. One that arrived empty would
 * otherwise be a gap in the middle of a list of faults, which reads as the
 * panel being broken rather than as a definition being refused.
 */
export function importProblems(problems: string[] | null | undefined): ImportProblems | null {
  const refusals = (problems ?? [])
    .map(refusal)
    .filter((item): item is Refusal => item !== null);
  if (refusals.length === 0) return null;
  return {
    // Singular and plural spelled out rather than a "(s)": this is the sentence
    // that has to make somebody go and look at a file. Counted in files rather
    // than in faults -- three missing fields in one definition is one file to
    // go and fix, and "3 definitions were not loaded" would send the reader
    // looking for two that do not exist.
    label:
      refusals.length === 1
        ? "A definition was not loaded"
        : `${refusals.length} definitions were not loaded`,
    refusals,
  };
}
