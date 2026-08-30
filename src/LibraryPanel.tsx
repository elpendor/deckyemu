import {
  ToggleField,
  ButtonItem,
  ConfirmModal,
  PanelSection,
  PanelSectionRow,
} from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  clearLibrary,
  getSettings,
  listAdded,
  setSettings,
  type AddedGame,
} from "./backend";
import { removeShortcut } from "./steam";
import { sweepEmptyCollections, unfileGames } from "./collections";
import { AddedGamesModal } from "./AddedGamesModal";
import { clearWarning, shouldConfirmClear } from "./clearWarning";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { InstallProgress } from "./InstallProgress";
import { OrphanModal } from "./OrphanModal";
import { SaveBackupModal } from "./SaveBackupModal";
import { RestoreSavesModal } from "./RestoreSavesModal";
import { callWithRetry } from "./timeout";
import { humanSize } from "./TransferModal";
import { logError } from "./logError";
import { openModal } from "./modalStack";

interface Props {
  onRefresh: () => void;
}

/**
 * How much of the bar the backend's own work is worth.
 *
 * Deleting the files is where the minutes go -- an unpacked PS3 game is an
 * rmtree over tens of gigabytes -- while emptying the collections and removing
 * the shortcuts is a handful of Steam calls. A bar split evenly would crawl to
 * halfway and then jump.
 */
const BACKEND_SHARE = 0.9;

/**
 * What to do about games already in Steam: find the ones that drifted out of
 * sync, or take every one of them back out.
 *
 * Nothing here is a setting, which is why it is no longer called one -- both
 * controls act on the library immediately.
 */
