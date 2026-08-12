import {
  ButtonItem,
  ConfirmModal,
  PanelSection,
  PanelSectionRow,
  showModal,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useState } from "react";

import { clearLibrary } from "./backend";
import { removeAppsFromCollection, removeShortcut } from "./steam";
import { DANGER_CLASS, DANGER_CSS } from "./danger";
import { OrphanModal } from "./OrphanModal";
import { humanSize } from "./TransferModal";

interface Props {
  onRefresh: () => void;
}

/**
 * What to do about games already in Steam: find the ones that drifted out of
 * sync, or take every one of them back out.
 *
 * Nothing here is a setting, which is why it is no longer called one -- both
 * controls act on the library immediately.
 */
export function LibraryPanel({ onRefresh }: Props) {
  const [clearing, setClearing] = useState(false);

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
    try {
      const cleared = await clearLibrary();

      const byCollection = new Map<string, number[]>();
      for (const game of cleared.games) {
        if (!game.collection) continue;
        const existing = byCollection.get(game.collection) ?? [];
        existing.push(game.app_id);
        byCollection.set(game.collection, existing);
      }
      for (const [tag, appIds] of byCollection) {
        await removeAppsFromCollection(tag, appIds);
      }

      for (const game of cleared.games) {
        removeShortcut(game.app_id);
      }

      toaster.toast({
        title:
          cleared.games.length > 0
            ? `Removed ${cleared.games.length} game(s)`
            : "Nothing to remove",
        body:
          cleared.games.length > 0
            ? `${cleared.launchers_deleted} launcher(s) deleted` +
              (cleared.freed ? `, ${humanSize(cleared.freed)} freed.` : ".")
            : "No games were tracked by DeckyEmu.",
      });
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
  }, [onRefresh]);

  const confirmClearEverything = useCallback(() => {
    showModal(
      <ConfirmModal
        strTitle="Remove every DeckyEmu game?"
        strDescription={
          "This deletes every Steam shortcut this plugin added, its launcher scripts, any collection it created that ends up empty, " +
          "and every game it put on this Deck — the ROMs it filed and the games it unpacked into emulators. " +
          "Playing any of them again means sending the files from another machine again. " +
          "Save data is kept, collections holding games you added yourself are kept, and ROMs you keep somewhere of your own are not touched."
        }
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
            <ButtonItem
              layout="below"
              onClick={confirmClearEverything}
              disabled={clearing}
              description="Deletes every shortcut, launcher and empty collection this plugin created, and every ROM and unpacked game it put on this Deck."
            >
              {clearing ? "Removing..." : "Remove all DeckyEmu games from Steam"}
            </ButtonItem>
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
