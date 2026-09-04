import { Focusable } from "@decky/ui";
import type { CSSProperties, ReactNode } from "react";

import { COLUMN, MUTED } from "./dialogStyle";
import { QrCode } from "./QrCode";

/**
 * QR on one side, the typed address on the other.
 *
 * Stacked, the code sat below the fold and the dialog scrolled -- which defeats
 * the point of a glance-and-scan dialog. They are alternatives to each other, so
 * side by side also reads better than one after the other.
 *
 * `wrap` rather than a fixed split: at a narrow width the columns stack instead
 * of squeezing the QR code, which has to stay large enough for a camera.
 */
const SPLIT: CSSProperties = {
  display: "flex",
  gap: "18px",
  alignItems: "center",
  flexWrap: "wrap",
};

interface Props {
  /** Carries the access token, and is what the QR code encodes. */
  url: string;
  /** The tokenless address, short enough that somebody will type it. */
  shortUrl?: string;
  /** The six digits that redirect to `url`. */
  pin?: string;
  /** Too many wrong codes; this one is spent until the server restarts. */
  pinLocked?: boolean;
  /**
   * The one thing this particular errand has to say, rendered inside the
   * column beside the code.
   *
   * Inside rather than under, because this is the one place in a dialog where
   * height is free: the split is as tall as the QR code beside it, so anything
   * the column does not use is simply empty. Moving the sentence out to a
   * full-width row of its own reads like it should be cheaper and is strictly
   * worse -- it leaves that space blank and adds a row.
   */
  children?: ReactNode;
}

/**
 * Handing an address on this Deck to a device with a camera or a keyboard.
 *
 * Four dialogs make this crossing -- a transfer, a diagnostic report, a save
 * backup and cloud sign-in -- and until this file existed each drew it itself.
 * They had drifted into two dialects: the transfer's, at 19px and 28px, and a
 * smaller 17px one the other three copied from each other, with different words
 * for the same two instructions. Somebody who has scanned one of these has
 * scanned all of them, and the screen should not make them look twice to be
 * sure.
 *
 * The transfer's sizes won, because it is the one that is used most and the one
 * whose numbers were argued out on the device: 190px of QR is scannable at
 * arm's length, and the six digits are read off this screen by somebody typing
 * them into a laptop.
 */
export function HandoffCode({ url, shortUrl, pin, pinLocked, children }: Props) {
  return (
    <Focusable style={SPLIT}>
      <QrCode text={url} />

      {/* For anything without a camera. The token URL is 22 characters of
          random text and nobody will type it, so the short address plus a
          six-digit code is the way in from a computer. */}
      <div style={{ ...COLUMN, flex: "1 1 240px", gap: "2px" }}>
        <div style={MUTED}>Scan the code, or open this on a computer:</div>
        <div style={{ fontSize: "19px", fontWeight: 600, wordBreak: "break-all" }}>
          {shortUrl}
        </div>
        <div style={{ ...MUTED, marginTop: "8px" }}>then enter</div>
        <div style={{ fontSize: "28px", fontWeight: 700, letterSpacing: "0.24em" }}>
          {pin}
        </div>

        {pinLocked && (
          <div style={{ color: "#e35d5d", fontSize: "13px", marginTop: "6px" }}>
            Too many wrong codes. Stop and start again for a new one.
          </div>
        )}

        {children && <div style={{ ...MUTED, marginTop: "10px" }}>{children}</div>}
      </div>
    </Focusable>
  );
}
