import { DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useMemo, useRef, useState } from "react";
import qrcode from "qrcode-generator";

import { endReport, startReport, type FileServerStatus } from "./backend";

/**
 * Reading a diagnostic report off the Deck, from a device with a keyboard.
 *
 * The plugin logs plenty and none of it is reachable from Game Mode: the log is
 * a file, the frontend's errors go to a console nobody opens, and there is no
 * keyboard worth the name. So the best bug report a user can give is "it didn't
 * work", which is also the least useful one.
 *
 * The way across is the one the transfer flow already established, run
 * backwards: a QR code for anything with a camera, and a short address with six
 * digits for anything without one. Same server, same token, same lockout.
 */

function QrCode({ text, size = 190 }: { text: string; size?: number }) {
  const svg = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    return qr.createSvgTag({ cellSize: 4, margin: 4, scalable: true });
  }, [text]);

  return (
    <div
      style={{
        width: size,
        height: size,
        // The quiet zone is part of the spec, and white behind it keeps the
        // contrast a camera needs whatever the surrounding theme is doing.
        background: "#ffffff",
        borderRadius: "8px",
        padding: "8px",
        boxSizing: "border-box",
      }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

const LABEL: React.CSSProperties = { opacity: 0.7, fontSize: "13px" };
const VALUE: React.CSSProperties = { fontSize: "17px", fontWeight: 600, wordBreak: "break-all" };

interface Props {
  closeModal?: () => void;
}

export function ReportModal({ closeModal }: Props) {
  const [status, setStatus] = useState<Partial<FileServerStatus> | null>(null);
  const [error, setError] = useState("");
  // Whether there is something to withdraw on the way out. A ref rather than
  // state: the cleanup below reads it after the last render, where state would
  // still be whatever it was when the effect was created.
  const offered = useRef(false);

  useEffect(() => {
    let live = true;
    void startReport()
      .then((result) => {
        if (!result.ok) {
          if (live) setError(result.error ?? "The report could not be prepared.");
          return;
        }
        // Set even if this modal has since closed, or a report offered by a
        // call that landed late would be left being served with nothing to
        // withdraw it.
        offered.current = true;
        if (live) setStatus(result);
      })
      .catch((startError) => {
        console.error("[deckyemu] could not prepare the report", startError);
        if (live) setError("The report could not be prepared.");
      });

    return () => {
      live = false;
      /*
       * Every way out, not just the Done button. A modal is also dismissed with
       * B and with the X, and hanging the withdrawal off one button would leave
       * the log served on the network for anyone who left by either of the
       * other two -- which is most people.
       *
       * Only when something was actually offered: with no report of ours out
       * there, `end_report` would still consider stopping a server that may be
       * up for a transfer somebody else started.
       */
      if (!offered.current) return;
      void endReport().catch((endError) =>
        console.error("[deckyemu] could not stop sharing the report", endError),
      );
    };
  }, []);

  const url = status?.report_url ?? "";

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Report a problem
      </div>
      <div style={{ ...LABEL, marginBottom: "12px" }}>
        Open this on a phone or PC, copy the text, and paste it into the issue. It carries no
        keys, tokens or game titles.
      </div>

      {error && <div style={{ color: "#e35d5d", fontSize: "13px" }}>{error}</div>}

      {!error && !url && (
        <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
          <Spinner style={{ height: "32px" }} />
        </div>
      )}

      {url && (
        <Focusable style={{ display: "flex", gap: "16px", alignItems: "center" }}>
          <QrCode text={url} />
          <div style={{ display: "flex", flexDirection: "column", gap: "10px", flex: 1 }}>
            <div>
              <div style={LABEL}>Scan the code, or go to</div>
              <div style={VALUE}>{status?.short_url}</div>
            </div>
            <div>
              <div style={LABEL}>and enter</div>
              <div style={{ ...VALUE, letterSpacing: "2px" }}>{status?.pin}</div>
            </div>
            {/* The code lands on the transfer page, which is the same server.
                Saying so is cheaper than the alternative, which is somebody
                typing six digits and wondering why they are looking at an
                upload form. Quoted exactly as the button reads, so what is on
                this screen and what is on the other one are the same words. */}
            <div style={LABEL}>then press "Diagnostic report" at the top.</div>
          </div>
        </Focusable>
      )}

      {/*
        Done means done: the report is the tail of a log and it stops being
        served the moment this closes.

        An earlier version left it up, on the reasoning that stopping would pull
        the page out from under somebody still reading it. That reasoning was
        wrong -- the report is a single page load, so once it is open its text is
        in that browser and nothing is fetched again. Stopping prevents a
        reload, which is not the same as taking it away, and is a poor trade
        against leaving a log served on the network after the user said they had
        finished.
      */}
      {url && (
        <div style={{ ...LABEL, marginTop: "14px" }}>
          Open it before pressing Done — it stops being shared then, and in any case
          after {Math.round((status?.idle_timeout ?? 1800) / 60)} minutes.
        </div>
      )}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {/* Just closes. Withdrawing the report is the effect's cleanup above,
            so B and the X do it too. */}
        <DialogButton onClick={() => closeModal?.()}>Done</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
