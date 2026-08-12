import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaPen, FaTrash } from "react-icons/fa";

import { listEmulators, removeEmulator, type CustomEmulator } from "./backend";
import { EmulatorCatalogPanel } from "./EmulatorCatalogPanel";
import { EmulatorEditorModal } from "./EmulatorEditorModal";
import { FirmwarePanel } from "./FirmwarePanel";
import { byName } from "./order";
import { callWithRetry } from "./timeout";

interface Props {
  /** Re-read status/cores after a change, so new emulators become selectable. */
  onChanged: () => void;
}

/**
 * What system an emulator runs, for display.
 *
 * `databases` is empty for the systems libretro has no entry for -- Switch, Wii U,
 * PS3 -- and those store their label directly instead. Reading only `databases`
 * reported "No system set" for a Switch emulator with Nintendo Switch selected,
 * which reads like the setting failed to save.
 */
function systemLabel(emulator: CustomEmulator): string {
  return (
    emulator.databases[0] ||
    emulator.platform_full ||
    emulator.platform ||
    "No system set"
  );
}

export function EmulatorsPanel({ onChanged }: Props) {
  const [emulators, setEmulators] = useState<CustomEmulator[]>([]);

  const load = useCallback(() => {
    callWithRetry(listEmulators)
      .then(setEmulators)
      .catch((error) => console.error("[retroarch] could not list emulators", error));
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
      showModal(<EmulatorEditorModal emulator={emulator} onSaved={afterChange} />);
    },
    [afterChange],
  );

  const confirmRemove = useCallback(
    (emulator: CustomEmulator) => {
      showModal(
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

      <PanelSection
        title={`Custom emulators${emulators.length ? ` (${emulators.length})` : ""}`}
      >
        {emulators.length === 0 && (
          <PanelSectionRow>
            <Field description="Anything the list above does not cover. Point the plugin at a Flatpak or an executable and tell it which system it runs; artwork then works the same as for cores." />
          </PanelSectionRow>
        )}

        {/* By name, like every other list of emulators here. The stored order
            is the order they were registered in, which means the list reshuffles
            itself every time one is added. */}
        {[...emulators].sort(byName).map((emulator) => (
          <PanelSectionRow key={emulator.id}>
            <Field
              label={emulator.name}
              description={`${systemLabel(emulator)} · ${emulator.extensions
                .map((extension) => `.${extension}`)
                .join(" ")}`}
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
      </PanelSection>
    </>
  );
}
