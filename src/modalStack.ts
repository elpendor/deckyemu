import { showModal, type ShowModalResult } from "./steamui";
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
 * The two defaults -- the popup's title, and leaving the main window shown --
 * are restated because passing props at all replaces them.
 */
export function openModal(modal: ReactNode): ShowModalResult {
  // `fnOnClose` closes over `handle` before the assignment completes, which is
  // fine and not a trick: the arrow is only built here, and by the time Steam
  // calls it the binding is the same object the caller was handed back.
  const handle: ShowModalResult = showModal(modal, undefined, {
    strTitle: "DeckyEmu",
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
 * For the moment before going somewhere else -- pressing something in the Quick
 * Access panel, navigating to a page, starting a game. Anything of ours still
 * standing would be revealed on top of it.
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

/**
 * Close our modals when something in the Quick Access panel is pressed.
 *
 * Steam re-reveals each modal as the one above it dismisses, so a modal left
 * open under the panel came back over it once the panel opened something of
 * its own -- the file browser, a dropdown, a dialog -- and took the overlay, so
 * the panel would not open again. Opening the panel alone is no reason to
 * close anything: Steam's own dialogs stay put under it, and a glance at Quick
 * Access cost the game editor its unsaved edits.
 *
 * A press (A, or a tap) raises `vgp_onok` and `click` on what was pressed;
 * listening in the capture phase closes ours before its handler opens
 * anything. D-pad moves raise neither. Returns the cleanup.
 */
export function closeModalsOnPress(element: HTMLElement): () => void {
  const close = () => closeOpenModals();
  for (const type of PRESS_EVENTS) element.addEventListener(type, close, CAPTURE);
  return () => {
    for (const type of PRESS_EVENTS) element.removeEventListener(type, close, CAPTURE);
  };
}

const PRESS_EVENTS = ["vgp_onok", "click"];
const CAPTURE = { capture: true };

/** How many are open. For checks; nothing in the plugin asks. */
export function openModalCount(): number {
  return open.size;
}
