import { toaster } from "@decky/api";

import { addedGame } from "./addedGames";
import { approveLaunch, launchBounced } from "./backend";
import { showCloseRunning, showLaunchConflict } from "./LaunchConflictModal";
import { launchApp, onGameLaunch, runningGames, type RunningGame } from "./steam";
import { logError } from "./logError";

/**
 * Two games at once, which Steam will not warn about for anything we added.
 *
 * Its check is gated on `app_type & 1` (`EAppType.Game`) and every DeckyEmu game
 * is a non-Steam shortcut, `1073741824`. The gate is false in both directions --
 * a running DeckyEmu game is not counted either -- so nothing is said whichever
 * way round it happens.
 *
 * **Stopping the launch is the launcher's job, not this file's.** Nothing on the
 * Steam side can do it: `CancelGameAction` terminates the game about a second
 * after it starts, and `CancelLaunch` does not stop it at all, only detaches
 * Steam's tracking and leaves the emulator running with no Stop button. Both
 * measured on a device. The generated launcher script refuses instead, which
 * works because it *is* the thing Steam starts -- see `launchers.py`.
 *
 * So this half is the panel catching up with a decision already made:
 *
 *   Steam starts a launch  ->  onGameLaunch
 *     the launcher refused (backend has the note)  ->  the dialog, then relaunch
 *     the launcher ran, but something of ours is up  ->  a toast, after the fact
 *
 * The second line is the case the gate cannot cover: a *real Steam game* started
 * over one of ours. Its launcher is not ours to gate, so nothing was stopped and
 * the most that can be done is say so.
 */

/** How long to wait for the launcher to leave its note, and how often to look. */
const BOUNCE_TIMEOUT_MS = 4000;
const BOUNCE_POLL_MS = 250;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Wait for this launch to be refused, or decide it was not.
 *
 * Polled rather than pushed because the two ends do not share a channel: the
 * launcher is `/bin/sh` with Steam's runtime stripped out of its environment,
 * and a file it can write is the whole protocol. The launch and the note are
 * milliseconds apart in practice -- the script runs about 90ms after the launch
 * starts -- but the backend call has to get there too, so the window is generous
 * and cheap: a handful of calls that stop at the first yes.
 */
async function waitForBounce(appId: number): Promise<string | null> {
  const deadline = Date.now() + BOUNCE_TIMEOUT_MS;
  for (;;) {
    try {
      const result = await launchBounced(appId);
      if (result?.bounced) return result.others ?? "";
    } catch (error) {
      // The backend is the only thing that can answer this. If it cannot, the
      // launcher has already made the decision either way and nothing here can
      // improve on it.
      logError("could not check whether the launch was stopped", error);
      return null;
    }
    if (Date.now() >= deadline) return null;
    await sleep(BOUNCE_POLL_MS);
  }
}

/**
 * The games worth naming when `startedAppId` came up, or null for "not ours to
 * mention".
 *
 * Two rules. Nothing else running is nothing to say. And **one side has to be
 * ours**: two Steam games together is a case Steam already warned about, and
 * repeating it a second later would be noise about somebody else's dialog.
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
 * Watch for a second game and deal with it. Returns an unregister function.
 *
 * Everything is read when the notification arrives: `RunningApps` is a computed
 * getter and the added-games cache is refreshed elsewhere, so nothing here holds
 * state that could go stale between launches.
 */
export function watchForDoubleLaunch(): () => void {
  return onGameLaunch((appId) => {
    void handleLaunch(appId);
  });
}

async function handleLaunch(appId: number): Promise<void> {
  const game = addedGame(appId);
  // Read now, not after the wait: by then the launch has resolved one way or
  // the other and this list has moved on.
  const others = runningGames(appId);

  if (game) {
    const bounced = await waitForBounce(appId);
    if (bounced !== null) {
      // The launcher refused, so nothing started and the full question is still
      // worth asking -- close what is running and go, or go anyway, or neither.
      showLaunchConflict({
        title: game.title,
        running: others.length ? others : namedFromIds(bounced),
        onLaunch: () => {
          void (async () => {
            try {
              await approveLaunch(appId);
            } catch (error) {
              // Without the token the next launch bounces again, which is a
              // loop the user cannot get out of. Better to say nothing started
              // than to start something that will not.
              logError("could not approve the launch", error);
              return;
            }
            launchApp(appId);
          })();
        },
      });
      return;
    }
  }

  // Either not ours, or ours and it started anyway. Nothing was stopped, so the
  // most that can be done is notice.
  const mention = othersToMention(appId, others, (id) => Boolean(addedGame(id)));
  if (!mention) return;

  toaster.toast({
    title: "Two games are running",
    body: stillRunningLine(mention),
    duration: 8000,
    // Deliberately not "close it" on the tap itself. Closing a game can lose
    // unsaved work, and a toast is the easiest thing on this device to press by
    // accident -- so the tap opens the question and the question does the
    // closing.
    onClick: () => showCloseRunning(mention),
  });
}

/**
 * Fall back to the ids the launcher saw when Steam's own list has nothing.
 *
 * The script writes what it found; `RunningApps` is the nicer source because it
 * carries names, but the two are read at slightly different moments and this
 * dialog must never open with an empty list behind it.
 */
function namedFromIds(others: string): RunningGame[] {
  return others
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => ({ appId: Number(id), title: "another game", gameId: id }));
}
