import {
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  ModalRoot,
  Spinner,
} from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { FaHistory, FaTrash } from "react-icons/fa";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  cloudDescribe,
  cloudEmulators,
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
import {
  missingCount,
  missingIds,
  presentCount,
  restoreSummary,
  sourceLine,
} from "./saveBackup";
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
  | { kind: "cloud"; remote: string; label: string; stamp: string }
  /** Not a source: the list of what one storage's copies have replaced. */
  | { kind: "earlier"; remote: string; label: string };

/** What a row does when it is pressed: nothing. See the emulator list. */
const noop = () => {};

/**
 * What to call one storage on screen.
 *
 * The service, because that is what a person calls this -- the config key
 * rclone needs is the Deck's business and is never shown. Two accounts of the
 * same service are the one case where the service alone is not enough to tell
 * two rows apart, so they take a number, and only then: numbering a list of one
 * is noise about a distinction that is not being made.
 *
 * The same rule and the same wording as the setup dialog, which is where a
 * second account gets added and where these have carried numbers all along.
 * Without it here you could pick the right Dropbox to copy to and then have no
 * way to tell which one you were restoring from -- and neither Dropbox nor
 * pCloud will say who they are signed in as, so there is no address to show
 * instead: both answer `doesn't support UserInfo`.
 */
function nameOf(one: CloudRemote, all: CloudRemote[]) {
  const service = (which: CloudRemote) => which.label || which.kind || which.name;
  const mine = service(one);
  const same = all.filter((other) => service(other) === mine);
  if (same.length < 2) return mine;
  return `${mine} (${same.findIndex((other) => other.name === one.name) + 1})`;
}

