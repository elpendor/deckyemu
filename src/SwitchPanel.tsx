import { useEffect, useState } from "react";
import { ButtonItem, ConfirmModal, PanelSection, PanelSectionRow } from "./steamui";

import { switchBuild, switchOffer, takeOver, type SwitchOffer } from "./backend";
import { openModal } from "./modalStack";
import { restartSteam } from "./restartSteam";

const NAMES = { service: "standalone version", plugin: "plugin version" } as const;

/** Each build has its own tab, patched in as Steam loads, so a switch shows
 * the other one's only after a restart. Asked now, to save looking for it. */
function switched(version: string | undefined, to: string) {
  openModal(
    <ConfirmModal
      strTitle="Switched"
      strDescription={
        `DeckyEmu ${version ?? ""} is in use now, as the ${to}, with the same games and settings. ` +
        "Restart Steam to see its tab."
      }
      strOKButtonText="Restart Steam"
      strCancelButtonText="Later"
      onOK={restartSteam}
    />,
  );
}

function notSwitched(error: string | undefined) {
  openModal(
    <ConfirmModal
      strTitle="Not switched"
      strDescription={`${error ?? "The switch did not finish."} DeckyEmu is running as before.`}
      strOKButtonText="Close"
      bAlertDialog
    />,
  );
}

function description(offer: SwitchOffer): string {
  if (offer.to === "plugin") {
    return (
      `DeckyEmu ${offer.version} is installed as a plugin too. Switching turns this ` +
      "standalone version off; your games and settings stay."
    );
  }
  if (offer.installed) {
    return (
      `DeckyEmu ${offer.version} is installed as a standalone version too. Switching ` +
      "turns this plugin off; your games and settings stay."
    );
  }
  return (
    `DeckyEmu ${offer.version} runs on its own and keeps working when a Steam ` +
    "update breaks plugins. Your games and settings carry over."
  );
}

/**
 * The way to the other build of DeckyEmu, the service or the plugin.
 *
 * Renders nothing until the backend has found one. Last in the panel: it is
 * never why the panel was opened.
 */
export function SwitchPanel({ onSwitched }: { onSwitched: () => void }) {
  const [offer, setOffer] = useState<SwitchOffer | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    switchOffer()
      .then((found) => setOffer(found.available && found.to ? found : null))
      .catch((error) => console.error("[deckyemu] could not look for the other version", error));
  }, []);

  if (!offer?.to) return null;
  const to = NAMES[offer.to];

  const run = async () => {
    setBusy(true);
    try {
      const result = await switchBuild();
      if (result.ok) {
        onSwitched();
        switched(result.version ?? offer.version, to);
      } else {
        notSwitched(result.error);
      }
    } catch (error) {
      console.error("[deckyemu] could not switch", error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelSection title="Other version">
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={busy}
          description={description(offer)}
          onClick={() =>
            openModal(
              <ConfirmModal
                strTitle={`Switch to the ${to}?`}
                strDescription={
                  (offer.installed ? "" : `DeckyEmu ${offer.version} is downloaded and installed. `) +
                  `This one turns off, and the ${to} starts with the same games and settings.`
                }
                strOKButtonText="Switch"
                onOK={() => void run()}
              />,
            )
          }
        >
          {busy ? "Switching..." : `Switch to the ${to}`}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

/** On the panel of the build that stays off, while the other is in use. */
export function TakeOverRows({ onTaken }: { onTaken: () => void }) {
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const result = await takeOver();
      onTaken();
      if (result.ok) {
        openModal(
          <ConfirmModal
            strTitle="Switched"
            strDescription="DeckyEmu is in use here now. Restart Steam to remove the other version's tab."
            strOKButtonText="Restart Steam"
            strCancelButtonText="Later"
            onOK={restartSteam}
          />,
        );
      } else {
        notSwitched("The other version did not let go in time.");
      }
    } catch (error) {
      console.error("[deckyemu] could not take over", error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void run()}>
          {busy ? "Switching..." : "Use this one instead"}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={restartSteam}>
          Restart Steam
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}
