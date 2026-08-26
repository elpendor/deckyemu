/**
 * Non-Steam shortcuts: making one, pointing it somewhere, and starting it.
 *
 * What Steam will not tell you from here is what a shortcut *runs* -- the
 * overview carries no path -- which is why `steam_shortcuts.py` reads
 * shortcuts.vdf on the backend and why `shortcutExists` can only answer whether
 * something exists under an id, not whether it is still the right game.
 */
import { appStore, collectionStore, steamClient, waitForOverview } from "./client";
import { pinGamepadLayout } from "./layout";

export interface CreateShortcutArgs {
  title: string;
  exe: string;
  startDir: string;
  launchOptions: string;
  /**
   * A Steam Input layout this game's emulator needs, as a `template://` url.
   *
   * Empty for almost everything, which leaves Steam's own choice alone unless it
   * guessed one that cannot play a game. Vita3K sets it because the Deck powers
   * its gyro down unless the running game's layout binds it.
   */
  layout?: string;
}

/**
 * Creates the non-Steam shortcut and returns its appId.
 *
 * Current Steam clients accept all four AddShortcut arguments but only
 * reliably act on the first two -- it does not even set the name dependably.
 * The fields therefore have to be applied afterwards with the explicit
 * setters, and those only stick once Steam has registered the new app in
 * appStore. Both quirks are load-bearing here, not defensive padding.
 */
export async function createShortcut(args: CreateShortcutArgs): Promise<number> {
  const apps = steamClient()?.Apps;
  if (!apps?.AddShortcut) {
    throw new Error("SteamClient.Apps.AddShortcut is unavailable.");
  }

  const appId: number = await apps.AddShortcut(args.title, args.exe, "", "");

  if (typeof appId !== "number" || appId <= 0) {
    throw new Error("Steam did not return an app id for the new shortcut.");
  }

  if (!(await waitForOverview(appId))) {
    console.warn("[deckyemu] app overview never appeared; applying fields anyway");
  }

  try {
    apps.SetShortcutName?.(appId, args.title);
    apps.SetShortcutExe?.(appId, args.exe);
    apps.SetShortcutStartDir?.(appId, args.startDir);
    apps.SetShortcutLaunchOptions?.(appId, args.launchOptions);
  } catch (error) {
    console.error("[deckyemu] could not apply shortcut fields", error);
    throw new Error("Steam created the shortcut but rejected its settings.");
  }

  // Not awaited. It has to wait for Steam to notice the name before it can tell
  // whether the layout needs repairing, and nothing about adding a game depends
  // on the answer -- making the caller hold for a couple of seconds would buy
  // only a return value nobody reads. See layout.ts for what it is repairing.
  void pinGamepadLayout(appId, 8, args.layout ?? "");

  return appId;
}

export function removeShortcut(appId: number): boolean {
  try {
    const apps = steamClient()?.Apps;
    if (!apps?.RemoveShortcut) return false;
    apps.RemoveShortcut(appId);
    // Whether Steam has finished removing it is not knowable from here -- the
    // call returns nothing and the library updates on its own schedule. What
    // this reports is that the request was made, which is what a caller
    // counting "how many did I ask to go" needs.
    return true;
  } catch (error) {
    console.error("[deckyemu] RemoveShortcut failed", error);
    return false;
  }
}

/** True when Steam still has a shortcut for this appId. */
export function shortcutExists(appId: number): boolean {
  try {
    return Boolean(appStore()?.GetAppOverviewByAppID?.(appId));
  } catch (error) {
    console.error("[deckyemu] could not look up app", appId, error);
    // Assume it exists rather than inviting the user to delete a live entry.
    return true;
  }
}

/**
 * Rename an existing shortcut.
 *
 * The same call is used when creating one, where it is known to work. Whether
 * Steam refreshes an already-visible library entry immediately is less certain,
 * so the caller should not treat a stale-looking name as a failure.
 */
export function renameShortcut(appId: number, name: string): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.SetShortcutName) return false;
  try {
    apps.SetShortcutName(appId, name);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not rename shortcut", appId, error);
    return false;
  }
}

/**
 * Steam's GameID for a shortcut.
 *
 * Read from the app overview when possible, since that is what Steam itself
 * passes to RunGame. The fallback computes it the way Steam encodes a non-Steam
 * shortcut -- the appid in the high 32 bits with the shortcut type bits set --
 * for the case where the overview has not materialised yet.
 */
function shortcutGameId(appId: number): string {
  try {
    const fromStore = appStore()?.GetAppOverviewByAppID?.(appId)?.gameid;
    if (fromStore) return String(fromStore);
  } catch (error) {
    console.error("[deckyemu] could not read gameid for", appId, error);
  }
  return ((BigInt(appId) << 32n) | 0x0200000000000000n).toString();
}

/**
 * Launch a game through Steam, exactly as selecting it in the library would.
 *
 * Going through Steam rather than running the script ourselves means gamescope,
 * Steam Input and the overlay all behave as they do in normal play -- which is
 * the point of a test launch.
 */
export function launchApp(appId: number): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.RunGame) return false;
  try {
    apps.RunGame(shortcutGameId(appId), "", -1, 100);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not launch app", appId, error);
    return false;
  }
}

/**
 * Keep a shortcut out of the library without deleting it.
 *
 * For the setup shortcut, which exists only because gamescope composites nothing
 * Steam did not launch. It has to be a real Steam entry to work at all, and
 * nobody wants it on their shelf next to their games.
 *
 * Steam models hidden as a collection rather than a flag, which is why this goes
 * through `collectionStore` rather than `SteamClient.Apps`. Returns whether it
 * took: a failure here is untidy rather than broken -- the shortcut still works,
 * it is just visible -- so the caller carries on either way.
 */
export function setAppHidden(appId: number, hidden: boolean): boolean {
  try {
    const store = collectionStore() as unknown as {
      SetAppsAsHidden?: (appIds: number[], hidden: boolean) => void;
    } | null;
    if (typeof store?.SetAppsAsHidden !== "function") return false;
    store.SetAppsAsHidden([appId], hidden);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not hide app", appId, error);
    return false;
  }
}

/** Point an adopted game's shortcut at its rebuilt launcher script. */
export function repointShortcut(appId: number, exe: string): boolean {
  const apps = steamClient()?.Apps;
  if (!apps?.SetShortcutExe) return false;
  try {
    apps.SetShortcutExe(appId, exe);
    apps.SetShortcutStartDir?.(appId, exe.slice(0, Math.max(0, exe.lastIndexOf("/"))));
    return true;
  } catch (error) {
    console.error("[deckyemu] could not repoint shortcut", appId, error);
    return false;
  }
}
