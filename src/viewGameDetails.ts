import { Navigation } from "@decky/ui";

/**
 * Steam's own page for one app. Non-Steam shortcuts use the same route.
 */
export function gameRoute(appId: number): string {
  return `/library/app/${appId}`;
}

/**
 * Open a game's Steam page from inside a modal: dismiss first, navigate second.
 *
 * The order is the whole of it, and it is the rule `playGame` follows for the
 * same reason: Steam re-reveals each modal as the one above it dismisses, so
 * anything still standing comes back on top of the page just navigated to.
 *
 * `CloseSideMenus` last, because the Quick Access panel is an overlay over
 * whatever the main UI is showing — navigating under it leaves the panel in
 * front of the thing it was asked to go to.
 */
export function viewGameDetails(appId: number, dismiss?: () => void): void {
  dismiss?.();
  Navigation.Navigate(gameRoute(appId));
  Navigation.CloseSideMenus();
}
