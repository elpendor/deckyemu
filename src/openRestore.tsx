import { RestoreSavesModal } from "./RestoreSavesModal";
import { openModal } from "./modalStack";

/**
 * Open the restore dialog on whatever backups are on the Deck.
 *
 * Out here for the reason `importDefinition` is: there are two ways in and they
 * must not diverge. The Library tab offers it on anything already here; the
 * transfer dialog offers it on a backup that has just arrived, the same way that
 * dialog offers Import on a definition and Install on a firmware file. Both land
 * on the same screen, so the counts and the confirmation are the same wherever
 * somebody started.
 *
 * A module rather than an import straight into `TransferModal`, which the
 * restore dialog itself imports to send a backup here -- the indirection is what
 * keeps that from being a two-file cycle read by anyone opening either.
 */
export function openRestoreSaves(): void {
  openModal(<RestoreSavesModal />);
}
