import { toaster } from "@decky/api";

import { addedGame } from "./addedGames";
import { showCloseRunning } from "./LaunchConflictModal";
import { onAppStarted, runningGames, type RunningGame } from "./steam";

/**
 * Noticing two games at once, when stopping it was not on offer.
 *
 * Steam warns before launching a second game, and that warning is unreachable
 * for anything this plugin adds: its check is gated on `app_type & 1`
 * (`EAppType.Game`) and every DeckyEmu game is a non-Steam shortcut,
 * `1073741824`. The gate is false, so the dialog never appears -- in either
 * direction, since a running DeckyEmu game is not counted either.
 *
 * Reaching that dialog would mean replacing a function inside Steam's own
 * running code, which is the one thing this file exists to avoid. The other
 * candidate was measured and does not work: by the time
 * `RegisterForGameActionStart` fires, the app is in `RunningApps` about 100ms
 * later and the launcher is already executing, so cancelling terminates a game
 * rather than preventing one.
 *
 * **So this stops trying to intervene and reports instead.** The real cost of
 * two games at once is not the launch, it is not *noticing*: the first one sits
 * there holding memory and heat until somebody remembers it. A toast says so the
 * moment it happens, and offers to close it -- which is what Steam's dialog
 * offers, one step later and without touching anything of Steam's.
 *
 * What it buys over the dialog on the plugin's own play button is coverage: this
 * keys off a game *starting*, so it fires however that happened -- the library,
 * the home carousel, a collection, a controller shortcut, or this plugin.
 */

/**
 * The games worth naming when `startedAppId` came up, or null for "not ours to
 * mention".
 *
 * Two rules. Nothing else running is nothing to say. And **one side has to be
 * ours**: two Steam games together is a case Steam already warned about, and
 * repeating it a second later with a toast would be noise about somebody else's
 * dialog.
 *
 * `isOurs` is passed rather than imported so this stays a function of its
 * arguments, which is the only reason it can be checked without a Steam.
 */
export function othersToMention(
  startedAppId: number,
  others: RunningGame[],
  isOurs: (appId: number) => boolean,
): RunningGame[] | null {
  if (others.length === 0) return null;
  if (!isOurs(startedAppId) && !others.some((game) => isOurs(game.appId))) return null;
  return others;
}

/** "PARANORMASIGHT is still running." -- or a count, past one. */
export function stillRunningLine(others: RunningGame[]): string {
  if (others.length === 1) return `${others[0].title} is still running.`;
  return `${others.length} other games are still running.`;
}

/**
 * Watch for a second game and say so. Returns an unregister function.
 *
 * Everything is read at the moment the notification arrives: `RunningApps` is a
 * computed getter and the added-games cache is refreshed elsewhere, so nothing
 * here holds state that could go stale between launches.
 */
export function watchForDoubleLaunch(): () => void {
  return onAppStarted((appId) => {
    const others = othersToMention(appId, runningGames(appId), (id) => Boolean(addedGame(id)));
    if (!others) return;

    toaster.toast({
      title: "Two games are running",
      body: stillRunningLine(others),
      // Running two at once is a performance problem rather than a failure, so
      // this is the same weight as any other notice. `critical` would put it in
      // front of the game that just started, which is precisely the intrusion
      // being complained about.
      duration: 8000,
      // Deliberately not "close it" on the tap itself. Closing a game can lose
      // unsaved work, and a toast is the easiest thing on this device to press
      // by accident -- so the tap opens the question and the question does the
      // closing.
      onClick: () => showCloseRunning(others),
    });
  });
}
