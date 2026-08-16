import { collectionShape, forgetCollections } from "./backend";
import { ownedCollectionMatcher } from "./collectionMatch";
import { deleteCollections, findEmptyCollections, removeAppsFromCollection } from "./steam";
import { logError } from "./logError";

/**
 * Taking games off their shelves, and clearing away shelves left holding
 * nothing.
 *
 * Four places did the first of these and three did the second, each with its
 * own copy: removing one game, forgetting entries the library check found,
 * clearing the library, and the development reset. They had already drifted --
 * one of the four removed the Steam shortcut before taking the game out of its
 * collection, which does not work (see below) while looking exactly like the
 * three that do.
 *
 * Kept out of `steam.ts` because that file must stay free of backend imports:
 * it is exercised by tests that run under Node, where `@decky/api` will not
 * load. Same reason `reuseShortcut.ts` and `addGame.ts` sit beside it.
 */

export interface FiledGame {
  app_id: number;
  /**
   * Where the game was filed. Optional, and absent means the same as empty:
   * a game added before the collection was recorded, or one whose filing did
   * not take. Both are "nothing to unfile", so neither is a caller's problem.
   */
  collection?: string;
}

/**
 * Take games out of the collections they were filed into.
 *
 * **Call this before removing their Steam shortcuts, never after.** Steam takes
 * apps out of a collection by app *overview*, and an overview stops existing
 * with the shortcut -- so afterwards the removal silently does nothing while
 * the collection goes on listing an id that no longer resolves. It then never
 * reads as empty either, so the shelf outlives every game on it. A reset that
 * left twenty dead shortcuts also left the shelves they sat on, and that is
 * what this ordering is for.
 *
 * Grouped so each collection is one call rather than one per game, and a game
 * with no recorded collection is skipped rather than searched for.
 *
 * Returns how many collections were touched, which is what the callers report.
 */
export async function unfileGames(
  games: FiledGame[],
  // Called before each collection is emptied, for the callers that clear the
  // whole library and would otherwise show a still bar for the length of it.
  onProgress?: (done: number, total: number) => void,
): Promise<number> {
  const byCollection = new Map<string, number[]>();
  for (const game of games) {
    if (!game.collection || !game.app_id) continue;
    const existing = byCollection.get(game.collection);
    // Appended in place: rebuilding the array per game copies every id already
    // grouped under that name, and clearing a library groups all of them.
    if (existing) existing.push(game.app_id);
    else byCollection.set(game.collection, [game.app_id]);
  }

  let done = 0;
  // Whichever of them this emptied. They have to be given back to the backend
  // or it goes on claiming shelves that no longer exist -- see `deleteEmptied`.
  const deleted: string[] = [];
  for (const [tag, appIds] of byCollection) {
    onProgress?.(done, byCollection.size);
    const result = await removeAppsFromCollection(tag, appIds);
    if (result.deleted) deleted.push(result.deleted);
    done += 1;
  }
  await forgetDeleted(deleted);
  return byCollection.size;
}

/** Stop claiming collections that have gone. Best effort; see `deleteEmptied`. */
export async function forgetDeleted(tags: string[]): Promise<void> {
  if (tags.length === 0) return;
  try {
    await forgetCollections(tags);
  } catch (error) {
    logError("could not stop claiming deleted collections", error);
  }
}

/**
 * Delete collections this plugin made that now hold nothing.
 *
 * A collection is deleted as its last game leaves, but only where something was
 * there to notice: a shortcut removed in Steam itself, or a reset, leaves the
 * shelf standing empty and no registered game names it afterwards. So this asks
 * Steam what is there and matches on the naming the plugin uses.
 *
 * A backstop, not the mechanism -- `RemoveShortcut` is fire and forget and
 * Steam recomputes collections on its own schedule, so a collection emptied
 * moments ago may still look occupied from here. Taking the apps out explicitly
 * first is what handles those; this catches what earlier sessions left.
 */
export async function sweepEmptyCollections(): Promise<number> {
  return deleteEmptied(findEmptyCollections(ownedCollectionMatcher(await collectionShape())));
}

/**
 * Delete collections and stop claiming the ones that went.
 *
 * Both halves, always together. The record of what this plugin made is what
 * decides ownership now, so leaving a deleted name in it means the plugin goes
 * on claiming a shelf that no longer exists -- and would claim a new one if the
 * user ever made a collection of their own by that name. Deleting without
 * forgetting is the one way recording ownership could be worse than deriving
 * it, so the two are not offered separately.
 *
 * Returns how many were deleted. Forgetting is best effort: a name still
 * claimed after its collection has gone costs nothing until such a collection
 * exists again, and failing the whole sweep over it would be worse.
 */
export async function deleteEmptied(tags: string[]): Promise<number> {
  if (tags.length === 0) return 0;
  const deleted = await deleteCollections(tags);
  await forgetDeleted(tags);
  return deleted;
}
