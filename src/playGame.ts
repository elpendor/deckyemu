import { toaster } from "@decky/api";

import { launchApp } from "./steam";

/**
 * Start a game from inside a modal: dismiss first, launch second.
 *
 * The order is the whole of it, and it is the same rule the navigation buttons
 * follow -- close every modal, then go. Steam re-reveals each modal as the one
 * above it dismisses, so anything still standing comes back over the game that
 * is starting -- and unlike a page, a game cannot be backed out of to close it.
 * `dismiss` therefore runs before the launch and not after.
 *
 * The failure toast lives here rather than at the call sites for the same
 * reason: by the time it could fire, the modal that would have shown an error
 * message has already gone.
 *
 * Its own module rather than a method on either modal because both want it --
 * the game editor's "save and test launch" and the added-games list's play
 * button are the same two steps, and the version that drifts is the one nobody
 * is looking at. Imports no component, so it costs nothing to reach for.
 *
 * Returns whether Steam accepted the request, which is all `RunGame` reports;
 * a game that starts and then dies is a launcher problem and shows up on the
 * screen, not here.
 */
export function playGame(appId: number, dismiss?: () => void): boolean {
  dismiss?.();

  if (launchApp(appId)) return true;

  toaster.toast({
    title: "Could not start the game",
    body: "Steam did not accept the launch request. Try it from the library.",
  });
  return false;
}
