import { useCallback, useEffect, useState } from "react";
import { ConfirmModal, DialogButton, Focusable, ModalRoot, ToggleField } from "./steamui";
import { addEventListener, removeEventListener } from "./host";

import {
  cancelFullBackup,
  fullBackupDrives,
  fullBackupSizes,
  startFullBackup,
  type BackupDrive,
} from "./backend";
import { openModal } from "./modalStack";
import { ProgressBar, humanSize } from "./TransferModal";
import { logError } from "./logError";
import { keepAwakeUntil } from "./keepAwake";

/** The checklist, in the order it reads. Everything starts ticked. */
const PARTS: { id: string; label: string; note?: string }[] = [
  { id: "roms", label: "ROMs" },
  { id: "saves", label: "Saves" },
  { id: "emulators", label: "Emulators", note: "Reinstalled if left out" },
  { id: "firmware", label: "BIOS and firmware" },
  { id: "settings", label: "Settings and games" },
  { id: "signins", label: "Cloud sign-ins", note: "Login tokens, keep the backup safe" },
];

/**
 * Everything DeckyEmu keeps, as one zip on an SD card or USB drive (see
 * fullbackup.py), for resetting this Deck or moving to another.
 */
export function FullBackupModal({ closeModal }: { closeModal?: () => void }) {
  const [drives, setDrives] = useState<BackupDrive[] | null>(null);
  const [unreadable, setUnreadable] = useState<{ name: string; size: number }[]>([]);
  const [drive, setDrive] = useState("");
  const [sizes, setSizes] = useState<Record<string, { bytes: number }>>({});
  const [include, setInclude] = useState<string[]>(PARTS.map((part) => part.id));
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState({ text: "", percent: 0 });

  const loadDrives = useCallback(() => {
    fullBackupDrives()
      .then((result) => {
        setDrives(result.drives);
        setUnreadable(result.unreadable ?? []);
        setDrive((current) =>
          result.drives.some((one) => one.path === current) ? current : (result.drives[0]?.path ?? ""),
        );
      })
      .catch((error) => logError("could not list drives", error));
  }, []);

  useEffect(() => {
    loadDrives();
    fullBackupSizes()
      .then((result) => setSizes(result.sizes))
      .catch((error) => logError("could not measure the backup", error));
  }, [loadDrives]);

  useEffect(() => {
    const moving = addEventListener<[text: string, percent: number]>(
      "full_backup_progress",
      (text, percent) => setStatus({ text, percent }),
    );
    const done = addEventListener<[ok: boolean, error: string, files: number, ejected: boolean]>(
      "full_backup_done",
      (ok, error, _files, ejected) => {
        setRunning(false);
        const cancelled = error.startsWith("Cancelled");
        openModal(
          <ConfirmModal
            strTitle={ok ? "Backup finished" : cancelled ? "Backup cancelled" : "Backup failed"}
            strDescription={
              ok
                ? ejected
                  ? "You can remove the drive."
                  : "Saved to the drive."
                : cancelled
                  ? "Any earlier backup on the drive is kept."
                  : error
            }
            strOKButtonText="Close"
            bAlertDialog
          />,
        );
        if (ok) closeModal?.();
      },
    );
    return () => {
      removeEventListener("full_backup_progress", moving);
      removeEventListener("full_backup_done", done);
    };
  }, [closeModal]);

  const chosen = drives?.find((one) => one.path === drive);
  const total = include.reduce((sum, id) => sum + (sizes[id]?.bytes ?? 0), 0);

  // Room for this backup only once the old one is gone: ask before deleting it.
  const needs = total + 64 * 1024 ** 2;
  const roomOnlyWithoutOld =
    !!chosen && needs > chosen.free && needs <= chosen.free + chosen.backup_bytes;

  const start = () => {
    if (roomOnlyWithoutOld) {
      openModal(
        <ConfirmModal
          strTitle="Delete the old backup first?"
          strDescription="There isn't room for both. Until this one finishes, the drive has no backup."
          strOKButtonText="Delete and back up"
          onOK={() => begin(true)}
        />,
      );
      return;
    }
    begin(false);
  };

  const begin = (replaceFirst: boolean) => {
    setRunning(true);
    setStatus({ text: "Starting", percent: 0 });
    keepAwakeUntil("full_backup_done");
    startFullBackup(drive, include, replaceFirst)
      .then((result) => {
        if (!result.ok) {
          setRunning(false);
          openModal(
            <ConfirmModal
              strTitle="The backup did not start"
              strDescription={result.error ?? ""}
              strOKButtonText="Close"
              bAlertDialog
            />,
          );
        }
      })
      .catch((error) => {
        setRunning(false);
        logError("could not start the backup", error);
        openModal(
          <ConfirmModal
            strTitle="Backup failed"
            strDescription={String(error)}
            strOKButtonText="Close"
            bAlertDialog
          />,
        );
      });
  };

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Back up DeckyEmu
      </div>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "8px" }}>
        One file, to restore after a reset or on another Deck.
      </div>

      {drives !== null && drives.length === 0 && (
        <div style={{ padding: "12px 0" }}>
          {unreadable.length > 0
            ? "Can't read this drive. Format it in Settings → Storage, or use another."
            : "Insert an SD card or USB drive."}
        </div>
      )}

      {drives !== null && drives.length > 1 && (
        <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
          {drives.map((one) => (
            <DialogButton
              key={one.path}
              onClick={() => setDrive(one.path)}
              style={{ opacity: one.path === drive ? 1 : 0.6 }}
            >
              {one.label}
            </DialogButton>
          ))}
        </Focusable>
      )}

      {chosen && (
        <>
          {PARTS.map((part) => (
            <ToggleField
              key={part.id}
              label={part.label}
              description={
                [
                  sizes[part.id] && part.id !== "signins" ? humanSize(sizes[part.id].bytes) : "",
                  part.note ?? "",
                ]
                  .filter(Boolean)
                  .join(" · ") || undefined
              }
              checked={include.includes(part.id)}
              disabled={running}
              onChange={(on) =>
                setInclude((now) => (on ? [...now, part.id] : now.filter((id) => id !== part.id)))
              }
            />
          ))}
          <div style={{ fontSize: "13px", opacity: 0.8, margin: "8px 0" }}>
            {`${humanSize(total)} to ${chosen.label} · ${humanSize(chosen.free)} free` +
              (chosen.backups.length ? " · replaces the backup there" : "")}
          </div>
        </>
      )}

      {running && (
        <div style={{ margin: "8px 0" }}>
          <div style={{ fontSize: "13px", marginBottom: "4px" }}>{status.text}</div>
          <ProgressBar fraction={status.percent / 100} />
        </div>
      )}

      <Focusable flow-children="row" style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {chosen ? (
          <DialogButton onClick={start} disabled={running || include.length === 0}>
            {running ? "Backing up..." : "Start"}
          </DialogButton>
        ) : (
          <DialogButton onClick={loadDrives}>Look again</DialogButton>
        )}
        {running ? (
          <DialogButton onClick={() => void cancelFullBackup()}>Cancel</DialogButton>
        ) : (
          <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
        )}
      </Focusable>
    </ModalRoot>
  );
}