export function LibraryPanel({ onRefresh }: Props) {
  const [clearing, setClearing] = useState(false);
  /*
   * What the clear is doing right now, on one 0-100 scale that spans both
   * halves of it.
   *
   * The backend reports its own progress and knows nothing of the Steam side,
   * so its number is folded into the first `BACKEND_SHARE` here rather than
   * shown raw -- otherwise the bar would fill, then sit at 100% while the
   * collections and shortcuts are still going.
   */
  const [progress, setProgress] = useState({ text: "", percent: 0 });
  // null while unread and after a failed read, which is not the same as 0 --
  // nothing here may treat "could not ask" as "there is nothing there".
  const [games, setGames] = useState<AddedGame[] | null>(null);
  /**
   * The added-games layout, or null until the setting has been read.
   *
   * Null disables the switch rather than showing it off, so it cannot be
   * flipped in the moment before its real value lands -- which would write the
   * default back over whatever was already stored.
   */
  const [tabs, setTabs] = useState<boolean | null>(null);

  // Bound to the component rather than started with the clear: the backend
  // emits from the moment the call lands, and a listener attached inside the
  // handler races the first few events on a large library.
  useEffect(() => {
    const onProgress = (text: string, percent: number) =>
      setProgress({
        text,
        percent: Math.round(Math.max(0, Math.min(100, percent)) * BACKEND_SHARE),
      });
    const listener = addEventListener<[text: string, percent: number]>(
      "clear_library_progress",
      onProgress,
    );
    return () => removeEventListener("clear_library_progress", listener);
  }, []);

  useEffect(() => {
    // A failure leaves the switch disabled rather than reporting anything: not
    // knowing the layout preference is a switch nobody can flip, which is a far
    // smaller problem than the two buttons below it not working.
    callWithRetry(getSettings)
      .then((settings) => setTabs(Boolean(settings.added_games_tabs)))
      .catch((error) => logError("could not read the added-games layout", error));
  }, []);

  const loadGames = useCallback(async () => {
    try {
      setGames(await callWithRetry(listAdded));
    } catch (error) {
      logError("could not list added games", error);
      setGames(null);
    }
  }, []);

  useEffect(() => {
    void loadGames();
  }, [loadGames]);

  /**
   * Undo everything this plugin has added: shortcuts, collections and launchers.
   *
   * Order matters. Collections are emptied first, while the app overviews Steam
   * needs to identify those apps still exist -- removing the shortcuts first would
   * leave the collections behind holding nothing. Each collection is only deleted
   * once it is empty, so anything the user dragged in by hand survives.
   *
   * The games go too — the ROMs this plugin filed and the games it unpacked into
   * emulators — for the same reason removing one game deletes it. A ROM the user
   * keeps somewhere of their own was never ours to move and is left alone.
   */
  const clearEverything = useCallback(async () => {
    setClearing(true);
    // Named before the first event arrives. The backend has to read the
    // registry and walk the first game before it can say whose files it is
    // deleting, and an empty bar in the meantime says nothing.
    setProgress({ text: "Deleting games", percent: 0 });
    try {
      const cleared = await clearLibrary();

      await unfileGames(cleared.games, (done, total) =>
        setProgress({
          text: `Emptying collections (${done + 1} of ${total})`,
          percent: Math.round(100 * BACKEND_SHARE + (5 * done) / total),
        }),
      );

      setProgress({ text: "Removing shortcuts", percent: 95 });
      for (const game of cleared.games) {
        removeShortcut(game.app_id);
      }

      // A backstop for shelves earlier sessions left standing, not the
      // mechanism for the games just removed -- see `sweepEmptyCollections`.
      // Clearing the library was the one place certain to have just made some
      // and it swept none of them.
      setProgress({ text: "Deleting empty collections", percent: 97 });
      const emptied = await sweepEmptyCollections();
      setProgress({ text: "Done", percent: 100 });

      const removed = [`${cleared.launchers_deleted} launcher(s) deleted`];
      if (emptied > 0) removed.push(`${emptied} empty collection(s) deleted`);
      if (cleared.freed) removed.push(`${humanSize(cleared.freed)} freed`);

      toaster.toast({
        title:
          cleared.games.length > 0
            ? `Removed ${cleared.games.length} game(s)`
            : "Nothing to remove",
        body:
          cleared.games.length > 0
            ? `${removed.join(", ")}.`
            : "No games were tracked by DeckyEmu.",
      });
      // The row above still shows the old count until this runs, and it sits
      // directly over the button that was just pressed.
      void loadGames();
      onRefresh();
    } catch (error) {
      logError("could not clear the library", error);
      toaster.toast({
        title: "Could not clear the library",
        body: "Nothing may have been removed. Check the plugin log.",
      });
    } finally {
      setClearing(false);
    }
  }, [onRefresh, loadGames]);

  /*
   * Counted at the moment of asking, not from whatever the tab read on mount.
   *
   * The confirmation sentence is the whole of the protection here -- there is no
   * undo and no checkbox -- so a number in it has to be the number that is about
   * to go. The list can have changed since this tab loaded: the games modal
   * above removes games, and it is the obvious thing to have just been using.
   *
   * A failed read falls back to the wording with no count rather than guessing
   * one. Vague and true beats specific and wrong on a dialog that deletes games.
   */
  const confirmClearEverything = useCallback(async () => {
    let count: number | null = null;
    try {
      const current = await callWithRetry(listAdded);
      setGames(current);
      count = current.length;
    } catch (error) {
      logError("could not count games before clearing", error);
    }

    if (!shouldConfirmClear(count)) {
      toaster.toast({
        title: "Nothing to remove",
        body: "No games are tracked by DeckyEmu.",
      });
      return;
    }

    openModal(
      <ConfirmModal
        strTitle="Remove every DeckyEmu game?"
        strDescription={clearWarning(count)}
        strOKButtonText="Remove everything"
        bDestructiveWarning
        onOK={() => void clearEverything()}
      />,
    );
  }, [clearEverything]);

  return (
    <>
      <style>{DANGER_CSS}</style>

      {/* Untitled: the sidebar already says "Library", and a PanelSection title
          that repeats its tab prints the heading twice. */}
      <PanelSection>
        {/* First, and above the two controls that act on the library, because
            this is the one that shows what they would be acting on. The count
            was only in the Quick Access panel, so the tab holding
            "remove everything" was the one place you could not see what
            everything meant.

            Rendered whether or not the count has arrived, rather than appearing
            when it does -- a row that materialises reflows the two buttons under
            it, and those buttons are the reason anyone is on this tab. */}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={games !== null && games.length === 0}
            onClick={() =>
              openModal(
                <AddedGamesModal
                  onChanged={() => {
                    void loadGames();
                    onRefresh();
                  }}
                />,
              )
            }
            description={
              games === null
                ? "Rename a game, change what runs it, replace its artwork, or remove it."
                : games.length === 0
                  ? "Games added from the Quick Access panel appear here."
                  : "Rename a game, change what runs it, replace its artwork, or remove it."
            }
          >
            {games === null
              ? "Added games"
              : games.length === 0
                ? "No games added yet"
                : `Added games (${games.length})`}
          </ButtonItem>
        </PanelSectionRow>

        {/* Directly under the button it governs, rather than in a settings
            group of its own: it changes what opening that list looks like, and
            nothing else. */}
        <PanelSectionRow>
          <ToggleField
            label="One tab per system"
            description="Added games opens with a tab for each system, paged with L1 and R1, instead of one scrolling list of headed groups. Better when a system has many games; the grouped list shows more of what you own at once."
            checked={tabs === true}
            disabled={tabs === null}
            onChange={(value) => {
              // Optimistic, and safe to be: the switch is the whole of the
              // change, so a write that fails leaves a stale toggle rather than
              // a library in a state nobody asked for. Put back on failure.
              setTabs(value);
              setSettings({ added_games_tabs: value }).catch((error) => {
                logError("could not save the added-games layout", error);
                setTabs(!value);
              });
            }}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<OrphanModal onChanged={onRefresh} />)}
            description="Finds games whose ROM or launcher has gone missing, records with no Steam shortcut, empty collections, and games left behind by a previous install."
          >
            Check the library
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {/* Its own group, because it is its own subject. These two are a pair --
          one makes the file, the other reads it back -- and neither is about
          the games in Steam, which is what the section above is. Between them
          and the button that deletes everything, so somebody reading down the
          tab meets the way to keep their saves before the way to lose them. */}
      <PanelSection title="Save data">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<SaveBackupModal />)}
            description="Collects the save data of every emulator on this Deck into one file and offers it to a phone or PC on this network. Nothing here is changed or removed."
          >
            Back up save data
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openModal(<RestoreSavesModal />)}
            description="Puts saves back from a backup you have sent to this Deck. Nothing already here is overwritten unless you ask for it."
          >
            Restore save data
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Starting over">
        <PanelSectionRow>
          <div className={DANGER_CLASS}>
            {/* The bar goes where the description does, and the button stays
                put. This can run for minutes -- deleting an unpacked game is
                tens of gigabytes -- and "Removing..." over a disabled button
                looked the same at second one and minute three. There is no
                second window on a Deck to check whether it is still alive. */}
            <ButtonItem
              layout="below"
              onClick={() => void confirmClearEverything()}
              disabled={clearing}
              description={
                clearing ? (
                  <InstallProgress
                    inline
                    label="Removing"
                    percent={progress.percent}
                    status={progress.text}
                  />
                ) : (
                  "Deletes every shortcut, launcher and empty collection this plugin created, and every ROM and unpacked game it put on this Deck."
                )
              }
            >
              {clearing ? "Removing..." : "Remove all DeckyEmu games from Steam"}
            </ButtonItem>
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
