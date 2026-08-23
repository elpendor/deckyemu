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
  firmwareStatus,
  type FirmwareReport,
  getSettings,
  installFirmware,
  resetTransferLink,
  setSettings,
  startFileServer,
  stopFileServer,
  stopFileServerIfIdle,
  type FileServerStatus,
} from "./backend";
import { selectRom } from "./addFlow";
import { FileName } from "./FileName";
import { QrCode } from "./QrCode";

/**
 * What marks a sent file as an emulator definition rather than a ROM.
 *
 * Kept in step with `emulator_catalog.imported.SUFFIX` by a test, not by
 * remembering: the two halves disagreeing means the Import button never appears
 * and the file looks like a ROM the picker cannot read.
 */
const DEFINITION_SUFFIX = ".deckyemu.json";
import { DANGER_CLASS, DANGER_CSS, DANGER_TEXT } from "./danger";
import { logError } from "./logError";
import { installThroughEmulator } from "./firmwareInstall";
import { requirementForFile, type RequirementMatch } from "./firmwareMatch";
import { confirmDiscardTransfer } from "./discardTransfer";
import { importDefinition } from "./importDefinition";
import { closeOpenModals, openModal } from "./modalStack";

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
   */
  purpose?: "roms" | "firmware";
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

// 8px rather than 10: this gap is paid between every section of the dialog, so it
// is one of the cheapest places to reclaim height without changing what is shown.
const COLUMN = { display: "flex", flexDirection: "column" as const, gap: "8px" };
const MUTED = { fontSize: "13px", opacity: 0.7 };

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
 * QR on one side, the typed address on the other.
 *
 * Stacked, the code sat below the fold and the dialog scrolled -- which defeats
 * the point of a glance-and-scan dialog. They are alternatives to each other, so
 * side by side also reads better than one after the other.
 *
 * `wrap` rather than a fixed split: at a narrow width the columns stack instead of
 * squeezing the QR code, which has to stay large enough for a camera.
 */
const SPLIT = {
  display: "flex",
  gap: "18px",
  alignItems: "center",
  flexWrap: "wrap" as const,
};

/**
 * A progress bar, hand-rolled.
 *
 * @decky/ui does export Steam's own ProgressBar, but it is resolved at runtime by
 * searching the webpack bundle for a matching module -- it returns undefined when
 * Steam renames or reshapes it, and rendering undefined takes the whole dialog
 * with it. The same reasoning as steam.ts: a Steam change should cost a feature,
 * not the panel. Two divs and a width owe nothing to Steam's internals.
 */
