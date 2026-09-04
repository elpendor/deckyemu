import { ConfirmModal, DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { FaTrash } from "react-icons/fa";

import {
  chooseCloudRemote,
  cloudStatus,
  endCloudSetup,
  forgetCloudRemote,
  setSettings,
  startCloudSetup,
  type CloudRemote,
  type CloudState,
  type FileServerStatus,
} from "./backend";
import { DANGER_CLASS, DANGER_CSS, DANGER_TEXT } from "./danger";
import { COLUMN, MUTED } from "./dialogStyle";
import { HandoffCode } from "./HandoffCode";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";
import { logError } from "./logError";
import { openModal } from "./modalStack";

/** Whatever happens next happens on the phone, so this end has to watch for it. */
const POLL_MS = 2000;

/**
 * The account list is the only thing here that grows, so it scrolls rather than
 * the dialog -- the same reasoning, and the same numbers, as the transfer's
 * received list. A QR code pushed off the bottom of the screen is the one
 * failure a glance-and-scan dialog cannot afford.
 */
const ACCOUNTS = {
  display: "flex",
  flexDirection: "column" as const,
  gap: "6px",
  maxHeight: "22vh",
  overflowY: "auto" as const,
};

/**
 * Setting up where save data gets copied to, from a device with a keyboard.
 *
 * The same crossing the transfer flow and the diagnostic report already make --
 * a QR code for a camera, a short address and six digits for anything else --
 * because it is the same problem yet again, and it is drawn by the same
 * component they use. What this one collects is a sign-in with a storage
 * provider, or an address and a password, and doing either on the Deck's
 * on-screen keyboard is the experience that put ROM transfers on a phone to
 * begin with.
 *
 * Opening this is also what switches cloud saves on, which is what fetches
 * rclone. Nobody is asked to install a binary to unlock a setting: the feature
 * being wanted is the request for the tool it needs.
 *
 * Signing in is the web half. Everything after it -- which account saves go to,
 * and which ones to be rid of -- is the Deck half, because choosing between
 * accounts already set up needs neither a browser nor a keyboard, and it is a
 * decision about this device.
 */

/** Free space, rounded the way a person would say it. */
function gigabytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

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
  const remotes = cloud?.remotes ?? [];

  /*
   * What to call each row.
   *
   * The service, because that is what a person calls this -- the config key
   * rclone needs is the Deck's business and is never shown. Two accounts of the
   * same service are the one case where the service alone is not enough to tell
   * two rows apart, so they take a number, and only then: numbering a list of
   * one is noise about a distinction that is not being made.
   */
  const seen = new Map<string, number>();
  const named = remotes.map((one) => {
    const label = one.label || one.kind || one.name;
    const nth = (seen.get(label) ?? 0) + 1;
    seen.set(label, nth);
    return { one, label, nth };
  });
  const repeated = new Set(
    named.filter(({ label }) => (seen.get(label) ?? 0) > 1).map(({ label }) => label),
  );

  /**
   * Ask before removing an account.
   *
   * The same friction a discarded transfer gets, for a better reason: this
   * deletes a stored credential, and getting it back means finding the phone or
   * the PC again. Signing in is not hard, but it is not something to be nudged
   * into by a thumb landing on the wrong row.
   */
  const confirmForget = (one: CloudRemote) =>
    openModal(
      <ConfirmModal
        strTitle="Sign out of this storage?"
        strOKButtonText="Sign out"
        bDestructiveWarning
        onOK={() =>
          void forgetCloudRemote(one.name)
            .then(setCloud)
            .catch((dropError) => logError("could not remove storage", dropError))
        }
        strDescription={
          <div style={DANGER_TEXT}>
            The Deck forgets how to reach {one.label || one.kind}. Nothing already
            copied there is touched, and coming back means signing in again from a
            phone or a PC.
          </div>
        }
      />,
    );

  return (
    /*
     * `bAllowFullSize` because this is a list modal, the same reason
     * `SaveBackupModal` sets it: without it the dialog is a smaller box than the
     * content needs, and the buttons at the bottom are simply cut off.
     */
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/* Injected here as well as in the panels: the rule is scoped to a class,
          not global, and a modal renders outside whichever panel opened it. */}
      <style>{DANGER_CSS}</style>

      {/* Matches the button that opened it, which changes wording once
          something is signed in. The transfer dialog learned this one the hard
          way: arriving under a heading that is not the button you pressed reads
          as having gone somewhere else. */}
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        {remotes.length > 0 ? "Cloud storage" : "Set up cloud storage"}
      </div>
      <div style={{ ...MUTED, marginBottom: "12px" }}>
        Open this on a phone or PC and sign in to where saves should go. The storage
        is yours — the Deck only keeps how to reach it.
      </div>

      <Focusable style={COLUMN}>
        {error && <div style={{ color: "#e35d5d", fontSize: "13px" }}>{error}</div>}

        {!error && !url && (
          <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
            <Spinner style={{ height: "32px" }} />
          </div>
        )}

        {url && (
          <HandoffCode
            url={url}
            shortUrl={status?.short_url}
            pin={status?.pin}
            pinLocked={status?.pin_locked}
          >
            {/* Named as the page labels them, so what is on this screen and
                what is on the other one are the same words. */}
            then pick a service and press "Sign in".
          </HandoffCode>
        )}

        {/* Every storage set up on this Deck, and which one saves go to.
            The transfer's received list decides the shape: what it is on the
            left, the action beside it, the destructive one last -- gamepad
            focus enters a row from the left, so the first control is the one a
            thumb lands on without aiming. */}
        {remotes.length > 0 && (
          <div style={{ ...COLUMN, gap: "6px" }}>
            <div style={{ fontWeight: 600 }}>Signed in ({remotes.length})</div>
            <Focusable style={ACCOUNTS}>
              {named.map(({ one, label, nth }) => {
                const chosen = one.name === cloud?.remote;
                // Free space only where it is known, and it is known for the
                // chosen one because reading it is how the Deck checks the
                // sign-in still works. Asking every remote every two seconds
                // to fill in a subtitle is a poll over somebody's wifi.
                const under = [
                  chosen ? cloud?.account : "",
                  chosen && cloud?.space?.free !== undefined
                    ? `${gigabytes(cloud.space.free)} free`
                    : "",
                ].filter(Boolean);
                return (
                  <Focusable
                    key={one.name}
                    style={{ display: "flex", alignItems: "center", gap: "10px" }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div>
                        {label}
                        {repeated.has(label) ? ` (${nth})` : ""}
                        {/* Beside the name rather than out at the right edge,
                            where it read as a control and sat where every other
                            list in the plugin puts a button. It is a fact about
                            this row, so it belongs to the row's name. */}
                        {chosen && <span style={MUTED}> — In use</span>}
                      </div>
                      {under.length > 0 && <div style={MUTED}>{under.join(" · ")}</div>}
                    </div>

                    {/* Nothing to press on the row that is already chosen: the
                        tick has said so, and a button that does nothing is
                        worse than no button. */}
                    {!chosen && (
                      <DialogButton
                        onClick={() => {
                          void chooseCloudRemote(one.name)
                            .then(setCloud)
                            .catch((pickError) =>
                              logError("could not choose storage", pickError),
                            );
                        }}
                        style={ICON_BUTTON_WIDE}
                      >
                        Use this
                      </DialogButton>
                    )}

                    <div className={DANGER_CLASS}>
                      <DialogButton onClick={() => confirmForget(one)} style={ICON_BUTTON}>
                        <FaTrash />
                      </DialogButton>
                    </div>
                  </Focusable>
                );
              })}
            </Focusable>
          </div>
        )}

        {url && !cloud?.remote && (
          <div style={MUTED}>
            Nothing is copied anywhere yet. The page checks that the storage answers,
            and backing up stays something you ask for here.
          </div>
        )}

        <Focusable style={{ display: "flex", gap: "8px" }}>
          {/* Just closes. Withdrawing the form is the effect's cleanup above, so
              B and the X do it too. */}
          <DialogButton onClick={() => closeModal?.()} style={{ flex: 1, minWidth: "auto" }}>
            Done
          </DialogButton>
        </Focusable>
      </Focusable>
    </ModalRoot>
  );
}
