import { ButtonItem, Field, PanelSection, PanelSectionRow } from "./steamui";
import { FileSelectionType, openFilePicker, useQuickAccessVisible } from "./host";
import { useCallback, useEffect, useState } from "react";

import {
  getSettings,
  listAdded,
  listInstalledPs3Games,
  listInstalledPs4Games,
  listInstalledVitaGames,
  setSettings,
  startFileServer,
  type PluginSettings,
  type RetroArchStatus,
} from "./backend";
import { startBatch } from "./batchImport";
import { BatchImportModal } from "./BatchImportModal";
import { PackagedGameEntries } from "./PackageRows";
import { TransferModal } from "./TransferModal";
import { logError } from "./logError";
import { closeOpenModals, openModal } from "./modalStack";
import { showFailure } from "./showFailure";

interface Props {
  status: RetroArchStatus;
  onGameAdded: () => void;
}

/**
 * The ways in: a file from another device, a file already on this one, and
 * the games RPCS3, shadPS4 and Vita3K have installed. Each one leads to the
 * same review, which is where a game is checked, fixed and added -- one file
 * or fifty. Nothing is decided here, so nothing here needs a narrow column.
 */
export function AddGamePanel({ status, onGameAdded }: Props) {
  const [settings, setLocalSettings] = useState<PluginSettings | null>(null);
  const [error, setError] = useState("");
  // How many games RPCS3, shadPS4 and Vita3K have installed that are not in
  // the library yet, so the route to them is offered only when there is
  // something behind it.
  const [ps3Count, setPs3Count] = useState(0);
  const [ps4Count, setPs4Count] = useState(0);
  const [vitaCount, setVitaCount] = useState(0);
  const visible = useQuickAccessVisible();

  useEffect(() => {
    getSettings().then(setLocalSettings).catch(() => undefined);
  }, [visible]);

  useEffect(() => {
    // Counted after subtracting what is already in the library, so the number
    // on the button matches the number of rows behind it.
    Promise.all([listInstalledPs3Games(), listInstalledPs4Games(), listInstalledVitaGames(), listAdded()])
      .then(([ps3, ps4, vita, added]) => {
        const inSteam = new Set(added.map((game) => game.rom_path));
        const addable = (list: { eboot: string }[]) =>
          list.filter((game) => !inSteam.has(game.eboot)).length;
        setPs3Count(addable(ps3.games ?? []));
        setPs4Count(addable(ps4.games ?? []));
        setVitaCount(addable(vita.games ?? []));
      })
      .catch(() => undefined);
  }, [visible]);

  /**
   * Start receiving, then show the QR code. Started before the dialog opens, so
   * nothing depends on when a component mounts. An empty folder lets the
   * backend pick the default.
   */
  const openTransfer = useCallback(async () => {
    try {
      const result = await startFileServer("");
      if (!result.ok) {
        showFailure("Could not start receiving", result.error ?? "You can try again from the dialog.");
      }
    } catch (transferError) {
      logError("could not start the file server", transferError);
    }
    openModal(<TransferModal />);
  }, []);

  /**
   * A file already on this Deck, into the review. The picker opens where a file
   * was last picked from, else home; not the transfer folder, whose files are
   * listed in the transfer dialog with their own buttons.
   */
  const pickRom = useCallback(async () => {
    setError("");
    let picked: { path: string; realpath: string } | undefined;
    try {
      picked = await openFilePicker(
        FileSelectionType.FILE,
        settings?.last_rom_dir || status.home_dir,
        true, true, undefined, undefined, false, true,
      );
    } catch (pickError) {
      // The picker rejects when backed out of, which is not a failure.
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        logError("file picker failed", pickError);
        setError("Could not open the file browser.");
      }
      return;
    }
    // The footer button submits the current directory, so a path without a
    // filename is a real possibility.
    const path = picked?.realpath || picked?.path || "";
    if (!path || path.endsWith("/")) {
      setError("That selection did not return a file.");
      return;
    }
    const folder = path.slice(0, Math.max(0, path.lastIndexOf("/")));
    if (folder) setSettings({ last_rom_dir: folder }).catch(() => undefined);
    void startBatch([{ path, name: path.slice(path.lastIndexOf("/") + 1) }]);
    closeOpenModals();
    openModal(<BatchImportModal />);
  }, [settings?.last_rom_dir, status.home_dir]);

  // A custom emulator is enough on its own, so do not require RetroArch here.
  if (!status.found && status.emulator_count === 0) return null;

  return (
    <PanelSection title="Add a game">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => void openTransfer()}
          description="From a phone or PC, over the local network."
        >
          Transfer to Deck
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => void pickRom()}
          description="A game already on this Deck. Opens your last folder, or home."
        >
          Choose an existing file
        </ButtonItem>
      </PanelSectionRow>
      <PackagedGameEntries
        ps3Count={ps3Count}
        ps4Count={ps4Count}
        vitaCount={vitaCount}
        disabled={false}
        onGameAdded={onGameAdded}
      />
      {error && (
        <PanelSectionRow>
          <Field description={error} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
