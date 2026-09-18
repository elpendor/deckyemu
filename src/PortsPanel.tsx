import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { useCallback, useState } from "react";

import { EmulatorCatalogPanel } from "./EmulatorCatalogPanel";
import { ImportDefinitionModal } from "./ImportDefinitionModal";
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
 * only where the entries come from: a definition the user sends, since this
 * plugin ships no ports.
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
            description="A .deckyemu.json somebody gave you, sent with Transfer to Deck. One file can hold several. You are shown what each one installs before anything happens."
            onClick={() => openModal(<ImportDefinitionModal onImported={afterChange} />)}
          >
            Import a definition
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
