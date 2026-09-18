import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useCallback, useState } from "react";

import { EmulatorCatalogPanel } from "./EmulatorCatalogPanel";
import { ImportPortsModal } from "./ImportPortsModal";
import { RegisteredEmulatorsPanel } from "./RegisteredEmulatorsPanel";
import { openModal } from "./modalStack";

interface Props {
  /** Re-read status/cores after a change, so a new port becomes selectable. */
  onChanged: () => void;
}

/**
 * Native ports of single games, laid out like the Emulators tab.
 *
 * The list is the catalog filtered to ports, so installing, updating and
 * removing one are the rows and buttons that tab already has. What differs is
 * only where the entries come from: a ports list the user sends, since this
 * plugin ships none.
 */
export function PortsPanel({ onChanged }: Props) {
  // As on the emulators tab: installing above registers a port below.
  const [changes, setChanges] = useState(0);
  const afterChange = useCallback(() => {
    setChanges((count) => count + 1);
    onChanged();
  }, [onChanged]);

  return (
    <>
      <EmulatorCatalogPanel onChanged={afterChange} ports />
      <RegisteredEmulatorsPanel onChanged={afterChange} ports reloadKey={changes} />
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description="A .deckyports.json somebody gave you, sent with Transfer to Deck. You are shown what each port installs before anything happens."
            onClick={() => openModal(<ImportPortsModal onImported={afterChange} />)}
          >
            Import a ports list
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
