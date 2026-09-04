import {
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  Spinner,
  ToggleField,
} from "@decky/ui";
import { addEventListener, removeEventListener } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  cloudBackupNow,
  cloudStatus,
  endSaveBackup,
  saveBackupSources,
  startSaveBackup,
  type FileServerStatus,
  type SaveSource,
} from "./backend";
import { logError } from "./logError";
import { HandoffCode } from "./HandoffCode";
import { MUTED } from "./dialogStyle";
import { backupSummary, defaultSelection, totals } from "./saveBackup";
import { humanSize, ProgressBar } from "./TransferModal";

/**
 * Taking save data off the Deck, on the server that already brings ROMs in.
 *
 * Two of this plugin's own buttons destroy saves -- uninstalling an emulator
 * with its data, and clearing the library -- and neither is recoverable. Game
 * Mode offers no route to the directories they live in, so until now the only
 * way to keep a save was to leave Game Mode, which is the one thing this plugin
 * exists to avoid.
 *
 * The way across is the one the transfer flow established and the report already
 * reuses: a QR code for anything with a camera, a short address and six digits
 * for anything with a keyboard. What differs from the report is that this stages
 * a real file, so it has a lifetime -- see the cleanup below, which deletes it.
 */


interface Props {
  closeModal?: () => void;
}

