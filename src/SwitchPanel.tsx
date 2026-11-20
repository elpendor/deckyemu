import { useEffect, useState } from "react";
import { FaExchangeAlt } from "react-icons/fa";
import { ButtonItem, ConfirmModal, DialogButton, PanelSectionRow } from "./steamui";

import {
  getSettings,
  setSettings,
  switchBuild,
  switchOffer,
  takeOver,
  type SwitchOffer,
} from "./backend";
import { openModal } from "./modalStack";
import { restartSteam } from "./restartSteam";

const NAMES = { service: "standalone version", plugin: "plugin version" } as const;

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
/** The confirmation both ways in share; `setBusy` tracks the switch itself. */
function confirmSwitch(offer: SwitchOffer, setBusy: (busy: boolean) => void) {
  const to = NAMES[offer.to!];
  const run = async () => {
    setBusy(true);
    try {
      const result = await switchBuild();
      if (result.ok) {
        window.dispatchEvent(new Event(SWITCHED));
        // Each build patches its own tab in as Steam loads, so the other one
        // shows only after a restart: part of the switch, not a second ask.
        restartSteam();
      } else {
        notSwitched(result.error);
      }
    } catch (error) {
      console.error("[deckyemu] could not switch", error);
    } finally {
      setBusy(false);
    }
  };
  openModal(
    <ConfirmModal
      strTitle={`Switch to the ${to}?`}
      strDescription={
        description(offer) +
        (offer.installed ? "" : ` DeckyEmu ${offer.version} is downloaded and installed first.`) +
        " Steam restarts to show it."
      }
      strOKButtonText="Switch and restart"
      // The ⇄ button is one Up from Added games: a stray A must not
      // restart Steam.
      bFocusCancel
      onOK={() => void run()}
    />,
  );
}

function useSwitchOffer(): SwitchOffer | null {
  const [offer, setOffer] = useState<SwitchOffer | null>(null);
  useEffect(() => {
    switchOffer()
      .then((found) => setOffer(found.available && found.to ? found : null))
      .catch((error) => console.error("[deckyemu] could not look for the other version", error));
  }, []);
  return offer;
}

/**
 * The header button. In the plugin build, until first pressed, a dot on it
 * says the standalone version exists: the one-time hint, saved either way.
 */
export function SwitchButton() {
  const offer = useSwitchOffer();
  const [busy, setBusy] = useState(false);
  const [hinted, setHinted] = useState(false);

  useEffect(() => {
    getSettings()
      .then((settings) => setHinted(!settings.standalone_offer_answered))
      .catch((error) => console.error("[deckyemu] could not read settings", error));
  }, []);

  if (!offer?.to) return null;
  const dot = hinted && offer.to === "service";

  return (
    <DialogButton
      style={{ ...HEADER_BUTTON, position: "relative" }}
      disabled={busy}
      onClick={() => {
        if (dot) {
          setHinted(false);
          void setSettings({ standalone_offer_answered: true }).catch((error) =>
            console.error("[deckyemu] could not save the hint", error),
          );
        }
        confirmSwitch(offer, setBusy);
      }}
    >
      <FaExchangeAlt style={{ display: "block" }} />
      {dot && (
        <div
          style={{
            position: "absolute",
            top: "3px",
            right: "3px",
            // As the update dot, so all of DeckyEmu's dots look the same.
            height: "10px",
            width: "10px",
            background: "orange",
            borderRadius: "50%",
          }}
        />
      )}
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
