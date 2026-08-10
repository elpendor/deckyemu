import {
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  PanelSectionRow,
  ToggleField,
} from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  emulatorBuildList,
  holdEmulator,
  rollbackEmulator,
  updateEmulator,
  type EmulatorBuild,
  type PastBuild,
} from "./backend";
import { buildDate } from "./buildDate";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { ProgressBar } from "./TransferModal";

interface Props {
  closeModal?: () => void;
  emulator: EmulatorBuild;
  onChanged: () => void;
}

/**
 * Everything about which build of one emulator is installed, behind one button.
 *
 * A modal rather than three more controls on the catalog row. That row can
 * already carry install, remove, register and open-its-window, and version
 * management is four more things — update, the list of past builds, the hold and
 * its release. Rows of six small icons are unusable with a thumbstick, and this
 * is not something anybody visits while adding a game.
 *
 * Watches `emulator_build_*` rather than the install events, so the catalog panel
 * behind it does not report an update as a fresh install.
 */
export function EmulatorVersionModal({ closeModal, emulator, onChanged }: Props) {
  const [held, setHeld] = useState(emulator.held);
  const [builds, setBuilds] = useState<PastBuild[] | null>(null);
  const [listError, setListError] = useState("");
  const [busy, setBusy] = useState("");
  const [status, setStatus] = useState("");
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState("");

  const loadBuilds = useCallback(async () => {
    setListError("");
    try {
      const result = await emulatorBuildList(emulator.id);
      setBuilds(result.builds ?? []);
      if (!result.ok) setListError(result.error ?? "Could not read the build history.");
    } catch (loadError) {
      console.error("[deckyemu] could not list builds", loadError);
      setBuilds([]);
      setListError("Could not read the build history.");
    }
  }, [emulator.id]);

  // On open: this costs a network round trip, which is why it is not done for
  // every row of the tab behind this dialog.
  useEffect(() => {
    void loadBuilds();
  }, [loadBuilds]);

  useEffect(() => {
    const onProgress = (id: string, text: string, pct: number) => {
      if (id !== emulator.id) return;
      setStatus(text.length > 90 ? `${text.slice(0, 87)}...` : text);
      if (pct >= 0) setPercent(Math.max(0, Math.min(100, pct)));
    };
    const onDone = (id: string, ok: boolean, message: string) => {
      if (id !== emulator.id) return;
      setBusy("");
      setStatus("");
      setPercent(ok ? 100 : 0);
      if (!ok) {
        setError(message || "That did not complete.");
        return;
      }
      /*
       * A non-empty message on success is the one outcome worth a toast: the
       * build moved but could not be pinned, so an update will move it again.
       * Silence there would be the whole trap this feature exists to avoid.
       */
      toaster.toast({
        title: message ? `${emulator.name} moved, but is not held` : `${emulator.name} updated`,
        body: message || "It is now on the newest build.",
      });
      void loadBuilds();
      onChanged();
    };

    const progress = addEventListener<[id: string, text: string, percent: number]>(
      "emulator_build_progress",
      onProgress,
    );
    const done = addEventListener<[id: string, ok: boolean, message: string]>(
      "emulator_build_done",
      onDone,
    );
    return () => {
      removeEventListener("emulator_build_progress", progress);
      removeEventListener("emulator_build_done", done);
    };
  }, [emulator.id, emulator.name, loadBuilds, onChanged]);

  const start = useCallback(
    async (what: string, call: () => Promise<{ ok: boolean; error?: string }>) => {
      setBusy(what);
      setError("");
      setPercent(0);
      setStatus("Starting...");
      try {
        const result = await call();
        if (!result.ok) {
          setError(result.error ?? "Could not start.");
          setBusy("");
          setStatus("");
        }
      } catch (startError) {
        console.error("[deckyemu] could not change build", startError);
        setError("Could not start.");
        setBusy("");
        setStatus("");
      }
    },
    [],
  );

  const toggleHold = useCallback(
    async (next: boolean) => {
      // Optimistic, then corrected from what the backend read back, because a
      // mask that did not take must not sit on screen as one that did.
      setHeld(next);
      setError("");
      try {
        const result = await holdEmulator(emulator.id, next);
        if (!result.ok) {
          setHeld(!next);
          setError(result.error ?? "Could not change the hold.");
          return;
        }
        setHeld(Boolean(result.held));
        onChanged();
      } catch (holdError) {
        console.error("[deckyemu] could not hold", holdError);
        setHeld(!next);
        setError("Could not change the hold.");
      }
    },
    [emulator.id, onChanged],
  );

  const running = Boolean(busy);

  return (
    <ModalRoot closeModal={closeModal}>
      <style>{DANGER_CSS}</style>
      <h1 style={{ marginBottom: 0 }}>{emulator.name}</h1>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "12px" }}>
        {emulator.build ? `Build ${emulator.build}` : "Build unknown"}
        {held ? " · held" : ""}
      </div>

      {error && (
        <PanelSectionRow>
          <Field description={error} />
        </PanelSectionRow>
      )}

      {running && (
        <>
          <PanelSectionRow>
            <Field label={busy} description={status} />
          </PanelSectionRow>
          <div style={{ paddingBottom: "10px" }}>
            <ProgressBar fraction={percent / 100} />
          </div>
        </>
      )}

      {!running && emulator.update_available && (
        <PanelSectionRow>
          <DialogButton
            onClick={() => void start("Updating", () => updateEmulator(emulator.id))}
          >
            Update to the newest build
          </DialogButton>
        </PanelSectionRow>
      )}

      {!running && !emulator.update_available && (
        <PanelSectionRow>
          <Field description="This is the newest build on Flathub." />
        </PanelSectionRow>
      )}

      <ToggleField
        label="Hold this version"
        description="Stops updates moving it. Turn this on when a build works and you would rather it stayed."
        checked={held}
        onChange={(next) => void toggleHold(next)}
        disabled={running}
      />

      <Field label="Earlier builds" />
      {builds === null && <Field description="Reading the build history..." />}
      {listError && <Field description={listError} />}
      {builds !== null && builds.length === 0 && !listError && (
        <Field description="No earlier builds are published for this emulator." />
      )}

      {/* Scrolled by the dialog itself rather than a nested region: a scroll area
          holding only text has nothing focusable in it, so a controller cannot
          enter one. Each row here has a button, which is what makes the list
          reachable at all. */}
      {(builds ?? [])
        .filter((build) => !build.current)
        .map((build) => (
          <Focusable
            key={build.commit}
            style={{ display: "flex", alignItems: "center", gap: "8px", paddingBottom: "6px" }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "14px" }}>{buildDate(build.date)}</div>
              <div
                style={{
                  fontSize: "12px",
                  opacity: 0.6,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {build.subject || build.commit.slice(0, 12)}
              </div>
            </div>
            <div className={DANGER_CLASS} style={{ display: "flex" }}>
              <DialogButton
                disabled={running}
                style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                onClick={() =>
                  void start("Going back", () => rollbackEmulator(emulator.id, build.commit))
                }
              >
                Go back
              </DialogButton>
            </div>
          </Focusable>
        ))}

      <Field description="Going back also holds the version, so an update cannot undo it. Save data is not touched." />
    </ModalRoot>
  );
}
