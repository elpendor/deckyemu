import { addedGame } from "./addedGames";
import { addEventListener, removeEventListener } from "@decky/api";

import { cloudBackupAfterPlay, cloudReleaseLaunch } from "./backend";
import { showCloudDiffer } from "./CloudDifferModal";
import { showCloudFetch } from "./CloudFetchModal";
import { logError } from "./logError";
import { onGameLaunch, runningGames } from "./steam";

/**
 * Copying a game's saves up once it has been put down.
 *
 * **Why this lives in the panel and not in the launcher.** The launcher script
 * is the obvious place -- it already has an `EXIT INT TERM` trap and it knows
 * exactly which emulator ran. It is the wrong place: Steam's reaper waits for
 * every descendant of the process it started, so an upload in that trap holds
 * the library tile on "Running" until the network finishes. A save directory
 * over hotel wifi is minutes of a game that has already quit, and there is
 * nothing on screen to explain it.
 *
 * So the copy runs in decky's own process, which the reaper knows nothing
 * about, and this is the part that notices when to ask for it.
 *
 * **Watched rather than notified**, because Steam offers nothing better.
 * `RegisterForAppLifetimeNotifications` never fires for non-Steam shortcuts --
 * measured on the device across ten launches, zero lifetime events -- and every
 * DeckyEmu game is one. `RunningApps` does update, so a launch is a real event
 * and the ending is found by looking. See `steam/running.ts`.
 *
 * The polling costs nothing when nothing is running: it starts on a launch of
 * one of ours and stops the moment that game is gone. There is no timer at rest.
 *
 * The other end of the same launch is watched from here but not driven from
 * here. Bringing saves *down* is the backend's own loop, because Steam tells
 * this side about a launch a moment after the script has already run -- twice
 * that cost a game its save. The launcher announces itself and the backend
 * answers; this only puts the dialogs on screen, on the two events that
 * reports.
 */

/**
 * How often to look while a game is running.
 *
 * Reading `RunningApps` is a property read on a store Steam keeps up to date,
 * not a call into anything, so the interval is about how soon the copy starts
 * rather than about cost. Four seconds is under the time it takes to get from a
 * game closing to the library redrawing, which is when somebody would next
 * think about it.
 */
const LOOK_MS = 4000;

/**
 * How long to keep watching one game.
 *
 * A guard, not a policy. If `RunningApps` ever stops listing a game that has
 * ended -- a Steam change, a shortcut that never registered -- the alternative
 * to this is an interval that runs until the Deck is rebooted. Eight hours is
 * longer than anybody plays one thing in a sitting and short enough that a leak
 * is bounded.
 */
const GIVE_UP_MS = 8 * 60 * 60 * 1000;

/**
 * How long a launch may be held before it is worth explaining.
 *
 * Under this, nothing appears at all. The ordinary launch has nothing to fetch
 * and is answered in a fraction of a second, and a dialog for that is a flash
 * on every launch of every game -- worse than silence, and impossible to read.
 *
 * Over it, the alternative is several seconds of a black screen that looks
 * exactly like a game which has failed to start, which is the one moment this
 * is worth interrupting for. 1.2s is past the fast path with room to spare and
 * short enough that the dialog arrives before somebody starts wondering.
 */
const EXPLAIN_AFTER_MS = 1200;

/** The games being watched, so a relaunch does not start a second interval. */
const watching = new Set<number>();

function stillRunning(appId: number): boolean {
  // `runningGames` takes what to *exclude*, so asking with no argument and
  // looking for the id is how to ask whether one particular game is up.
  return runningGames().some((game) => game.appId === appId);
}

/**
 * Watch one game, and copy its emulator's saves up when it ends.
 *
 * Exported for the test: the interval and the two conditions that end it are
 * the whole of the logic, and a fake clock reaches them where a real one does
 * not.
 */
