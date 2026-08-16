import { Navigation } from "@decky/ui";

/**
 * Where the setup page lives, and how to get to one of its tabs.
 *
 * Its own module, holding no components and importing none. `ManagePage` renders
 * most of the panels in this plugin, and several of those want to send the user
 * to a tab -- the game editor to the core list, the add panel to RetroArch or
 * artwork. Importing `ManagePage` for that closes a loop:
 *
 *   ManagePage -> LibraryPanel -> AddedGamesModal -> GameEditorModal -> ManagePage
 *
 * which rollup reports and which only works because the call happens inside a
 * handler rather than while the modules are evaluating. Two lines of navigation
 * are not worth depending on that.
 *
 * The same reason `src/steam/` keeps clear of backend imports: what a thing
 * *needs* decides where it lives, and this needs nothing.
 */

/**
 * A route per tab, because the route *is* the selection.
 *
 * SidebarNavigation has no "selected page" prop, whatever `@decky/ui`'s types
 * suggest. Steam's own component picks the tab by matching the current URL
 * against each page's `route` and falls back to the first page, then navigates
 * with `history.replace` when a tab is tapped. Pages carrying no route all
 * compare equal to "no route", which is why supplying `page`/`onPageRequested`
 * made every tab a no-op.
 *
 * Selection living in the URL is also what fixes the tab being lost: opening
 * SteamGridDB pushes the browser route, and pressing B pops back to this exact
 * URL rather than to a bare page that starts over at the first tab.
 *
 * `MANAGE_ROUTE` must be registered non-exact for these to resolve (see
 * `index.tsx`).
 */
export const MANAGE_ROUTE = "/deckyemu/manage";

export const tabRoute = (tab: string) => `${MANAGE_ROUTE}/${tab}`;

/** The tabs anything outside the page is allowed to ask for by name. */
export type ManageTab = "artwork" | "retroarch" | "emulators";

/**
 * Navigate to the setup page, optionally straight to one tab.
 *
 * Naming a tab works for the same reason the tabs work at all: the selection is
 * the URL, so arriving at a tab's route selects it. Bare `MANAGE_ROUTE` matches
 * no page and falls back to the first, which is the wanted default.
 */
export function openManagePage(tab?: ManageTab) {
  Navigation.Navigate(tab ? tabRoute(tab) : MANAGE_ROUTE);
  Navigation.CloseSideMenus();
}
