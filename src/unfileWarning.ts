/**
 * What the dialog says before games are taken out of their collections.
 *
 * Its own module for the same reason as `clearWarning`: the sentence is the
 * whole of what the user gets to react to. This is far less destructive than
 * removing games -- nothing is deleted that cannot be rebuilt by switching the
 * setting back on -- so the wording's job is not to frighten anyone, it is to
 * say plainly that something is about to happen to games already added, and
 * that it is reversible. A dialog that reads as dangerous when it is not
 * teaches people to dismiss the ones that are.
 *
 * The numbers matter for the same reason they do there: "47 games out of 12
 * collections" is a claim somebody can recognise as wrong about their own
 * library, and "your games" is not.
 */

/**
 * How many games are in a collection, and how many collections that is.
 *
 * Counted from what each game recorded when it was added, so the answer does
 * not depend on the setting being off already -- the dialog has to state it
 * while collections are still on, which is exactly when a plan would say there
 * is nothing to do.
 *
 * A game that records no collection is not counted. It was added before that
 * was stored, or was never filed; either way there is no shelf to name and
 * nothing this dialog can promise about it. The migration still takes it out if
 * it turns out to be somewhere.
 */
export function countFiled(names: (string | undefined)[]): {
  games: number;
  shelves: number;
} {
  const filed = names.filter((name): name is string => Boolean(name));
  return { games: filed.length, shelves: new Set(filed).size };
}

/**
 * The line under the button, when collections are off and games are still in
 * them. Says what is true rather than what is wrong: leaving them there is a
 * choice, and the row exists to make that choice visible and reversible, not to
 * nag about it.
 */
export function strandedSummary(games: number, collections: number): string {
  const count = games === 1 ? "1 game" : `${games} games`;
  const shelves =
    collections === 1 ? "1 collection" : `${collections} collections`;
  const where = collections === 0 ? "still in collections" : `still in ${shelves}`;

  return (
    `${count} added while collections were on ${where}. Nothing new is being ` +
    "filed there."
  );
}

/** The dialog's body text. */
export function unfileWarning(filed: number, collections: number): string {
  const games = filed === 1 ? "1 game" : `${filed} games`;
  const shelves =
    collections === 1 ? "1 collection" : `${collections} collections`;

  return (
    `This takes ${games} out of ${shelves}. Any collection left empty is ` +
    "removed; one still holding games you put there yourself is kept, with " +
    "those games. Nothing is deleted from your library and no save data is " +
    "touched — switching this back on files them again."
  );
}
