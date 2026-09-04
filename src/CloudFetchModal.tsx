import { DialogButton, Focusable, ModalRoot } from "@decky/ui";
import { openModal } from "./modalStack";
import { addEventListener, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";

import { MUTED } from "./dialogStyle";
import { ProgressBar } from "./TransferModal";

/**
 * What is happening while a game is held at the starting line.
 *
 * **Shown when files are moving, and never otherwise.** This used to open on a
 * timer -- if a launch was still held after N milliseconds, explain -- and N
 * was wrong twice, because what it was racing is a network round trip with no
 * settled duration: 1.2s flashed the dialog for twenty-six milliseconds on an
 * ordinary launch, and the next launch measured on the device took 2.39s. A
 * percentage only ever arrives from a transfer, so the first one is the signal,
 * and a launch that finds nothing to do puts nothing on screen however long it
 * takes.
 *
 * There is no close button and B does not dismiss it, because dismissing it
 * would not release the launch -- the two are not the same thing and a dialog
 * that looks like it did something it did not is worse than one that cannot be
 * closed. Starting the game is a button that says so.
 */
interface Props {
  /** What is being started, so the dialog is about something. */
  title: string;
  /** Let the game go now, with whatever is already on the Deck. */
  onSkip: () => void;
}

export function CloudFetchModal({ title, onSkip }: Props) {
  // Below zero until rclone says a figure. A small save finishes before the
  // first one arrives, and a bar stuck at zero reads as nothing happening.
  const [percent, setPercent] = useState(-1);

  useEffect(() => {
    const progress = addEventListener<[name: string, done: number]>(
      "cloud_sync_progress",
      (_name, done) => setPercent(done),
    );
    return () => removeEventListener("cloud_sync_progress", progress);
  }, []);

  return (
    // No `closeModal` handed to ModalRoot: B and the X would take the dialog
    // away and leave the launch held for the rest of its wait, with nothing on
    // screen. The caller closes this when the fetch is done.
    <ModalRoot>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
Getting your saves
      </div>
      <div style={{ ...MUTED, marginBottom: "14px" }}>
        Copying save data to this Deck. {title} starts on its own when this is
        done.
      </div>

      <ProgressBar fraction={percent / 100} />

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
        {/* Always a way to the game. A save arriving late is a save that can be
            fetched again from the restore screen; a game that will not start is
            the failure nothing here is worth. */}
        <DialogButton onClick={() => onSkip()} style={{ flex: 1, minWidth: "auto" }}>
          Start {title} now
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}

/**
 * Put it up, and hand back the way to take it down.
 *
 * The same shape as `showCloudDiffer`, and for the reason that decides where
 * everything in this plugin lives: `playWatch` is watched by a test, and a test
 * here has no DOM by design. JSX in that file drags in React's runtime and the
 * whole module stops being loadable outside Steam -- so the JSX is here and the
 * decision is there.
 */
export function showCloudFetch(title: string, onSkip: () => void): () => void {
  const handle = openModal(<CloudFetchModal title={title} onSkip={onSkip} />);
  return () => handle.Close();
}
