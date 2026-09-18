import { DialogButton, Field, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { FaTrash } from "react-icons/fa";

import { listPortLists, type PortListFile } from "./backend";
import { FileName } from "./FileName";
import { openModal } from "./modalStack";
import { humanSize, TransferModal } from "./TransferModal";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { confirmDiscardTransfer } from "./discardTransfer";
import { importPortList } from "./importPortList";
import { logError } from "./logError";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";

interface Props {
  closeModal?: () => void;
  /** Re-read the emulator lists after one is imported. */
  onImported: () => void;
}

/**
 * Ports lists waiting in the transfer folder, and a button each.
 *
 * `ImportDefinitionModal` for the other kind of file, and the reasoning for
 * both is there: why a list rather than importing the only candidate, and why
 * this exists beside the transfer dialog at all.
 */
export function ImportPortsModal({ closeModal, onImported }: Props) {
  const [files, setFiles] = useState<PortListFile[] | null>(null);
  const [suffix, setSuffix] = useState(".deckyports.json");
  const [path, setPath] = useState("");

  const load = useCallback(() => {
    listPortLists()
      .then((result) => {
        setFiles(result.files ?? []);
        if (result.suffix) setSuffix(result.suffix);
        setPath(result.path ?? "");
      })
      .catch((error) => {
        logError("could not list ports lists", error);
        setFiles([]);
      });
  }, []);

  useEffect(load, [load]);

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/* The rule is scoped to a class rather than global, and a modal renders
          outside whichever panel opened it -- so without this the delete button
          below is an ordinary grey one. */}
      <style>{DANGER_CSS}</style>
      <div style={{ fontSize: "18px", fontWeight: 600, marginBottom: "8px" }}>
        Import a ports list
      </div>

      {files === null && <Spinner />}

      {files?.length === 0 && (
        <Field
          label="Nothing waiting"
          description={
            `A ports list is a ${suffix} file somebody gave you. Send one with ` +
            `the button below and it appears here — or import it from the ` +
            `transfer dialog as it arrives. ` +
            (path ? `They are read from ${path}.` : "")
          }
        />
      )}

      {/* Newest first, which is the one somebody just sent. */}
      {files?.map((file) => (
        <Field
          key={file.name}
          // Clamped rather than wrapped: this is a row in a list, and the
          // delete confirmation shows the whole name when it matters.
          label={<FileName name={file.name} />}
          description={humanSize(file.size)}
          childrenContainerWidth="min"
        >
          <div style={{ display: "flex", gap: "6px" }}>
            <DialogButton
              onClick={() => {
                // The dialog goes before the confirmation opens. Steam
                // re-reveals each modal as the one above it dismisses, so
                // leaving this underneath would put the list back over the
                // panel afterwards (see modalStack).
                closeModal?.();
                importPortList(file.name, onImported);
              }}
              style={ICON_BUTTON_WIDE}
            >
              Import
            </DialogButton>

            {/* After Import, matching every other row in the plugin: gamepad
                focus enters from the left, so the destructive control must not
                be what a thumb lands on first.

                It is here at all because a definition this plugin refused stays
                in the folder on purpose -- it is still the only copy on the
                device, and the reasons are what tell its author what to fix.
                But then it is here forever, and this is the way out. */}
            <div className={DANGER_CLASS}>
              <DialogButton
                onClick={() => {
                  closeModal?.();
                  confirmDiscardTransfer(file, onImported);
                }}
                style={ICON_BUTTON}
              >
                <FaTrash />
              </DialogButton>
            </div>
          </div>
        </Field>
      ))}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {/* The way to send one, rather than a sentence naming a control in
            another panel. Closes first, for the reason in `modalStack`. */}
        <DialogButton
          onClick={() => {
            closeModal?.();
            openModal(
              <TransferModal
                expecting={[
                  {
                    label: "Ports list",
                    expects: `A ${suffix} file.`,
                  },
                ]}
              />,
            );
          }}
          style={{ flex: 2 }}
        >
          Transfer to Deck
        </DialogButton>
        <DialogButton onClick={() => closeModal?.()} style={{ flex: 1 }}>
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
