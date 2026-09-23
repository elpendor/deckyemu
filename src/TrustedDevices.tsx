import { ConfirmModal, DialogButton } from "@decky/ui";

import { MUTED } from "./dialogStyle";
import { ICON_BUTTON_WIDE } from "./iconButton";
import { openModal } from "./modalStack";

/**
 * Whether a device can come back to this Deck without the code again.
 *
 * **Not a switch, and that is the point.** It was a `ToggleField`, one press
 * from wherever focus happened to land — and changing it stops and restarts the
 * transfer server to reissue the link, which `stop_file_server` does "whatever
 * is happening". So a stray press while a four-gigabyte ROM was arriving ended
 * the transfer. A row that states the mode with a **Change** beside it cannot
 * be altered by a press that was meant for the button below it, and the confirm
 * behind it says what the answer costs — the same shape as discarding a file or
 * installing an unrecognised dump.
 *
 * The restart is the caller's, and it has one rule: never under a live
 * transfer. `deferred` says the caller will hold it back, so the dialog can
 * promise that nothing is interrupted rather than staying quiet about it.
 */
interface Props {
  remember: boolean;
  onChange: (next: boolean) => void;
  busy?: boolean;
  /** Something is arriving, so the change waits for the next start. */
  deferred?: boolean;
}

function confirmTrusted(next: boolean, deferred: boolean): Promise<boolean> {
  // What the restart costs, or that there is not going to be one. Said either
  // way: "the code changes" is the part that surprises somebody holding a phone
  // with the old one open.
  const restart = deferred
    ? "A transfer is arriving, so this takes effect the next time receiving starts — nothing is interrupted."
    : "Receiving restarts and the code changes.";

  return new Promise((resolve) =>
    openModal(
      <ConfirmModal
        strTitle={
          next ? "Keep the same address between sessions?" : "Issue a new link each session?"
        }
        strDescription={
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {next ? (
              <>
                <div>
                  A device that has been here once comes straight back with
                  nothing to type, until you reset the link.
                </div>
                <div>
                  Anyone who kept the address can come back too, so this suits a
                  network you trust rather than a shared one.
                </div>
              </>
            ) : (
              <div>
                Devices that bookmarked this page stop working and will need the
                QR code again.
              </div>
            )}
            <div>{restart}</div>
          </div>
        }
        strOKButtonText={next ? "Keep the address" : "New link each time"}
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    ),
  );
}

export function TrustedDevices({ remember, onChange, busy, deferred }: Props) {
  return (
    // Label and description are one block, with the button centred against the
    // pair. Measured on the device with the label outside the row: the button
    // centred on the description alone, which left the description sitting 17px
    // under its own heading and the heading with nothing beside it.
    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600 }}>Trusted devices</div>
        <div style={MUTED}>
          {remember
            ? "The same address every session, so a device can bookmark it."
            : "A new address and code each session."}
        </div>
      </div>
      <DialogButton
        disabled={busy}
        style={ICON_BUTTON_WIDE}
        onClick={() =>
          void (async () => {
            if (await confirmTrusted(!remember, Boolean(deferred))) {
              onChange(!remember);
            }
          })()
        }
      >
        Change
      </DialogButton>
    </div>
  );
}
