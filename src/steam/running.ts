import { appStore, steamClient, uiStore } from "./client";

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
 * Call `launched` when Steam starts a launch, with the app id it is for.
 *
 * `RegisterForGameActionStart` is an ordinary registered callback -- nothing
 * matched in minified source, nothing of Steam's replaced -- and it is the one
 * that fires. `RegisterForAppLifetimeNotifications` was here first and was
 * wrong: it registers cleanly, returns a handle, and then never fires for a
 * non-Steam shortcut. Measured across a whole launch-and-quit of one of our
 * games: ten game-action events, zero lifetime ones. `RunningApps` updates by
 * some other route.
 *
 * Fires at the *start* of the launch, before the app is running, which is
 * exactly when the answer to "what else is on" is still the interesting one.
 *
 * Steam passes a **GameID**, not an appid; `resolve` turns one into the other.
 * Returns an unregister function, and one that does nothing if the callback
 * could not be registered, so `onDismount` never has to ask which it got.
 */
export function onGameLaunch(launched: (appId: number) => void): () => void {
  const apps = steamClient()?.Apps;
  if (!apps?.RegisterForGameActionStart) {
    console.error("[deckyemu] no game action notifications; launches will not be noticed");
    return () => undefined;
  }
  try {
    const handle = apps.RegisterForGameActionStart(
      (_actionId: number, gameId: string, _action: string) => {
        // Inside Steam's own dispatcher. A throw here is not ours to spend.
        try {
          const appId = appIdForGameId(gameId);
          if (appId) launched(appId);
        } catch (error) {
          console.error("[deckyemu] launch handler failed", error);
        }
      },
    );
    return () => {
      try {
        handle?.unregister?.();
      } catch (error) {
        console.error("[deckyemu] could not stop watching launches", error);
      }
    };
  } catch (error) {
    console.error("[deckyemu] could not watch launches", error);
    return () => undefined;
  }
}

/**
 * The appid behind one of Steam's GameIDs.
 *
 * `GetAppOverviewByGameID` is what Steam's own code uses. The fallback undoes
 * the encoding a non-Steam shortcut's GameID is built with -- the appid in the
 * high 32 bits -- which covers a shortcut Steam has not materialised an
 * overview for yet, the same gap `shortcutGameId` fills going the other way.
 */
export function appIdForGameId(gameId: string): number {
  try {
    const fromStore = appStore()?.GetAppOverviewByGameID?.(gameId)?.appid;
    if (fromStore) return Number(fromStore);
  } catch (error) {
    console.error("[deckyemu] could not resolve gameid", gameId, error);
  }
  try {
    const value = BigInt(gameId);
    // A plain appid rather than a 64-bit GameID: Steam's own games arrive this
    // way and need no unpacking.
    if (value < 0x100000000n) return Number(value);
    return Number(value >> 32n);
  } catch {
    return 0;
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
