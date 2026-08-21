import { toaster } from "@decky/api";

import { showLaunchConflict } from "./LaunchConflictModal";
import { launchApp, runningGames } from "./steam";

/** What `playGame` did, which is not always "launched". */
export type PlayResult = "launched" | "refused" | "asked";

/**
 * Ask Steam to start the game, and toast if it will not.
 *
 * Split out from `playGame` because the conflict dialog needs the same two
 * steps at a different moment -- after the user has chosen -- and a second copy
 * of the toast is a second wording to keep in step.
 */
function launchNow(appId: number): PlayResult {
  if (launchApp(appId)) return "launched";
  toaster.toast({
    title: "Could not start the game",
    body: "Steam did not accept the launch request. Try it from the library.",
  });
  return "refused";
}

/**
 * Start a game from inside a modal: dismiss first, launch second.
 *
 * The order is the whole of it, and it is the same rule the navigation buttons
 * follow -- close every modal, then go. Steam re-reveals each modal as the one
 * above it dismisses, so anything still standing comes back over the game that
 * is starting -- and unlike a page, a game cannot be backed out of to close it.
 * `dismiss` therefore runs before the launch and not after.
 *
 * The failure toast lives here rather than at each call site for the same
 * reason: by the time it could fire, the modal that would have shown an error
 * message has already gone.
 *
 * **Another game already running takes a detour.** `SteamClient.Apps.RunGame`
 * is the launch and nothing else -- Steam's own warning about running two games
 * at once belongs to its library button, so going straight to `RunGame` starts
 * a second game over the first in silence. `LaunchConflictModal` asks Steam's
 * question instead, and `dismiss` is held back until the user has answered:
 * closing the list first would take away the thing the dialog was opened from
 * and leave a cancel with nowhere to go back to. Returns "asked" in that case;
 * the launch happens later or not at all.
 *
 * Its own module rather than a method on either modal because both want it --
 * the game editor's "save and test launch" and the added-games list's play
 * button are the same steps, and the version that drifts is the one nobody is
 * looking at.
 *
 * The dialog arrives through `showLaunchConflict` rather than as JSX here, and
 * that is what keeps this file testable: `react` is not an installed package --
 * Steam provides it at runtime and rollup leaves it external -- so a module that
 * renders anything cannot be imported under Node at all. Every ordering below
 * is a thing that fails only on a device and never as an error, which is
 * precisely what needs a check.
 */
export function playGame(appId: number, title: string, dismiss?: () => void): PlayResult {
  // Read at the moment of the press. `RunningApps` is a computed getter, so an
  // answer from when the list was opened would be a guess about now.
  const others = runningGames(appId);

  if (others.length) {
    showLaunchConflict({
      title,
      running: others,
      onLaunch: () => {
        dismiss?.();
        launchNow(appId);
      },
    });
    return "asked";
  }

  dismiss?.();
  return launchNow(appId);
}
