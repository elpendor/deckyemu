/**
 * What the dialog says before collections are switched off, and whether to ask.
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

/** Whether switching collections off is worth asking about at all. */
export function shouldConfirmUnfile(filed: number): boolean {
  // Nothing filed, nothing to take out: the setting only affects what happens
  // from now on, so a dialog would be asking permission to do nothing.
  return filed > 0;
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
