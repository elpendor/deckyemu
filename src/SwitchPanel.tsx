import { useEffect, useState } from "react";
import { FaExchangeAlt } from "react-icons/fa";
import { ButtonItem, ConfirmModal, DialogButton, PanelSectionRow } from "./steamui";

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

const SWITCHED = "deckyemu-switched";

/** Runs `listener` after this panel switched to the other build. */
export function onSwitched(listener: () => void): () => void {
  window.addEventListener(SWITCHED, listener);
  return () => window.removeEventListener(SWITCHED, listener);
}

/**
 * The way to the other build of DeckyEmu, the service or the plugin: an icon
 * in the tab's header, beside the cog. Renders nothing until the backend has
 * found one.
 */
export function SwitchButton() {
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
        window.dispatchEvent(new Event(SWITCHED));
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
    <DialogButton
      style={HEADER_BUTTON}
      disabled={busy}
      onClick={() =>
        openModal(
          <ConfirmModal
            strTitle={`Switch to the ${to}?`}
            strDescription={
              description(offer) +
              (offer.installed ? "" : ` DeckyEmu ${offer.version} is downloaded and installed first.`)
            }
            strOKButtonText="Switch"
            onOK={() => void run()}
          />,
        )
      }
    >
      <FaExchangeAlt style={{ display: "block" }} />
    </DialogButton>
  );
}

/** A Quick Access header button: 28x40 like Steam's own, glyph centred. */
export const HEADER_BUTTON = {
  height: "28px",
  width: "40px",
  minWidth: 0,
  padding: 0,
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
} as const;

/**
 * Whether Steam needs a restart to show the version in use: only on the
 * plugin's tab, until the standalone version's tab has loaded. The plugin's
 * tab shows whenever the plugin is installed.
 */
function restartWouldHelp(inUse: string | undefined): boolean {
  if (inUse !== "service") return false;
  const started = (window as unknown as { __deckyemu?: { status?: { started?: string } } }).__deckyemu?.status?.started;
  return !started;
}

/** On the panel of the build that stays off, while the other is in use. */
export function TakeOverRows({ onTaken, inUse }: { onTaken: () => void; inUse?: string }) {
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
      {restartWouldHelp(inUse) && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={restartSteam}>
            Restart Steam
          </ButtonItem>
        </PanelSectionRow>
      )}
    </>
  );
}
