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
  /**
   * Draw the address and the code without the QR square beside them.
   *
   * For a dialog where the crossing has already been made and the screen has
   * turned into something else — the transfer dialog once files are arriving,
   * where 190px of QR sits above the list you came back to read. A second
   * device can still be sent here by typing, which is why the code stays.
   *
   * Here rather than in the caller because the sizes and the two instructions
   * are this component's whole reason to exist: a dialog that drew its own
   * shorter version would be the drift this file was made to end, and
   * `test_handoff` would say so.
   */
  compact?: boolean;
}

/**
 * The same crossing as one line, for a dialog that has become about something
 * else.
 *
 * The transfer dialog once files are arriving: 190px of QR above the list you
 * came back to read, and the list capped at 22vh under it because the dialog
 * had run out of height. A second device can still be sent here by typing, so
 * the code stays -- it is the square that goes.
 *
 * Here rather than in the caller because the sizes and the wording are this
 * file's whole reason to exist, and a dialog drawing its own shorter version is
 * the drift it was made to end. `test_handoff` checks exactly that.
 */
function CompactCode({ shortUrl, pin, pinLocked, children }: Props) {
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "12px" }}>
      {/* Address first, then the code, because that is the order they are used
          in: you open the page and it asks for the digits. Leading with the
          code put the answer before the question. */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {pinLocked ? (
          <div style={{ color: "#e35d5d", fontSize: "13px" }}>
            Too many wrong codes. Stop and start again for a new one.
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "10px",
              flexWrap: "wrap",
            }}
          >
            <div style={{ fontSize: "19px", fontWeight: 600, wordBreak: "break-all" }}>
              {shortUrl}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
              <span style={MUTED}>then</span>
              <span
                style={{ fontSize: "19px", fontWeight: 700, letterSpacing: "0.24em" }}
              >
                {pin}
              </span>
            </div>
          </div>
        )}
      </div>
      {children}
    </Focusable>
  );
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
export function HandoffCode({
  url,
  shortUrl,
  pin,
  pinLocked,
  children,
  compact,
}: Props) {
  if (compact) {
    return (
      <CompactCode shortUrl={shortUrl} pin={pin} pinLocked={pinLocked} url={url}>
        {children}
      </CompactCode>
    );
  }

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
