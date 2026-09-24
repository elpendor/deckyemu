import { DialogButton, ModalRoot } from "@decky/ui";

import { COLUMN } from "./dialogStyle";
import { HandoffCode } from "./HandoffCode";
import { TrustedDevices } from "./TrustedDevices";

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
  /** Something is arriving, so the change waits rather than cutting it off. */
  deferred?: boolean;
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
  deferred,
  busy,
  closeModal,
}: Props) {
  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/*
        * A column with a gap, because a modal's own content box has none.
        * Measured on the device: the settings row sat against the bottom of a
        * 190px QR block with zero between them, so it read as part of the code
        * rather than as a thing of its own, and the only separation anywhere
        * was 8px of margin somebody had put on the Close button.
        */}
      <div style={{ ...COLUMN, gap: "14px" }}>
        <h1 style={{ margin: 0, fontSize: "23px" }}>Send from another device</h1>

        <HandoffCode url={url} shortUrl={shortUrl} pin={pin} pinLocked={pinLocked}>
          Saving into {targetDir}. Stops after {idleMinutes} min idle — closing
          this is fine, transfers keep going.
        </HandoffCode>

        {/* A rule and a wider gap above it. A settings row under a block that
            large needs saying that it is not part of it, and the gap alone was
            not enough to do that. */}
        <div
          style={{
            borderTop: "1px solid rgba(255, 255, 255, 0.1)",
            paddingTop: "14px",
            marginTop: "2px",
          }}
        >
          <TrustedDevices
            remember={remember}
            onChange={(next) => {
              onRemember(next);
              // This dialog holds the address and the code it was opened with,
              // and changing the setting reissues both -- so a moment from now
              // the square on screen encodes a dead token and the digits are
              // somebody else's. Close rather than show them. Deferred is the
              // exception: nothing is reissued until receiving next starts, so
              // what is on screen stays true.
              if (!deferred) closeModal?.();
            }}
            busy={busy}
            deferred={deferred}
          />
        </div>

        <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
      </div>
    </ModalRoot>
  );
}