export function SaveBackupModal({ closeModal }: Props) {
  const [sources, setSources] = useState<SaveSource[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<Partial<FileServerStatus> | null>(null);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState("");
  /* The storage in use, when there is one, and what it is called. Read once:
     signing in happens on a phone, so it cannot change while this is open. */
  const [cloud, setCloud] = useState<{ remote: string; label: string } | null>(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<string[] | null>(null);
  /* What rclone last said it was doing, and how far through. A copy of a save
     directory over wifi is not instant, and a button reading "Copying..." for
     ninety seconds cannot be told from one that has hung. */
  const [carrying, setCarrying] = useState<{ name: string; percent: number } | null>(
    null,
  );
  /*
   * Whether there is a backup on disk to delete on the way out. A ref rather
   * than state for the same reason `ReportModal` uses one: the cleanup below
   * runs after the last render, where state would still hold whatever it was
   * when the effect was created.
   */
  const staged = useRef(false);

  useEffect(() => {
    let live = true;
    void cloudStatus()
      .then((result) => {
        if (live && result.remote) {
          setCloud({ remote: result.remote, label: result.label || result.kind });
        }
      })
      .catch((cloudError) => logError("could not read the cloud destination", cloudError));
    void saveBackupSources()
      .then((result) => {
        if (!live) return;
        setSources(result.sources);
        setSelected(defaultSelection(result.sources));
      })
      .catch((listError) => {
        logError("could not list what there is to back up", listError);
        if (live) setError("Could not work out what there is to back up.");
      });

    return () => {
      live = false;
      /*
       * Every way out, not just Done. A modal is also dismissed with B and with
       * the X, and hanging this off one button would leave a copy of somebody's
       * save files in decky's runtime directory for anyone who left by either of
       * the other two -- which is most people.
       *
       * Only when something was actually staged: with no backup of ours out
       * there, `end_save_backup` would still consider stopping a server that may
       * be up for a transfer somebody else started.
       */
      if (!staged.current) return;
      void endSaveBackup().catch((endError) =>
        logError("could not clear away the save backup", endError),
      );
    };
  }, []);

  // The copy runs in the backend and says how it is going, so this end listens
  // rather than polls -- the same pair of events the emulator installs use, and
  // the same reason: a percentage that arrives when it changes beats one asked
  // for on a timer.
  useEffect(() => {
    const progress = addEventListener<[name: string, percent: number]>(
      "cloud_sync_progress",
      (name, percent) => setCarrying({ name, percent }),
    );
    const done = addEventListener<[ok: boolean, error: string, names: string[]]>(
      "cloud_sync_done",
      (ok, failure, names) => {
        setSending(false);
        setCarrying(null);
        if (!ok) {
          setError(failure || "The saves could not be copied.");
          return;
        }
        setSent(names);
      },
    );
    return () => {
      removeEventListener("cloud_sync_progress", progress);
      removeEventListener("cloud_sync_done", done);
    };
  }, []);

  const toggle = useCallback((id: string, on: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const build = useCallback(() => {
    setBuilding(true);
    setError("");
    void startSaveBackup([...selected])
      .then((result) => {
        if (!result.ok) {
          setError(result.error ?? "The backup could not be built.");
          return;
        }
        // Set even if this modal has since closed: a backup written by a call
        // that landed late would otherwise be left on disk with nothing to
        // delete it.
        staged.current = true;
        setStatus(result);
      })
      .catch((buildError) => {
        logError("could not build the save backup", buildError);
        setError("The backup could not be built.");
      })
      .finally(() => setBuilding(false));
  }, [selected]);

  /*
   * The other destination.
   *
   * Same list, same ticks, same totals -- what differs is where it lands, so it
   * is a second button rather than a second dialog. What goes up is loose files
   * per emulator rather than the archive built above: a zip cannot be diffed,
   * so a second copy of it would send every save again to record a change of a
   * few kilobytes.
   */
  const toCloud = useCallback(() => {
    if (!cloud) return;
    setSending(true);
    setError("");
    setSent(null);
    setCarrying({ name: "", percent: 0 });
    // Only starts it. How it went arrives on `cloud_sync_done` above, which is
    // also what puts the button back -- so there is no `finally` here: this
    // resolving means the copy began, not that it finished.
    void cloudBackupNow([...selected])
      .then((result) => {
        if (!result.ok) {
          setError(result.error ?? "The saves could not be copied.");
          setSending(false);
          setCarrying(null);
        }
      })
      .catch((sendError) => {
        logError("could not copy saves to the cloud", sendError);
        setError("The saves could not be copied.");
        setSending(false);
        setCarrying(null);
      });
  }, [cloud, selected]);

  const url = status?.download_url ?? "";
  const sums = totals(sources ?? [], selected);

  return (
    /*
     * `bAllowFullSize` because this is a list modal, the same reason
     * `OrphanModal` sets it. Without it the modal is a smaller box than the
     * content needs and the buttons at the bottom are simply cut off.
     */
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/*
        One flex column with a bound, so the list absorbs whatever room is left
        rather than a fixed slice of the viewport.

        Sizing the list in `vh` was the first attempt and it does not work: the
        header, the summary and the buttons are also on screen, so any number
        big enough to be useful on a short list overflows a long one, and the
        buttons go over the bottom edge. Here the bound is on the column and
        only the list flexes -- so the buttons are laid out first and the list
        gets the remainder, whatever that turns out to be.
      */}
        <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
          Back up save data
        </div>
        <div style={{ ...MUTED, marginBottom: "12px" }}>
          Builds one file holding your saves and offers it to another device on this
          network. Nothing on the Deck is changed or removed.
        </div>

        {error && <div style={{ color: "#e35d5d", fontSize: "13px" }}>{error}</div>}

        {!error && sources === null && (
          <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
            <Spinner style={{ height: "32px" }} />
          </div>
        )}

        {sources !== null && sources.length === 0 && (
          <Field description="No installed emulator has any save data yet. Play something first, then come back." />
        )}

        {/* The list, until a backup exists. Once one does the screen is about
            getting it off the device, and a list of ticks that no longer change
            anything would be the loudest thing on it. */}
        {!url && sources !== null && sources.length > 0 && (
          <>
            {/* Scrolled, because `ModalRoot` does not scroll its own content:
                measured on the device, a list this long simply runs off the
                bottom of the screen and the buttons never render. Focusable
                rather than a div so a controller can reach past the first
                screenful. The summary and the buttons stay outside it.

                Sized to about three rows. A row here is ~105px measured on
                the device, so three is ~315px, and 38vh of the Deck's 800
                is close to it while still scaling with the window.
                */}
            <Focusable style={{ maxHeight: "38vh", overflowY: "auto" }}>
              {sources.map((source) => (
                <ToggleField
                  key={source.id}
                  label={source.name}
                  description={
                    `${humanSize(source.bytes)}, ${source.files} file(s)` +
                    // The row whose size can dwarf every other one, said on the
                    // row itself rather than only in the total -- this is where
                    // somebody decides to untick it.
                    (source.whole
                      ? " - everything it keeps, since it does not say where its saves are"
                      : "")
                  }
                  checked={selected.has(source.id)}
                  onChange={(on) => toggle(source.id, on)}
                />
              ))}
            </Focusable>
            <div style={{ ...MUTED, marginTop: "10px" }}>
              {backupSummary(sums, humanSize(sums.bytes))}
            </div>
            {/* A bar rather than a spinner, because the question while this
                runs is not whether it is doing something but how much longer.
                It takes the row the summary below would otherwise use, so
                nothing moves when it appears. */}
            {carrying && (
              <div style={{ marginTop: "10px" }}>
                <div style={{ ...MUTED, marginBottom: "4px" }}>
                  {carrying.name
                    ? `Copying ${carrying.name} to ${cloud?.label}...`
                    : `Copying to ${cloud?.label}...`}
                </div>
                <ProgressBar fraction={carrying.percent / 100} />
              </div>
            )}

            {/* What went up, said where the decision was made rather than as a
                toast that is gone before the dialog is. */}
            {sent !== null && !carrying && (
              <div style={{ ...MUTED, marginTop: "10px" }}>
                {sent.length > 0
                  ? `Copied to ${cloud?.label}: ${sent.join(", ")}.`
                  : "Nothing was copied."}
              </div>
            )}

            {/* Equal thirds with `minWidth: auto`, which is the only shape that
                works here. Cancel was left to size itself and Steam's own
                minimum width for a DialogButton carried it clean off the right
                of the dialog -- the same failure RestoreSavesModal records four
                attempts at, and the same fix. */}
            <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
              <DialogButton
                disabled={building || sending || sums.names.length === 0}
                onClick={() => build()}
                style={{ flex: 1, minWidth: "auto" }}
              >
                {building ? "Building..." : "Build the backup"}
              </DialogButton>
              {/* Offered only once there is somewhere for it to go. A button
                  that opens the setup page would be a second route into it,
                  and the row that opens that page is directly above this one
                  in the panel. */}
              {cloud && (
                <DialogButton
                  disabled={building || sending || sums.names.length === 0}
                  onClick={() => toCloud()}
                  style={{ flex: 1, minWidth: "auto" }}
                >
                  {sending ? "Copying..." : `Copy to ${cloud.label}`}
                </DialogButton>
              )}
              <DialogButton
                disabled={sending}
                onClick={() => closeModal?.()}
                style={{ flex: 1, minWidth: "auto" }}
              >
                Cancel
              </DialogButton>
            </Focusable>
          </>
        )}

        {url && (
          <>
            <HandoffCode
              url={url}
              shortUrl={status?.short_url}
              pin={status?.pin}
              pinLocked={status?.pin_locked}
            >
              {status?.download_name} - {humanSize(status?.download_bytes ?? 0)}
            </HandoffCode>

            {/*
              Done means gone. The report this borrows its shape from is a log tail
              held in memory; this is a copy of the user's save files sitting on
              disk, so leaving it behind after they said they had finished is a
              copy nobody asked to keep.
            */}
            <div style={{ ...MUTED, marginTop: "14px" }}>
              Download it before pressing Done - the file is deleted from the Deck
              then, and in any case after {Math.round((status?.idle_timeout ?? 1800) / 60)}{" "}
              minutes.
            </div>

            <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
              {/* Just closes. Deleting the backup is the effect's cleanup above,
                  so B and the X do it too. */}
              <DialogButton onClick={() => closeModal?.()} style={{ flex: 1 }}>
              Done
            </DialogButton>
            </Focusable>
          </>
        )}
    </ModalRoot>
  );
}
