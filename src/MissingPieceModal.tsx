import { ConfirmModal } from "@decky/ui";

import { missingPieceMessage, type MissingPiece } from "./missingPiece";
import { openModal } from "./modalStack";

/**
 * Say why a launch was stopped, when what is missing is part of the game.
 *
 * **One button, because there is no second thing to offer.** The launch
 * conflict dialog has "launch anyway" and this deliberately does not: the game
 * cannot start, so an override would only reproduce the silent failure this
 * exists to replace.
 *
 * Opened from `launchGate`, which is also where the launch conflict is decided,
 * so the two dialogs can never both appear for one launch — the script writes
 * one note or the other and exits.
 */
export function showMissingPiece(piece: MissingPiece, title: string, name = "") {
  const message = missingPieceMessage(piece, title, name);
  openModal(
    <ConfirmModal
      strTitle={message.heading}
      strDescription={message.body}
      strOKButtonText="Close"
      // No cancel: the two buttons would do the same nothing, and a dialog with
      // a meaningless choice in it reads as though something was declined.
      bAlertDialog
    />,
  );
}
