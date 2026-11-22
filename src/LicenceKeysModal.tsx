import { useState } from "react";
import { FaTrash } from "react-icons/fa";
import { ConfirmModal, DialogButton, Focusable, ModalRoot } from "./steamui";

import { discardTransferredFile, forgetTakenLicences, type ReceivedFile } from "./backend";
import { DANGER_CLASS } from "./danger";
import { confirmDiscardTransfer } from "./discardTransfer";
import { FileName } from "./FileName";
import { ICON_BUTTON } from "./iconButton";
import { logError } from "./logError";
import { openModal } from "./modalStack";
import { ScrollList } from "./ScrollList";
import { showFailure } from "./showFailure";

/**
 * Ask once, then delete every key in `keys` and forget every licence in
 * `taken`. `onDone` runs afterwards either way, so the list catches up.
 */
export function confirmDeleteKeys(
  keys: ReceivedFile[],
  taken: TakenLicence[],
  onDone: () => void,
): void {
  const count = keys.length + taken.length;
  openModal(
    <ConfirmModal
      strTitle={count === 1 ? "Delete this licence key?" : `Delete ${count} licence keys?`}
      strDescription={keys.length
        ? "A waiting key's game can no longer install until it is sent again. Licences already in RPCS3 stay there."
        : "They stay in RPCS3; this only clears them from the list."}
      strOKButtonText="Delete"
      bDestructiveWarning
      onOK={() =>
        void (async () => {
          try {
            if (taken.length) await forgetTakenLicences(taken.map((one) => one.id));
            for (const key of keys) {
              const result = await discardTransferredFile(key.name);
              if (!result.ok) {
                showFailure("Could not delete", result.error);
                break;
              }
            }
          } catch (error) {
            logError("could not delete licence keys", error);
            showFailure("Could not delete", error);
          } finally {
            onDone();
          }
        })()
      }
    />,
  );
}

/** A licence that went into RPCS3 as it arrived. */
export interface TakenLicence {
  id: number;
  game: string;
  note: string;
}

/** "2 waiting for their game · 1 installed into RPCS3", for the entry. */
export function licenceSummary(waiting: number, taken: TakenLicence[]): string {
  const counts = new Map<string, number>();
  for (const one of taken) counts.set(one.note, (counts.get(one.note) ?? 0) + 1);
  return [
    waiting ? `${waiting} waiting for their game` : "",
    ...[...counts].map(([note, count]) => `${count} ${note}`),
  ].filter(Boolean).join(" · ");
}

/**
 * The licence keys waiting in the transfer folder, each deletable, and the
 * ones that went into RPCS3 as they arrived.
 */
export function LicenceKeysModal({ keys, taken, onChanged, closeModal }: {
  keys: ReceivedFile[];
  taken: TakenLicence[];
  /** After a delete, so the transfer list counts again. */
  onChanged: () => void;
  closeModal?: () => void;
}) {
  const [left, setLeft] = useState(keys);
  const [shown, setShown] = useState(taken);
  const gone = (name: string) => {
    const next = left.filter((key) => key.name !== name);
    setLeft(next);
    onChanged();
    if (next.length === 0 && shown.length === 0) closeModal?.();
  };
  // A taken licence stays in RPCS3: this only clears its line, so no question.
  const forget = (id: number) => {
    const next = shown.filter((one) => one.id !== id);
    setShown(next);
    void forgetTakenLicences([id]).catch((error) => logError("could not forget a licence", error))
      .finally(onChanged);
    if (next.length === 0 && left.length === 0) closeModal?.();
  };

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <h1 style={{ marginTop: 0, marginBottom: "4px", fontSize: "23px" }}>Licence keys</h1>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "12px" }}>
        A waiting key goes in with its game when the game is added.
      </div>
      <ScrollList style={{ maxHeight: "256px" }}>
        {left.map((key) => (
          <Focusable key={key.path} style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <FileName name={key.name} />
            </div>
            <div className={DANGER_CLASS}>
              <DialogButton
                onClick={() => confirmDiscardTransfer({ name: key.name, size: key.size }, () => gone(key.name))}
                style={ICON_BUTTON}
              >
                <FaTrash />
              </DialogButton>
            </div>
          </Focusable>
        ))}
        {shown.map((one) => (
          <Focusable key={`taken-${one.id}`} style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div>{one.game}</div>
              <div style={{ opacity: 0.7, fontSize: "13px" }}>Licence {one.note}</div>
            </div>
            <div className={DANGER_CLASS}>
              <DialogButton onClick={() => forget(one.id)} style={ICON_BUTTON}>
                <FaTrash />
              </DialogButton>
            </div>
          </Focusable>
        ))}
      </ScrollList>
      <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <DialogButton autoFocus onClick={closeModal} style={{ flex: 1 }}>Close</DialogButton>
        {left.length + shown.length > 0 && (
          <DialogButton
            onClick={() => confirmDeleteKeys(left, shown, () => {
              onChanged();
              closeModal?.();
            })}
            style={{ flex: 1 }}
          >
            Delete all
          </DialogButton>
        )}
      </Focusable>
    </ModalRoot>
  );
}
