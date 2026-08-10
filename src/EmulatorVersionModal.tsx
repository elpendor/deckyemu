import {
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  PanelSectionRow,
  ToggleField,
} from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  emulatorBuildList,
  holdEmulator,
  rollbackEmulator,
  updateEmulator,
  type EmulatorBuild,
  type PastBuild,
} from "./backend";
import { buildDate } from "./buildDate";
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
  // Which action is in flight, for the message at the end of it. A ref rather
  // than state because the done handler must not re-subscribe every time this
  // changes, and nothing renders from it.
  const action = useRef<"update" | "switch">("update");

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
       * A non-empty message on success means the build moved but could not be
       * pinned, so an update will move it again. That is the one thing here worth
       * interrupting somebody over -- silence would be the whole trap this
       * feature exists to avoid.
       *
       * Otherwise the wording follows what was actually asked for. "Updated" and
       * "now on the newest build" are wrong for a build chosen from the list,
       * which may be older *or* newer than the one that was installed.
       */
      toaster.toast({
        title: message
          ? `${emulator.name} moved, but is not held`
          : action.current === "update"
            ? `${emulator.name} updated`
            : `${emulator.name} changed build`,
        body:
          message ||
          (action.current === "update"
            ? "It is now on the newest build."
            : "It is on the build you chose, and held there."),
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
    async (
      what: string,
      kind: "update" | "switch",
      call: () => Promise<{ ok: boolean; error?: string }>,
    ) => {
      action.current = kind;
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

  /*
   * Whether the newest published build is the one installed, read from the list
   * rather than from the `emulator` prop.
   *
   * The prop is a snapshot the tab behind this dialog took before it opened, and
   * it does not change while the dialog is up. So after choosing an older build,
   * "This is the newest build on Flathub" would still be sitting there — describing
   * the state from two operations ago. The list is reloaded after every change, and
   * its first entry is the newest, so `current` on it is always the live answer.
   *
   * Falls back to the prop only until the list arrives.
   */
  const onNewest = builds?.length ? Boolean(builds[0].current) : !emulator.update_available;

  return (
    <ModalRoot closeModal={closeModal}>
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

      {!running && !onNewest && (
        <PanelSectionRow>
          <DialogButton
            onClick={() => void start("Updating", "update", () => updateEmulator(emulator.id))}
          >
            Update to the newest build
          </DialogButton>
        </PanelSectionRow>
      )}

      {!running && onNewest && (
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

      {/*
        "Other builds", not "Earlier builds", and the button says neither "go
        back" nor "downgrade". The list is every published build except the one
        installed, and flatpak's log is newest-first, so when the installed build
        is a few behind, entries *above* it are newer. Any wording implying a
        direction is wrong for half the rows.
      */}
      <div style={{ marginTop: "14px", marginBottom: "2px", fontWeight: 500 }}>Other builds</div>
      {builds === null && <Field description="Reading the build history..." />}
      {listError && <Field description={listError} />}
      {builds !== null && builds.length === 0 && !listError && (
        <Field description="Flathub publishes no other build of this emulator." />
      )}

      {/* Scrolled by the dialog itself rather than a nested region: a scroll area
          holding only text has nothing focusable in it, so a controller cannot
          enter one. Each row here has a button, which is what makes the list
          reachable at all.

          Spacing rather than a border between rows: 12px of padding and a gap
          wide enough that the date, the subject and the button read as one row.
          At 6px they ran together into a wall of text that could not be scanned
          for the date, which is the only thing anybody is choosing on. */}
      {(builds ?? [])
        .filter((build) => !build.current)
        .map((build, index) => (
          <Focusable
            key={build.commit}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "14px",
              padding: "12px 0",
              // Between rows only, so the list does not open with a stray line
              // directly under its own heading.
              borderTop: index === 0 ? "none" : "1px solid rgba(255, 255, 255, 0.08)",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "15px", lineHeight: 1.25 }}>{buildDate(build.date)}</div>
              <div
                style={{
                  fontSize: "12px",
                  opacity: 0.6,
                  marginTop: "3px",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {build.subject || build.commit.slice(0, 12)}
              </div>
            </div>
            {/* Not styled as destructive. Nothing is destroyed -- save data and
                configuration are untouched and the move is repeatable -- and red
                on every row would make the list look dangerous to read. */}
            <DialogButton
              disabled={running}
              style={{
                minWidth: "auto",
                width: "auto",
                padding: "8px 14px",
                flexShrink: 0,
              }}
              onClick={() =>
                void start("Switching", "switch", () => rollbackEmulator(emulator.id, build.commit))
              }
            >
              Use this build
            </DialogButton>
          </Focusable>
        ))}

      <div style={{ marginTop: "14px" }}>
        <Field description="Choosing a build also holds it, so an update cannot move it again. Save data and configuration are not touched." />
      </div>
    </ModalRoot>
  );
}
