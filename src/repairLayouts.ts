import { gamesNeedingLayout } from "./backend";
import { pinGamepadLayout } from "./steam";
import { logError } from "./logError";

/** Between games, so a library of them cannot monopolise the frontend. */
const BETWEEN = 300;

/**
 * Give games added earlier the layout their emulator now depends on.
 *
 * Adding a game pins the layout its emulator asks for. That does nothing for
 * the games added before the emulator asked -- and for Vita3K the symptom is
 * silent: the Deck powers its gyro down unless the *running game's* layout binds
 * it, so motion in every Vita game added before this stays dead, with nothing on
 * screen to say why and no reason for anybody to suspect a controller layout.
 *
 * The alternative was a release note asking people to remove and re-add their
 * Vita games, which is both a poor trade for them and a thing most would never
 * read.
 *
 * Everything that makes this safe is in `pinGamepadLayout`: it replaces a layout
 * Steam guessed, or one this plugin pinned itself, and never one somebody chose.
 * Re-running it on every start is therefore cheap and idempotent -- a game
 * already on the right layout reads back as an explicit `template://` selection
 * and is left alone.
 */
export async function repairGameLayouts(): Promise<number> {
  let games;
  try {
    games = await gamesNeedingLayout();
  } catch (error) {
    // Never the thing that breaks a start: without it, motion is missing in
    // games that were already missing it.
    logError("could not check which games need a layout", error);
    return 0;
  }

  let repaired = 0;
  for (const game of games) {
    if (!game?.app_id) continue;
    try {
      // An empty layout is an instruction, not an absence: this emulator's
      // motion has been switched off and its games have to come *off* our gyro
      // layout, or its gyro-to-stick binding keeps drifting the camera through
      // Steam's virtual pad. `restore` is what makes that replace our own pin.
      const moved = game.layout
        ? await pinGamepadLayout(game.app_id, 8, game.layout, true)
        : await pinGamepadLayout(game.app_id, 8, "", true, true);
      if (moved) repaired += 1;
    } catch (error) {
      logError(`could not set the layout for ${game.app_id}`, error);
    }
    await new Promise((resolve) => setTimeout(resolve, BETWEEN));
  }

  if (repaired > 0) {
    console.log(`[deckyemu] gave ${repaired} game(s) the layout their emulator needs`);
  }
  return repaired;
}
