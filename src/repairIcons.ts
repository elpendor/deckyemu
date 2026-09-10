import { gameIcon, gamesWithoutIcon, listAdded } from "./backend";
import { hasShortcutIcon, setShortcutIcon } from "./steam";
import { logError } from "./logError";

/** Between games, so a library of them cannot monopolise the frontend. */
const BETWEEN = 300;

/**
 * Give games added earlier an icon, so they stop being a blank square.
 *
 * Adding a game sets its icon. That does nothing for the games added before
 * this existed, which is every game in every library that predates it -- and
 * unlike most gaps, this one is visible on the library list all day.
 *
 * **Only the shipped picture, never a lookup.** The icon a game deserves comes
 * from SteamGridDB, and asking for one per game would be a search per game on
 * every start; a library of fifty would hammer an endpoint the plugin already
 * treats as rate-limited, to replace something a generic tile fixes offline.
 * A game worth real art gets it from **Look up name and artwork again** in its
 * editor, one game at a time and only when somebody asks.
 *
 * **Never replaces an icon that is already there** -- unless it is one of ours,
 * in which case it is re-pointed at the file we hold for it. That second half
 * is not tidiness: `hasShortcutIcon` reads Steam's own overview, and a few
 * seconds after a plugin reload that can say "no icon" for a game which has a
 * perfectly good one. The first version of this trusted that answer and wrote
 * the plain tile over real artwork on whichever games lost the race. The
 * backend's own list is the authority now, and the overview only gets a say
 * about games we have nothing for.
 */
export async function repairGameIcons(): Promise<number> {
  let games;
  let plain;
  try {
    [games, plain] = await Promise.all([listAdded(), gamesWithoutIcon()]);
  } catch (error) {
    // Never the thing that breaks a start: without it, games look exactly as
    // they looked before.
    logError("could not check which games need an icon", error);
    return 0;
  }

  const withoutOwn = new Set(plain.map((one) => one.app_id));

  let repaired = 0;
  for (const game of games) {
    if (!game?.app_id) continue;

    if (withoutOwn.has(game.app_id)) {
      // Nothing of ours to point at, so this is the plain tile or nothing --
      // and the overview decides. Unknown is not "no icon": Steam materialises
      // overviews as it loads, and reading an absent one as blank would stamp
      // the tile on a shortcut whose icon is simply not visible yet.
      if (hasShortcutIcon(game.app_id) !== false) continue;
    }

    try {
      // Answers with the game's own icon when it has one, so this both gives a
      // plain tile to a game with nothing and puts a real icon back on a game
      // that had one taken off it.
      const { path } = await gameIcon(game.app_id, "");
      if (path && setShortcutIcon(game.app_id, path)) repaired += 1;
    } catch (error) {
      logError(`could not set the icon for ${game.app_id}`, error);
    }
    await new Promise((resolve) => setTimeout(resolve, BETWEEN));
  }

  if (repaired > 0) {
    console.log(`[deckyemu] gave ${repaired} game(s) an icon`);
  }
  return repaired;
}