export function ProgressBar({ fraction }: { fraction: number }) {
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
      <div
        style={{
          height: "100%",
          width: `${clamped * 100}%`,
          background: "#4c6ef5",
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
    try {
      const result = await fileServerStatus();
      setStatus(result);
      setDir((current) => current || result.target_dir || result.suggested_dir || "");
    } catch (loadError) {
      logError("could not read file server status", loadError);
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
    (path: string, name: string) => {
      void selectRom(path);
      toaster.toast({ title: "Ready to add", body: name });
      void close();
      // Everything else of ours, not just this dialog. Steam re-reveals each
      // modal as the one above it dismisses, so anything still on the stack
      // arrives on top of the panel opened below -- and with the added-games
      // list underneath, that is exactly what happened: the panel appeared with
      // the game ready and closed again about a second later, as the list came
      // back and took the active overlay. Same rule as "navigate last" (§5),
      // one layer down.
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
      (installInto
        ? {
            entryId: installInto.entryId,
            emulatorName: "",
            requirement: installInto.requirement,
            guiInstall: false,
            prompt: "",
          }
        : undefined),
    [firmware, installInto],
  );

  const install = useCallback(
    async (name: string) => {
      const match = matchFor(name);
      if (!match) return;
      const { entryId, requirement } = match;

      setBusy(true);
      setError("");
      try {
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
    [matchFor, load, close],
  );

  const running = Boolean(status?.running);
  const received = status?.received ?? [];
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
          <div style={SPLIT}>
            {/* The default 190 rather than 210: still comfortably scannable at
                arm's length, and this dialog has gained a progress section and
                a settings toggle since it was sized, so the height it gives
                back is worth more than the pixels. */}
            <QrCode text={status.url} />

            {/* For anything without a camera. The token URL is 22 characters of
                random text and nobody will type it, so the short address plus a
                six-digit code is the way in from a computer. */}
            <div style={{ ...COLUMN, flex: "1 1 240px", gap: "2px" }}>
              <div style={MUTED}>Scan the code, or open this on a computer:</div>
              <div style={{ fontSize: "19px", fontWeight: 600 }}>{status.short_url}</div>
              <div style={{ ...MUTED, marginTop: "8px" }}>then enter</div>
              {/* 28px, down from 34. It is read off the screen at arm's length by
                  someone typing it into a laptop, not across a room, and the
                  height it gives back is height the text below it can use before
                  this column starts driving the split. */}
              <div style={{ fontSize: "28px", fontWeight: 700, letterSpacing: "0.24em" }}>
                {status.pin}
              </div>

              {status.pin_locked && (
                <div style={{ color: "#e35d5d", fontSize: "13px", marginTop: "6px" }}>
                  Too many wrong codes. Stop and start again for a new one.
                </div>
              )}

              {/* Inside the column, not below the split.

                  This is the one place in the dialog where height is free: the
                  split is as tall as the QR code beside it, so anything this
                  column does not use is simply empty. Moving this text out to a
                  full-width row of its own read like it should be cheaper and was
                  strictly worse -- it left that space blank and added a row.

                  Worth saying at all because the Close button reads like it
                  cancels. It does not, and a transfer still running is exactly
                  when someone wants to put the Deck down. */}
              <div style={{ ...MUTED, marginTop: "10px" }}>
                Saving into {status.target_dir}. Stops after{" "}
                {Math.round(status.idle_timeout / 60)} min idle — closing this is
                fine, transfers keep going.
              </div>
            </div>
          </div>
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
                      style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
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

        {received.length > 0 && (
          <div style={{ ...COLUMN, gap: "6px" }}>
            <div style={{ fontWeight: 600 }}>Received ({received.length})</div>
            <Focusable style={RECEIVED}>
              {received.map((file) => (
                <Focusable
                  key={file.path}
                  style={{ display: "flex", alignItems: "center", gap: "10px" }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <FileName name={file.name} />
                    <div style={MUTED}>{humanSize(file.size)}</div>
                  </div>
                  {/* What the file is for decides the button. A BIOS offered
                      "Add" was being offered the ROM add flow, which would have
                      made a Steam entry out of a firmware dump. */}
                  {file.name.endsWith(DEFINITION_SUFFIX) ? (
                    <DialogButton
                      onClick={() => importDefinition(file.name, load)}
                      style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
                    >
                      Import
                    </DialogButton>
                  ) : matchFor(file.name) ? (
                    <DialogButton
                      disabled={busy}
                      onClick={() => void install(file.name)}
                      style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
                    >
                      Install
                    </DialogButton>
                  ) : purpose === "firmware" ? (
                    // A firmware send with no requirement named -- nothing to
                    // install it into from here, so it says where it went
                    // rather than offering an action that would be wrong.
                    <div style={MUTED}>In the firmware folder</div>
                  ) : (
                    <DialogButton
                      onClick={() => use(file.path, file.name)}
                      style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
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
                  <div className={DANGER_CLASS}>
                    <DialogButton
                      onClick={() => confirmDiscardTransfer(file, load)}
                      style={{ minWidth: "auto", width: "auto", padding: "6px 12px" }}
                    >
                      <FaTrash />
                    </DialogButton>
                  </div>
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
