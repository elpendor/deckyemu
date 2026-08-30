import { DialogButton, Field, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { FaTrash } from "react-icons/fa";

import { listEmulatorDefinitions, type DefinitionFile } from "./backend";
import { FileName } from "./FileName";
import { openModal } from "./modalStack";
import { humanSize, TransferModal } from "./TransferModal";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { confirmDiscardTransfer } from "./discardTransfer";
import { importDefinition } from "./importDefinition";
import { logError } from "./logError";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";

interface Props {
  closeModal?: () => void;
  /** Re-read the emulator lists after one is imported. */
  onImported: () => void;
}

/**
 * Definition files waiting in the transfer folder, and a button each.
 *
 * The only way to import one used to be the transfer dialog's received list,
 * which holds what *this session* took delivery of. So a definition sent
 * yesterday, or sent before a reload, was sitting on the device with no route
 * into the plugin at all -- the file was right there and the only way to reach
 * it was to send it again.
 *
 * A list even when there is one file, rather than importing the only candidate
 * outright. It costs a press and answers the question the empty case raises
 * anyway: *which* files can it see. Somebody whose definition is not here needs
 * to know that before they go looking for a bug.
 */
export function ImportDefinitionModal({ closeModal, onImported }: Props) {
  const [files, setFiles] = useState<DefinitionFile[] | null>(null);
  const [suffix, setSuffix] = useState(".deckyemu.json");
  const [path, setPath] = useState("");

  const load = useCallback(() => {
    listEmulatorDefinitions()
      .then((result) => {
        setFiles(result.files ?? []);
        if (result.suffix) setSuffix(result.suffix);
        setPath(result.path ?? "");
      })
      .catch((error) => {
        logError("could not list emulator definitions", error);
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
        Import an emulator definition
      </div>

      {files === null && <Spinner />}

      {files?.length === 0 && (
        <Field
          label="Nothing waiting"
          description={
            `A definition is a ${suffix} file somebody gave you. Send one with ` +
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
                // The dialog goes before the confirmation opens. Steam re-reveals
                // each modal as the one above it dismisses, so leaving this
                // underneath would put the list back over the panel afterwards --
                // the same fault the added-games list caused (see modalStack).
                closeModal?.();
                importDefinition(file.name, onImported);
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
        {/*
         * The way to get a definition here, rather than a sentence naming a
         * control somewhere else.
         *
         * The empty state used to say "send one with Transfer to Deck", which
         * from this tab is a dead end: that button lives in the Quick Access
         * panel, so the instruction meant closing this, leaving the settings
         * page and finding it. An instruction that describes an action should
         * be the action.
         *
         * This dialog closes rather than sitting underneath -- Steam re-reveals
         * each modal as the one above it dismisses, and a list left below would
         * come back over whatever follows. Nothing is lost by it: the transfer
         * dialog offers Import on a `.deckyemu.json` the moment it lands, so
         * the file can be sent and imported without coming back here at all.
         */}
        <DialogButton
          onClick={() => {
            closeModal?.();
            openModal(
              <TransferModal
                expecting={[
                  {
                    label: "Emulator definition",
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
