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

/** A migration move, narrowed to what counting needs. */
interface Move {
  from: string;
  to: string;
}

/**
 * How many games are filed, and across how many collections.
 *
 * Derived from the plan rather than counted separately: with collections off,
 * every move the backend produces is an unfiling, so the plan already is the
 * answer. Three call sites worked this out by hand and had to agree on which
 * moves counted and how to deduplicate the names.
 */
export function countStranded(moves: Move[]): { games: number; shelves: number } {
  const leaving = moves.filter((move) => !move.to);
  return {
    games: leaving.length,
    // A game whose old collection was never recorded -- added by a build before
    // that was stored -- still has to be taken out, but names no shelf to count.
    shelves: new Set(leaving.map((move) => move.from).filter(Boolean)).size,
  };
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
