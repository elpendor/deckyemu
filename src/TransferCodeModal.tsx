import { DialogButton, ModalRoot, ToggleField } from "@decky/ui";

import { HandoffCode } from "./HandoffCode";

/**
 * The QR code and the settings behind it, on top of the transfer dialog.
 *
 * A modal rather than the strip expanding in place. Expanding put the dialog
 * back the way it was — 200px of QR above the list — with nothing to press to
 * undo it, so the fold was one-way in the wrong direction. Opening it over the
 * top gives the B button a job and leaves the dialog underneath exactly as it
 * was found.
 *
 * The two settings come with it because they belong to the thing it shows: the
 * address the code is for, and whether that address survives the session.
 */
interface Props {
  url: string;
  shortUrl: string;
  pin: string;
  pinLocked: boolean;
  targetDir: string;
  idleMinutes: number;
  remember: boolean;
  onRemember: (next: boolean) => void;
  busy?: boolean;
  closeModal?: () => void;
}

export function TransferCodeModal({
  url,
  shortUrl,
  pin,
  pinLocked,
  targetDir,
  idleMinutes,
  remember,
  onRemember,
  busy,
  closeModal,
}: Props) {
  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <h1 style={{ marginTop: 0, marginBottom: "12px", fontSize: "23px" }}>
        Send from another device
      </h1>

      <HandoffCode url={url} shortUrl={shortUrl} pin={pin} pinLocked={pinLocked}>
        Saving into {targetDir}. Stops after {idleMinutes} min idle — closing
        this is fine, transfers keep going.
      </HandoffCode>

      <ToggleField
        label="Remember trusted devices"
        description="Keeps the same address between sessions, so a device can bookmark this page and come straight back with no code to type. Off issues a new link each time."
        checked={remember}
        onChange={onRemember}
        disabled={busy}
      />

      <DialogButton onClick={() => closeModal?.()} style={{ marginTop: "8px" }}>
        Close
      </DialogButton>
    </ModalRoot>
  );
}
