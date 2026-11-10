import { useEffect, useRef, useState } from "react";
import { ConfirmModal, DialogButton, Focusable, ModalRoot } from "./steamui";
import { addEventListener, removeEventListener } from "./host";

import { cancelCompress, compressPlan, startCompress, type CompressGame } from "./backend";
import { openModal } from "./modalStack";
import { ProgressBar, humanSize } from "./TransferModal";
import { ScrollList } from "./ScrollList";
import { SwitchLabel } from "./SwitchLabel";
import { ICON_BUTTON_WIDE } from "./iconButton";
import { logError } from "./logError";
import { keepAwakeUntil } from "./keepAwake";

type Failed = { title: string; reason: string };

/** The result as one dialog: what was saved, then what wasn't done. */
function finished(done: number, saved: number, failed: Failed[], cancelled: boolean) {
  const lines = [
    done
      ? `Compressed ${done} game${done === 1 ? "" : "s"}, saving ${humanSize(saved)}.`
      : "Nothing was compressed.",
    cancelled ? "Cancelled. The game being compressed was left as it was." : "",
    ...failed.map((one) => `${one.title}: ${one.reason}`),
  ].filter(Boolean);
  openModal(
    <ConfirmModal
      strTitle={failed.length ? "Some games weren't compressed" : "Compression finished"}
      strDescription={lines.join("\n")}
      strOKButtonText="Close"
      bAlertDialog
    />,
  );
}

/**
 * Library games compressed into formats their emulators read directly (see
 * romcompress.py). Every game starts ticked; originals go once each is checked.
 */
export function CompressModal({ closeModal }: { closeModal?: () => void }) {
  const [games, setGames] = useState<CompressGame[] | null>(null);
  const [skipped, setSkipped] = useState<Failed[]>([]);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [running, setRunning] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const cancelled = useRef(false);
  const [status, setStatus] = useState({ text: "", percent: 0 });

  useEffect(() => {
    compressPlan()
      .then((result) => {
        setGames(result.games);
        setSkipped(result.skipped);
        setChosen(new Set(result.games.map((game) => game.app_id)));
      })
      .catch((error) => {
        logError("could not plan compression", error);
        setGames([]);
      });
  }, []);

  useEffect(() => {
    const moving = addEventListener<[text: string, percent: number]>(
      "compress_progress",
      (text, percent) => {
        setRunning(true);
        setStatus({ text, percent });
      },
    );
    const done = addEventListener<
      [ok: boolean, error: string, done: number, saved: number, failed: Failed[]]
    >("compress_done", (ok, error, count, saved, failed) => {
      setRunning(false);
      setCancelling(false);
      if (ok) finished(count, saved, failed, cancelled.current);
      else {
        openModal(
          <ConfirmModal
            strTitle="Compression failed"
            strDescription={error}
            strOKButtonText="Close"
            bAlertDialog
          />,
        );
      }
      closeModal?.();
    });
    return () => {
      removeEventListener("compress_progress", moving);
      removeEventListener("compress_done", done);
    };
  }, [closeModal]);

  const picked = (games ?? []).filter((game) => chosen.has(game.app_id));
  const total = picked.reduce((sum, game) => sum + game.bytes, 0);

  // Grouped under the shelf names the library uses.
  const groups = new Map<string, CompressGame[]>();
  for (const game of games ?? []) {
    groups.set(game.platform, [...(groups.get(game.platform) ?? []), game]);
  }

  const toggle = (id: number) =>
    setChosen((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const start = () => {
    setRunning(true);
    setStatus({ text: "Starting", percent: 0 });
    const letSleep = keepAwakeUntil("compress_done");
    startCompress(picked.map((game) => game.app_id)).catch((error) => {
      letSleep();
      setRunning(false);
      logError("could not start compressing", error);
      openModal(
        <ConfirmModal
          strTitle="Compression failed"
          strDescription={String(error)}
          strOKButtonText="Close"
          bAlertDialog
        />,
      );
    });
  };

  return (
    <ModalRoot closeModal={running ? undefined : closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>Compress games</div>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "8px" }}>
        Smaller files that play the same. Each original is deleted once its copy is checked.
      </div>

      {games === null && <div style={{ fontSize: "13px" }}>Looking at your games...</div>}
      {games !== null && games.length === 0 && (
        <div style={{ fontSize: "13px", margin: "8px 0" }}>
          Nothing to compress. Games already compressed, and ones whose emulator can't read a
          compressed file, aren't listed.
        </div>
      )}

      {games !== null && games.length > 0 && (
        <ScrollList style={{ maxHeight: "50vh" }}>
          {[...groups.entries()].map(([platform, list]) => (
            <div key={platform}>
              <div style={{ fontSize: "13px", opacity: 0.7, margin: "8px 0 4px" }}>
                {platform} · {humanSize(list.reduce((sum, game) => sum + game.bytes, 0))}
              </div>
              {list.map((game) => (
                <Focusable key={game.app_id} style={{ display: "flex", marginBottom: "4px" }}>
                  <DialogButton
                    onClick={() => toggle(game.app_id)}
                    disabled={running}
                    style={{ ...ICON_BUTTON_WIDE, flexGrow: 1 }}
                  >
                    <SwitchLabel
                      name={`${game.title} · ${humanSize(game.bytes)} → .${game.format}`}
                      on={chosen.has(game.app_id)}
                    />
                  </DialogButton>
                </Focusable>
              ))}
            </div>
          ))}
        </ScrollList>
      )}

      {skipped.length > 0 && !running && (
        <div style={{ fontSize: "13px", opacity: 0.8, marginTop: "8px" }}>
          Can't compress: {skipped.map((one) => `${one.title} (${one.reason})`).join(", ")}
        </div>
      )}

      {running ? (
        <div style={{ margin: "8px 0" }}>
          <div style={{ fontSize: "13px", marginBottom: "4px" }}>
            {cancelling ? "Stopping..." : status.text}
          </div>
          <ProgressBar fraction={status.percent / 100} />
        </div>
      ) : (
        picked.length > 0 && (
          <div style={{ fontSize: "13px", opacity: 0.8, margin: "8px 0" }}>
            {humanSize(total)} in {picked.length} game{picked.length === 1 ? "" : "s"}
          </div>
        )
      )}

      <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <DialogButton onClick={start} disabled={running || picked.length === 0}>
          {running ? "Compressing..." : "Start"}
        </DialogButton>
        {running ? (
          <DialogButton
            disabled={cancelling}
            onClick={() => {
              setCancelling(true);
              cancelled.current = true;
              void cancelCompress();
            }}
          >
            Cancel
          </DialogButton>
        ) : (
          <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
        )}
      </Focusable>
    </ModalRoot>
  );
}
