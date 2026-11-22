import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
} from "./steamui";
import { toaster } from "./host";
import { useCallback, useEffect, useState } from "react";
import { FaPen, FaTrash } from "react-icons/fa";

import { listEmulatorCatalog, listEmulators, removeEmulator, type CustomEmulator } from "./backend";
import { EmulatorEditorModal } from "./EmulatorEditorModal";
import { ImportDefinitionModal } from "./ImportDefinitionModal";
import { byName } from "./order";
import { registeredDescription } from "./registeredEmulator";
import { callWithRetry } from "./timeout";
import { openModal } from "./modalStack";
import { ICON_BUTTON } from "./iconButton";
import { showFailure } from "./showFailure";

interface Props {
  /** Re-read status/cores after a change, so a new entry becomes selectable. */
  onChanged: () => void;
  /**
   * List the registered ports instead of the registered emulators.
   *
   * One list, one set of rows, one editor: a port is registered exactly as an
   * emulator is, and the only question either tab asks is which of the two it
   * is looking at.
   */
  ports?: boolean;
  /**
   * Bumped by the tab when anything above changes the list -- installing from
   * the catalog registers an entry, and this section would otherwise keep
   * showing what it read on mount.
   */
  reloadKey?: number;
}

/**
 * Everything wired up for adding games, and where each one's details change.
 *
 * Its own file because two tabs show it. It was written inside the emulators
 * tab, which made a port -- registered the same way, edited the same way --
 * appear in a list headed "All registered emulators".
 */
export function RegisteredEmulatorsPanel({
  onChanged, ports = false, reloadKey = 0,
}: Props) {
  const [emulators, setEmulators] = useState<CustomEmulator[]>([]);

  // Only what the catalog list above does not show: that list carries its own
  // Edit button. Without the catalog, everything, rather than hiding entries
  // that have nowhere else to be edited.
  const load = useCallback(() => {
    void (async () => {
      try {
        const all = await callWithRetry(listEmulators);
        const listed = await callWithRetry(listEmulatorCatalog)
          .then((catalog) => new Set(catalog.map((entry) => entry.id)))
          .catch(() => new Set<string>());
        setEmulators(all.filter((one) => Boolean(one.port) === ports && !listed.has(one.id)));
      } catch (error) {
        console.error("[deckyemu] could not list emulators", error);
      }
    })();
  }, [ports]);

  useEffect(load, [load, reloadKey]);

  const afterChange = useCallback(() => {
    load();
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
                showFailure(
                  "Could not remove emulator",
                  result.error,
                );
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

  // A port only ever comes from a list, so one the catalog does not show is
  // rare; with none there is nothing for this section to say.
  if (ports && emulators.length === 0) return null;

  return (
    <PanelSection title={ports ? "Other ports" : "Your own emulators"}>
      <PanelSectionRow>
        <Field
          description={
            ports
              ? "Ports set up for adding games that the list above does not show."
              : emulators.length === 0
                ? "Not in the list above? Point the plugin at a Flatpak or executable of your own and tell it which system it runs."
                : "Emulators you added by hand. Edit one to change its system, file types or launch arguments."
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
            description={
              <>
                {registeredDescription(emulator)}
                {/* Here rather than inside the editor, because the thing to do
                    about either notice is update the emulator, and this is
                    where somebody would do that. A message behind two modals
                    is not a message. */}
                {(emulator.fix_notices ?? []).map((notice) => (
                  <div key={notice.id} style={{ paddingTop: "4px", opacity: 0.9 }}>
                    {notice.name}: {notice.note}
                  </div>
                ))}
                {/* Stays until the emulator is updated, unlike the dialog at
                    launch, which is said once. Somebody who dismissed that
                    and forgot still has somewhere to find out what it was. */}
                {emulator.source_notice && (
                  <div style={{ paddingTop: "4px", opacity: 0.9 }}>
                    {emulator.source_notice}
                  </div>
                )}
              </>
            }
            childrenContainerWidth="min"
          >
            <div style={{ display: "flex", gap: "6px" }}>
              <DialogButton onClick={() => edit(emulator)} style={ICON_BUTTON}>
                <FaPen />
              </DialogButton>
              <DialogButton onClick={() => confirmRemove(emulator)} style={ICON_BUTTON}>
                <FaTrash />
              </DialogButton>
            </div>
          </Field>
        </PanelSectionRow>
      ))}

      {/* Only for emulators. A port is a recipe for one game from a list
          somebody wrote; there is nothing to describe by hand, and the way to
          get another is to import a list. */}
      {!ports && (
        <>
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
              onClick={() => openModal(<ImportDefinitionModal onImported={afterChange} />)}
            >
              Import a definition
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  );
}
