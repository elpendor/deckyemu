/**
 * What a game should be called after its artwork was picked by hand.
 *
 * Reaching for the picker means the automatic match was wrong, and a bad
 * filename is the commonest reason it was — so leaving the name that filename
 * produced is keeping the one answer already known to be bad. Choosing an entry
 * in the picker is the user saying which game this is, which is a better source
 * for the name than any heuristic.
 *
 * The exception is a name the user wrote. That is the rule the rest of the
 * plugin uses everywhere it might overwrite something — launch arguments, an
 * emulator's config, a collection's extensions — and it is the same rule here:
 * a value that still matches what the plugin produced is the plugin's to
 * change, and anything else is theirs.
 *
 * Its own function rather than the same three lines in the add panel and the
 * editor, because it was written twice before this and the two would have
 * drifted on the first correction to either.
 */
export function titleAfterArtPick(
  /** What is in the name field right now. */
  current: string,
  /** What the plugin last put there itself, from the filename or the database. */
  automatic: string,
  /** The name the picked artwork belongs to, already tidied by the backend. */
  suggested: string,
): string {
  // Nothing to offer: keep whatever is there rather than blanking a name.
  if (!suggested) return current;
  // Written by the user, and theirs. Compared trimmed because the field they
  // typed into does not trim for them.
  if (current.trim() !== automatic.trim()) return current;
  return suggested;
}
