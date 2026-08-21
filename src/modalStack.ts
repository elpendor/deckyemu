import { showModal, type ShowModalResult } from "@decky/ui";
import { type ReactNode } from "react";

/**
 * Every modal this plugin has open, so they can be dismissed together.
 *
 * Steam has no "close all modals" -- what it offers is a `fnCloseModal` prop per
 * dialog -- and `showModal` hands back a `Close` that nothing was keeping. So
 * the plugin could open modals and never close one it did not have in scope.
 *
 * **That is a real fault and not tidiness.** Steam re-reveals each modal as the
 * one above it dismisses, so a modal left on the stack lands over whatever comes
 * next. Taking a received file into the add flow closes the transfer dialog and
 * opens the Quick Access panel; with the added-games list still underneath, the
 * list was revealed, took the active overlay back, and the panel closed again
 * about a second after it appeared. Read off the device: overlay 19 active and
 * holding "Added games (6)", with the panel not mounted at all.
 *
 * It is the same rule as "close every modal before navigating", one layer down:
 * anything still on the stack arrives on top of where you just went.
 *
 * Open every modal through `openModal` so this stays complete. A registry that
 * some call sites use is worse than none -- it reads as a guarantee and is not
 * one.
 */
const open = new Set<ShowModalResult>();

/**
 * Show a modal and remember it until it closes.
 *
 * `fnOnClose` is what keeps the set honest: a modal dismissed the ordinary way
 * -- the B button, its own Close, a dialog closing itself -- takes itself out,
 * so `closeOpenModals` is never calling `Close` on things that went long ago.
 *
 * The two defaults are decky's own, restated because passing props at all
 * replaces them.
 */
export function openModal(modal: ReactNode): ShowModalResult {
  // Declared first: the callback closes over it, and it has to be the same
  // object the caller gets back.
  let handle: ShowModalResult;
  handle = showModal(modal, undefined, {
    strTitle: "Decky Dialog",
    bHideMainWindowForPopouts: false,
    fnOnClose: () => {
      open.delete(handle);
    },
  });
  open.add(handle);
  return handle;
}

/**
 * Dismiss everything this plugin has open.
 *
 * For the moment before going somewhere else -- opening the Quick Access panel,
 * navigating to a page, starting a game. Anything of ours still standing would
 * be revealed on top of it.
 *
 * Never throws. A handle whose modal has already gone is the ordinary case
 * during a cascade, and one that refuses is not a reason to leave the rest
 * open.
 */
export function closeOpenModals(): void {
  for (const handle of [...open]) {
    open.delete(handle);
    try {
      handle.Close();
    } catch (error) {
      console.error("[deckyemu] could not close a modal", error);
    }
  }
}

/** How many are open. For checks; nothing in the plugin asks. */
export function openModalCount(): number {
  return open.size;
}