export function RestoreSavesModal({ closeModal }: Props) {
  const [files, setFiles] = useState<SaveBackupFile[] | null>(null);
  const [accounts, setAccounts] = useState<CloudRemote[]>([]);
  /** Which storage saves are being copied to, of the ones signed into. */
  const [inUse, setInUse] = useState("");
  /* Per account, the states its copies replaced. Read alongside the accounts
     themselves so the chooser is drawn once rather than growing rows under
     somebody's thumb. */
  const [replaced, setReplaced] = useState<Record<string, CloudSnapshot[]>>({});
  const [chosen, setChosen] = useState<Picked | null>(null);
  /* The list to go back to, when a pick came from one. Two levels deep is as
     deep as this goes, so this is a breadcrumb rather than a stack. */
  const [cameFrom, setCameFrom] = useState<Picked | null>(null);
  /** Storages whose earlier copies have been asked for, so each is asked once. */
  const asked = useRef(new Set<string>());
  /*
   * **Which screen the answers still in the air belong to.**
   *
   * Opening a storage is one listing and then one request per emulator, and
   * they land seconds apart. Pressing Back before they do used to leave every
   * one of them still holding a `setContents`: rows for a storage nobody is
   * looking at appeared over the chooser, the outstanding count ran on under a
   * screen with no list, and opening something else raced its own answers
   * against the last screen's.
   *
   * Every screen takes a number on the way in, and every answer checks that its
   * number is still the current one before it writes anything. Going back bumps
   * it, which is what makes an abandoned screen's answers land nowhere.
   *
   * The requests themselves are already with the provider and cannot be called
   * back -- what this stops is them arriving somewhere they no longer belong.
   */
  const showing = useRef(0);

  const [contents, setContents] = useState<SaveBackupContents[] | null>(null);
  /** Emulators whose figures have not arrived yet. */
  const [pending, setPending] = useState(0);
  const [working, setWorking] = useState(false);
  /* How far through a cloud restore is. A .zip is read off local disk and is
     done before a bar could draw; coming down from a remote is wifi, and a
     dialog that says nothing for ninety seconds reads as one that has hung. */
  /* `keeping` is the first half of a replace that was asked to keep a copy:
     the saves going *up* before anything comes down. It says so, because the
     other half's words over this half's work read as the restore having started
     and then stalled. The first progress line from the copy down clears it --
     that line cannot arrive until the upload is over. */
  const [carrying, setCarrying] = useState<
    { name: string; percent: number; keeping?: boolean } | null
  >(
    null,
  );
  const [error, setError] = useState("");
  // Where a backup belongs, so the transfer server can be pointed at it.
  const [backupDir, setBackupDir] = useState("");

  /**
   * What one storage has set aside, fetched when somebody asks to see it.
   *
   * **Nothing about it happens on the way into a storage.** It was fetched
   * there so the button could carry a count, and a count is decoration: it
   * bought a number on a button and cost a request -- a second or two of
   * Dropbox -- on every open of a screen people come to for the current saves.
   * Opening a storage now asks for exactly what that screen shows.
   */
  // Closing the dialog is leaving every screen at once, so nothing still on its
  // way should write to a component that has gone. Same counter, same rule.
  useEffect(() => () => {
    showing.current += 1;
  }, []);

  const showEarlier = useCallback((from: Picked & { kind: "cloud" }) => {
    const mine = (showing.current += 1);
    setContents(null);
    setCameFrom(from);
    setChosen({ kind: "earlier", remote: from.remote, label: from.label });
    if (asked.current.has(from.remote)) return;
    asked.current.add(from.remote);
    void cloudSnapshots(from.remote)
      .then((held) => {
        if (showing.current !== mine) return;
        setReplaced((was) => ({ ...was, [from.remote]: held.snapshots ?? [] }));
      })
      .catch((error) => {
        logError("could not list earlier copies", error);
        if (showing.current !== mine) return;
        setReplaced((was) => ({ ...was, [from.remote]: [] }));
      });
  }, []);

  const open = useCallback(async (file: SaveBackupFile) => {
    const mine = (showing.current += 1);
    setError("");
    setCameFrom(null);
    setChosen({ kind: "file", file });
    setContents(null);
    try {
      const described = await describeSaveBackup(file.path);
      if (!described.ok) {
        setError(described.error ?? "That backup could not be read.");
        setChosen(null);
        return;
      }
      if (showing.current !== mine) return;
      setContents(described.sources ?? []);
    } catch (describeError) {
      logError("could not read a save backup", describeError);
      setError("That backup could not be read.");
      setChosen(null);
    }
  }, []);

  /*
   * A storage, opened in two stages.
   *
   * **The rows appear, then say what they hold.** Describing one emulator is a
   * tree walk on the storage -- 4.7 seconds against Dropbox, the same however
   * the question is put -- and the provider throttles them when they run at
   * once, so fourteen of them is eleven and a half seconds. All of it used to
   * happen behind a spinner before anything appeared. The names are one cheap
   * listing, about a second, and each row fills itself in when its own answer
   * lands: the emulator somebody came for is usually readable long before the
   * rest have finished.
   */
  const openCloud = useCallback(async (
    one: CloudRemote, snapshot?: CloudSnapshot, from?: Picked,
  ) => {
    const mine = (showing.current += 1);
    const service = nameOf(one, accounts);
    const label = snapshot ? `${service} — ${snapshot.label}` : service;
    const stamp = snapshot?.stamp ?? "";
    setError("");
    setCameFrom(from ?? null);
    setChosen({ kind: "cloud", remote: one.name, label, stamp });
    setContents(null);
    setPending(0);
    try {
      const listed = await cloudEmulators(one.name, stamp);
      if (showing.current !== mine) return;
      if (!listed.ok) {
        setError(listed.error ?? "That storage could not be read.");
        setChosen(null);
        return;
      }
      // Nothing up there is a finished answer, not an empty screen waiting.
      setContents([]);
      setPending(listed.emulators.length);
      listed.emulators.forEach((emulator) => {
        void cloudDescribe(one.name, emulator, stamp)
          .then((said) => {
            if (showing.current !== mine) return;
            if (said.row) {
              setContents((was) => [...(was ?? []), said.row!]
                .sort((a, b) => a.name.localeCompare(b.name)));
            }
          })
          .catch((describeError) =>
            logError("could not read one emulator's cloud saves", describeError),
          )
          .finally(() => {
            if (showing.current !== mine) return;
            setPending((was) => Math.max(0, was - 1));
          });
      });
    } catch (readError) {
      logError("could not read cloud saves", readError);
      if (showing.current !== mine) return;
      setError("That storage could not be read.");
      setChosen(null);
    }
  }, [accounts]);

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
    // `false`: this screen wants the list of storages, which is a local file.
    // The two figures the setup dialog shows -- the account name and the free
    // space -- are a network round trip each, and were being paid for on the
    // way into every restore.
    void cloudStatus(false)
      .catch((cloudError) => {
        logError("could not list cloud storage", cloudError);
        return null;
      })
      .then(async (cloud) => {
        if (!live) return;
        /* Kept in the order the config file has them, and sorted where it
           is drawn -- see the list itself. What numbers a repeated label is
           position in this array, so sorting here would make the number depend
           on which storage was in use. */
        signedIn = cloud?.remotes ?? [];
        setInUse(cloud?.remote ?? "");
        setAccounts(signedIn);
        decide();
        // Not asked for here. What a storage has set aside is a listing of
        // its own, and every account paid for one on the way into a screen
        // most people open to restore the current saves. It is fetched when a
        // storage is opened instead -- one account, alongside the read that is
        // happening anyway.
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
    const progress = addEventListener<
      [name: string, percent: number, phase: string, kind: string]
    >(
      "cloud_sync_progress",
      /* The third argument says which half of a keep-and-replace this line
         belongs to. Every other screen ignores it; here it is the difference
         between "your saves are going up" and "the storage's are coming down",
         which are opposite directions under one bar. The fourth says which copy
         it belongs to at all: a game closing starts one that says nothing, and
         this screen used to close itself over it, toasting "Saves restored". */
      (name, percent, phase, kind) => {
        if (kind !== "restore") return;
        setCarrying({ name, percent, keeping: phase === "keeping" });
      },
    );
    const done = addEventListener<
      [ok: boolean, error: string, names: string[], kind: string]
    >(
      "cloud_sync_done",
      (ok, failure, names, kind) => {
        if (kind !== "restore") return;
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
    (replace: boolean, keep = false) => {
      if (!chosen) return;
      setWorking(true);
      setError("");

      /*
       * Which emulators to touch.
       *
       * Restoring what is missing goes to the rows that have something missing
       * -- see `missingIds`. Replacing goes to all of them, because that is
       * what the confirmation counted before it was agreed to: it names a
       * number of files across the whole list, and quietly restoring fewer than
       * it said would be its own kind of wrong.
       */
      const scope = replace ? null : missingIds(contents ?? []);

      if (chosen.kind === "cloud") {
        setCarrying({ name: "", percent: -1, keeping: keep });
        // Only starts it; the listener above closes the dialog when it lands.
        void cloudRestore(chosen.remote, scope, replace, chosen.stamp, keep)
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

      // A list of earlier copies is not a source: nothing is restored from it
      // until one of them is chosen, which replaces this with a cloud pick.
      if (chosen.kind !== "file") {
        setWorking(false);
        return;
      }
      const file = chosen.file;
      void restoreSaveBackup(file.path, scope, replace)
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
    [chosen, contents, closeModal],
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
            : `${overwritten} save file(s) on this Deck will be overwritten. ` +
              (chosen?.kind === "cloud"
                ? "Keeping a copy first puts them in your storage under earlier copies, where you can get them back. Replacing without one cannot be undone."
                : "Whatever they hold now is gone, and there is no undo.")
        }
        {...(chosen?.kind === "cloud"
          ? {
              /* **Offered, not imposed.** Replacing is the one thing here that
                 destroys a save with nothing set aside, and it is two presses
                 from a list of storages -- so the way out is put in front of
                 whoever is about to need it. It is not made compulsory because
                 somebody restoring onto a wiped Deck has nothing worth keeping
                 and no reason to wait for it to upload.

                 The safe one is the primary button, and the one that cannot be
                 undone sits beside Cancel: the same shape Steam's own
                 three-button dialogs use, and the same order this plugin uses
                 wherever an answer should not be landed on by a thumb. */
              strOKButtonText: "Keep a copy first",
              onOK: () => run(true, true),
              strMiddleButtonText: "Replace without keeping",
              onMiddleButton: () => run(true),
            }
          : { strOKButtonText: "Restore all", onOK: () => run(true) })}
        bDestructiveWarning
      />,
    );
  }, [chosen?.kind, contents, run]);

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

  const ready = chosen !== null && chosen.kind !== "earlier" && contents !== null;
  /** Showing one storage's replaced copies rather than the sources themselves. */
  const earlier = chosen?.kind === "earlier" ? chosen : null;
  /**
   * A source is being read, which against a storage is fifteen seconds.
   *
   * The chooser goes away while it happens. It used to stay, with a spinner
   * underneath it and every Choose button still live -- so a second press
   * started a second read of a different source, and whichever answered last
   * won. A wait that leaves its own cause on screen and pressable is an
   * invitation to make it worse.
   */
  const reading = chosen !== null && !earlier && contents === null && !error;
  const choosing = !ready && !earlier && !reading;

  /** Back to whatever this was picked from: a list of copies, or the sources. */
  const goBack = () => {
    // Whatever is still on its way belongs to the screen being left.
    showing.current += 1;
    setError("");
    setContents(null);
    setPending(0);
    const to = cameFrom;
    setCameFrom(null);
    if (to?.kind === "cloud") {
      // A storage has to be read again to be shown again. Going back to the
      // chooser instead would be cheaper and wrong: it is not where this was.
      const account = accounts.find((one) => one.name === to.remote);
      if (account) {
        void openCloud(account, to.stamp ? { stamp: to.stamp } as CloudSnapshot : undefined);
        return;
      }
    }
    setChosen(to);
  };

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

      {/* **One scroller over both kinds**, sized the way every list in these
          dialogs is sized: about three rows, and the rest reached by scrolling
          rather than by running off the bottom of the screen. Files and
          storages share it because from here they are the same thing --
          somewhere a backup is -- and two scrollers over one list of sources
          would be two places to look for the same answer. */}
      {choosing && (files?.length || accounts.length > 0) ? (
      <Focusable style={{ maxHeight: "38vh", overflowY: "auto" }}>
      {/* Which backup, when there is a choice -- more than one file on the
          Deck, or a storage signed into. A lone file with nowhere else to read
          from is opened for you, so this does not appear. */}
      {files !== null && choosing && (files.length > 1 || accounts.length > 0)
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
      {/* **The one saves go to, first and said so.** It is the storage
          somebody is nearly always here for -- what a restore usually means is
          "put back what this Deck has been copying up" -- and the list gave it
          no more prominence than an account signed into once a year. The word
          is the setup dialog's word, because a storage that reads "In use"
          there and nothing here is two names for one fact. */}
      {choosing && [...accounts]
        .sort((a, b) => Number(b.name === inUse) - Number(a.name === inUse))
        .map((one) => (
        <Focusable key={one.name}>
          <Field
            label={
              <>
                {nameOf(one, accounts)}
                {one.name === inUse && (
                  <span style={{ opacity: 0.7, fontWeight: 400 }}> — In use</span>
                )}
              </>
            }
            description="Signed in on this Deck"
            childrenContainerWidth="min"
          >
            <DialogButton onClick={() => void openCloud(one)} style={ICON_BUTTON_WIDE}>
              Choose
            </DialogButton>
          </Field>
        </Focusable>
      ))}
      </Focusable>
      ) : null}

      {/* The second level, and the only one: a snapshot picked here is read
          exactly as a storage is, so everything below this point is shared. */}
      {earlier && (
        <>
          {/* Plain text and spaced away from the list, exactly as the header
              over the emulator rows is and for the same reason: as a `Field` it
              was the same grey block at the same size as the rows under it, so
              it read as the first earlier copy rather than as what they are. */}
          <div style={{ marginBottom: "14px" }}>
            <div style={{ fontSize: "14px", fontWeight: 600 }}>
              {`${earlier.label} — earlier copies`}
            </div>
            <div style={{ fontSize: "12px", opacity: 0.7, marginTop: "3px" }}>
              Each is what one copy to this storage replaced. Choosing one shows
              what it holds before anything is put back.
            </div>
          </div>
          {replaced[earlier.remote] === undefined && (
            <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
              <Spinner style={{ height: "32px" }} />
            </div>
          )}
          {replaced[earlier.remote]?.length === 0 && (
            <Field
              label="Nothing has been replaced"
              description="A copy to this storage has never had to overwrite anything, so there is nothing to go back to."
            />
          )}
          {/* Scrolled, and sized the same way the emulator list below is: about
              three rows. `KEEP` is per emulator, so a Deck with several of them
              offers far more than five here and the rows ran off the bottom of
              the screen with the buttons never rendering -- which is the exact
              thing that container was added downstairs to stop. */}
          <Focusable style={{ maxHeight: "38vh", overflowY: "auto" }}>
          {(replaced[earlier.remote] ?? []).map((snapshot) => (
            <Field
              key={snapshot.stamp}
              label={snapshot.label}
              // No description: it was the same sentence on every row, and the
              // header above the list says it once for all of them. The date is
              // what tells one of these from another.
              childrenContainerWidth="min"
            >
              <DialogButton
                onClick={() => {
                  const account = accounts.find((one) => one.name === earlier.remote);
                  // Back from one of these goes to this list, and back from
                  // this list goes to the storage it belongs to -- which is
                  // where the way in is.
                  if (account) void openCloud(account, snapshot, earlier);
                }}
                style={ICON_BUTTON_WIDE}
              >
                Choose
              </DialogButton>
            </Field>
          ))}
          </Focusable>
        </>
      )}

      {reading && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "10px",
            padding: "24px",
          }}
        >
          <Spinner style={{ height: "32px" }} />
          {/* Named, because reading a storage is fifteen seconds and a bare
              spinner for that long says only that something is stuck. */}
          <div style={{ fontSize: "13px", opacity: 0.7 }}>
            Reading {chosen!.kind === "cloud" ? chosen!.label : "the backup"}...
          </div>
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
                {/* The tally is not the tally until every row has answered,
                    and half of one reads as a smaller storage rather than an
                    unfinished sentence. */}
                {chosen!.kind === "file" ? (
                  `${humanSize(chosen!.file.bytes)} - ${restoreSummary(contents!)}`
                ) : pending > 0 ? (
                  // The count belongs on the line that is already saying this is
                  // not finished. Under the list it was a second sentence about
                  // the same thing, in the space the rows and the buttons are
                  // fighting over.
                  <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                    <Spinner style={{ height: "12px" }} />
                    {`Reading what it holds - ${pending} to go`}
                  </span>
                ) : (
                  restoreSummary(contents!, "storage")
                )}
              </div>
            </div>
            {/* **A corner, not a row.** What a storage set aside is a way out
                of a mistake, not one of the things it holds -- as a full-width
                row at the bottom of the list it read as another emulator. The
                count is the whole label: five means there is something to go
                back to, and nothing means the button is not there at all. */}
            {chosen!.kind === "cloud" && !chosen!.stamp && (
              <DialogButton
                disabled={working}
                onClick={() =>
                  showEarlier(chosen as Picked & { kind: "cloud" })
                }
                style={{ ...ICON_BUTTON, flex: "none" }}
              >
                <FaHistory />
              </DialogButton>
            )}

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
          {(contents ?? []).map((entry) => {
            const said = sourceLine(entry, humanSize(entry.bytes));
            return (
              // Wrapped so a controller can enter the list at all. A `Field`
              // with no interactive child is not focusable, and a scroller only
              // scrolls when focus moves into it -- so a list of plain rows
              // cannot be reached or scrolled with a gamepad, however tall the
              // container is. This is why the list read as "not scrollable"
              // while the backup dialog, whose rows are ToggleFields, scrolled
              // fine.
              //
              // **The wrapper is not enough on its own.** Steam passes over a
              // `Focusable` that has no `onActivate`, no `onClick` and no
              // focusable child, so wrapping the rows changed nothing: the list
              // still moved under a finger and not at all under the sticks.
              // There is nothing to do to an emulator here -- the row is a
              // statement of what the storage holds -- so activating one does
              // nothing on purpose. The handler is what makes the row reachable.
              <Focusable
                key={entry.id}
                focusWithinClassName="gpfocuswithin"
                onActivate={noop}
              >
                {/* Dimmed when there is nothing to restore from it.
                    Emphasis by contrast rather than by decoration: what a
                    person is looking for here is the row that will change, and
                    on a list of thirteen emulators with one file missing it was
                    the same weight as the twelve that would do nothing. No icon
                    -- the difference is a fact about the row, and the row says
                    it in words directly underneath. */}
                <div style={{ opacity: said.missing > 0 || !entry.installed ? 1 : 0.5 }}>
                  <Field label={entry.name} description={said.line} />
                </div>
              </Focusable>
            );
          })}
          </Focusable>

        </>
      )}

      {carrying && (
        <div style={{ marginTop: "10px" }}>
          {/* **A bar once there is something to measure, and until then a
              spinner beside the words.** Before the first stats line lands
              there is no fraction to draw, and a bar sitting at zero reads as
              one that has stuck. The spinner belongs on the same line as the
              sentence it is about -- centred on a row of its own it read as a
              second thing happening, and it is the same thing the row above
              said, still happening. Same shape as the outstanding-rows line
              further up this dialog. */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              fontSize: "13px",
              opacity: 0.7,
              marginBottom: carrying.percent < 0 ? 0 : "4px",
            }}
          >
            {carrying.percent < 0 && <Spinner style={{ height: "14px" }} />}
            {carrying.keeping
              ? carrying.name
                ? `Keeping a copy of ${carrying.name}...`
                : "Keeping a copy of your saves first..."
              : carrying.name
                ? `Bringing back ${carrying.name}...`
                : "Bringing saves back..."}
          </div>
          {carrying.percent < 0 ? null : (
            <ProgressBar fraction={carrying.percent / 100} />
          )}
        </div>
      )}

      {/* Three columns, shared by equal `flex` -- which is how the import dialog
          lays its row out, and the thing four rounds of `flex: 1 1 auto`,
          `minWidth` and `flexWrap` never managed: those made the buttons either
          run off the side of the screen or take a full row each. */}
      <Focusable style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        {/* **Back, not just Close.** Picking a source used to be one-way: the
            only button out closed the dialog, so looking at what a storage
            holds and then wanting the one next to it meant starting again --
            fifteen seconds of listing included. It leads the row because it is
            the one that undoes the last thing pressed. */}
        {(ready || earlier) && (
          <DialogButton
            disabled={working}
            onClick={goBack}
            // An equal share, like everything else in this row. `flex: "none"`
            // was tried and is what the docstring above is about: a
            // DialogButton left to size itself claims Steam's own default
            // width, which pushed this row wider than the screen and took the
            // dialog off both edges with it. Measured on the device, twice --
            // the backup dialog's Cancel button did the same thing.
            style={{ flex: 1, minWidth: "auto" }}
          >
            Back
          </DialogButton>
        )}
        {ready ? (
          <>
            <DialogButton
              // While rows are still arriving the count is not yet the answer,
              // and a restore is about all of them.
              disabled={working || pending > 0 || missingCount(contents ?? []) === 0}
              onClick={() => run(false)}
              style={{ flex: 1, minWidth: "auto" }}
            >
              {/* **The pair differs in one thing, so the names differ in one
                  thing.** Against "Replace saves" this read as a different kind
                  of operation rather than the same one at a different scope --
                  the same fault the backup dialog's buttons had. Both restore;
                  one restores what is absent and the other restores the lot.
                  The word that matters, that this overwrites and cannot be
                  undone, belongs on the confirmation rather than on a button
                  somebody presses to find out what it means. */}
              {working ? "Working..." : "Restore missing"}
            </DialogButton>
            <DialogButton
              disabled={working || pending > 0}
              onClick={() => confirmReplace()}
              style={{ flex: 1, minWidth: "auto" }}
            >
              Restore all
            </DialogButton>
          </>
        ) : (
          // Not while looking at a list of earlier copies: sending a backup is
          // about getting a new one here, which is not what that screen is for.
          choosing && (
            <DialogButton
              onClick={() => sendOne()}
              style={{ flex: 2, minWidth: "auto" }}
            >
              Send a backup to this Deck
            </DialogButton>
          )
        )}
        {/* Three at most, which is what fits: with Back present a fourth wrapped
            "Restore missing" onto two lines and ran the row off the edge. B
            dismisses the dialog, and the footer says so, so the explicit Close
            is the one that can go. */}
        {!ready && (
          <DialogButton
            disabled={working}
            onClick={() => closeModal?.()}
            style={{ flex: 1, minWidth: "auto" }}
          >
            Close
          </DialogButton>
        )}
      </Focusable>
    </ModalRoot>
  );
}
