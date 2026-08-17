import { listAdded, type AddedGame } from "./backend";
import { logError } from "./logError";

/**
 * The added games, cached at module scope and readable synchronously.
 *
 * The library context menu needs to know, *while rendering*, whether the game
 * under the cursor is one of ours -- the item has to be absent for every other
 * game rather than present and refusing. A render cannot await, and a backend
 * call per menu open would put a round trip in front of a context menu on a
 * device where that menu is opened constantly.
 *
 * So the list is kept here and refreshed when it changes. Stale is survivable
 * in both directions and neither is worse than a wrong menu: a game added since
 * the last refresh shows no item until the next one, and a game removed since
 * shows an item whose editor then finds nothing. Refreshing on every library
 * change keeps that window short.
 */
let games: AddedGame[] = [];

/** Everything the panel already knows, handed over rather than re-fetched. */
export function rememberAddedGames(list: AddedGame[]) {
  games = list;
}

/** The game with this Steam app id, or undefined for anything not ours. */
export function addedGame(appId: number): AddedGame | undefined {
  return games.find((game) => game.app_id === appId);
}

/**
 * Re-read the library.
 *
 * Failure is swallowed to the log: this runs alongside things the user asked
 * for, and a context menu missing an item is a smaller problem than an error
 * appearing for something nobody pressed.
 */
export async function refreshAddedGames(): Promise<void> {
  try {
    games = await listAdded();
  } catch (error) {
    logError("could not refresh the added-games cache", error);
  }
}
