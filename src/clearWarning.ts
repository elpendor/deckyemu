/**
 * What the remove-everything dialog says, and whether to show it at all.
 *
 * Its own module because this sentence is the entire protection on the most
 * destructive thing the plugin does. There is no undo, no per-game checkbox and
 * no second dialog -- what stops a mistake is the user reading this and stopping.
 * That makes the wording worth testing rather than worth trusting, which is also
 * why the count is threaded through it: "this deletes all 47 games" is a fact
 * somebody can recognise as wrong about their own library, and "this deletes
 * every game" is not.
 *
 * `count` is null when the library could not be read. That is deliberately not
 * the same as zero.
 */

/** Whether the dialog is worth showing. Only a known-empty library skips it. */
export function shouldConfirmClear(count: number | null): boolean {
  // A failed read still confirms. Treating "could not ask" as "nothing there"
  // would silently refuse a cleanup somebody came here to do, and the backend
  // is the authority on what actually goes anyway.
  return count !== 0;
}

/** The dialog's body text. Never claims a number it does not have. */
export function clearWarning(count: number | null): string {
  const scope =
    count === null || count === 0
      ? "This deletes every Steam shortcut this plugin added"
      : count === 1
        ? "This deletes the 1 game DeckyEmu added: its Steam shortcut"
        : `This deletes all ${count} games DeckyEmu added: every Steam shortcut`;

  // The tail is one string rather than assembled per case, so a change to what
  // is destroyed cannot be made in the singular branch and missed in the plural.
  return (
    scope +
    ", its launcher scripts, any collection it created that ends up empty, " +
    "and every game it put on this Deck — the ROMs it filed and the games it " +
    "unpacked into emulators. Playing any of them again means sending the files " +
    "from another machine again. Save data is kept, collections holding games " +
    "you added yourself are kept, and ROMs you keep somewhere of your own are " +
    "not touched."
  );
}
