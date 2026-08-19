import { ConfirmModal, ToggleField } from "@decky/ui";
import { useState } from "react";

import { type CatalogEmulator } from "./backend";

interface Props {
  closeModal?: () => void;
  emulator: CatalogEmulator;
  /** Runs the removal. The panel owns the busy row and the toast. */
  onConfirm: (deleteData: boolean) => void;
}

/**
 * Removing an emulator, and the one question that goes with it.
 *
 * A component rather than a bare `ConfirmModal` because the answer has to be
 * held somewhere while the dialog is open, and it changes what the dialog says:
 * a sentence promising that saves are kept, above a switch that deletes them,
 * is how somebody loses a memory card.
 *
 * The switch appears for a flatpak only. That is the kind whose data outlives
 * it -- `flatpak uninstall` leaves `~/.var/app/<id>` in place, so a reinstall
 * inherits the last install's configuration, which is the state that had
 * DuckStation coming back with a setup wizard nobody could dismiss. An AppImage
 * keeps its data in ordinary folders and this does not remove them, so it must
 * not offer a switch that says it does.
 *
 * Off by default, and it stays off every time the dialog opens: this is the
 * press that destroys save games, and a remembered answer is one somebody gave
 * about a different emulator on a different day.
 */
export function RemoveEmulatorModal({ closeModal, emulator, onConfirm }: Props) {
  const [deleteData, setDeleteData] = useState(false);
  const offersData = emulator.kind === "flatpak";

  return (
    <ConfirmModal
      closeModal={closeModal}
      strTitle={
        deleteData ? `Remove ${emulator.name} and delete its data?` : `Remove ${emulator.name}?`
      }
      strDescription={
        "Games already added to Steam keep working — their launcher scripts are " +
        "unaffected, and reinstalling makes them run again. " +
        (deleteData
          ? "Its saves, memory cards, configuration and any firmware it holds are deleted " +
            "with it, and none of that can be recovered."
          : "Saves and configuration are kept.")
      }
      strOKButtonText={deleteData ? "Remove and delete data" : "Remove"}
      bDestructiveWarning
      onOK={() => onConfirm(deleteData)}
    >
      {offersData && (
        <ToggleField
          label="Also delete its saves and configuration"
          description={
            "Off keeps everything the emulator owns, so reinstalling picks up where you " +
            "left off. On leaves nothing behind, which is what a genuinely fresh install " +
            "needs — an emulator's data outlives it otherwise."
          }
          checked={deleteData}
          onChange={setDeleteData}
        />
      )}
    </ConfirmModal>
  );
}
