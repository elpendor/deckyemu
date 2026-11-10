import { useCallback, useEffect, useState } from "react";
import { ConfirmModal, DialogButton, Focusable, ModalRoot } from "./steamui";
import { addEventListener, removeEventListener } from "./host";

import {
  cancelFullBackup,
  fullBackupDrives,
  fullRestoreArt,
  fullRestoreFinished,
  fullRestoreGames,
  fullRestoreRekey,
  gameIcon,
  installCore,
  installEmulator,
  installRetroArch,
  rebuildLaunchers,
  startFileServer,
  startFullRestore,
  type BackupDrive,
  type RestoreTodo,
} from "./backend";
import { openModal } from "./modalStack";
import { createOrReuseShortcut } from "./reuseShortcut";
import { addToCollection, applyArtwork, setShortcutIcon, shortcutExists } from "./steam";
import { ProgressBar, TransferModal, humanSize } from "./TransferModal";
import { logError } from "./logError";
import { keepAwake } from "./keepAwake";
import { BackupPlaces, NETWORK } from "./BackupPlaces";

/** Steam's sleep blocker for the restore under way, through its last step. */
let awake = () => {};

/** "DeckyEmu-backup-20261109-190426.zip" as "9 Nov 2026, 19:04". */
function when(name: string): string {
  const found = /(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(name);
  if (!found) return name;
  const [, y, m, d, hh, mm] = found;
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  return `${date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}, ${hh}:${mm}`;
}

/** The next event of `name` whose arguments `match`. */
function nextEvent<T extends unknown[]>(name: string, match: (...args: T) => boolean): Promise<T> {
  return new Promise((resolve) => {
    const listener = addEventListener<T>(name, (...args: T) => {
      if (!match(...args)) return;
      removeEventListener(name, listener);
      resolve(args);
    });
  });
}

/**
 * After the files are back: reinstall what is missing, rebuild the launchers,
 * and add the games Steam lost back under new ids. Returns what failed.
 */
async function finish(todo: RestoreTodo, say: (text: string) => void): Promise<string[]> {
  const problems: string[] = [];
  const attempt = async (label: string, work: () => Promise<void>) => {
    say(label);
    try {
      await work();
    } catch (error) {
      problems.push(`${label}: ${String(error)}`);
    }
  };

  if (todo.retroarch) {
    await attempt("Installing RetroArch", async () => {
      const done = nextEvent<[ok: boolean, message?: string]>("retroarch_install_done", () => true);
      const started = await installRetroArch();
      if (!started.ok) throw new Error(started.error);
      const [ok, message] = await done;
      if (!ok) throw new Error(message ?? "failed");
    });
  }
  const { games, cores } = await fullRestoreGames();
  for (const core of cores) {
    await attempt(`Installing ${core}`, async () => {
      const result = await installCore(core);
      if (!result.ok) throw new Error(result.error ?? "failed");
    });
  }
  for (const emulator of todo.emulators) {
    await attempt(`Installing ${emulator.name}`, async () => {
      const done = nextEvent<[id: string, ok: boolean, message?: string]>(
        "emulator_install_done",
        (id) => id === emulator.id,
      );
      const started = await installEmulator(emulator.id);
      if (!started.ok) throw new Error(started.error);
      const [, ok, message] = await done;
      if (!ok) throw new Error(message ?? "failed");
    });
  }
  await attempt("Rebuilding launchers", async () => {
    await rebuildLaunchers();
  });

  const lost = games.filter((game) => !shortcutExists(game.app_id));
  for (const [index, game] of lost.entries()) {
    await attempt(`Adding games to Steam ${index + 1}/${lost.length}`, async () => {
      const { appId } = await createOrReuseShortcut({
        title: game.title,
        exe: game.exe,
        startDir: game.start_dir,
        launchOptions: "",
        layout: game.layout,
      });
      const moved = await fullRestoreRekey(game.app_id, appId);
      if (!moved.ok) throw new Error(moved.error);
      const { art } = await fullRestoreArt(appId);
      if (Object.keys(art).length) await applyArtwork(appId, art);
      try {
        const { path } = await gameIcon(appId, "");
        setShortcutIcon(appId, path);
      } catch (iconError) {
        logError("could not set a restored game's icon", iconError);
      }
      if (game.collection) await addToCollection(appId, game.collection);
    });
  }
  await fullRestoreFinished().catch((error) => logError("could not drop restored art", error));
  return problems;
}

/**
 * Restore a full backup from an SD card or USB drive, or one sent from a
 * phone or PC (see fullbackup.py).
 */
export function RestoreEverythingModal({ closeModal }: { closeModal?: () => void }) {
  const [drives, setDrives] = useState<BackupDrive[] | null>(null);
  const [onDeck, setOnDeck] = useState<{ path: string; name: string; bytes: number }[]>([]);
  const [arrivals, setArrivals] = useState("");
  const [place, setPlace] = useState("");
  const [unreadable, setUnreadable] = useState(0);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState({ text: "", percent: 0 });

  const load = useCallback(() => {
    fullBackupDrives()
      .then((result) => {
        setDrives(result.drives);
        setUnreadable(result.unreadable?.length ?? 0);
        setOnDeck(result.on_deck ?? []);
        setArrivals(result.arrivals ?? "");
        // Where a backup is: a drive holding one, else one sent over, else
        // the first drive, else Phone or PC.
        setPlace((current) => {
          const paths = result.drives.map((drive) => drive.path);
          if (current === NETWORK || paths.includes(current)) return current;
          const holding = result.drives.find((drive) => drive.backups.length > 0);
          if (holding) return holding.path;
          if ((result.on_deck ?? []).length > 0) return NETWORK;
          return paths[0] ?? NETWORK;
        });
      })
      .catch((error) => logError("could not list drives", error));
  }, []);

  useEffect(() => load(), [load]);

  useEffect(() => {
    const moving = addEventListener<[text: string, percent: number]>(
      "full_restore_progress",
      (text, percent) => setStatus({ text, percent }),
    );
    const done = addEventListener<[ok: boolean, error: string, todo: RestoreTodo | null]>(
      "full_restore_done",
      (ok, error, todo) => {
        const report = (title: string, body: string) => {
          awake();
          setRunning(false);
          openModal(
            <ConfirmModal strTitle={title} strDescription={body} strOKButtonText="Close" bAlertDialog />,
          );
        };
        if (!ok) {
          report(error.startsWith("Cancelled") ? "Restore cancelled" : "Restore failed", error);
          return;
        }
        setStatus({ text: "Finishing", percent: -1 });
        void finish(
          todo ?? { emulators: [], retroarch: false, games: [] },
          (text) => setStatus({ text, percent: -1 }),
        )
          .then((problems) => {
            report(
              "Restored",
              problems.length ? `Everything else is back. These didn't work: ${problems.join("; ")}` : "Everything is back.",
            );
            closeModal?.();
          })
          .catch((finishError) => report("Restore failed", String(finishError)));
      },
    );
    return () => {
      removeEventListener("full_restore_progress", moving);
      removeEventListener("full_restore_done", done);
    };
  }, [closeModal]);

  const network = place === NETWORK;
  const drive = (drives ?? []).find((one) => one.path === place);
  const backups = network
    ? onDeck.map((one) => ({ name: one.name, path: one.path, label: `${when(one.name)} · ${humanSize(one.bytes)}` }))
    : (drive?.backups ?? []).map((name) => ({ name, path: `${drive!.path}/${name}`, label: when(name) }));

  // From a phone or PC: received into the backups folder, then restored here.
  const sendOne = () => {
    closeModal?.();
    void (async () => {
      try {
        const started = await startFileServer(arrivals);
        if (!started.ok) logError("could not start receiving a backup", started.error);
      } catch (error) {
        logError("could not start receiving a backup", error);
      }
      openModal(
        <TransferModal
          purpose="backup"
          expecting={[
            {
              label: "DeckyEmu backup",
              expects: "The DeckyEmu-backup .zip made by Back up DeckyEmu.",
            },
          ]}
          onRestore={() => openModal(<RestoreEverythingModal />)}
        />,
      );
    })();
  };

  const restore = (path: string) =>
    openModal(
      <ConfirmModal
        strTitle="Restore this backup?"
        strDescription="It replaces DeckyEmu's settings and games on this Deck."
        strOKButtonText="Restore"
        onOK={() => {
          setRunning(true);
          setStatus({ text: "Starting", percent: 0 });
          awake = keepAwake();
          startFullRestore(path)
            .then((result) => {
              if (!result.ok) {
                awake();
                setRunning(false);
                openModal(
                  <ConfirmModal
                    strTitle="Restore failed"
                    strDescription={result.error ?? ""}
                    strOKButtonText="Close"
                    bAlertDialog
                  />,
                );
              }
            })
            .catch((error) => {
              awake();
              setRunning(false);
              logError("could not start the restore", error);
              openModal(
                <ConfirmModal
                  strTitle="Restore failed"
                  strDescription={String(error)}
                  strOKButtonText="Close"
                  bAlertDialog
                />,
              );
            });
        }}
      />,
    );

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "8px" }}>
        Restore DeckyEmu
      </div>

      {drives !== null && !running && (
        <BackupPlaces drives={drives} chosen={place} onChoose={setPlace} />
      )}

      {drives !== null && drives.length === 0 && unreadable > 0 && (
        <div style={{ padding: "4px 0 8px", fontSize: "13px" }}>
          Can't read the drive. Format it in Settings → Storage, or use another.
        </div>
      )}

      {!running &&
        backups.map((one, index) => (
          <Focusable key={one.path} style={{ marginBottom: "8px" }}>
            <DialogButton autoFocus={index === 0} onClick={() => restore(one.path)}>
              {one.label}
            </DialogButton>
          </Focusable>
        ))}

      {drives !== null && !running && !network && backups.length === 0 && (
        <div style={{ padding: "8px 0", fontSize: "13px", opacity: 0.8 }}>
          No backup on this drive.
        </div>
      )}

      {drives !== null && !running && network && (
        <Focusable style={{ marginBottom: "8px" }}>
          <DialogButton autoFocus={backups.length === 0 && drives.length === 0} onClick={sendOne}>
            Send a backup to this Deck
          </DialogButton>
        </Focusable>
      )}

      {running && (
        <div style={{ margin: "8px 0" }}>
          <div style={{ fontSize: "13px", marginBottom: "4px" }}>{status.text}</div>
          <ProgressBar fraction={status.percent < 0 ? -1 : status.percent / 100} />
        </div>
      )}

      <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {!running && drives?.length === 0 && <DialogButton onClick={load}>Look for drives</DialogButton>}
        {running ? (
          <DialogButton onClick={() => void cancelFullBackup()}>Cancel</DialogButton>
        ) : (
          <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
        )}
      </Focusable>
    </ModalRoot>
  );
}
