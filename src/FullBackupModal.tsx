import { useCallback, useEffect, useRef, useState } from "react";
import { ConfirmModal, DialogButton, Focusable, ModalRoot, ToggleField } from "./steamui";
import { addEventListener, removeEventListener } from "./host";

import {
  cancelFullBackup,
  endFullBackupNetwork,
  fullBackupDrives,
  fullBackupSizes,
  startFullBackup,
  startFullBackupNetwork,
  type BackupDrive,
  type FileServerStatus,
} from "./backend";
import { HandoffCode } from "./HandoffCode";
import { BackupPlaces, NETWORK } from "./BackupPlaces";
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
 * Everything DeckyEmu keeps, as one zip on an SD card or USB drive, or
 * downloaded to a phone or PC (see fullbackup.py), for resetting this Deck or
 * moving to another.
 */
export function FullBackupModal({ closeModal }: { closeModal?: () => void }) {
  const [drives, setDrives] = useState<BackupDrive[] | null>(null);
  const [unreadable, setUnreadable] = useState<{ name: string; size: number }[]>([]);
  const [drive, setDrive] = useState("");
  const [sizes, setSizes] = useState<Record<string, { bytes: number }>>({});
  const [include, setInclude] = useState<string[]>(PARTS.map((part) => part.id));
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState({ text: "", percent: 0 });
  // The download on offer, once a phone or PC backup has started.
  const [served, setServed] = useState<Partial<FileServerStatus> | null>(null);
  const offered = useRef(false);
  const awake = useRef(false);

  const loadDrives = useCallback(() => {
    fullBackupDrives()
      .then((result) => {
        setDrives(result.drives);
        setUnreadable(result.unreadable ?? []);
        setDrive((current) =>
          current === NETWORK || result.drives.some((one) => one.path === current)
            ? current
            : (result.drives[0]?.path ?? NETWORK),
        );
      })
      .catch((error) => logError("could not list drives", error));
  }, []);

  // Every way out withdraws the download; one under way still finishes.
  useEffect(
    () => () => {
      if (offered.current) {
        void endFullBackupNetwork().catch((error) => logError("could not withdraw the backup", error));
      }
    },
    [],
  );

  useEffect(() => {
    loadDrives();
    fullBackupSizes()
      .then((result) => setSizes(result.sizes))
      .catch((error) => logError("could not measure the backup", error));
  }, [loadDrives]);

  useEffect(() => {
    const moving = addEventListener<[text: string, percent: number]>(
      "full_backup_progress",
      (text, percent) => {
        // A download starts when the browser asks, not when Start is pressed.
        if (!awake.current) {
          awake.current = true;
          keepAwakeUntil("full_backup_done");
        }
        setRunning(true);
        setStatus({ text, percent });
      },
    );
    const done = addEventListener<[ok: boolean, error: string, files: number, ejected: boolean]>(
      "full_backup_done",
      (ok, error, _files, ejected) => {
        awake.current = false;
        setRunning(false);
        const cancelled = error.startsWith("Cancelled");
        const network = offered.current;
        openModal(
          <ConfirmModal
            strTitle={ok ? "Backup finished" : cancelled ? "Backup cancelled" : "Backup failed"}
            strDescription={
              ok
                ? network
                  ? "Downloaded. Keep it somewhere that is not this Deck."
                  : ejected
                    ? "You can remove the drive."
                    : "Saved to the drive."
                : cancelled
                  ? network
                    ? "Download it again when you're ready."
                    : "Any earlier backup on the drive is kept."
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

  const network = drive === NETWORK;
  const chosen = network ? undefined : drives?.find((one) => one.path === drive);
  const total = include.reduce((sum, id) => sum + (sizes[id]?.bytes ?? 0), 0);

  // Room for this backup only once the old one is gone: ask before deleting it.
  const needs = total + 64 * 1024 ** 2;
  const roomOnlyWithoutOld =
    !!chosen && needs > chosen.free && needs <= chosen.free + chosen.backup_bytes;

  const start = () => {
    if (network) {
      startFullBackupNetwork(include)
        .then((result) => {
          if (!result.ok) {
            openModal(
              <ConfirmModal
                strTitle="The backup did not start"
                strDescription={result.error ?? ""}
                strOKButtonText="Close"
                bAlertDialog
              />,
            );
            return;
          }
          offered.current = true;
          setServed(result);
        })
        .catch((error) => logError("could not offer the backup", error));
      return;
    }
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
    awake.current = true;
    const letSleep = keepAwakeUntil("full_backup_done");
    const failed = () => {
      awake.current = false;
      letSleep();
      setRunning(false);
    };
    startFullBackup(drive, include, replaceFirst)
      .then((result) => {
        if (!result.ok) {
          failed();
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
        failed();
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

      {drives !== null && drives.length === 0 && unreadable.length > 0 && (
        <div style={{ padding: "4px 0 8px", fontSize: "13px" }}>
          Can't read the drive. Format it in Settings → Storage, or use another.
        </div>
      )}

      {drives !== null && !served && (
        <BackupPlaces drives={drives} chosen={drive} onChoose={setDrive} />
      )}

      {served && (
        <HandoffCode
          url={served.download_url ?? ""}
          shortUrl={served.short_url}
          pin={served.pin}
          pinLocked={served.pin_locked}
        >
          {served.download_name} - {humanSize(served.download_bytes ?? 0)}
        </HandoffCode>
      )}

      {(chosen || (network && !served)) && (
        <>
          {PARTS.map((part, index) => (
            <ToggleField
              key={part.id}
              // Start at the top: Steam otherwise focused Start, out of view.
              {...(index === 0 && !(drives && drives.length > 0) ? { autoFocus: true } : {})}
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
            {chosen
              ? `${humanSize(total)} to ${chosen.label} · ${humanSize(chosen.free)} free` +
                (chosen.backups.length ? " · replaces the backup there" : "")
              : `${humanSize(total)} to a phone or PC on this network`}
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
        {!served && (
          <DialogButton onClick={start} disabled={running || include.length === 0}>
            {running ? "Backing up..." : "Start"}
          </DialogButton>
        )}
        {!served && drives?.length === 0 && (
          <DialogButton onClick={loadDrives}>Look for drives</DialogButton>
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
