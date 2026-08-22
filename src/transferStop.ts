import { type FileServerStatus } from "./backend";

/**
 * Whether dismissing the transfer dialog should also stop the file server.
 *
 * The dialog is not the transfer. Closing it while something is arriving has to
 * leave the server up — the send is happening on another device, which has no
 * idea a dialog was dismissed here, and TransferStatusPanel keeps the progress
 * visible in the Quick Access panel for as long as it lasts.
 *
 * **Paused counts as arriving**, and that is the whole subtlety. A transfer
 * between two attempts — the wifi dropped, the phone locked — has nothing in
 * flight for as long as the sender's backoff lasts. Reading "nothing uploading"
 * as "nothing happening" in that window stops the server underneath a sender
 * that is about to come back, which is exactly what resuming was built to
 * survive.
 *
 * Out here as a function rather than inline in the dialog because two different
 * dismissals have to reach the same answer: the dialog's own close, and being
 * dismissed from outside by `closeOpenModals` when the Quick Access panel opens.
 * Those disagreed — the second one bypassed the first entirely — and a rule this
 * easy to state is not one to write twice.
 */
export function shouldStopServer(status: FileServerStatus | null | undefined): boolean {
  if (!status?.running) return false;
  return (status.uploading ?? 0) + (status.paused ?? 0) === 0;
}
