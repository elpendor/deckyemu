import { ConfirmModal } from "@decky/ui";
import { toaster } from "@decky/api";

import { discardTransferredFile } from "./backend";
import { DANGER_TEXT } from "./danger";
import { logError } from "./logError";
import { openModal } from "./modalStack";
import { humanSize } from "./TransferModal";

/**
 * Deleting a file from the transfer folder, with the one question worth asking.
 *
 * The transfer folder is a staging post, and until this existed nothing could
 * take anything out of it except by *using* it -- an import consumes a
 * definition, a firmware install moves the file, a cancel deletes the partial
 * it was writing. A file that was simply not wanted stayed forever, and the
 * only way to remove it was Desktop Mode and a file manager.
 *
 * Shared by the two lists that show these files so both ask the same way. A
 * delete offered twice with two different amounts of friction is worse than
 * either, because the lighter one teaches you the heavier one is noise.
 */

/**
 * Ask, then delete `name`. `onDiscarded` runs only if something was removed.
 *
 * A confirmation for a plain delete, which is more friction than a staging
 * folder usually deserves -- but the file arrived over wifi from another
 * device, it can be several gigabytes, and there is no undo anywhere in Game
 * Mode. One press against sending a 4 GB ROM twice is a fair trade.
 */
export function confirmDiscardTransfer(
  file: { name: string; size: number },
  onDiscarded: () => void,
): void {
  openModal(
    <ConfirmModal
      strTitle={`Delete ${file.name}?`}
      strOKButtonText="Delete"
      bDestructiveWarning
      onOK={() =>
        void (async () => {
          try {
            const result = await discardTransferredFile(file.name);
            if (!result.ok) {
              toaster.toast({ title: "Could not delete", body: result.error ?? "" });
              return;
            }
            // Quiet when it was already gone: the list was stale, the folder is
            // in the state the user asked for, and a toast saying nothing
            // happened reads as a failure.
            if (result.removed) {
              toaster.toast({ title: "Deleted", body: `${file.name} · ${humanSize(file.size)}` });
            }
            onDiscarded();
          } catch (error) {
            logError("could not discard a transferred file", error);
            toaster.toast({ title: "Could not delete", body: "Something went wrong." });
          }
        })()
      }
      strDescription={
        <div style={DANGER_TEXT}>
          This deletes {humanSize(file.size)} from the transfer folder on this Deck.
          It cannot be undone from here — the file would have to be sent again.
          Anything already added to your library or installed into an emulator is
          unaffected.
        </div>
      }
    />,
  );
}
