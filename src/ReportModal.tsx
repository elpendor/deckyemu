import { DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useMemo, useState } from "react";
import qrcode from "qrcode-generator";

import { startReport, stopFileServer, type FileServerStatus } from "./backend";

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

  useEffect(() => {
    let live = true;
    void startReport()
      .then((result) => {
        if (!live) return;
        if (!result.ok) setError(result.error ?? "The report could not be prepared.");
        else setStatus(result);
      })
      .catch((startError) => {
        console.error("[deckyemu] could not prepare the report", startError);
        if (live) setError("The report could not be prepared.");
      });
    return () => {
      live = false;
    };
  }, []);

  /*
   * The server is left running when this closes.
   *
   * It stops on its own after half an hour, and stopping it here would pull the
   * page out from under somebody who is still reading it -- the whole point is
   * that they are looking at another device, not at this one. The Transfer row
   * in the panel shows it is up, and stops it on demand.
   */
  const finish = () => {
    closeModal?.();
  };

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
                upload form. */}
            <div style={LABEL}>then follow "Open the diagnostic report".</div>
          </div>
        </Focusable>
      )}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
        <DialogButton onClick={finish}>Done</DialogButton>
        <DialogButton
          onClick={() => {
            void stopFileServer().catch(() => undefined);
            closeModal?.();
          }}
        >
          Done, and stop sharing now
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
