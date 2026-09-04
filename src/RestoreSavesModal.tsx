import {
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  Spinner,
} from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { FaTrash } from "react-icons/fa";
import { useCallback, useEffect, useState } from "react";

import {
  cloudContents,
  cloudRestore,
  cloudSnapshots,
  cloudStatus,
  describeSaveBackup,
  discardSaveBackup,
  listSaveBackups,
  restoreSaveBackup,
  startFileServer,
  type CloudRemote,
  type CloudSnapshot,
  type SaveBackupContents,
  type SaveBackupFile,
} from "./backend";
import { DANGER_CLASS, DANGER_CSS, DANGER_TEXT } from "./danger";
import { FileName } from "./FileName";
import { logError } from "./logError";
import { openModal } from "./modalStack";
import { missingCount, presentCount, restoreSummary } from "./saveBackup";
import { humanSize, ProgressBar, TransferModal } from "./TransferModal";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";

/**
 * Backups waiting on this Deck, and what to do with one.
 *
 * **Built to `ImportDefinitionModal`'s shape, deliberately.** That dialog
 * answers the same question about a different file -- what has been sent here,
 * and what can be done with it -- and it is the one in this plugin that lays out
 * correctly on the device. Four attempts at a layout of its own failed here in
 * four different ways: the list collapsed to one clipped row, then burst off the
 * top of the screen, then pushed the buttons past the bottom edge, then ran off
 * the right-hand side because five buttons cannot share a row. Copying a working
 * dialog beats another number.
 *
 * A row per backup rather than jumping straight in when there is one, for the
 * reason the import list gives: it costs a press and answers the question the
 * empty case raises anyway -- *which* files can it see. Somebody whose backup is
 * not listed needs to know that before they go looking for a bug.
 *
 * **Cloud storage is another place a backup can be, not another dialog.** A
 * signed-in account is listed beside the files on the Deck and picking one
 * produces the same per-emulator rows and the same two buttons, because it is
 * the same decision -- put back what is missing, or replace what is here. Any
 * account signed into is offered, not only the one saves currently go to: that
 * is what makes switching storage cost nothing, since what was left on the old
 * one is still one press away rather than stranded.
 *
 * The list is the per-emulator breakdown, rendered as import renders its files:
 * plain `Field` rows, no scroll container of its own, and the dialog left to
 * size itself. Every scroller and flex bound written here before this was an
 * attempt to make that list fit alongside furniture it should not have been
 * competing with.
 */

interface Props {
  closeModal?: () => void;
}

/** Where a restore is reading from: a file on the Deck, or a storage signed into. */
type Picked =
  | { kind: "file"; file: SaveBackupFile }
  /** `stamp` empty is the live saves; set, it is what one copy replaced. */
  | { kind: "cloud"; remote: string; label: string; stamp: string };

