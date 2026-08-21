import { steamClient, uiStore } from "./client";

/** A game Steam currently has running. */
export interface RunningGame {
  appId: number;
  title: string;
  /** Steam's 64-bit GameID as a string. `TerminateApp` wants this, not the appid. */
  gameId: string;
}

/**
 * What Steam has running right now, other than `exceptAppId`.
 *
 * `SteamUIStore.RunningApps` is a computed getter rather than a stored array, so
 * this reads it at the moment it is asked and never holds on to the result --
 * caching it would answer with whatever was running when a modal opened.
 *
 * The app about to be launched is excluded, which is what Steam's own launch
 * button does: relaunching something already running is not two games at once,
 * and warning about it would be a dialog about itself.
 *
 * Everything else Steam considers running is included, the plugin's own setup
 * shortcut among them. That shortcut opens a real emulator window, so it is
 * exactly the kind of thing worth naming -- "you are currently running RPCS3"
 * is true and useful, not a false positive.
 *
 * Returns an empty list rather than throwing when the store is missing or its
 * shape has changed, which turns a Steam rename into "no warning" rather than
 * into a play button that does nothing.
 */
export function runningGames(exceptAppId?: number): RunningGame[] {
  try {
    const apps = uiStore()?.RunningApps;
    if (!Array.isArray(apps)) return [];
    return apps
      .filter((app: any) => app?.appid !== undefined && app.appid !== exceptAppId)
      .map((app: any) => ({
        appId: app.appid,
        title: app.display_name || "another game",
        gameId: String(app.gameid ?? app.appid),
      }));
  } catch (error) {
    console.error("[deckyemu] could not read the running apps", error);
    return [];
  }
}

/**
 * Ask Steam to close a running game.
 *
 * `false` is the second argument Steam's own "close and launch" passes: a
 * request to quit rather than a kill, so the game gets to save. That is also
 * why the dialog above this warns about unsaved data -- a game that ignores the
 * request loses it.
 *
 * Returns whether the request was accepted, not whether the game is gone; there
 * is no synchronous way to know the second thing.
 */
export function terminateGame(gameId: string): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.TerminateApp) return false;
  try {
    apps.TerminateApp(gameId, false);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not close", gameId, error);
    return false;
  }
}
