import {
  ConfirmModal,
  DialogButton,
  Focusable,
  ModalRoot,
  Navigation,
  QuickAccessTab,
  ToggleField,
} from "@decky/ui";
import { FileSelectionType, openFilePicker, toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { FaTrash } from "react-icons/fa";

import {
  cancelUpload,
  fileServerStatus,
  firmwareDir,
  firmwareMatches,
  firmwareStatus,
  moveToFirmware,
  type FirmwareReport,
  getSettings,
  installFirmware,
  installPs3Licence,
  resetTransferLink,
  setSettings,
  startFileServer,
  stopFileServer,
  stopFileServerIfIdle,
  type FileServerStatus,
} from "./backend";
import { selectRom } from "./addFlow";
import { askDiscChoice } from "./confirmDiscSet";
import { FileName } from "./FileName";
import { HandoffCode } from "./HandoffCode";

/**
 * What marks a sent file as an emulator definition rather than a ROM.
 *
 * Kept in step with `emulator_catalog.imported.SUFFIX` by a test, not by
 * remembering: the two halves disagreeing means the Import button never appears
 * and the file looks like a ROM the picker cannot read.
 */
const DEFINITION_SUFFIX = ".deckyemu.json";

/**
 * A ROM hack, which belongs to a game rather than being one.
 *
 * By name here, unlike the editor, which reads the bytes. This only decides
 * which sentence a row shows; getting it wrong costs a wrong hint, and the add
 * that matters still checks the file itself.
 */
const PATCH_SUFFIXES = [".ips", ".bps", ".ups"];
import { DANGER_CLASS, DANGER_CSS, DANGER_TEXT } from "./danger";
import { COLUMN, MUTED } from "./dialogStyle";
import { logError } from "./logError";
import { installThroughEmulator } from "./firmwareInstall";
import { requirementForFile, type RequirementMatch } from "./firmwareMatch";
import { confirmUnknownDump } from "./confirmUnknownDump";
import { confirmDiscardTransfer } from "./discardTransfer";
import { importDefinition } from "./importDefinition";
import { installContentFor } from "./installContent";
import { openPatchInstall } from "./installPatch";
import { openRestoreSaves } from "./openRestore";
import { DiscTracksModal } from "./DiscTracksModal";
import { groupReceived, ownedCount, ownedNoun } from "./receivedGroups";
import { closeOpenModals, openModal } from "./modalStack";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";

/** How often to re-check while running, to pick up newly arrived files. */
const POLL_MS = 3000;
/** While bytes are moving the numbers change, so they are read more often. */
const ACTIVE_POLL_MS = 1000;

/** Exported for the panel, which reports the same sizes and must round them alike. */
export function humanSize(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

interface Props {
  closeModal?: () => void;
  /**
   * What is being sent. "firmware" starts in the firmware folder instead of the
   * ROM folder, so BIOS files and keys do not land among the games -- the same
   * reason `fileserver.default_dir()` is not the ROM picker's default.
   * "backup" is the same idea for a save backup, which has a folder of its own
   * so it never appears in the ROM picker.
   */
  purpose?: "roms" | "firmware" | "backup";
  /**
   * What the sender should be looking for, shown for as long as the dialog is
   * open. Matching is on the filename, so the names are the thing they need in
   * front of them at the moment they pick a file — realising afterwards means
   * renaming and sending again.
   */
  expecting?: Array<{ label: string; expects: string }>;
  /**
   * Which requirement an arriving file should be installed into.
   *
   * Present only for a firmware send, and it is what lets the received list
   * finish the job rather than hand the file on. Without it every arrival was
   * offered to the ROM add flow -- so a PS3 firmware .PUP came with a button
   * asking to add it to Steam as a game.
   */
  installInto?: { entryId: string; requirement: string };
  /**
   * Called once when the dialog goes away, however it was dismissed.
   *
   * Fired from an unmount effect rather than from the close handler because the
   * B button, the Close button and the auto-close after a transfer are three
   * different paths out, and a panel that has to re-read what arrived must not
   * depend on which one was taken. Without this, a file sent from another device
   * did not appear as installable until the settings page was left and reopened.
   */
  onClosed?: () => void;
}

/**
 * Something worth reading, which is not an error.
 *
 * This dialog is mostly muted grey by design -- the address, the folder, the
 * idle countdown, the hints under the toggles -- so a fifth line of it is
 * invisible however carefully it is worded. A paused transfer is the one thing
 * here somebody has to notice *before* pressing Done, and it first shipped as
 * exactly that fifth line.
 *
 * The bar down the left is doing the work rather than the colour: it is the
 * only vertical accent in the dialog, so the block reads as a different kind of
 * thing at a glance, before any of it has been read. Amber rather than the red
 * used for errors, because nothing has gone wrong -- the transfer is coming
 * back.
 */
const NOTICE = {
  display: "flex",
  flexDirection: "column" as const,
  gap: "2px",
  padding: "8px 10px",
  borderLeft: "4px solid #e8a33d",
  borderRadius: "4px",
  background: "rgba(232, 163, 61, 0.12)",
  fontSize: "13px",
};

/**
 * The stripe an unknown-length transfer sweeps back and forth.
 *
 * Injected beside the bar rather than kept in a stylesheet, for the reason the
 * danger styling gives: a modal renders outside whichever panel opened it, so
 * anything scoped to a panel is not there.
 */
const SWEEP = `
@keyframes deckyemu-sweep {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(300%); }
}`;

/**
 * A progress bar, hand-rolled.
 *
 * @decky/ui does export Steam's own ProgressBar, but it is resolved at runtime by
 * searching the webpack bundle for a matching module -- it returns undefined when
 * Steam renames or reshapes it, and rendering undefined takes the whole dialog
 * with it. The same reasoning as steam.ts: a Steam change should cost a feature,
 * not the panel. Two divs and a width owe nothing to Steam's internals.
 */
/**
 * A bar, and what it does when there is no number yet.
 *
 * `fraction` below zero means "something is happening and nobody knows how
 * much of it". That is not a hypothetical: rclone reports a percentage once a
 * second, and a 40KB save is finished before the first one arrives -- so a
 * plain bar sat at zero for the whole transfer and then vanished, which reads
 * exactly like a transfer that never started. Measured on the device, on the
 * save that prompted this.
 *
 * A stripe that moves says the same thing an empty bar cannot: this is running,
 * the figure is what is missing.
 */
export function ProgressBar({ fraction }: { fraction: number }) {
  const unknown = fraction < 0;
  const clamped = Math.max(0, Math.min(1, fraction));
  return (
    <div
      style={{
        height: "6px",
        borderRadius: "3px",
        background: "rgba(255, 255, 255, 0.15)",
        overflow: "hidden",
      }}
    >
      <style>{SWEEP}</style>
      <div
        style={{
          height: "100%",
          width: unknown ? "35%" : `${clamped * 100}%`,
          background: "#4c6ef5",
          ...(unknown ? { animation: "deckyemu-sweep 1.1s ease-in-out infinite" } : {}),
          // Matches the poll interval, so the bar glides between readings
          // instead of stepping once a second.
          transition: "width 1s linear",
        }}
      />
    </div>
  );
}

/**
 * The received list is the only thing that grows, so it scrolls, not the dialog.
 *
 * 22vh rather than 26: the dialog now also carries an Arriving section and the
 * remembered-link toggle, and the list is the one part that can afford to give
 * height back -- it scrolls by design, so a smaller window costs a little more
 * scrolling *inside* it and nothing else, whereas the dialog scrolling costs the
 * QR code being off screen.
 */
const RECEIVED = {
  display: "flex",
  flexDirection: "column" as const,
  gap: "6px",
  maxHeight: "22vh",
  overflowY: "auto" as const,
};

/**
 * Send files to the Deck from another device.
 *
 * A modal rather than a page: this is a thing you do for a minute and dismiss, not
 * somewhere you configure. It used to be a tab on the manage page, which meant
 * navigating away from the panel to reach it and navigating back afterwards --
 * three taps to see a QR code. Opened from the Quick Access panel with the server
 * already running, it is one.
 *
 * Steam unmounts the panel behind a modal, so a file chosen here is handed over
 * through the shared draft (see romDraft.ts) rather than through a callback into a
 * component that no longer exists.
 */
export function TransferModal({
  closeModal,
  purpose = "roms",
  onClosed,
  expecting = [],
  installInto,
}: Props) {
  const [status, setStatus] = useState<FileServerStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dir, setDir] = useState("");
  // Which requirement each waiting file belongs to, read from the backend's own
  // matching rather than guessed at here -- it tells an MCPX ROM from an Xbox
  // BIOS by size, which no filename can do.
  const [firmware, setFirmware] = useState<FirmwareReport | null>(null);
  // The same question for a ROM send: a BIOS sent from the Quick Access
  // transfer lands among the ROMs and was only ever offered Add.
  const [inboxFirmware, setInboxFirmware] = useState<
    Record<string, RequirementMatch>
  >({});
  const [remember, setRemember] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  // Through a ref so the unmount effect below can stay dependency-free: given
  // `onClosed` in its dependency list, a caller passing an inline function would
  // make it fire on every render instead of once at the end.
  const closedRef = useRef(onClosed);
  // Updated in an effect rather than assigned during render. A ref written
  // while rendering is written again if React discards and replays that render,
  // and the value is not the one the committed tree is holding -- so the rule
  // against it is not pedantry even where, as here, the write happens to be
  // idempotent. No dependency array: it has to track the latest prop, and the
  // cost of running after every render is one assignment.
  useEffect(() => {
    closedRef.current = onClosed;
  });
  useEffect(() => () => closedRef.current?.(), []);

  /*
   * Stopping the server has to happen however the dialog goes, and whether it
   * *should* stop is not this side's decision.
   *
   * `close` is only one of the ways out. Opening the Quick Access panel
   * dismisses every modal this plugin has open (see index.tsx), and that path
   * calls Steam's own `Close` on the handle rather than anything in here -- so
   * for a while the two disagreed, and a dialog dismissed from outside left an
   * idle server standing until its own timeout swept it up.
   *
   * The condition used to be evaluated here, against the last polled status.
   * That status is up to a few seconds old, so closing the dialog in the second
   * after sending a file read "nothing is uploading" from a snapshot taken
   * before the upload began -- and stopped the server on top of a transfer that
   * had already started. The sending device went on showing progress into a
   * socket that was closing. `stop_file_server_if_idle` asks the backend, which
   * reads what is in flight under the same lock the upload handlers write it
   * with.
   */
  // So a dismissal that already asked does not ask again on the way out. Not
  // merely wasteful: the second call would race a server the user has since
  // restarted from the panel.
  const stoppedRef = useRef(false);

  const stopIfIdle = useCallback(async () => {
    if (stoppedRef.current) return;
    stoppedRef.current = true;
    try {
      await stopFileServerIfIdle();
    } catch (stopError) {
      logError("could not stop the file server", stopError);
    }
  }, []);

  useEffect(() => () => void stopIfIdle(), [stopIfIdle]);

  useEffect(() => {
    getSettings()
      .then((loaded) => setRemember(Boolean(loaded.transfer_remember)))
      .catch(() => undefined);
  }, []);

  // Resolved before the status load can seed `dir`, so the firmware folder wins
  // over whatever the server was last pointed at.
  useEffect(() => {
    if (purpose !== "firmware") return;
    firmwareDir()
      .then((result) => setDir((current) => result.path || current))
      .catch(() => undefined);
  }, [purpose]);

  const load = useCallback(async () => {
    let received: string[] = [];
    try {
      const result = await fileServerStatus();
      setStatus(result);
      setDir((current) => current || result.target_dir || result.suggested_dir || "");
      received = (result.received ?? []).map((file) => file.name);
    } catch (loadError) {
      logError("could not read file server status", loadError);
    }
    if (purpose === "roms" && received.length) {
      try {
        const matches = await firmwareMatches(received);
        setInboxFirmware(
          Object.fromEntries(
            Object.entries(matches ?? {}).map(([name, match]) => [
              name,
              {
                entryId: match.entry_id,
                emulatorName: match.emulator,
                requirement: match.requirement,
                guiInstall: match.gui_install,
                prompt: match.prompt,
                unrecognised: Boolean(match.unrecognised),
              },
            ]),
          ),
        );
      } catch (matchError) {
        logError("could not match sent files to firmware", matchError);
      }
    }
    // What each arrival is actually for. Only on a firmware send: on a ROM send
    // nothing here installs anything, and the call would be asking the backend
    // a question with no bearing on the dialog.
    //
    // A failure is not allowed to cost the transfer. Not knowing which
    // requirement a file belongs to loses the Install button; not knowing the
    // server is running loses the QR code, which is the dialog's whole job.
    if (purpose === "firmware") {
      try {
        setFirmware(await firmwareStatus());
      } catch (reportError) {
        logError("could not read firmware status", reportError);
      }
    }
  }, [purpose]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while running: that is the only time anything changes on its own.
  const active = (status?.uploading ?? 0) > 0;
  useEffect(() => {
    if (!status?.running) {
      window.clearInterval(timer.current);
      return;
    }
    timer.current = window.setInterval(() => void load(), active ? ACTIVE_POLL_MS : POLL_MS);
    return () => window.clearInterval(timer.current);
  }, [status?.running, active, load]);

  const pickDir = useCallback(async () => {
    try {
      const picked = await openFilePicker(
        FileSelectionType.FOLDER,
        dir || status?.suggested_dir || status?.target_dir || "/",
        false,
        true,
        undefined,
        undefined,
        false,
        true,
      );
      const path = picked?.realpath || picked?.path || "";
      if (path) setDir(path);
    } catch (pickError) {
      if (!String(pickError ?? "").toLowerCase().includes("cancel")) {
        logError("folder picker failed", pickError);
      }
    }
  }, [dir, status?.suggested_dir, status?.target_dir]);

  const start = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const result = await startFileServer(dir);
      if (!result.ok) {
        setError(result.error ?? "Could not start the server.");
        return;
      }
      await load();
    } catch (startError) {
      logError("could not start file server", startError);
      setError("Could not start the server.");
    } finally {
      setBusy(false);
    }
  }, [dir, load]);

  /**
   * Dismiss, and stop the server on the way out.
   *
   * One button rather than two: a separate "Stop receiving" was redundant, since
   * nobody wants the server left listening once they are done reading the code off
   * the screen. A listening socket should not outlive the window that opened it.
   *
   * Unless something is still arriving -- dismissing a dialog you were only using
   * to read a code must not kill a multi-gigabyte transfer. It stops on its own
   * once idle.
   */
  const close = useCallback(async () => {
    await stopIfIdle();
    // Nothing is announced when a transfer is left running. A toast here was
    // measured on the device as unreadable: the Quick Access panel slides in over
    // the same corner as the dialog closes, so it was occluded before it could be
    // read. The panel it was occluded by is now the answer -- TransferStatusPanel
    // sits at the top of it with the live progress, for as long as the transfer
    // lasts, which is both more visible and true for longer than a toast.
    closeModal?.();
  }, [stopIfIdle, closeModal]);

  /**
   * Turn the durable link on or off.
   *
   * Restarted when the server is already up, because the setting *is* the
   * address: leaving it running would show the old link beside a toggle claiming
   * the new behaviour, and the QR code on screen would be the one that is about
   * to stop working.
   */
  const changeRemember = useCallback(
    async (next: boolean) => {
      setRemember(next);
      setBusy(true);
      try {
        await setSettings({ transfer_remember: next });
        if (status?.running) {
          await stopFileServer();
          await startFileServer(status.target_dir || dir);
        }
        await load();
      } catch (rememberError) {
        logError("could not change the remembered link", rememberError);
        setError("Could not change that setting.");
      } finally {
        setBusy(false);
      }
    },
    [status?.running, status?.target_dir, dir, load],
  );

  /** Invalidate every saved link, and hand out a new one. */
  const resetLink = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const result = await resetTransferLink();
      if (!result.ok) {
        setError(result.error ?? "Could not reset the link.");
        return;
      }
      await load();
      toaster.toast({
        title: "Transfer link reset",
        body: "Saved bookmarks no longer work. Scan or type the new one to pair again.",
      });
    } catch (resetError) {
      logError("could not reset the transfer link", resetError);
      setError("Could not reset the link.");
    } finally {
      setBusy(false);
    }
  }, [load]);

  /**
   * Ask before invalidating every saved link.
   *
   * It is the one control here that reaches devices which are not in the room.
   * The link *is* the credential -- there is nothing per-device to revoke, so
   * this is all or nothing -- and a phone that bookmarked it simply stops
   * working, with nothing on this screen to say which phones those were.
   *
   * The tell that it wanted asking: the toast afterwards already explains what
   * broke. If the consequence needs a sentence, it needed the sentence first.
   *
   * Recoverable, and the dialog says so: re-pairing is scanning the code again.
   * That is why this warns rather than demanding the emphasis a deletion gets.
   */
  const confirmResetLink = useCallback(() => {
    openModal(
      <ConfirmModal
        strTitle="Reset the transfer link?"
        strOKButtonText="Reset link"
        bDestructiveWarning
        onOK={() => void resetLink()}
        strDescription={
          <div style={DANGER_TEXT}>
            Every device that bookmarked this link stops being able to reach the
            Deck, and there is no way to undo it or to reset only one of them.
            Pairing again is scanning the code, the same as the first time.
          </div>
        }
      />,
    );
    // `resetLink` is stable, and listing it here would rebuild this callback on
    // every render that touches `load`.
  }, [resetLink]);

  /**
   * Abandon a transfer.
   *
   * No confirmation step: this is the ordinary "stop this download" gesture, and
   * the row it sits on is showing the transfer it stops. The half-written file
   * goes with it, which is the point -- nothing can resume an upload, so keeping
   * it would leave a dead .uploading file in the folder the ROM picker opens on.
   */
  const abandon = useCallback(
    async (uploadId: number) => {
      try {
        setStatus(await cancelUpload(uploadId) as FileServerStatus);
      } catch (cancelError) {
        logError("could not cancel the upload", cancelError);
        // Fall back to a plain read, so the row reflects reality either way.
        void load();
      }
    },
    [load],
  );

  /**
   * Take a received file into the add flow.
   *
   * The selection lands in the shared draft, so dismissing this modal reveals the
   * panel with the game already probed and its artwork resolved.
   */
  const use = useCallback(
    async (path: string, name: string) => {
      /*
       * Asked here, before the flow starts, because merging discs must never be
       * implied: the detection is a guess from filenames, and this is the one
       * screen where both discs are in front of you. The answer is carried into
       * the panel -- a no adds this disc alone and takes the row away with it,
       * rather than leaving a switch that offers again what was just declined.
       *
       * A failure to ask is not a failure to add. The set is a nicety; the
       * press was about getting this file into the add flow, and it goes there
       * undecided, which is what the panel already handles.
       */
      void selectRom(path, await askDiscChoice(path));
      toaster.toast({ title: "Ready to add", body: name });
      void close();
      // Everything else of ours, not just this dialog. Steam re-reveals each
      // modal as the one above it dismisses, so anything still on the stack
      // arrives on top of the panel opened below -- and with the added-games
      // list underneath, that is exactly what happened: the panel appeared with
      // the game ready and closed again about a second later, as the list came
      // back and took the active overlay. The same reason navigating has to
      // come after closing every modal, one layer down.
      //
      // Unconditional because none of them is a place to come back to. The user
      // is adding the file they just pressed a button about; a list of games
      // they opened beforehand is answering a question they have moved on from.
      closeOpenModals();
      Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
    },
    [close],
  );

  /**
   * Put what has arrived where the emulator reads it, without leaving.
   *
   * The row that opened this dialog can do the same thing, and having to close
   * the dialog, find that row again and press a second button is a step that
   * exists only because the two were built separately. The dialog stays open:
   * a requirement can want more than one file, and xemu wants three.
   *
   * Installs the requirement rather than the one file the button sits on --
   * that is what the backend does, and it is why the result is reported by
   * count instead of by the name that was pressed. Saying "mcpx.bin installed"
   * while quietly moving the other two would be a lie in the safe direction,
   * which is still a lie.
   */
  /**
   * The requirement a given arrival satisfies.
   *
   * The file's own, not the one whose Send button opened the dialog — those
   * agree only for the first file sent, which is why xemu's second dump used to
   * run the first one's requirement and report that nothing matched it.
   *
   * `installInto` remains the fallback for the moment before the report has
   * loaded, and for a file the backend does not recognise at all: the dialog
   * was opened from a row that wanted something, so offering that row's
   * requirement is a better guess than offering nothing.
   */
  const matchFor = useCallback(
    (name: string): RequirementMatch | undefined =>
      requirementForFile(firmware, name) ??
      inboxFirmware[name] ??
      (installInto
        ? {
            entryId: installInto.entryId,
            emulatorName: "",
            requirement: installInto.requirement,
            guiInstall: false,
            prompt: "",
          }
        : undefined),
    [firmware, inboxFirmware, installInto],
  );

  // A PS3 licence sent on its own. Refusals are a dialog, as for an update: the
  // list is about to be looked at again, and a corner toast goes unseen.
  const installLicence = useCallback(
    async (name: string) => {
      const refuse = (body: string) =>
        openModal(
          <ConfirmModal
            strTitle="Licence not installed"
            strDescription={body}
            strOKButtonText="Close"
            bAlertDialog
          />,
        );
      setBusy(true);
      try {
        const result = await installPs3Licence(name);
        if (result.ok) {
          toaster.toast({ title: "Licence installed", body: result.name ?? name });
        } else {
          refuse(result.error || "Could not install that licence.");
        }
      } catch (licenceError) {
        logError("could not install a licence", licenceError);
        refuse("Could not install that licence.");
      } finally {
        setBusy(false);
        void load();
      }
    },
    [load],
  );

  const install = useCallback(
    async (name: string) => {
      const match = matchFor(name);
      if (!match) return;
      const { entryId, requirement } = match;

      if (match.unrecognised && !(await confirmUnknownDump([name], requirement))) {
        return;
      }

      setBusy(true);
      setError("");
      try {
        // Arrived among the ROMs: every install reads the firmware folder, so
        // the file goes there first and then takes the same path.
        if (inboxFirmware[name] && !requirementForFile(firmware, name)) {
          let moved = await moveToFirmware(name);
          // A different file of the same name is already waiting there. Only
          // the user knows which dump is the right one, so ask; an identical
          // one never gets here, the backend just drops the spare.
          if (!moved.ok && moved.exists) {
            const replace = await new Promise<boolean>((resolve) =>
              openModal(
                <ConfirmModal
                  strTitle="Replace the waiting file?"
                  strDescription={`A different ${name} is already in the firmware folder, not yet installed. Replace it with the one you just sent?`}
                  strOKButtonText="Replace"
                  onOK={() => resolve(true)}
                  onCancel={() => resolve(false)}
                />,
              ),
            );
            if (!replace) return;
            moved = await moveToFirmware(name, true);
          }
          if (!moved.ok) {
            setError(moved.error ?? "Could not move that file.");
            return;
          }
        }
        // Some requirements are not a copy at all: the emulator will only take
        // the file through its own window. Falling through to the copy path
        // returned that requirement's instructions *as an error*, which read
        // as the plugin refusing to do what it was describing.
        if (match.guiInstall) {
          const started = await installThroughEmulator(
            entryId,
            match.emulatorName,
            requirement,
            match.prompt,
          );
          /*
           * This one dismisses the dialog, and only this one.
           *
           * The rule is the kind of install, not the emulator: a copy is
           * instant and local, and a requirement can want several files -- xemu
           * wants three -- so staying open is right for those and is why it
           * does. An install through the emulator's own window is not that. It
           * launches a game through Steam and takes the screen for minutes,
           * with this dialog left drawn over the top of it, and the file server
           * still listening the whole time because `close` is what stops it.
           *
           * Only once it has actually started. A prepare that failed, or a
           * Steam that would not launch it, has just put a toast on screen and
           * left something to retry -- closing over that would take the retry
           * away along with the reason.
           *
           * This is the narrow form of a wider question: every action in this
           * list is a one-shot hand-off attached to a list that is plural, and
           * that is what makes each of them want its own rule. Worth solving
           * properly rather than growing a second exception here.
           */
          if (started) {
            await close();
            return;
          }
          await load();
          return;
        }

        const result = await installFirmware(entryId, requirement);
        if (!result.ok) {
          setError(result.error ?? "Could not install that file.");
          return;
        }
        const moved = result.copied?.length ?? 0;
        const kept = result.kept?.length ?? 0;
        toaster.toast({
          title: `${requirement} installed`,
          body: kept
            ? `${moved} file(s) moved into place; ${kept} already there and left alone.`
            : `${moved} file(s) moved into place.`,
        });
        await load();
      } catch (installError) {
        logError("could not install firmware", installError);
        setError("Could not install that file.");
      } finally {
        setBusy(false);
      }
    },
    [matchFor, inboxFirmware, firmware, load, close],
  );

  const running = Boolean(status?.running);
  const received = status?.received ?? [];
  /*
   * One row per game, not per file. A CD rip is a sheet and a dozen tracks, and
   * listed flat each track got its own Add -- which makes a Steam entry out of
   * raw sectors. The count above the list still counts files, so it still says
   * what arrived; see receivedGroups.
   */
  // Plainly, not memoised: the list is capped at a hundred names and the poll
  // hands back a new array every few seconds anyway, so a memo would recompute
  // on the renders that matter and only bind the two together.
  const groups = groupReceived(received);
  const stopped = status?.stopped ?? [];
  const uploads = status?.uploads ?? [];

  // ModalRoot gets our handler, not the raw one, so dismissing with B stops the
  // server too rather than leaving it listening behind a closed dialog.
  return (
    <ModalRoot closeModal={() => void close()} bAllowFullSize>
      {/* Injected here as well as in the panels: the rule is scoped to a class,
          not global, and a modal renders outside whichever panel opened it. */}
      <style>{DANGER_CSS}</style>
      {/* Matches the button that opens it. The heading and the button used to
          use different words for the same thing, so arriving here read as
          having gone somewhere else. */}
      <div style={{ fontSize: "18px", fontWeight: 600, marginBottom: "8px" }}>
        Transfer to Deck
      </div>

      {/* Shown while sending, not only in the panel that opened this: the
          filenames are the thing the sender needs in front of them at the
          moment they pick a file, and renaming afterwards means sending twice. */}
      {expecting.length > 0 && (
        <div style={{ ...MUTED, marginBottom: "8px" }}>
          {expecting.map((item) => (
            <div key={item.label}>
              <b>{item.label}</b> — {item.expects}
            </div>
          ))}
        </div>
      )}

      <Focusable style={COLUMN}>
        {!running && (
          <>
            <div style={MUTED}>
              Starts a small upload page on your local network. Scan the QR code with a
              camera, or open the short address on a computer and type the code shown.
            </div>
            {/* Start leads; changing the folder is the exception, so they share a
                row rather than taking one each. */}
            <Focusable style={{ display: "flex", gap: "8px" }}>
              <DialogButton
                onClick={() => void start()}
                disabled={busy || !dir}
                style={{ flex: 2 }}
              >
                {busy ? "Starting..." : "Start receiving"}
              </DialogButton>
              <DialogButton onClick={() => void pickDir()} disabled={busy} style={{ flex: 1 }}>
                Change folder
              </DialogButton>
            </Focusable>
            <div style={MUTED}>{dir || "Choose a folder"}</div>
          </>
        )}

        {running && status && (
          <HandoffCode
            url={status.url}
            shortUrl={status.short_url}
            pin={status.pin}
            pinLocked={status.pin_locked}
          >
            {/* Worth saying at all because the Close button reads like it
                cancels. It does not, and a transfer still running is exactly
                when someone wants to put the Deck down. */}
            Saving into {status.target_dir}. Stops after{" "}
            {Math.round(status.idle_timeout / 60)} min idle — closing this is fine,
            transfers keep going.
          </HandoffCode>
        )}

        {error && <div style={{ color: "#e35d5d", fontSize: "13px" }}>{error}</div>}

        {/* A transfer that lost its connection, waiting for the sender to carry
            on. Said here as well as in the panel because this is the screen with
            the Done button on it, and "nothing is arriving" is what somebody
            reads just before pressing it -- which would end the transfer they
            are waiting for. */}
        {uploads.length === 0 && (status?.paused ?? 0) > 0 && (
          <div style={NOTICE}>
            <div style={{ fontWeight: 600 }}>
              {status?.paused === 1 ? "A transfer is paused" : `${status?.paused} transfers are paused`}
            </div>
            <div style={{ opacity: 0.85 }}>
              {status?.paused === 1
                ? "It carries on where it left off when the sender reconnects. Closing this does not stop it."
                : "They carry on where they left off when the sender reconnects. Closing this does not stop them."}
            </div>
          </div>
        )}

        {/* Above the received list, because this is the thing changing. Until
            this existed a multi-gigabyte ROM produced no sign of life at all --
            a file only appeared once it had finished and been renamed into
            place, so a long transfer and a dead connection looked identical. */}
        {uploads.length > 0 && (
          <div style={{ ...COLUMN, gap: "8px" }}>
            <div style={{ fontWeight: 600 }}>Arriving</div>
            {/* Two lines per file, not three: name and size share a row with the
                button, and the bar gets the row under it. Three rows each meant
                two simultaneous uploads could push the dialog into scrolling,
                which is the one thing a glance-and-scan dialog must not do. */}
            {uploads.map((file) => (
              <Focusable key={file.id} style={{ ...COLUMN, gap: "4px" }}>
                <Focusable
                  style={{ display: "flex", alignItems: "center", gap: "10px" }}
                >
                  <FileName name={file.name} style={{ flex: 1 }} />
                  <div style={{ ...MUTED, whiteSpace: "nowrap" }}>
                    {file.cancelled
                      ? "Cancelling..."
                      : `${humanSize(file.received)} of ${humanSize(file.total)}`}
                  </div>
                  <div className={DANGER_CLASS}>
                    <DialogButton
                      onClick={() => void abandon(file.id)}
                      disabled={file.cancelled}
                      style={ICON_BUTTON_WIDE}
                    >
                      Cancel
                    </DialogButton>
                  </div>
                </Focusable>
                <ProgressBar fraction={file.total > 0 ? file.received / file.total : 0} />
              </Focusable>
            ))}
          </div>
        )}

        {/* Half-sent files nobody is sending: cancelled, or interrupted and not
            picked up again. Kept so choosing the file again carries on, which
            made them invisible -- the list skips half-files, and the only way
            to be rid of one was to wait for the next server session. A heading
            of their own, so Received still counts only finished files. */}
        {stopped.length > 0 && (
          <div style={{ ...COLUMN, gap: "6px" }}>
            <div>
              <div style={{ fontWeight: 600 }}>Stopped ({stopped.length})</div>
              {/* Said once for the group: nothing else on this screen tells you a
                  cancel kept what arrived, so the bin reads as the only way on. */}
              {/* "While this stays open" is the load-bearing half: closing the
                  dialog lets the server stop, and starting it again clears
                  what a cancelled transfer left. */}
              <div style={MUTED}>
                Resume it from the page that sent it while this stays open, or send
                the same file again.
              </div>
            </div>
            <Focusable style={RECEIVED}>
              {stopped.map((file) => (
                <Focusable
                  key={file.partial}
                  style={{ display: "flex", alignItems: "center", gap: "10px" }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <FileName name={file.name} />
                    <div style={MUTED}>
                      {file.total > 0
                        ? `${file.cancelled ? "Cancelled" : "Stopped"} at ${Math.floor((file.received / file.total) * 100)}% · ${humanSize(file.received)} of ${humanSize(file.total)}`
                        : `${file.cancelled ? "Cancelled" : "Stopped"} · ${humanSize(file.received)} sent`}
                    </div>
                  </div>
                  <div className={DANGER_CLASS}>
                    <DialogButton
                      onClick={() =>
                        confirmDiscardTransfer(
                          { name: file.name, size: file.received },
                          load,
                          { partial: file.partial },
                        )
                      }
                      style={ICON_BUTTON}
                    >
                      <FaTrash />
                    </DialogButton>
                  </div>
                </Focusable>
              ))}
            </Focusable>
          </div>
        )}

        {received.length > 0 && (
          <div style={{ ...COLUMN, gap: "6px" }}>
            <div style={{ fontWeight: 600 }}>Received ({received.length})</div>
            <Focusable style={RECEIVED}>
              {groups.map(({ file, tracks, size }) => (
                <Focusable
                  key={file.path}
                  style={{ display: "flex", alignItems: "center", gap: "10px" }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <FileName name={file.name} />
                    <div style={MUTED}>
                      {/* The set, not the two kilobytes of text naming it --
                          the size a reader checks against what they sent, and
                          what deleting the row costs. */}
                      {humanSize(size)}
                      {tracks.length > 0
                        ? ` · ${ownedCount(file.name, tracks.length)}`
                        : ""}
                      {file.game_content
                        ? ` · ${file.game_content.label}` +
                          (file.game_content.app_id ? ` for ${file.game_content.title}` : "")
                        : ""}
                    </div>
                  </div>
                  {/* Before the action, because it is about the row rather
                      than a second thing to do with it -- and folding twelve
                      rows away raises "did the rest arrive?", which nothing
                      else here can answer. Only on a row that folded some. */}
                  {tracks.length > 0 && (
                    <DialogButton
                      onClick={() =>
                        openModal(
                          <DiscTracksModal playlist={file.name} tracks={tracks} />,
                        )
                      }
                      style={ICON_BUTTON_WIDE}
                    >
                      {ownedNoun(file.name) === "track" ? "Tracks" : "Files"}
                    </DialogButton>
                  )}
                  {/* What the file is for decides the button. A BIOS offered
                      "Add" was being offered the ROM add flow, which would have
                      made a Steam entry out of a firmware dump. */}
                  {file.name.endsWith(DEFINITION_SUFFIX) ? (
                    <DialogButton
                      onClick={() => importDefinition(file.name, load)}
                      style={ICON_BUTTON_WIDE}
                    >
                      Import
                    </DialogButton>
                  ) : matchFor(file.name) ? (
                    <DialogButton
                      disabled={busy}
                      onClick={() => void install(file.name)}
                      style={ICON_BUTTON_WIDE}
                    >
                      Install
                    </DialogButton>
                  ) : file.name.toLowerCase().endsWith(".rap") ? (
                    // A PS3 licence, not a game: Add would make a Steam entry
                    // out of sixteen bytes. Install puts it where RPCS3 looks.
                    <DialogButton
                      disabled={busy}
                      onClick={() => void installLicence(file.name)}
                      style={ICON_BUTTON_WIDE}
                    >
                      Install
                    </DialogButton>
                  ) : file.licence_key ? (
                    // Vita3K reads a key only while it installs the package, so
                    // there is nothing to put it into from here.
                    <div style={MUTED}>Used when its .pkg is unpacked</div>
                  ) : file.game_content ? (
                    // A Switch update or DLC names the game it is for, so this
                    // installs straight into that game -- the same Install a
                    // BIOS row has, and never Add, which would make a Steam
                    // entry out of something that is not a game. Offered even
                    // when that game is not in the library: pressing it says so.
                    <DialogButton
                      disabled={busy}
                      onClick={() => {
                        setBusy(true);
                        void installContentFor(file.game_content!, file.path).finally(() => {
                          setBusy(false);
                          void load();
                        });
                      }}
                      style={ICON_BUTTON_WIDE}
                    >
                      Install
                    </DialogButton>
                  ) : PATCH_SUFFIXES.some((one) =>
                      file.name.toLowerCase().endsWith(one),
                    ) ? (
                    // Not "Add": a patch is not a game, and the add flow would
                    // make a Steam entry out of one. Install, like an update --
                    // but a patch does not say which game it is for, so the
                    // button asks first.
                    <DialogButton
                      disabled={busy}
                      onClick={() => openPatchInstall(file.path, file.name, () => void load())}
                      style={ICON_BUTTON_WIDE}
                    >
                      Install
                    </DialogButton>
                  ) : purpose === "firmware" ? (
                    // A firmware send with no requirement named -- nothing to
                    // install it into from here, so it says where it went
                    // rather than offering an action that would be wrong.
                    <div style={MUTED}>In the firmware folder</div>
                  ) : purpose === "backup" ? (
                    // The action, not a sentence about where the file went --
                    // the same shape Import and Install have above. A save
                    // backup is not a game, so Add would make a Steam entry out
                    // of somebody's save files; Restore is what it is for, and
                    // it lands on the same screen the Library tab opens.
                    <DialogButton
                      onClick={() => {
                        // The dialog goes first. Steam re-reveals each modal as
                        // the one above it dismisses, so leaving this underneath
                        // would put the transfer list back over the restore
                        // screen afterwards -- see modalStack.
                        closeModal?.();
                        openRestoreSaves();
                      }}
                      style={ICON_BUTTON_WIDE}
                    >
                      Restore
                    </DialogButton>
                  ) : (
                    <DialogButton
                      onClick={() => void use(file.path, file.name)}
                      style={ICON_BUTTON_WIDE}
                    >
                      Add
                    </DialogButton>
                  )}

                  {/* Last, and that is the whole of the reasoning: gamepad
                      focus enters a row from the left, so the first control is
                      the one a thumb lands on without aiming. Every other row
                      in this plugin already puts the destructive one at the end
                      -- edit before remove, register before forget -- and this
                      was briefly the exception.

                      Beside the action rather than instead of it: a file can be
                      both usable and unwanted, and until this existed the only
                      way out of the folder was to use it. */}
                  {purpose !== "backup" && (
                    <div className={DANGER_CLASS}>
                      <DialogButton
                        onClick={() =>
                          confirmDiscardTransfer(
                            { name: file.name, size, owned: tracks.length },
                            load,
                          )
                        }
                        style={ICON_BUTTON}
                      >
                        <FaTrash />
                      </DialogButton>
                    </div>
                  )}
                </Focusable>
              ))}
            </Focusable>
          </div>
        )}

        {/* Below the code and the received list: this is setup, not the thing you
            opened the dialog to do. Offered even before the server starts, so the
            choice can be made once rather than discovered mid-transfer.

            The description is deliberately two short lines. It was a paragraph,
            and a paragraph here is what tipped the dialog into scrolling -- which
            costs more than the nuance it was carrying, since the toggle is read
            once and the QR code is read every time. */}
        <ToggleField
          label="Remember trusted devices"
          description="Keeps the same address between sessions, so a device can bookmark this page and come straight back with no code to type. Off issues a new link each time."
          checked={remember}
          onChange={(next) => void changeRemember(next)}
          disabled={busy}
        />

        {/* One row, the same shape as Start receiving / Change folder above.
            Reset is conditional and secondary, so it takes the narrow half and
            leaves twice the width to the button everyone actually presses --
            rather than each taking a full row of its own. */}
        <Focusable style={{ display: "flex", gap: "8px" }}>
          <DialogButton
            onClick={() => void close()}
            disabled={busy}
            style={{ flex: 2, minWidth: "auto" }}
          >
            {running && (status?.uploading ?? 0) === 0 ? "Done" : "Close"}
          </DialogButton>
          {/* After the button everybody presses, not before it. Gamepad focus
              enters a row from the left, so the first control is the one a
              thumb lands on without aiming -- and this one revokes a credential
              on devices that are not in the room. Every other row in the plugin
              puts the destructive control last. */}
          {remember && (
            <div className={DANGER_CLASS} style={{ flex: 1, display: "flex" }}>
              <DialogButton
                onClick={confirmResetLink}
                disabled={busy}
                style={{ flex: 1, minWidth: "auto" }}
              >
                Reset link
              </DialogButton>
            </div>
          )}
        </Focusable>
      </Focusable>
    </ModalRoot>
  );
}
