import { useEffect, useState } from "react";
import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow } from "./steamui";
import { callable } from "./host";

import { openModal } from "../../src/modalStack";
import { restartSteam } from "./restartSteam";

const serviceOffer = callable<[], { available: boolean; version?: string }>("service_offer");
const switchToService = callable<[], { ok: boolean; error?: string; version?: string }>(
  "switch_to_service",
);

/**
 * The way from this plugin to the standalone service, once one is released.
 *
 * Renders nothing until the backend has found a service release. Last in the
 * panel: it is never why the panel was opened.
 */
export function SwitchToServicePanel({ onSwitched }: { onSwitched: () => void }) {
  const [version, setVersion] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    serviceOffer()
      .then((offer) => setVersion(offer.available ? offer.version ?? "" : ""))
      .catch((error) => console.error("[deckyemu] could not look for the service", error));
  }, []);

  if (!version) return null;

  const run = async () => {
    setBusy(true);
    try {
      const result = await switchToService();
      if (result.ok) {
        onSwitched();
        // Asked now, since the service's tab only appears after a restart.
        openModal(
          <ConfirmModal
            strTitle="Switched"
            strDescription={
              `DeckyEmu ${result.version ?? version} is running on its own. ` +
              "Its tab appears in Quick Access once Steam restarts."
            }
            strOKButtonText="Restart Steam"
            strCancelButtonText="Later"
            onOK={restartSteam}
          />,
        );
        return;
      }
      openModal(
        <ConfirmModal
          strTitle="Not switched"
          strDescription={`${result.error ?? "The switch did not finish."} The plugin is still running as before.`}
          strOKButtonText="Close"
          bAlertDialog
        />,
      );
    } catch (error) {
      console.error("[deckyemu] could not switch to the service", error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Without the plugin loader">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description={`DeckyEmu ${version} runs on its own and keeps working when a Steam update breaks the loader. Your games and settings carry over.`}
          onClick={() =>
            openModal(
              <ConfirmModal
                strTitle="Switch to the standalone version?"
                strDescription={
                  `DeckyEmu ${version} is installed and started, with the same games and settings, ` +
                  "and this plugin turns off. Remove the plugin from the loader's Plugins list afterwards."
                }
                strOKButtonText="Switch"
                onOK={() => void run()}
              />,
            )
          }
        >
          {busy ? "Switching..." : "Switch to the standalone version"}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}
