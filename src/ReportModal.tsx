import { DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useMemo, useState } from "react";
import qrcode from "qrcode-generator";

import { startReport, type FileServerStatus } from "./backend";

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
        Closing leaves the server up, which is the opposite of what the transfer
        dialog does and is deliberate: you are reading the report on the other
        device, and pulling the page out from under yourself because you
        dismissed a dialog on the Deck would be exactly wrong.

        So there is one button, not a choice between closing and stopping. It
        stops on its own, the panel says so while it is up, and stopping early is
        already a control that exists -- Receiving files -> Show transfer, then
        close that. A second button here would have been a third way to reach it
        and a decision to make on the way out.
      */}
      {url && (
        <div style={{ ...LABEL, marginTop: "14px" }}>
          Stays readable for {Math.round((status?.idle_timeout ?? 1800) / 60)} minutes, then
          stops. The panel shows it while it is up.
        </div>
      )}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <DialogButton onClick={() => closeModal?.()}>Done</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
