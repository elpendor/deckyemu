import { ButtonItem, Field, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import { fileServerStatus, type FileServerStatus } from "./backend";
import { humanSize, ProgressBar, TransferModal } from "./TransferModal";

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
  let description: string;
  if (uploads.length === 1) {
    const file = uploads[0];
    label = file.cancelled ? "Cancelling" : "Arriving";
    description = file.cancelled
      ? file.name
      : `${file.name} - ${humanSize(received)} of ${humanSize(total)}`;
  } else if (uploads.length > 1) {
    label = "Arriving";
    description = `${uploads.length} files - ${humanSize(received)} of ${humanSize(total)}`;
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
          onClick={() => showModal(<TransferModal />)}
          {...(uploads.length > 0 ? { autoFocus: true as const } : {})}
        >
          Show transfer
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
