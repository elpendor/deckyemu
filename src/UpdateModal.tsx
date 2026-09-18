import { DialogButton, Focusable, ModalRoot } from "@decky/ui";

import { UpdatePanel } from "./UpdatePanel";
import { ScrollList } from "./ScrollList";

interface Props {
  closeModal?: () => void;
}

/**
 * The release on offer, in a dialog, for the panel's update row.
 *
 * The Updates tab's own component with its checking and settings left out, so
 * installing is the same flow wherever it starts -- never a second one. A
 * dialog rather than a jump to the tab because a dialog does not go through
 * decky's router: when a Steam client breaks decky's pages, the settings page
 * is blank, and this row is then the only way left to install the build that
 * fixes it.
 */
export function UpdateModal({ closeModal }: Props) {
  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "18px", fontWeight: 600, marginBottom: "8px" }}>Updates</div>
      {/* Scrolled, because ModalRoot does not scroll its own content and an
          unfolded changelog runs well past the screen. */}
      <ScrollList style={{ maxHeight: "58vh" }}>
        <UpdatePanel onHandedOff={closeModal} releaseOnly />
      </ScrollList>
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <DialogButton onClick={() => closeModal?.()} style={{ flex: 1 }}>
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
