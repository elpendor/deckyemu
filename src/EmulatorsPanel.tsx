import { useCallback, useState } from "react";

import { EmulatorCatalogPanel } from "./EmulatorCatalogPanel";
import { RegisteredEmulatorsPanel } from "./RegisteredEmulatorsPanel";
import { FirmwarePanel } from "./FirmwarePanel";
import { ToolsPanel } from "./ToolsPanel";

interface Props {
  /** Re-read status/cores after a change, so new emulators become selectable. */
  onChanged: () => void;
}

export function EmulatorsPanel({ onChanged }: Props) {
  // Bumped whenever an emulator is installed, removed or registered, and read
  // by the firmware section below. It loads once on mount, so installing RPCS3
  // from the list above left the firmware it needs missing from a panel three
  // rows further down — and the only way to see it was to leave the settings
  // page and come back.
  const [changes, setChanges] = useState(0);

  const afterChange = useCallback(() => {
    setChanges((count) => count + 1);
    onChanged();
  }, [onChanged]);

  return (
    <>
      <EmulatorCatalogPanel onChanged={afterChange} />
      <FirmwarePanel reloadKey={changes} />
      {/* Under firmware, and separate from it: one section is the user's own
          dumps and promises nothing on it is downloaded, the other is what
          this plugin fetches. Neither can say that plainly if they are
          merged. */}
      <ToolsPanel reloadKey={changes} />

      <RegisteredEmulatorsPanel onChanged={afterChange} reloadKey={changes} />
    </>
  );
}
