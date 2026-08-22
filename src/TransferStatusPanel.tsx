import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
} from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { fileServerStatus, type FileServerStatus } from "./backend";
import { humanSize, ProgressBar, TransferModal } from "./TransferModal";
import { openModal } from "./modalStack";
import { splitTail } from "./filenameTail";

/**
 * What is happening with the file server, for the panel you land on afterwards.
 *
 * The transfer dialog is dismissable on purpose -- it is mostly a QR code to read
 * off -- but dismissing it left nothing anywhere saying a server was still
 * listening on the local network, or that a file was still arriving. The one
 * signal was a toast fired as the dialog closed, which the Quick Access panel
 * slides in over: it was reported as visible for a moment and then gone.
 *
 * So the state lives here instead, for as long as it is true.
 */
const POLL_MS = 2000;

/**
 * A filename on one line, cut in the middle when it does not fit.
 *
 * The measuring is the browser's, which is the point: the head is allowed to
 * shrink and ellipsizes when it does, the tail never shrinks, and the row is
 * whatever width the panel is. A character budget was tried first and produced
 * a name with two ellipses in it -- see filenameTail.ts.
 *
 * `minWidth: 0` on both the row and the head, because a flex child defaults to
 * `min-width: auto` and will refuse to shrink below its content, which is
 * exactly the overflow this is here to prevent.
 */
function FileName({ name }: { name: string }) {
  const [head, tail] = splitTail(name);
  return (
    <div style={{ display: "flex", minWidth: 0, overflow: "hidden" }}>
      <span
        style={{
          minWidth: 0,
          flex: "0 1 auto",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {head}
      </span>
      {/* Never shrinks, so the region, revision and extension survive whatever
          happens to the front of the name. */}
      <span style={{ flex: "0 0 auto", whiteSpace: "nowrap" }}>{tail}</span>
    </div>
  );
}

export function TransferStatusPanel() {
  const [status, setStatus] = useState<FileServerStatus | null>(null);
  const visible = useQuickAccessVisible();

  const load = useCallback(async () => {
    try {
      setStatus(await fileServerStatus());
    } catch (error) {
      // Deliberately keeps the last known state rather than blanking the row:
      // this is a status line, and a dropped call during a backend reload is not
      // evidence the transfer stopped.
      console.error("[deckyemu] could not read file server status", error);
    }
  }, []);

  // One read per panel open, which is what notices a server started from a
  // dialog that has since been dismissed.
  useEffect(() => {
    if (visible) void load();
  }, [visible, load]);

  // Only poll while there is something to watch, and only while the panel is on
  // screen -- Steam leaves this mounted behind other views.
  useEffect(() => {
    if (!visible || !status?.running) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [visible, status?.running, load]);

  if (!status?.running) return null;

  const uploads = status.uploads ?? [];
  const minutesLeft = Math.max(
    0,
    Math.round((status.idle_timeout - status.idle_seconds) / 60),
  );

  const received = uploads.reduce((sum, file) => sum + file.received, 0);
  const total = uploads.reduce((sum, file) => sum + file.total, 0);
  const fraction = total > 0 ? received / total : 0;

  let label: string;
  let description: ReactNode;
  if (uploads.length === 1) {
    const file = uploads[0];
    label = file.cancelled ? "Cancelling" : "Arriving";
    /*
     * The name on its own line, the sizes on theirs.
     *
     * Both were one string, and a long filename pushed the sizes off the end --
     * losing the only part of this row that changes, in the row whose whole job
     * is saying how far along a transfer is. A ROM named
     * `Some Game (USA) (Rev 2) (Disc 1 of 2).chd` is past the width of the Quick
     * Access panel before the first byte count is reached.
     *
     * Two lines rather than a wrap, for the reason InstallProgress keeps
     * flatpak's output to one: this repolls every couple of seconds, and a name
     * allowed to reflow would change the panel's height as the numbers beneath
     * it grow a digit.
     */
    description = (
      <>
        {/* No `title` attribute holding the full name: it would only ever
            surface on hover, and there is no pointer in Game Mode. The whole
            name is a button away, in the dialog behind "Show transfer". */}
        <FileName name={file.name} />
        {!file.cancelled && <div>{`${humanSize(received)} of ${humanSize(total)}`}</div>}
      </>
    );
  } else if (uploads.length > 1) {
    label = "Arriving";
    description = `${uploads.length} files - ${humanSize(received)} of ${humanSize(total)}`;
  } else if (status.paused > 0) {
    // Not idle and not arriving: a transfer lost its connection and the Deck is
    // holding what it has until the sender comes back. Said out loud because
    // this is the moment somebody would otherwise stop the server -- the row
    // above would have read "Waiting", which invites exactly that.
    label = "Paused";
    description =
      status.paused === 1
        ? "A transfer stopped partway. It carries on when the sender reconnects."
        : `${status.paused} transfers stopped partway. They carry on when the sender reconnects.`;
  } else {
    // Nothing arriving, so the useful fact is that it is still listening and for
    // how much longer -- that is the state someone would otherwise not know they
    // had left running.
    label = "Waiting";
    description = `Ready - stops in ${minutesLeft} min if unused`;
  }

  return (
    <PanelSection title="Receiving files">
      <PanelSectionRow>
        <Field label={label} description={description} />
      </PanelSectionRow>

      {/* The bar is the part that reads at a glance -- the point of this section
          is knowing how far along a transfer is without stopping to parse two
          file sizes. Only while something is actually arriving; an idle server
          has no progress to draw. */}
      {uploads.length > 0 && (
        <PanelSectionRow>
          <div style={{ paddingBottom: "8px" }}>
            <ProgressBar fraction={fraction} />
          </div>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        {/* Claims focus on mount, but only while something is actually arriving.
            Being first on the page is not the same as being noticed: the Quick
            Access panel opens with focus wherever Steam decides, and a section
            above that point needs a deliberate scroll up to find -- which is no
            good for the one thing here you might have opened the panel to stop.
            Not while merely listening, because stealing the cursor from the add
            flow every time an idle server happens to be up would be worse than
            the problem.

            `autoFocus` is absent from decky's ButtonItem typings but reaches the
            focusable Steam renders; see the same trick in ArtworkPanel for why it
            has to go through Steam's focus manager rather than a DOM .focus().
            Mount-only by nature, so a poll cannot re-steal the cursor from
            someone already using the panel. */}
        <ButtonItem
          layout="below"
          onClick={() => openModal(<TransferModal />)}
          {...(uploads.length > 0 ? { autoFocus: true as const } : {})}
        >
          Show transfer
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
