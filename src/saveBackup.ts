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
  // **The figures, and nothing the rows have already said.** This carried a
  // second sentence naming the emulators that contribute their whole directory
  // rather than a save folder -- which every one of those rows says on itself,
  // where somebody deciding whether to untick it is already looking. Repeated
  // underneath, it was the longest thing on the screen and told nobody
  // anything they had not just read.
  return `${totals.files} file(s), ${size}, from ${listNames(totals.names)}.`;
}

/** How many get named before a sentence turns into a list of the whole Deck. */
const NAMED = 3;

/**
 * "A", "A and B", "A, B and C", "A, B, C and 11 more".
 *
 * The plugin writes lists this way everywhere, and stops at three for the same
 * reason the differences dialog stops at five: a Deck with fourteen emulators
 * set up turned every one of these sentences into a roll-call of all of them,
 * which is a report rather than a summary, and it is the one thing nobody is
 * reading the line for. The count still says how many there are.
 */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  if (names.length <= NAMED) {
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  }
  return `${names.slice(0, NAMED).join(", ")} and ${names.length - NAMED} more`;
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
export function restoreSummary(
  contents: SaveBackupContents[],
  from: "backup" | "storage" = "backup",
): string {
  // **Nothing there and nothing usable are different things.** Both used to say
  // "None of these emulators are installed on this Deck", which is a sentence
  // about this Deck -- so a storage nothing had ever been copied to read as a
  // Deck missing every emulator it holds, and sent somebody looking for the
  // fault in the wrong place.
  if (contents.length === 0) {
    return from === "storage"
      ? "This storage holds no saves yet."
      : "This backup holds no saves.";
  }
  const usable = contents.filter((entry) => entry.installed);
  if (usable.length === 0) return "None of these emulators are installed on this Deck.";

  const files = usable.reduce((sum, entry) => sum + entry.files, 0);
  const present = usable.reduce((sum, entry) => sum + entry.present, 0);
  if (present === 0) return `${files} file(s), none of them already here.`;
  if (present === files) {
    // The case that reads as a failure unless it is named: every file is here,
    // so restoring what is missing does nothing and its button is disabled.
    return `${files} file(s), all of them already on this Deck, so only restoring all of them would change anything.`;
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
      // What to do about it is the summary's line, once, rather than this
      // row's -- on a Deck holding everything already it was the same clause
      // fourteen times over the same advice.
      line: `All ${entry.files} already on this Deck`,
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
