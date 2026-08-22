import { DialogButton, Field, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { FaTrash } from "react-icons/fa";

import { listEmulatorDefinitions, type DefinitionFile } from "./backend";
import { humanSize } from "./TransferModal";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { confirmDiscardTransfer } from "./discardTransfer";
import { importDefinition } from "./importDefinition";
import { logError } from "./logError";

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
            `Send a ${suffix} file with Transfer to Deck and it appears here. ` +
            (path ? `They are read from ${path}.` : "")
          }
        />
      )}

      {/* Newest first, which is the one somebody just sent. */}
      {files?.map((file) => (
        <Field
          key={file.name}
          // Wrapped, for the reason the delete confirmation is: a filename has
          // no spaces to break at, so a long one runs out of the row rather
          // than onto a second line.
          label={<span style={{ overflowWrap: "anywhere" }}>{file.name}</span>}
          description={humanSize(file.size)}
          childrenContainerWidth="min"
        >
          <div style={{ display: "flex", gap: "6px" }}>
            {/* A definition this plugin refused stays in the folder on purpose
                -- it is still the only copy on the device, and the reasons are
                what tell its author what to fix. But then it is here forever,
                and this is the way out. */}
            <div className={DANGER_CLASS}>
              <DialogButton
                onClick={() => {
                  closeModal?.();
                  confirmDiscardTransfer(file, onImported);
                }}
                style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
              >
                <FaTrash />
              </DialogButton>
            </div>
            <DialogButton
              onClick={() => {
                // The dialog goes before the confirmation opens. Steam re-reveals
                // each modal as the one above it dismisses, so leaving this
                // underneath would put the list back over the panel afterwards --
                // the same fault the added-games list caused (see modalStack).
                closeModal?.();
                importDefinition(file.name, onImported);
              }}
              style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
            >
              Import
            </DialogButton>
          </div>
        </Field>
      ))}

      <Focusable style={{ display: "flex", marginTop: "12px" }}>
        <DialogButton onClick={() => closeModal?.()} style={{ flex: 1 }}>
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