export function watchOne(appId: number, coreId: string): void {
  if (watching.has(appId)) return;
  watching.add(appId);

  const startedAt = Date.now();
  // A game does not appear in `RunningApps` the instant Steam says it is
  // launching, so "it is not running" is not yet true when this begins. Nothing
  // is decided until it has been seen running at least once -- otherwise every
  // launch would copy immediately and call it the end of the game.
  let seen = false;

  const timer = window.setInterval(() => {
    const up = stillRunning(appId);
    if (up) {
      seen = true;
      if (Date.now() - startedAt < GIVE_UP_MS) return;
      // Still going after the guard: stop watching rather than keep a timer
      // alive forever. Nothing is copied, because nothing has ended.
      window.clearInterval(timer);
      watching.delete(appId);
      return;
    }
    if (!seen) {
      // Never seen running. Either it is slow to appear or it failed to start;
      // either way there is nothing to copy, and the guard above ends this.
      if (Date.now() - startedAt < GIVE_UP_MS) return;
      window.clearInterval(timer);
      watching.delete(appId);
      return;
    }

    window.clearInterval(timer);
    watching.delete(appId);
    // Not awaited and quiet on failure: the game is over and the panel may not
    // even be open. The backend logs what happened and the Library row says
    // when saves last went up, which is where somebody looks for this.
    void cloudBackupAfterPlay(coreId, appId).catch((error) =>
      logError("could not copy saves up after playing", error),
    );
  }, LOOK_MS);
}

/**
 * Start noticing when DeckyEmu games end. Returns the way to stop.
 *
 * Registered at plugin scope beside `watchLaunches`, and for the same reason:
 * this has to work whether or not anybody has opened the Quick Access panel.
 */
export function watchPlaying(): () => void {
  const stopLaunches = onGameLaunch((appId) => {
    const game = addedGame(appId);
    // Not one of ours. Steam Cloud already covers a real Steam game, and a
    // shortcut somebody else made is not ours to copy anything for.
    if (!game) return;
    watchOne(appId, game.core_id);
  });

  /*
   * The saves coming down, which the backend is already doing by the time this
   * hears about it.
   *
   * Opened late, and that is the whole reason there is a timer here rather than
   * a dialog on the event itself: almost every launch has nothing to fetch and
   * is answered in a fraction of a second, and a dialog for that would be a
   * flash on every launch of every game.
   */
  let waiting: number | null = null;
  let close: (() => void) | null = null;
  let explain: number | null = null;

  const done = () => {
    if (explain !== null) window.clearTimeout(explain);
    explain = null;
    close?.();
    close = null;
    waiting = null;
  };

  const started = addEventListener<[appId: number, title: string]>(
    "cloud_fetch_started",
    (appId, title) => {
      done();
      waiting = appId;
      explain = window.setTimeout(() => {
        if (waiting !== appId) return;
        close = showCloudFetch(title || "Your game", () => {
          done();
          // The game goes now. What is still coming down keeps coming.
          void cloudReleaseLaunch(appId).catch((error) =>
            logError("could not release a held launch", error),
          );
        });
      }, EXPLAIN_AFTER_MS);
    },
  );

  /*
   * A save that differs on both sides, which is the one thing here nobody but
   * the person can settle. The game is still held while this is up -- the
   * backend keeps its heartbeat going until the answer comes back -- so this
   * closes the "getting your saves" dialog first and asks in its place.
   */
  const conflicted = addEventListener<
    [appId: number, names: string[], here: number, there: number]
  >("cloud_conflict", (appId, names, here, there) => {
    done();
    if (!names?.length) return;
    const game = addedGame(appId);
    showCloudDiffer({
      appId,
      title: game?.title ?? "this game",
      names,
      here,
      there,
    });
  });

  const finished = addEventListener<[appId: number, differing: string[]]>(
    "cloud_fetch_done",
    () => done(),
  );

  return () => {
    stopLaunches();
    done();
    removeEventListener("cloud_fetch_started", started);
    removeEventListener("cloud_fetch_done", finished);
    removeEventListener("cloud_conflict", conflicted);
  };
}
