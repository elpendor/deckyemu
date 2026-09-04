import { DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useRef, useState } from "react";

import {
  chooseCloudRemote,
  cloudStatus,
  endCloudSetup,
  forgetCloudRemote,
  setSettings,
  startCloudSetup,
  type CloudState,
  type FileServerStatus,
} from "./backend";
import { logError } from "./logError";
import { QrCode } from "./QrCode";

/** Whatever happens next happens on the phone, so this end has to watch for it. */
const POLL_MS = 2000;

/**
 * Setting up where save data gets copied to, from a device with a keyboard.
 *
 * The same crossing the transfer flow and the diagnostic report already make —
 * a QR code for a camera, a short address and six digits for anything else —
 * because it is the same problem yet again. What this one collects is a storage
 * address, a username and a password, and typing those on the Deck's on-screen
 * keyboard is the experience that put ROM transfers on a phone to begin with.
 *
 * Opening this is also what switches cloud saves on, which is what fetches
 * rclone. Nobody is asked to install a binary to unlock a setting: the feature
 * being wanted is the request for the tool it needs.
 */

const LABEL: React.CSSProperties = { opacity: 0.7, fontSize: "13px" };

/** Free space, rounded the way a person would say it. */
function gigabytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}
const VALUE: React.CSSProperties = {
  fontSize: "17px",
  fontWeight: 600,
  wordBreak: "break-all",
};

interface Props {
  closeModal?: () => void;
}

export function CloudSetupModal({ closeModal }: Props) {
  const [status, setStatus] = useState<Partial<FileServerStatus> | null>(null);
  const [error, setError] = useState("");
  const [cloud, setCloud] = useState<CloudState | null>(null);
  // Whether there is a form of ours to withdraw on the way out. A ref, not
  // state: the cleanup below runs after the last render, where state would be
  // whatever it was when the effect was created. Same reason as ReportModal.
  const offered = useRef(false);

  useEffect(() => {
    let live = true;

    // Switched on first, because that is what fetches rclone, and the setup
    // cannot run without it. The backend answers "still downloading" rather
    // than failing obscurely if this is the first time.
    void setSettings({ cloud_saves: true })
      .then(() => startCloudSetup())
      .then((result) => {
        if (!result.ok) {
          if (live) setError(result.error ?? "The setup page could not be opened.");
          return;
        }
        // Set even if this modal has since closed, or a form offered by a call
        // that landed late would be left being served with nothing to withdraw
        // it.
        offered.current = true;
        if (live) setStatus(result);
      })
      .catch((startError) => {
        logError("could not open cloud setup", startError);
        if (live) setError("The setup page could not be opened.");
      });

    return () => {
      live = false;
      // Every way out, not just the Done button: B and the X dismiss a modal
      // too, and a form that accepts a password must not outlive the dialog
      // that offered it by any of the three.
      if (!offered.current) return;
      void endCloudSetup().catch((endError) =>
        logError("could not stop the cloud setup page", endError),
      );
    };
  }, []);

  // The work happens on the other device, so this end learns it is done by
  // asking. Without it the Deck said nothing at all while the phone said the
  // storage was ready, which is indistinguishable from a setup that failed.
  useEffect(() => {
    let live = true;
    const tick = () =>
      void cloudStatus()
        .then((result) => {
          if (live) setCloud(result);
        })
        .catch((pollError) => logError("could not read cloud status", pollError));
    tick();
    const timer = window.setInterval(tick, POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const url = status?.url ?? "";

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Set up cloud storage
      </div>
      <div style={{ ...LABEL, marginBottom: "12px" }}>
        Open this on a phone or PC and fill in where saves should go. The storage is
        yours — the Deck only keeps how to reach it.
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
          </div>
        </Focusable>
      )}

      {/* Every storage set up on this Deck, and which one saves go to.
          Choosing between them belongs here rather than on the page: signing in
          needs a browser and a keyboard, picking needs neither, and it is a
          decision about this device. */}
      {(cloud?.remotes.length ?? 0) > 0 && (
        <div style={{ marginTop: "16px" }}>
          <div style={{ ...LABEL, marginBottom: "6px" }}>
            {cloud!.remotes.length > 1 ? "Signed in to" : "Signed in"}
          </div>
          {cloud!.remotes.map((one) => {
            const chosen = one.name === cloud!.remote;
            return (
              <Focusable
                key={one.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  padding: "9px 11px",
                  marginBottom: "6px",
                  borderRadius: "6px",
                  background: chosen ? "rgba(91, 163, 43, 0.14)" : "transparent",
                  border: `1px solid ${chosen ? "rgba(91, 163, 43, 0.5)" : "#3d4450"}`,
                }}
                onActivate={() => {
                  void chooseCloudRemote(one.name)
                    .then(setCloud)
                    .catch((pickError) => logError("could not choose storage", pickError));
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  {/* The service first. The name is a label somebody typed and
                      answers nothing on its own -- "saves go to cloud" was the
                      whole of what this used to say. */}
                  <div style={{ fontSize: "15px", fontWeight: 600 }}>
                    {one.label || one.kind || one.name}
                  </div>
                  <div style={LABEL}>
                    {chosen && cloud!.account ? cloud!.account : `as "${one.name}"`}
                    {chosen && cloud!.space?.free !== undefined
                      ? ` · ${gigabytes(cloud!.space.free)} free`
                      : ""}
                  </div>
                </div>
                <div style={{ ...LABEL, flex: "none" }}>
                  {chosen ? "Saves go here" : "Use this"}
                </div>
              </Focusable>
            );
          })}
          {cloud!.remotes.length > 0 && (
            <DialogButton
              style={{ marginTop: "2px", fontSize: "13px" }}
              onClick={() => {
                const drop = cloud!.remote || cloud!.remotes[0].name;
                void forgetCloudRemote(drop)
                  .then(setCloud)
                  .catch((dropError) => logError("could not remove storage", dropError));
              }}
            >
              Sign out of {cloud!.label || cloud!.remote || cloud!.remotes[0].label}
            </DialogButton>
          )}
        </div>
      )}

      {url && !cloud?.remote && (
        <div style={{ ...LABEL, marginTop: "14px" }}>
          Nothing is copied anywhere yet. The page checks that the storage answers, and
          backing up stays something you ask for here.
        </div>
      )}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {/* Just closes. Withdrawing the form is the effect's cleanup above, so
            B and the X do it too. */}
        <DialogButton onClick={() => closeModal?.()}>Done</DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
