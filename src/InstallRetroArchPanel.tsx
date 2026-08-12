import { ButtonItem, Field, PanelSection, PanelSectionRow } from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import { canInstallRetroArch, installRetroArch } from "./backend";
import { InstallProgress } from "./InstallProgress";

interface Props {
  onInstalled: () => void;
  onRescan: () => void;
}

/**
 * Shown when RetroArch is missing. The flatpak is a large download, so the
 * backend streams progress events rather than blocking on one long call.
 */
export function InstallRetroArchPanel({ onInstalled, onRescan }: Props) {
  const [flatpakAvailable, setFlatpakAvailable] = useState<boolean | null>(null);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    canInstallRetroArch()
      .then((result) => setFlatpakAvailable(result.flatpak_available))
      .catch(() => setFlatpakAvailable(false));
  }, []);

  useEffect(() => {
    const onProgress = (text: string, pct: number) => {
      // flatpak lines can be long; the bar's description is one line of space.
      setStatus(text.length > 110 ? `${text.slice(0, 107)}...` : text);
      // Clamped as well as parsed defensively in the backend: a value above 100
      // renders the bar past the right edge of its track.
      if (pct >= 0) setPercent(Math.max(0, Math.min(100, pct)));
    };
    const onDone = (ok: boolean, message: string) => {
      setRunning(false);
      setPercent(ok ? 100 : 0);
      if (ok) {
        toaster.toast({
          title: "RetroArch installed",
          body: "Install a core next, then add a game.",
        });
        onInstalled();
      } else {
        setError(message || "The install did not complete.");
      }
    };

    const progressListener = addEventListener<[text: string, percent: number]>(
      "retroarch_install_progress",
      onProgress,
    );
    const doneListener = addEventListener<[ok: boolean, message: string]>(
      "retroarch_install_done",
      onDone,
    );
    return () => {
      removeEventListener("retroarch_install_progress", progressListener);
      removeEventListener("retroarch_install_done", doneListener);
    };
  }, [onInstalled]);

  const start = useCallback(async () => {
    setRunning(true);
    setError("");
    setStatus("Starting...");
    setPercent(0);
    try {
      const result = await installRetroArch();
      if (!result.ok) {
        setError(result.error ?? "Could not start the install.");
        setRunning(false);
      }
    } catch (startError) {
      console.error("[retroarch] install could not start", startError);
      setError("Could not start the install.");
      setRunning(false);
    }
  }, []);

  return (
    // "Install RetroArch", not "RetroArch not found": the row above this already
    // says it is not detected, and a second verdict reads as a second problem.
    <PanelSection title="Install RetroArch">
      {flatpakAvailable === false ? (
        <PanelSectionRow>
          <Field description="Flatpak is not available on this system, so RetroArch cannot be installed from here. Install it manually, then rescan." />
        </PanelSectionRow>
      ) : (
        <>
          <PanelSectionRow>
            <Field description="RetroArch can be installed for your user from Flathub — no password needed. This downloads a few hundred megabytes." />
          </PanelSectionRow>

          {running && (
            <PanelSectionRow>
              <InstallProgress
                label="Installing RetroArch"
                percent={percent}
                status={status}
              />
            </PanelSectionRow>
          )}

          {!running && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={start} disabled={flatpakAvailable === null}>
                Install RetroArch
              </ButtonItem>
            </PanelSectionRow>
          )}
        </>
      )}

      {!running && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onRescan}>
            Rescan
          </ButtonItem>
        </PanelSectionRow>
      )}

      {error && (
        <PanelSectionRow>
          <div style={{ color: "#e35d5d", fontSize: "13px", padding: "4px 0" }}>{error}</div>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}
