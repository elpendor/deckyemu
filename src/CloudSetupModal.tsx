import { ConfirmModal, DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { FaTrash } from "react-icons/fa";

import {
  chooseCloudRemote,
  cloudStatus,
  endCloudSetup,
  forgetCloudRemote,
  setSettings,
  startCloudSetup,
  type CloudRemote,
  type CloudState,
  type FileServerStatus,
} from "./backend";
import { DANGER_CLASS, DANGER_CSS, DANGER_TEXT } from "./danger";
import { COLUMN, MUTED } from "./dialogStyle";
import { HandoffCode } from "./HandoffCode";
import { ICON_BUTTON, ICON_BUTTON_WIDE } from "./iconButton";
import { logError } from "./logError";
import { openModal } from "./modalStack";
import { ScrollList } from "./ScrollList";

/** Whatever happens next happens on the phone, so this end has to watch for it. */
const POLL_MS = 2000;

/**
 * The account list is the only thing here that grows, so it scrolls rather than
 * the dialog -- the same reasoning, and the same numbers, as the transfer's
 * received list. A QR code pushed off the bottom of the screen is the one
 * failure a glance-and-scan dialog cannot afford.
 *
 * **Three rows, and the same three as everywhere else.** The backup dialog's
 * list, the restore dialog's two, and this one are all the same shape now: a
 * bounded box holding about three rows with the rest scrolled. It was flexed
 * for a while, which was the right answer while the sign-in code block shared
 * the screen with it -- that is a screen of its own since, so the number can go
 * back to being the number every other list here uses.
 *
 * `ScrollList` carries the rest: the column, the scrollbar, and the
 * `minHeight: 0` a flex child needs to shrink below its content at all.
 */
const ACCOUNTS = {
  gap: "6px",
  maxHeight: "38vh",
};

/**
 * The dialog's body, bounded by the screen.
 *
 * `ModalRoot` does not scroll its own content and Steam's wrapper around it is
 * about 84% of the viewport, so this is that bound said in a way the layout can
 * use: a column that never exceeds it, with one part inside allowed to flex.
 */
const BODY = {
  display: "flex",
  flexDirection: "column" as const,
  gap: "8px",
  maxHeight: "76vh",
  minHeight: 0,
};

/**
 * Setting up where save data gets copied to, from a device with a keyboard.
 *
 * The same crossing the transfer flow and the diagnostic report already make --
 * a QR code for a camera, a short address and six digits for anything else --
 * because it is the same problem yet again, and it is drawn by the same
 * component they use. What this one collects is a sign-in with a storage
 * provider, or an address and a password, and doing either on the Deck's
 * on-screen keyboard is the experience that put ROM transfers on a phone to
 * begin with.
 *
 * Opening this is also what switches cloud saves on, which is what fetches
 * rclone. Nobody is asked to install a binary to unlock a setting: the feature
 * being wanted is the request for the tool it needs.
 *
 * Signing in is the web half. Everything after it -- which account saves go to,
 * and which ones to be rid of -- is the Deck half, because choosing between
 * accounts already set up needs neither a browser nor a keyboard, and it is a
 * decision about this device.
 *
 * **What is not here is the settings.** Whether a game closing copies on its
 * own, and when it last did, are a switch and a status, and this is a dialog
 * somebody opens for a minute to sign in and then dismisses. A setting behind a
 * modal is a setting nobody finds twice, so it lives on the panel row instead --
 * the same reasoning `TransferModal` gives for being a modal at all.
 */

/** Free space, rounded the way a person would say it. */
/**
 * When saves last went up, in as few words as the row has space for.
 *
 * Short on purpose: this sits beside an account and a free-space figure on a
 * 854px panel, so "Synced 12 min ago" is the whole sentence. Nothing at all
 * before the first copy, rather than "never" -- a storage signed into a minute
 * ago has not failed at anything.
 */
function syncedAgo(at?: number): string {
  if (!at) return "";
  const mins = Math.floor((Date.now() / 1000 - at) / 60);
  if (mins < 1) return "Synced just now";
  if (mins < 60) return `Synced ${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `Synced ${hours}h ago`;
  return `Synced ${Math.floor(hours / 24)}d ago`;
}

function gigabytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

interface Props {
  closeModal?: () => void;
}

export function CloudSetupModal({ closeModal }: Props) {
  const [status, setStatus] = useState<Partial<FileServerStatus> | null>(null);
  const [error, setError] = useState("");
  const [cloud, setCloud] = useState<CloudState | null>(null);
  /* The storage being switched to, while that is happening. Two jobs: the row
     says it was pressed, and the poll below stands off -- a status read that
     started before the press lands after it and puts "In use" back on the
     storage somebody has just moved away from, which reads as the press having
     done nothing. */
  const [switching, setSwitching] = useState("");
  /* Whether the sign-in half is on screen. See where it is used: with storages
     already set up it is the thing somebody came here for least often, and it
     is half the height of the dialog. */
  const [adding, setAdding] = useState(false);
  const picking = useRef(false);
  // Whether there is a form of ours to withdraw on the way out. A ref, not
  // state: the cleanup below runs after the last render, where state would be
  // whatever it was when the effect was created. Same reason as ReportModal.
  const offered = useRef(false);

  /*
   * **The form is served for exactly as long as its screen is up.**
   *
   * This used to start with the dialog and stop with it, which was right while
   * the dialog was one screen. It is two now, and the difference showed: a
   * sign-in that finished brought the Deck back to the list by itself and left
   * the page being served behind it -- a form that takes a provider password,
   * still answering, on a screen nobody is looking at and did not ask for
   * twice. Tied to the screen instead, it goes up on "Add another" and comes
   * down on Back, on the sign-in landing, and on the way out of the dialog.
   *
   * `cloud !== null` waits for the storages to be known. Without it every open
   * of this dialog would start a form for the split second before the list
   * arrives and says one was not wanted.
   */
  const remotes = cloud?.remotes ?? [];
  const showingCode = cloud !== null && (adding || remotes.length === 0);

  useEffect(() => {
    let live = true;

    if (!showingCode) {
      if (offered.current) {
        offered.current = false;
        setStatus(null);
        void endCloudSetup().catch((endError) =>
          logError("could not stop the cloud setup page", endError),
        );
      }
      return () => {
        live = false;
      };
    }

    // Switched on first, because that is what fetches rclone, and the setup
    // cannot run without it. The backend answers "still downloading" rather
    // than failing obscurely if this is the first time.
    void setSettings({ cloud_saves: true })
      .then(() => startCloudSetup())
      .then((result) => {
        if (!result.ok) {
          if (live) setError(result.error ?? "The setup page could not be opened.");
          return;
        }
        // Set even if this modal has since closed, or a form offered by a call
        // that landed late would be left being served with nothing to withdraw
        // it.
        offered.current = true;
        if (live) setStatus(result);
      })
      .catch((startError) => {
        logError("could not open cloud setup", startError);
        if (live) setError("The setup page could not be opened.");
      });

    return () => {
      live = false;
    };
  }, [showingCode]);

  // Every way out, not just the Done button: B and the X dismiss a modal too,
  // and a form that accepts a password must not outlive the dialog that offered
  // it by any of the three. Its own effect, because the one above now runs
  // whenever the screen changes and this must run only on the way out.
  useEffect(
    () => () => {
      if (!offered.current) return;
      void endCloudSetup().catch((endError) =>
        logError("could not stop the cloud setup page", endError),
      );
    },
    [],
  );

  // The work happens on the other device, so this end learns it is done by
  // asking. Without it the Deck said nothing at all while the phone said the
  // storage was ready, which is indistinguishable from a setup that failed.
  //
  // **The cheap status, twice a second-and-a-half.** What this watches for is a
  // storage appearing, which is a line in a local config file. The full status
  // asks the provider how much room is left -- 1.3 seconds against Box,
  // measured -- and asking that every two seconds for as long as somebody
  // leaves the dialog open is a poll over their wifi to redraw a subtitle that
  // does not change. The figures come from the effect below instead, once per
  // storage, and are carried across ticks here.
  useEffect(() => {
    let live = true;
    const tick = () =>
      void cloudStatus(false)
        .then((result) => {
          if (!live || picking.current) return;
          setCloud((was) =>
            was && was.remote === result.remote
              ? { ...result, account: was.account, space: was.space }
              : result,
          );
        })
        .catch((pollError) => logError("could not read cloud status", pollError));
    tick();
    const timer = window.setInterval(tick, POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  /*
   * Who the storage says you are, and how much room is left.
   *
   * Once per storage rather than on every tick, because that is how often the
   * answer changes -- and the request is the slow one. Read here rather than
   * left to the poll so that switching storages still fills the row in: the
   * numbers are also the proof that the sign-in still works, which is the whole
   * reason they are on screen.
   */
  const answered = useRef("");
  const tries = useRef({ remote: "", count: 0 });
  const [describing, setDescribing] = useState("");
  useEffect(() => {
    const remote = cloud?.remote ?? "";
    if (!remote || answered.current === remote) return;
    if (tries.current.remote !== remote) tries.current = { remote, count: 0 };
    // **Three, and then it stops asking.** A read that fails is worth trying
    // again -- a storage signed into a second ago may not answer the first
    // time -- but a read that fails forever must not be retried forever, and
    // the poll below would carry it round every two seconds.
    if (tries.current.count >= 3) return;
    tries.current.count += 1;
    const first = tries.current.count === 1;

    let live = true;
    // Only the first attempt says so. Saying it again on each retry is what
    // made the row flash between "Reading..." and nothing.
    if (first) setDescribing(remote);
    void cloudStatus(true)
      .then((full) => {
        if (!live || full.remote !== remote) return;
        // **An answer is an answer, even an empty one.** Plain WebDAV publishes
        // no quota -- `rclone about` on one returns `{}`, measured -- so a
        // storage with no figures to give is not a storage that failed to give
        // them, and asking it again gets the same nothing. What this exists to
        // retry is a request that did not come back at all, below.
        answered.current = remote;
        setCloud((was) =>
          was && was.remote === remote
            ? { ...was, account: full.account, space: full.space }
            : was,
        );
      })
      .catch((readError) => logError("could not read the storage's figures", readError))
      .finally(() => {
        if (live) setDescribing("");
      });
    return () => {
      live = false;
    };
    // The whole status, not just which storage it names: a tick that changes
    // nothing is what carries a retry back round.
  }, [cloud]);

  const url = status?.url ?? "";

  /*
   * What to call each row.
   *
   * The service, because that is what a person calls this -- the config key
   * rclone needs is the Deck's business and is never shown. Two accounts of the
   * same service are the one case where the service alone is not enough to tell
   * two rows apart, so they take a number, and only then: numbering a list of
   * one is noise about a distinction that is not being made.
   */
  const seen = new Map<string, number>();
  const numbered = remotes.map((one) => {
    const label = one.label || one.kind || one.name;
    const nth = (seen.get(label) ?? 0) + 1;
    seen.set(label, nth);
    return { one, label, nth };
  });
  const repeated = new Set(
    numbered.filter(({ label }) => (seen.get(label) ?? 0) > 1).map(({ label }) => label),
  );
  /*
   * The one saves go to, first -- as the restore dialog lists them, because it
   * is the same list answering the same question about the same storages.
   *
   * Numbered before it is sorted, and that order is the one the config file
   * keeps. Numbering the sorted list instead would make "Dropbox (1)" mean
   * whichever Dropbox happens to be in use, so choosing the second one would
   * renumber both -- a name that moves is worse than no number at all.
   */
  const named = [...numbered].sort(
    (a, b) =>
      Number(b.one.name === cloud?.remote) - Number(a.one.name === cloud?.remote),
  );

  /*
   * **The sign-in finishes on the phone, so the Deck has to notice.**
   *
   * Everything about this crossing happens on the other device, and until now
   * the only thing that changed here was a row appearing on a screen somebody
   * had to press Back to see. The poll above already learns about the new
   * storage within a couple of seconds; this is what it is for. Coming back by
   * itself is the answer to "did that work?" -- and the storage just signed
   * into is the one saves go to, so the row it lands on says "In use".
   */
  const counted = useRef<number | null>(null);
  useEffect(() => {
    const now = remotes.length;
    const was = counted.current;
    counted.current = now;
    if (was !== null && now > was && adding) setAdding(false);
  }, [remotes.length, adding]);

  /**
   * Ask before removing an account.
   *
   * The same friction a discarded transfer gets, for a better reason: this
   * deletes a stored credential, and getting it back means finding the phone or
   * the PC again. Signing in is not hard, but it is not something to be nudged
   * into by a thumb landing on the wrong row.
   */
  /** What saves would go to if `one` were signed out of, named for a person. */
  const nextInLine = (one: CloudRemote) => {
    const left = named.filter(({ one: other }) => other.name !== one.name);
    if (left.length === 0) return "";
    const first = left[0];
    return repeated.has(first.label) ? `${first.label} (${first.nth})` : first.label;
  };

  const confirmForget = (one: CloudRemote) =>
    openModal(
      <ConfirmModal
        strTitle="Sign out of this storage?"
        strOKButtonText="Sign out"
        bDestructiveWarning
        onOK={() =>
          void forgetCloudRemote(one.name)
            .then(setCloud)
            .catch((dropError) => logError("could not remove storage", dropError))
        }
        strDescription={
          <div style={DANGER_TEXT}>
            The Deck forgets how to reach {one.label || one.kind}. Nothing already
            copied there is touched, and coming back means signing in again from a
            phone or a PC.
            {/* **What saves do afterwards, said before it happens.** Signing out
                of the one in use is the only case here that changes where
                things go, and the row does not say which one that is once it is
                gone. */}
            {one.name === cloud?.remote &&
              (nextInLine(one)
                ? ` Saves go to ${nextInLine(one)} after this.`
                : " Nothing will be copied anywhere until you sign in to something.")}
          </div>
        }
      />,
    );

  return (
    /*
     * `bAllowFullSize` because this is a list modal, the same reason
     * `SaveBackupModal` sets it: without it the dialog is a smaller box than the
     * content needs, and the buttons at the bottom are simply cut off.
     */
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      {/* Injected here as well as in the panels: the rule is scoped to a class,
          not global, and a modal renders outside whichever panel opened it. */}
      <style>{DANGER_CSS}</style>

      {/* Matches the button that opened it, which changes wording once
          something is signed in. The transfer dialog learned this one the hard
          way: arriving under a heading that is not the button you pressed reads
          as having gone somewhere else. */}
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        {remotes.length > 0 ? "Cloud storage" : "Set up cloud storage"}
      </div>
      {/* About whatever the dialog is currently for. Two lines of setup
          instructions over a list of four storages was answering a question
          nobody with four storages is asking. */}
      <div style={{ ...MUTED, marginBottom: "12px" }}>
        {remotes.length > 0 && !adding
          ? "Saves go to the one marked in use. Switch between them, sign out, or add another."
          : "Open this on a phone or PC and sign in to where saves should go. The storage is yours — the Deck only keeps how to reach it."}
      </div>

      <Focusable style={BODY}>
        {error && <div style={{ color: "#e35d5d", fontSize: "13px" }}>{error}</div>}

        {/* Only while the code itself is being got ready. It used to mean "no
            url yet", which was the same thing while the dialog was one screen
            and stopped being it the moment the sign-in half became something
            asked for: on the list there is no page to wait for, so this sat
            spinning above the storages over nothing. */}
        {!error && showingCode && !url && (
          <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
            <Spinner style={{ height: "32px" }} />
          </div>
        )}

        {/*
          * **Not drawn until it is wanted.**
          *
          * The code block is a square QR, an address and six digits: measured on
          * the device it is 206 of the dialog's 452 usable pixels, and stacked
          * over a list of four storages the content came to 575 -- the last row
          * and Done were off the screen. Shrinking it does not get there (41px
          * of the 123 needed, because the address column sets that block's
          * height) and putting the two side by side made both halves cramped
          * enough to be worse than the overflow.
          *
          * So it waits for the press. With nothing signed in there is nothing
          * else here and it shows immediately, which is the first run; with
          * storages already set up, switching and signing out are what the
          * dialog is for, and adding another is one press away.
          */}
        {url && (adding || remotes.length === 0) && (
          <HandoffCode
            url={url}
            shortUrl={status?.short_url}
            pin={status?.pin}
            pinLocked={status?.pin_locked}
          >
            {/* Named as the page labels them, so what is on this screen and
                what is on the other one are the same words. */}
            then pick a service and press "Sign in".
          </HandoffCode>
        )}

        {/* The screen is doing something while nothing on it moves: it is
            asking, twice a second-and-a-half, whether the other device has
            finished. Said here because a dialog that will act on its own has to
            admit that it is waiting, or the wait reads as a dead end. */}
        {url && (adding || remotes.length === 0) && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              fontSize: "13px",
              opacity: 0.7,
              flex: "none",
            }}
          >
            <Spinner style={{ height: "14px" }} />
            Waiting for the sign-in to finish. This comes back on its own.
          </div>
        )}

        {/* Every storage set up on this Deck, and which one saves go to.
            The transfer's received list decides the shape: what it is on the
            left, the action beside it, the destructive one last -- gamepad
            focus enters a row from the left, so the first control is the one a
            thumb lands on without aiming. */}
        {remotes.length > 0 && !adding && (
          // Flexed, so the list inside it is what absorbs the leftover height.
          <div style={{ ...COLUMN, gap: "6px", flex: "1 1 auto", minHeight: 0 }}>
            <ScrollList style={ACCOUNTS}>
              {named.map(({ one, label, nth }) => {
                const chosen = one.name === cloud?.remote;
                // Free space only where it is known, and it is known for the
                // chosen one because reading it is how the Deck checks the
                // sign-in still works. Asking every remote every two seconds
                // to fill in a subtitle is a poll over somebody's wifi.
                // Said rather than left blank. Asking a provider how much room
                // is left is 1.3 seconds against Box, and a row that goes quiet
                // for that long after being pressed reads as one that did not
                // take. It replaces the line it is waiting for, so nothing
                // moves when the figures arrive.
                // The account on every row, not just this one: two accounts
                // of a service are why rows carry a number, and a number alone
                // never said which was which. Blank for a service that will
                // not name itself.
                //
                // "Synced" only on the row in use, because it is the only one
                // anything is copied to, and it is the question this screen is
                // opened with -- free space says the account exists, not that
                // saves are arriving.
                const under =
                  chosen && describing === one.name && cloud?.space?.free === undefined
                    ? ["Reading how much room is left..."]
                    : [
                        one.account || "",
                        chosen ? syncedAgo(cloud?.last_sync) : "",
                        chosen && cloud?.space?.free !== undefined
                          ? `${gigabytes(cloud.space.free)} free`
                          : "",
                      ].filter(Boolean);
                return (
                  <Focusable
                    key={one.name}
                    style={{ display: "flex", alignItems: "center", gap: "10px" }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div>
                        {label}
                        {repeated.has(label) ? ` (${nth})` : ""}
                        {/* Beside the name rather than out at the right edge,
                            where it read as a control and sat where every other
                            list in the plugin puts a button. It is a fact about
                            this row, so it belongs to the row's name. */}
                        {chosen && <span style={MUTED}> — In use</span>}
                      </div>
                      {under.length > 0 && <div style={MUTED}>{under.join(" · ")}</div>}
                    </div>

                    {/* Nothing to press on the row that is already chosen: the
                        tick has said so, and a button that does nothing is
                        worse than no button. */}
                    {!chosen && (
                      <DialogButton
                        disabled={Boolean(switching)}
                        onClick={() => {
                          picking.current = true;
                          setSwitching(one.name);
                          void chooseCloudRemote(one.name)
                            .then(setCloud)
                            .catch((pickError) =>
                              logError("could not choose storage", pickError),
                            )
                            .finally(() => {
                              picking.current = false;
                              setSwitching("");
                            });
                        }}
                        style={ICON_BUTTON_WIDE}
                      >
                        {switching === one.name ? "Switching..." : "Use this"}
                      </DialogButton>
                    )}

                    <div className={DANGER_CLASS}>
                      <DialogButton onClick={() => confirmForget(one)} style={ICON_BUTTON}>
                        <FaTrash />
                      </DialogButton>
                    </div>
                  </Focusable>
                );
              })}
            </ScrollList>
          </div>
        )}

        {url && !cloud?.remote && (
          <div style={MUTED}>
            Nothing is copied anywhere yet. The page checks that the storage answers,
            and backing up stays something you ask for here.
          </div>
        )}

        {/* `flex: none` so the list above gives up its height and this never
            does: a button pushed off the bottom of the screen is the failure
            this whole column is shaped to prevent. */}
        {/*
          * **One or the other, never both.** Signing in and choosing between
          * what is already signed in are two jobs, and stacked they are 575px
          * of content in the 452 this dialog gets -- measured with four
          * storages, with the last row and Done off the bottom of the screen.
          * Neither half is the one to cut, and side by side both are cramped,
          * so the dialog shows one at a time: 399px for the list, about 336 for
          * the code. Nothing scrolls in either, which is the point.
          */}
        {/*
          * **Every button this screen has, in one row.** Measured on the
          * device: Steam's own dialog chrome costs about 100px, so a 452px box
          * holds around 352 of ours -- and a second full-width row for one
          * button was 48 of them. One row is what took the list from scrolling
          * to fitting, and it is what the rest of these dialogs do anyway.
          */}
        <Focusable style={{ display: "flex", gap: "8px", flex: "none" }}>
          {remotes.length > 0 && !adding && (
            <DialogButton
              onClick={() => setAdding(true)}
              style={{ flex: 1, minWidth: "auto" }}
            >
              Add another
            </DialogButton>
          )}
          {adding && remotes.length > 0 && (
            <DialogButton
              onClick={() => setAdding(false)}
              style={{ flex: 1, minWidth: "auto" }}
            >
              Back
            </DialogButton>
          )}
          {/* Just closes. Withdrawing the form is the effect's cleanup above, so
              B and the X do it too. */}
          <DialogButton onClick={() => closeModal?.()} style={{ flex: 1, minWidth: "auto" }}>
            Done
          </DialogButton>
        </Focusable>
      </Focusable>
    </ModalRoot>
  );
}
