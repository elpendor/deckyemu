import { DialogButton, Focusable, ModalRoot } from "@decky/ui";
import { openModal } from "./modalStack";
import { addEventListener, removeEventListener } from "@decky/api";
import { useEffect, useState } from "react";

import { MUTED } from "./dialogStyle";
import { ProgressBar } from "./TransferModal";

/**
 * What is happening while a game is held at the starting line.
 *
 * **Shown late on purpose.** Almost every launch has nothing to fetch and the
 * check is over in well under a second; a dialog for that would be a flash of
 * something nobody could read, on every single launch, forever. So the caller
 * waits before opening this at all, and the ordinary launch never sees it.
 *
 * What it is for is the other launch: the one on hotel wifi with a save to
 * bring down, where the alternative is several seconds of a black screen that
 * looks exactly like a game that has failed to start. That is the moment worth
 * explaining, and it is the only one this appears in.
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
  const [percent, setPercent] = useState(0);

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
        {title} is waiting for save data from your cloud storage. It starts on its
        own when this is done.
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
