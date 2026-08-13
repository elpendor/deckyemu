/**
 * The line the panel shows when Steam has shortcuts of ours that the registry
 * cannot account for.
 *
 * This class of problem cannot be found by looking. A shortcut whose launcher
 * script and registry entry were both deleted appears in Steam as an ordinary
 * game that happens to do nothing when pressed, and the cleanup screen that can
 * fix it is somewhere nobody visits without already suspecting trouble. The
 * only reason the twenty that prompted this were ever noticed is that one of
 * them happened to be a visible duplicate.
 *
 * So the panel says it. The counts decide the wording, because "3 shortcuts
 * need attention" is worth interrupting somebody for and "3 games you added
 * before are still playable but untracked" is not the same sentence.
 */

export interface ShortcutCounts {
  unknown: number;
  dead: number;
  duplicate: number;
  orphan: number;
}

export interface Nudge {
  label: string;
  description: string;
}

/**
 * What to say, or null to say nothing.
 *
 * Null rather than an empty string: the caller renders no row at all, and a
 * blank row in a panel this short is worse than the problem it describes.
 */
export function shortcutNudge(counts: ShortcutCounts | null | undefined): Nudge | null {
  if (!counts || counts.unknown <= 0) return null;

  const parts: string[] = [];
  if (counts.dead > 0) {
    parts.push(
      `${counts.dead} cannot start — the launcher ${counts.dead === 1 ? "script is" : "scripts are"} gone`,
    );
  }
  if (counts.duplicate > 0) {
    // Noun rather than verb. "N duplicates a game" is right for one and wrong
    // for two, and "N duplicate a game" is the reverse -- the plural rule
    // inverts between the two readings, which is how this came out backwards
    // the first time.
    parts.push(
      counts.duplicate === 1
        ? "1 is a duplicate of a game you already have"
        : `${counts.duplicate} are duplicates of games you already have`,
    );
  }
  if (counts.orphan > 0) {
    parts.push(`${counts.orphan} still ${counts.orphan === 1 ? "plays" : "play"} but ${counts.orphan === 1 ? "is" : "are"} no longer tracked`);
  }

  return {
    // Deliberately not "error" or "problem". A shortcut that still plays is
    // neither, and one wording has to cover all three kinds.
    label: `${counts.unknown} Steam shortcut${counts.unknown === 1 ? "" : "s"} need${counts.unknown === 1 ? "s" : ""} attention`,
    description: `${parts.join("; ")}. Library tab, Check the library.`,
  };
}
