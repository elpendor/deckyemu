import {
  ButtonItem,
  ConfirmModal,
  PanelSection,
  PanelSectionRow,
  showModal,
} from "@decky/ui";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import { clearLibrary, listAdded, type AddedGame } from "./backend";
import { removeShortcut } from "./steam";
import { sweepEmptyCollections, unfileGames } from "./collections";
import { AddedGamesModal } from "./AddedGamesModal";
import { clearWarning, shouldConfirmClear } from "./clearWarning";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { InstallProgress } from "./InstallProgress";
import { OrphanModal } from "./OrphanModal";
import { callWithRetry } from "./timeout";
import { humanSize } from "./TransferModal";

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

  const loadGames = useCallback(async () => {
    try {
      setGames(await callWithRetry(listAdded));
    } catch (error) {
      console.error("[deckyemu] could not list added games", error);
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
      console.error("[deckyemu] could not clear the library", error);
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
      console.error("[deckyemu] could not count games before clearing", error);
    }

    if (!shouldConfirmClear(count)) {
      toaster.toast({
        title: "Nothing to remove",
        body: "No games are tracked by DeckyEmu.",
      });
      return;
    }

    showModal(
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
              showModal(
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

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => showModal(<OrphanModal onChanged={onRefresh} />)}
            description="Finds games whose ROM or launcher has gone missing, records with no Steam shortcut, empty collections, and games left behind by a previous install."
          >
            Check the library
          </ButtonItem>
        </PanelSectionRow>

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
