import { ConfirmModal } from "./steamui";
import { crashMessage } from "./crashMessage";
import { openModal } from "./modalStack";

/**
 * A failure somebody has to read: a dialog, not a toast that is gone in
 * seconds. Toasts are for confirmations only.
 *
 * `reason` is what the backend said, or what was thrown; an empty one reads as
 * `fallback`, so the dialog never says less than what was being done.
 */
export function showFailure(title: string, reason: unknown, fallback = "No reason was given.") {
  const said =
    typeof reason === "string" ? reason.trim() : reason == null ? "" : crashMessage(reason);
  openModal(
    <ConfirmModal
      strTitle={title}
      strDescription={said || fallback}
      strOKButtonText="Close"
      bAlertDialog
    />,
  );
}
