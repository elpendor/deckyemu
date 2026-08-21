import { addedGame } from "./addedGames";
import { approveLaunch, launchBounced } from "./backend";
import { showLaunchConflict } from "./LaunchConflictModal";
import { launchApp, onGameLaunch, runningGames, type RunningGame } from "./steam";
import { logError } from "./logError";

/**
 * The panel half of the launch gate.
 *
 * Steam will not warn before launching one of our games over a running one: its
 * check is gated on `app_type & 1` (`EAppType.Game`) and every DeckyEmu game is
 * a non-Steam shortcut, `1073741824`. Nothing on the Steam side can stop the
 * launch either -- `launchers.py` records what each of the two candidates did
 * instead, both measured on a device.
 *
 * What stops it is the generated launcher script, because that is what Steam
 * actually starts; the emulator is the line after. The script refuses and
 * leaves a note. This side collects the note and asks:
 *
 *   Steam starts a launch  ->  onGameLaunch
 *     one of ours, and the launcher refused  ->  the dialog, then relaunch
 *     anything else                          ->  nothing at all
 *
 * **Asked rather than predicted**, and that is the whole design. This side could
 * work out for itself that two games are about to overlap, but then the dialog
 * and the launcher would be two guesses that can disagree -- and the way they
 * disagree is a game that silently does not start with nothing on screen to say
 * why. Waiting for the note means the dialog only ever belongs to a launch that
 * really was stopped.
 */

/** How long to wait for the launcher to leave its note, and how often to look. */
const BOUNCE_TIMEOUT_MS = 4000;
const BOUNCE_POLL_MS = 250;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Wait for this launch to be refused, or decide it was not.
 *
 * Polled rather than pushed because the two ends share no channel: the launcher
 * is `/bin/sh` with Steam's runtime stripped out of its environment, and a file
 * it can write is the whole protocol. The two are milliseconds apart in practice
 * -- the script runs about 90ms after the launch starts -- but the backend call
 * has to get there too, so the window is generous and cheap: a handful of calls
 * that stop at the first yes.
 */
async function waitForBounce(appId: number): Promise<string | null> {
  const deadline = Date.now() + BOUNCE_TIMEOUT_MS;
  for (;;) {
    try {
      const result = await launchBounced(appId);
      if (result?.bounced) return result.others ?? "";
    } catch (error) {
      // The backend is the only thing that can answer this. If it cannot, the
      // launcher has already decided either way and nothing here improves on it.
      logError("could not check whether the launch was stopped", error);
      return null;
    }
    if (Date.now() >= deadline) return null;
    await sleep(BOUNCE_POLL_MS);
  }
}

/**
 * Fall back to the ids the launcher saw when Steam's own list has nothing.
 *
 * `RunningApps` is the better source because it carries names, but the two are
 * read at slightly different moments and this dialog must never open with an
 * empty list behind it -- it puts `running[0]` straight into a sentence.
 */
export function namedFromIds(others: string): RunningGame[] {
  return (others || "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => ({ appId: Number(id), title: "another game", gameId: id }));
}

/** Watch for a stopped launch and ask about it. Returns an unregister function. */
export function watchLaunches(): () => void {
  return onGameLaunch((appId) => {
    void handleLaunch(appId);
  });
}

async function handleLaunch(appId: number): Promise<void> {
  const game = addedGame(appId);
  // Not one of ours: the launcher is not ours to gate, so nothing was stopped
  // and there is nothing to say about it.
  if (!game) return;

  // Read now, not after the wait. By then the launch has resolved and this list
  // has moved on.
  const others = runningGames(appId);

  const bounced = await waitForBounce(appId);
  if (bounced === null) return;

  showLaunchConflict({
    title: game.title,
    running: others.length ? others : namedFromIds(bounced),
    onLaunch: () => {
      void (async () => {
        try {
          await approveLaunch(appId);
        } catch (error) {
          // Without the token the next launch bounces again, which is a loop
          // with no way out. Better that nothing starts than that something
          // starts which cannot.
          logError("could not approve the launch", error);
          return;
        }
        launchApp(appId);
      })();
    },
  });
}
