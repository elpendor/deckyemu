import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaPen, FaTrash } from "react-icons/fa";

import { listEmulators, removeEmulator, type CustomEmulator } from "./backend";
import { EmulatorCatalogPanel } from "./EmulatorCatalogPanel";
import { ImportDefinitionModal } from "./ImportDefinitionModal";
import { EmulatorEditorModal } from "./EmulatorEditorModal";
import { FirmwarePanel } from "./FirmwarePanel";
import { byName } from "./order";
import { registeredDescription } from "./registeredEmulator";
import { callWithRetry } from "./timeout";
import { openModal } from "./modalStack";

interface Props {
  /** Re-read status/cores after a change, so new emulators become selectable. */
  onChanged: () => void;
}

export function EmulatorsPanel({ onChanged }: Props) {
  const [emulators, setEmulators] = useState<CustomEmulator[]>([]);

  const load = useCallback(() => {
    callWithRetry(listEmulators)
      .then(setEmulators)
      .catch((error) => console.error("[deckyemu] could not list emulators", error));
  }, []);

  useEffect(load, [load]);

  // Bumped whenever an emulator is installed, removed or registered, and read
  // by the firmware section below. It loads once on mount, so installing RPCS3
  // from the list above left the firmware it needs missing from a panel three
  // rows further down — and the only way to see it was to leave the settings
  // page and come back.
  const [changes, setChanges] = useState(0);

  const afterChange = useCallback(() => {
    load();
    setChanges((count) => count + 1);
    onChanged();
  }, [load, onChanged]);

  const edit = useCallback(
    (emulator?: CustomEmulator) => {
      openModal(<EmulatorEditorModal emulator={emulator} onSaved={afterChange} />);
    },
    [afterChange],
  );

  const confirmRemove = useCallback(
    (emulator: CustomEmulator) => {
      openModal(
        <ConfirmModal
          strTitle={`Remove ${emulator.name}?`}
          strDescription="Games already added to Steam keep working — their launcher scripts are unaffected. You just will not be able to pick this emulator for new games."
          strOKButtonText="Remove"
          bDestructiveWarning
          onOK={() => {
            void (async () => {
              const result = await removeEmulator(emulator.id);
              if (!result.ok) {
                toaster.toast({
                  title: "Could not remove emulator",
                  body: result.error ?? "",
                });
                return;
              }
              toaster.toast({ title: "Emulator removed", body: emulator.name });
              afterChange();
            })();
          }}
        />,
      );
    },
    [afterChange],
  );

  return (
    <>
      <EmulatorCatalogPanel onChanged={afterChange} />
      <FirmwarePanel reloadKey={changes} />

      {/* Not "Custom": installing anything from the list above registers it
          here too, so most of these are not custom at all. What the list
          actually holds is everything wired up for adding games, however it got
          there -- and where each one's details can be changed. */}
      <PanelSection
        title={`All registered emulators${emulators.length ? ` (${emulators.length})` : ""}`}
      >
        {/* Always, not only when the list is empty. It used to explain itself
            only while it had nothing in it, so the moment it had contents it
            stopped saying what it was -- which is exactly when somebody asks
            why an emulator is in two lists at once. */}
        <PanelSectionRow>
          <Field
            description={
              emulators.length === 0
                ? "Everything set up for adding games appears here. Nothing is yet: install one above, or point the plugin at a Flatpak or executable of your own and tell it which system it runs."
                : "Everything set up for adding games, whether it came from the list above or you added it by hand. Edit one to change its system, file types or launch arguments."
            }
          />
        </PanelSectionRow>

        {/* By name, like every other list of emulators here. The stored order
            is the order they were registered in, which means the list reshuffles
            itself every time one is added. */}
        {[...emulators].sort(byName).map((emulator) => (
          <PanelSectionRow key={emulator.id}>
            <Field
              label={emulator.name}
              description={registeredDescription(emulator)}
              childrenContainerWidth="min"
            >
              <div style={{ display: "flex", gap: "6px" }}>
                <DialogButton
                  onClick={() => edit(emulator)}
                  style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                >
                  <FaPen />
                </DialogButton>
                <DialogButton
                  onClick={() => confirmRemove(emulator)}
                  style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                >
                  <FaTrash />
                </DialogButton>
              </div>
            </Field>
          </PanelSectionRow>
        ))}

        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => edit()}>
            Add an emulator
          </ButtonItem>
        </PanelSectionRow>

        {/* Beside adding one by hand, because it is the same errand reached a
            different way: an emulator this plugin does not ship, made usable.
            The only route in used to be the transfer dialog's received list,
            which holds what this session took delivery of -- so a definition
            sent before a reload sat in the folder with nothing able to open
            it. */}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description="A .deckyemu.json somebody gave you, sent with Transfer to Deck. You are shown what it installs before anything happens."
            onClick={() =>
              openModal(<ImportDefinitionModal onImported={afterChange} />)
            }
          >
            Import a definition
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
