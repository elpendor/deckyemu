import type { SaveBackupContents, SaveSource } from "./backend";

/**
 * What a save backup would carry, once the user has finished unticking.
 *
 * Out here rather than in the modal so it can be checked: the sums are the only
 * thing on that screen anybody makes a decision from, and a total that quietly
 * counts an unticked emulator is the kind of wrong that is never noticed until
 * the archive is on the other device.
 */

export interface BackupTotals {
  files: number;
  bytes: number;
  /** The emulators actually going in, in the order they were listed. */
  names: string[];
  /**
   * Selected emulators that declare no save directory, so what they contribute
   * is everything they keep. Named rather than counted because the sentence
   * says which ones.
   */
  whole: string[];
}

export function totals(sources: SaveSource[], selected: Set<string>): BackupTotals {
  const chosen = sources.filter((source) => selected.has(source.id));
  return {
    files: chosen.reduce((sum, source) => sum + source.files, 0),
    bytes: chosen.reduce((sum, source) => sum + source.bytes, 0),
    names: chosen.map((source) => source.name),
    whole: chosen.filter((source) => source.whole).map((source) => source.name),
  };
}

/**
 * Everything, on the first open.
 *
 * Predictable beats clever here. A default that dropped the large rows would be
 * defensible right up to the moment somebody restored a backup and found the one
 * emulator they cared about missing from it -- and the sizes are on screen, so
 * unticking is one press and needs no guessing on this side.
 */
export function defaultSelection(sources: SaveSource[]): Set<string> {
  return new Set(sources.map((source) => source.id));
}

/**
 * The line under the button, in the words the decision needs.
 *
 * `size` is passed in rather than formatted here so this module stays free of
 * the component file `humanSize` lives in -- importing that would pull React
 * into a test run that has no React.
 */
export function backupSummary(totals: BackupTotals, size: string): string {
  if (totals.names.length === 0) return "Nothing selected.";
  const scope =
    totals.whole.length === 0
      ? ""
      : ` Everything ${listNames(totals.whole)} keeps is included, not only saves,` +
        " because it does not say where its saves are.";
  return `${totals.files} file(s), ${size}, from ${listNames(totals.names)}.${scope}`;
}

/** "A", "A and B", "A, B and C" -- the plugin writes lists this way everywhere. */
function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * What is in a backup and how much of it this Deck already has.
 *
 * One sentence rather than one per option, because the options are the buttons
 * now. A switch labelled "replace" cost a row, a two-line explanation and a
 * summary that had to describe both states -- on a screen that was already too
 * tall for the device. Two buttons say the same thing in the place somebody is
 * already looking.
 */
export function restoreSummary(contents: SaveBackupContents[]): string {
  const usable = contents.filter((entry) => entry.installed);
  if (usable.length === 0) return "None of these emulators are installed on this Deck.";

  const files = usable.reduce((sum, entry) => sum + entry.files, 0);
  const present = usable.reduce((sum, entry) => sum + entry.present, 0);
  if (present === 0) return `${files} file(s), none of them already here.`;
  if (present === files) {
    // The case that reads as a failure unless it is named: every file is here,
    // so restoring what is missing does nothing and its button is disabled.
    return `${files} file(s), all of them already on this Deck. Only replacing would change anything.`;
  }
  return `${files} file(s), ${present} of them already on this Deck.`;
}

/**
 * What one emulator's row says, with the number that matters first.
 *
 * The row used to lead with what the backup holds and mention what is already
 * here at the end -- "3 file(s), 40 KB - 2 already on this Deck" -- which left
 * the only actionable number, the one file that would actually be written, as
 * arithmetic for the reader to do. Restoring is a decision about what is
 * *missing*, so that is what the row is about.
 *
 * A row with nothing to restore says so plainly rather than going quiet, since
 * "all of them are here" and "this row failed to load" must not look alike.
 */
export function sourceLine(
  entry: SaveBackupContents,
  size: string,
): { line: string; missing: number } {
  if (!entry.installed) {
    return {
      line: `${entry.files} file(s), ${size} - not installed here, so these stay in the backup`,
      missing: 0,
    };
  }
  const missing = Math.max(0, entry.files - entry.present);
  if (missing === 0) {
    return {
      line: `All ${entry.files} already on this Deck - only replacing would change anything`,
      missing: 0,
    };
  }
  return {
    line: `${missing} of ${entry.files} missing here, ${size} in the backup`,
    missing,
  };
}

/** How many files a plain restore would write. Zero disables its button. */
export function missingCount(contents: SaveBackupContents[]): number {
  return contents
    .filter((entry) => entry.installed)
    .reduce((sum, entry) => sum + entry.files - entry.present, 0);
}

/**
 * The emulators a plain restore would actually write to.
 *
 * What "restore missing" is *for*: with one file gone from one emulator, this
 * is one emulator, not thirteen. Passing them all is what the buttons used to
 * do, and against cloud storage that is a network call per save root of every
 * emulator up there -- twenty-odd round trips to write one file, with the
 * progress bar naming each in turn, which reads as restoring everything
 * because it very nearly is.
 *
 * `--ignore-existing` meant the extra calls changed nothing, so this was slow
 * and alarming rather than destructive. It was still wrong: the screen said one
 * row would change and the work said otherwise.
 */
export function missingIds(contents: SaveBackupContents[]): string[] {
  return contents
    .filter((entry) => entry.installed && entry.files - entry.present > 0)
    .map((entry) => entry.id);
}

/** How many an overwrite would destroy, for the sentence that confirms it. */
export function presentCount(contents: SaveBackupContents[]): number {
  return contents
    .filter((entry) => entry.installed)
    .reduce((sum, entry) => sum + entry.present, 0);
}

/** Emulators in the archive that this Deck does not have, for the line that says so. */
export function notInstalled(contents: SaveBackupContents[]): string[] {
  return contents.filter((entry) => !entry.installed).map((entry) => entry.name);
}