export function RestoreSavesModal({ closeModal }: Props) {
  const [files, setFiles] = useState<SaveBackupFile[] | null>(null);
  const [accounts, setAccounts] = useState<CloudRemote[]>([]);
  /* Per account, the states its copies replaced. Read alongside the accounts
     themselves so the chooser is drawn once rather than growing rows under
     somebody's thumb. */
  const [replaced, setReplaced] = useState<Record<string, CloudSnapshot[]>>({});
  const [chosen, setChosen] = useState<Picked | null>(null);
  const [contents, setContents] = useState<SaveBackupContents[] | null>(null);
  const [working, setWorking] = useState(false);
  /* How far through a cloud restore is. A .zip is read off local disk and is
     done before a bar could draw; coming down from a remote is wifi, and a
     dialog that says nothing for ninety seconds reads as one that has hung. */
  const [carrying, setCarrying] = useState<{ name: string; percent: number } | null>(
    null,
  );
  const [error, setError] = useState("");
  // Where a backup belongs, so the transfer server can be pointed at it.
  const [backupDir, setBackupDir] = useState("");

  const open = useCallback(async (file: SaveBackupFile) => {
    setError("");
    setChosen({ kind: "file", file });
    setContents(null);
    try {
      const described = await describeSaveBackup(file.path);
      if (!described.ok) {
        setError(described.error ?? "That backup could not be read.");
        setChosen(null);
        return;
      }
      setContents(described.sources ?? []);
    } catch (describeError) {
      logError("could not read a save backup", describeError);
      setError("That backup could not be read.");
      setChosen(null);
    }
  }, []);

  /* The same three steps against a remote, and the answer comes back in the
     same shape -- see `cloudsync.contents`, which builds it that way on
     purpose so one list and one pair of buttons serve both. */
  const openCloud = useCallback(async (one: CloudRemote, snapshot?: CloudSnapshot) => {
    const service = one.label || one.kind || one.name;
    const label = snapshot ? `${service} — replaced ${snapshot.label}` : service;
    setError("");
    setChosen({ kind: "cloud", remote: one.name, label, stamp: snapshot?.stamp ?? "" });
    setContents(null);
    try {
      const held = await cloudContents(one.name, snapshot?.stamp ?? "");
      if (!held.ok) {
        setError(held.error ?? "That storage could not be read.");
        setChosen(null);
        return;
      }
      setContents(held.sources ?? []);
    } catch (readError) {
      logError("could not read cloud saves", readError);
      setError("That storage could not be read.");
      setChosen(null);
    }
  }, []);

  useEffect(() => {
    let live = true;

    /*
     * The files show the moment they are read; the storages arrive when they
     * arrive.
     *
     * These were awaited together at first and it was the wrong shape. Reading
     * the folder is a directory listing and is instant; asking a storage what
     * it holds is `rclone` over wifi, twice per account. Waiting for the second
     * before drawing the first left the dialog as nothing but a spinner for
     * seconds, on a screen whose whole job is to show what is already here.
     *
     * What still has to be sequenced is only the *auto-open*: a lone backup
     * file is opened for you, and doing that before knowing whether a storage
     * exists is how the storage rows lose the place they would have appeared
     * in. So both halves report in and the decision waits for the pair.
     */
    let backups: SaveBackupFile[] | null = null;
    let signedIn: CloudRemote[] | null = null;
    const decide = () => {
      if (!live || backups === null || signedIn === null) return;
      // Read straight away when it is the only thing there is, so its row
      // carries the counts rather than a Choose button with one possible
      // answer. With a storage signed in there is a choice, and making it for
      // somebody is how the other option becomes invisible.
      if (backups.length === 1 && signedIn.length === 0) void open(backups[0]);
    };

    void listSaveBackups()
      .then((result) => {
        if (!live) return;
        backups = result.backups;
        setFiles(result.backups);
        setBackupDir(result.dir ?? "");
        decide();
      })
      .catch((listError) => {
        logError("could not list save backups", listError);
        if (live) setError("Could not look for backups on this Deck.");
      });

    /* Cloud failing is not an error on this screen: it is optional, and a Deck
       with none set up must not be told something went wrong with a dialog
       about the files it does have. */
    void cloudStatus()
      .catch((cloudError) => {
        logError("could not list cloud storage", cloudError);
        return null;
      })
      .then(async (cloud) => {
        if (!live) return;
        signedIn = cloud?.remotes ?? [];
        setAccounts(signedIn);
        decide();
        // Asked per account and folded in as one object, so the rows under a
        // storage appear together rather than one at a time.
        const kept = await Promise.all(
          signedIn.map((one) =>
            cloudSnapshots(one.name)
              .then((held) => [one.name, held.snapshots ?? []] as const)
              .catch(() => [one.name, [] as CloudSnapshot[]] as const),
          ),
        );
        if (live) setReplaced(Object.fromEntries(kept));
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /*
   * A cloud restore is watched; an archive is awaited.
   *
   * Not an inconsistency worth removing. Reading a .zip off local disk is over
   * before a bar could draw, and it can say exactly how many files it wrote.
   * Coming down from a remote is somebody's wifi, and rclone reports what it
   * moved to its own output rather than back to us -- so one says how many
   * files, the other says which emulators, and both answer "did the thing I
   * asked for happen".
   */
  useEffect(() => {
    const progress = addEventListener<[name: string, percent: number]>(
      "cloud_sync_progress",
      (name, percent) => setCarrying({ name, percent }),
    );
    const done = addEventListener<[ok: boolean, error: string, names: string[]]>(
      "cloud_sync_done",
      (ok, failure, names) => {
        setWorking(false);
        setCarrying(null);
        if (!ok) {
          setError(failure || "The saves could not be restored.");
          return;
        }
        toaster.toast({
          title: "Saves restored",
          body: names.length ? `${names.join(", ")}.` : "Nothing needed to come down.",
        });
        closeModal?.();
      },
    );
    return () => {
      removeEventListener("cloud_sync_progress", progress);
      removeEventListener("cloud_sync_done", done);
    };
  }, [closeModal]);

  const run = useCallback(
    (replace: boolean) => {
      if (!chosen) return;
      setWorking(true);
      setError("");

      if (chosen.kind === "cloud") {
        setCarrying({ name: "", percent: 0 });
        // Only starts it; the listener above closes the dialog when it lands.
        void cloudRestore(chosen.remote, null, replace, chosen.stamp)
          .then((result) => {
            if (!result.ok) {
              setError(result.error ?? "The saves could not be restored.");
              setWorking(false);
              setCarrying(null);
            }
          })
          .catch((restoreError) => {
            logError("could not restore saves from cloud storage", restoreError);
            setError("The saves could not be restored.");
            setWorking(false);
            setCarrying(null);
          });
        return;
      }

      const file = chosen.file;
      void restoreSaveBackup(file.path, null, replace)
        .then((result) => {
          if (!result.ok) {
            setError(result.error ?? "The saves could not be restored.");
            return;
          }
          // Both halves, always. "12 files restored" alone reads as success on
          // a run that skipped forty because they were already there, and that
          // is the run most likely to be misread.
          const parts = [`${result.written ?? 0} file(s) restored`];
          if (result.skipped) parts.push(`${result.skipped} left as they were`);
          if (result.refused) parts.push(`${result.refused} could not be written`);
          // Named, because the file going is a thing that happened to something
          // of theirs. Silence reads as "where did my backup go".
          if (result.removed) parts.push("the backup was removed from this Deck");
          toaster.toast({ title: "Saves restored", body: parts.join(", ") + "." });
          closeModal?.();
        })
        .catch((restoreError) => {
          logError("could not restore saves", restoreError);
          setError("The saves could not be restored.");
        })
        .finally(() => setWorking(false));
    },
    [chosen, closeModal],
  );

  /**
   * The one action here that destroys something, behind the plugin's own
   * confirmation. The sentence is the whole of the protection -- there is no
   * undo -- so it counts what goes rather than describing it.
   */
  const confirmReplace = useCallback(() => {
    if (!contents) return;
    const overwritten = presentCount(contents);
    openModal(
      <ConfirmModal
        strTitle="Replace saves on this Deck?"
        strDescription={
          overwritten === 0
            ? "Nothing here would be overwritten - no save in this backup is already on the Deck."
            : `${overwritten} save file(s) on this Deck will be overwritten with the backup's copies. Whatever they hold now is gone, and there is no undo.`
        }
        strOKButtonText="Replace saves"
        bDestructiveWarning
        onOK={() => run(true)}
      />,
    );
  }, [contents, run]);

  const confirmDiscard = useCallback(() => {
    // Files only. Nothing here deletes from somebody's cloud storage: that is
    // their account, they have a file browser for it, and a plugin that can
    // empty it from a modal is one bad press away from being the thing that
    // lost the saves.
    if (chosen?.kind !== "file") return;
    const file = chosen.file;
    openModal(
      <ConfirmModal
        strTitle="Delete this backup?"
        strOKButtonText="Delete"
        bDestructiveWarning
        onOK={() =>
          void (async () => {
            try {
              const result = await discardSaveBackup(file.path);
              if (!result.ok) {
                toaster.toast({ title: "Could not delete", body: result.error ?? "" });
                return;
              }
              toaster.toast({ title: "Deleted", body: file.name });
              closeModal?.();
            } catch (discardError) {
              logError("could not discard a save backup", discardError);
              toaster.toast({ title: "Could not delete", body: "Something went wrong." });
            }
          })()
        }
        strDescription={
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {/* Wrapped whole rather than clamped: this is a destructive question
                asked once, and the answer depends on being sure which file it
                is. `confirmDiscardTransfer` makes the same call for the same
                reason. */}
            <FileName name={file.name} mode="wrap" style={{ fontWeight: 600 }} />
            <div style={DANGER_TEXT}>
              This deletes {humanSize(file.bytes)} from this Deck. It cannot be undone
              from here — the backup would have to be sent again. Saves already on the
              Deck are unaffected.
            </div>
          </div>
        }
      />,
    );
  }, [chosen, closeModal]);

  /**
   * Get a backup here, rather than a sentence naming a control somewhere else.
   *
   * The empty state used to read "use Send files from another device, then come
   * back", which from this dialog is a dead end: that button is in the Quick
   * Access panel. `ImportDefinitionModal` settled the rule -- an instruction
   * that describes an action should be the action -- and this closes rather than
   * sitting underneath for the reason given there.
   */
  const sendOne = useCallback(() => {
    closeModal?.();
    void (async () => {
      // Started before the dialog opens, the way `FirmwarePanel` does it: the
      // errand is already decided, so making somebody press Start receiving is
      // a step that answers nothing. It is also what points the server at the
      // backups folder -- without it the dialog started on the ROM inbox and
      // said files would land there, while `take_delivery` moved them the
      // moment they arrived.
      try {
        const result = await startFileServer(backupDir);
        if (!result.ok) {
          toaster.toast({
            title: "Could not start receiving",
            body: result.error ?? "You can try again from the dialog.",
          });
        }
      } catch (startError) {
        logError("could not start the file server for a backup", startError);
      }
      openModal(
        <TransferModal
          purpose="backup"
          expecting={[
            {
              label: "DeckyEmu save backup",
              expects: "The .zip made by Back up save data, sent from wherever you kept it.",
            },
          ]}
        />,
      );
    })();
  }, [closeModal, backupDir]);

  const ready = Boolean(chosen) && contents !== null;

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/* Scoped to a class, and a modal renders outside whichever panel
          opened it -- so without this the trash button is grey. */}
      <style>{DANGER_CSS}</style>
      <div style={{ fontSize: "18px", fontWeight: 600, marginBottom: "8px" }}>
        Restore save data
      </div>

      {/* Sized and centred, as every other dialog here sizes it. Left bare it
          takes Steam's own default, which fills the dialog -- and this one now
          shows it more often than it used to, because a storage is asked what
          it holds. */}
      {files === null && (
        <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
          <Spinner style={{ height: "32px" }} />
        </div>
      )}

      {error && <div style={{ color: "#e35d5d", fontSize: "13px" }}>{error}</div>}

      {files?.length === 0 && accounts.length === 0 && (
        <Field
          label="Nothing waiting"
          description="A backup is the .zip made by Back up save data. Send one with the button below and it appears here."
        />
      )}

      {/* Which backup, when there is a choice -- more than one file on the
          Deck, or a storage signed into. A lone file with nowhere else to read
          from is opened for you, so this does not appear. */}
      {files !== null && !ready && (files.length > 1 || accounts.length > 0)
        && files.map((file) => (
        <Field
          key={file.path}
          label={<FileName name={file.name} />}
          description={humanSize(file.bytes)}
          childrenContainerWidth="min"
        >
          <DialogButton
            onClick={() => void open(file)}
            style={ICON_BUTTON_WIDE}
          >
            Choose
          </DialogButton>
        </Field>
      ))}

      {/* The storages signed into, listed with the files rather than behind a
          tab: from here they are the same thing -- somewhere a backup is. Shown
          whatever else is on the Deck, and shown while one file is already open
          only when nothing has been picked yet. */}
      {!ready && accounts.map((one) => (
        <Focusable key={one.name}>
          <Field
            label={one.label || one.kind || one.name}
            description="Signed in on this Deck"
            childrenContainerWidth="min"
          >
            <DialogButton onClick={() => void openCloud(one)} style={ICON_BUTTON_WIDE}>
              Choose
            </DialogButton>
          </Field>
          {/* Copying always sends this Deck's version, so it can put an older
              save over a newer one -- press it after restoring an old backup
              and that is exactly what happens. Whatever it replaced is kept,
              and this is where it is got back from. Reaching it through the
              storage provider's own website would be the second device this
              plugin exists to do without. */}
          {(replaced[one.name] ?? []).map((snapshot) => (
            <Field
              key={snapshot.stamp}
              label={`Replaced ${snapshot.label}`}
              description="What a copy to this storage overwrote"
              childrenContainerWidth="min"
            >
              <DialogButton
                onClick={() => void openCloud(one, snapshot)}
                style={ICON_BUTTON_WIDE}
              >
                Choose
              </DialogButton>
            </Field>
          ))}
        </Focusable>
      ))}

      {chosen && contents === null && !error && (
        <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
          <Spinner style={{ height: "32px" }} />
        </div>
      )}

      {ready && (
        <>
          {/* Plain text, not a `Field`. As a Field it rendered in the same grey
              block at the same size as the emulator rows under it, so it read as
              the first row of the list rather than as what the list is about. */}
          <Focusable
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              marginBottom: "14px",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "14px", fontWeight: 600 }}>
                {chosen!.kind === "file" ? (
                  <FileName name={chosen!.file.name} />
                ) : (
                  chosen!.label
                )}
              </div>
              <div style={{ fontSize: "12px", opacity: 0.7, marginTop: "3px" }}>
                {chosen!.kind === "file"
                  ? `${humanSize(chosen!.file.bytes)} - ${restoreSummary(contents!)}`
                  : restoreSummary(contents!)}
              </div>
            </div>
            {/* Restoring consumes the archive, so this is the other case: a
                backup finished with, sent by mistake, or simply the old one.
                Without it the only way to remove 75MB is to restore from it.

                An icon, in a DANGER_CLASS wrapper, exactly as the import
                dialog's rows carry theirs. Files only -- see `confirmDiscard`
                for why nothing here empties somebody's cloud storage. */}
            {chosen!.kind === "file" && (
              <div className={DANGER_CLASS} style={{ flex: "none" }}>
                <DialogButton
                  disabled={working}
                  onClick={() => confirmDiscard()}
                  style={ICON_BUTTON}
                >
                  <FaTrash />
                </DialogButton>
              </div>
            )}
          </Focusable>
          {/* One row per emulator, laid out as the import dialog lays out its
              files -- inside a scroller, because `ModalRoot` has none of its
              own. Measured on the device: with no container the rows simply run
              off the bottom of the screen and the buttons never render. Import
              never shows that because it only ever holds a file or two.

              Sized to about three rows. A row here is ~105px measured on
              the device, so three is ~315px, and 38vh of the Deck's 800
              is close to it while still scaling with the window.
              */}
          <Focusable style={{ maxHeight: "38vh", overflowY: "auto" }}>
          {(contents ?? []).map((entry) => (
            // Wrapped so a controller can enter the list at all. A `Field` with
            // no interactive child is not focusable, and a scroller only scrolls
            // when focus moves into it -- so a list of plain rows cannot be
            // reached or scrolled with a gamepad, however tall the container is.
            // This is why the list read as "not scrollable" while the backup
            // dialog, whose rows are ToggleFields, scrolled fine.
            <Focusable key={entry.id} focusWithinClassName="gpfocuswithin">
              <Field
                label={entry.name}
                description={
                `${entry.files} file(s), ${humanSize(entry.bytes)}` +
                (!entry.installed
                  ? " - not installed here, so these stay in the backup"
                  : entry.present > 0
                    ? ` - ${entry.present} already on this Deck`
                      : "")
                }
              />
            </Focusable>
          ))}
          </Focusable>
        </>
      )}

      {carrying && (
        <div style={{ marginTop: "10px" }}>
          <div style={{ fontSize: "13px", opacity: 0.7, marginBottom: "4px" }}>
            {carrying.name ? `Bringing back ${carrying.name}...` : "Bringing saves back..."}
          </div>
          <ProgressBar fraction={carrying.percent / 100} />
        </div>
      )}

      {/* Three columns, shared by equal `flex` -- which is how the import dialog
          lays its row out, and the thing four rounds of `flex: 1 1 auto`,
          `minWidth` and `flexWrap` never managed: those made the buttons either
          run off the side of the screen or take a full row each. */}
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {ready ? (
          <>
            <DialogButton
              disabled={working || missingCount(contents ?? []) === 0}
              onClick={() => run(false)}
              style={{ flex: 1 }}
            >
              {working ? "Working..." : "Restore missing"}
            </DialogButton>
            <DialogButton
              disabled={working}
              onClick={() => confirmReplace()}
              style={{ flex: 1 }}
            >
              Replace saves
            </DialogButton>
          </>
        ) : (
          <DialogButton onClick={() => sendOne()} style={{ flex: 2 }}>
            Send a backup to this Deck
          </DialogButton>
        )}
        <DialogButton disabled={working} onClick={() => closeModal?.()} style={{ flex: 1 }}>
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
