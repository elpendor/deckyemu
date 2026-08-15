import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  showModal,
  type SingleDropdownOption,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  collectionTemplates,
  getSettings,
  listAdded,
  planCollectionMigration,
  recordCollections,
  setSettings,
  type CollectionTemplate,
  type PluginSettings,
} from "./backend";
import { findFiledGames, migrateCollections, type CollectionMove } from "./steam";
import { forgetDeleted } from "./collections";
import { callWithRetry } from "./timeout";
import { countFiled, strandedSummary, unfileWarning } from "./unfileWarning";

const PLATFORM_NAME_OPTIONS: SingleDropdownOption[] = [
  { data: "short", label: "Short (SNES, N64, GBA)" },
  { data: "full", label: "Full (Super Nintendo Entertainment System)" },
];

/**
 * Show a rendered name in a dropdown label.
 *
 * The rendering itself is the backend's -- `collection_templates` runs the same
 * function that names a real collection, so a preview cannot promise a format
 * the filing does not use. This only makes a newline visible, which is a
 * property of the row rather than of the name. Steam renders collection titles
 * as single-line text and CSS collapses whitespace, so the newline will most
 * likely show as a space rather than a break wherever it really appears.
 */
const showNewlines = (preview: string) => preview.replace(/\n/g, " ⏎ ");

/**
 * How added games are grouped in the library.
 *
 * Its own tab rather than a section of Settings: every control here can move
 * games that are already in Steam, which is a different kind of act from the
 * switches next door that only affect the next game added.
 */
export function CollectionsPanel() {
  const [settings, setLocalSettings] = useState<PluginSettings | null>(null);
  // Typed locally and saved on blur. Writing through to the backend on every
  // keystroke would round-trip the whole settings object and clobber
  // characters typed while a save was in flight.
  const [collectionInput, setCollectionInput] = useState("");
  const [migrating, setMigrating] = useState(false);
  // Games still sitting in collections while the feature is switched off. Not
  // an error state -- declining the dialog is a legitimate answer -- but it is
  // a state the panel has to be able to show, or the only way to discover it is
  // to look at the library.
  const [filed, setFiled] = useState({ games: 0, shelves: 0 });
  // The offered formats and how each would read, rendered by the backend. Held
  // rather than derived because the previews contain the user's own collection
  // name, so they are re-fetched whenever that changes.
  const [templates, setTemplates] = useState<CollectionTemplate[]>([]);

  /**
   * Re-read the offered formats and their previews.
   *
   * After any settings change, because a preview quotes the collection name and
   * would otherwise go on showing the old one. Cheap, and it is the only thing
   * standing between the dropdown and a label that lies about what filing does.
   */
  const refreshTemplates = useCallback(async () => {
    try {
      setTemplates((await collectionTemplates()).templates);
    } catch (error) {
      console.error("[deckyemu] could not read the naming formats", error);
    }
  }, []);

  /**
   * Recount how many games are in a collection, from what each recorded when it
   * was added.
   *
   * Not from a migration plan, which was the first attempt: a plan is computed
   * against the stored settings, so while collections are still on it reports
   * nothing to unfile -- which is the exact moment the dialog needs the number.
   */
  const refreshFiled = useCallback(async () => {
    try {
      const added = await listAdded();
      const groups = findFiledGames(added.map((game) => game.app_id));
      // One name per game found, so the counter sees both numbers it needs.
      setFiled(countFiled(groups.flatMap((group) => group.appIds.map(() => group.tag))));
    } catch (error) {
      console.error("[deckyemu] could not count filed games", error);
    }
  }, []);

  useEffect(() => {
    callWithRetry(getSettings)
      .then((loaded) => {
        setLocalSettings(loaded);
        setCollectionInput(loaded.collection_name);
        // Both ways round: off, it decides whether the "still filed" row is
        // shown; on, it is the count the dialog quotes before anything moves.
        void refreshFiled();
        void refreshTemplates();
      })
      .catch(() => undefined);
  }, [refreshFiled, refreshTemplates]);

  const patch = useCallback(
    async (changes: Record<string, unknown>) => {
      try {
        setLocalSettings(await setSettings(changes));
        await refreshTemplates();
      } catch (error) {
        console.error("[deckyemu] failed to save settings", error);
      }
    },
    [refreshTemplates],
  );

  /** Carry out a plan that has already been made. Returns how many landed. */
  const applyMoves = useCallback(
    async (moves: CollectionMove[]) => {
      if (moves.length === 0) return 0;
      setMigrating(true);
      try {
        const { moved, assignments, deleted } = await migrateCollections(moves);
        if (Object.keys(assignments).length > 0) {
          await recordCollections(assignments);
        }
        // A rename is the operation most likely to leave a collection empty and
        // remove it, so it is also the one most likely to leave the backend
        // claiming a shelf that has gone.
        await forgetDeleted(deleted);

        // "Moved" is wrong for games that were taken out and put nowhere, and
        // this is the one dialog where the difference is the whole point.
        const leaving = moves.every((move) => !move.to);
        const failed = moves.length - moved;
        toaster.toast({
          title: moved > 0 ? "Collections updated" : "Could not update collections",
          body:
            failed > 0
              ? `${moved} of ${moves.length} game(s) ${leaving ? "taken out" : "moved"}; ` +
                `${failed} could not be.`
              : `${moved} game(s) ${leaving ? "taken out of their collections" : "moved"}.`,
        });
        return moved;
      } catch (error) {
        console.error("[deckyemu] collection migration failed", error);
        toaster.toast({
          title: "Could not update collections",
          body: "The setting was saved but existing games were not moved.",
        });
        return 0;
      } finally {
        setMigrating(false);
        void refreshFiled();
      }
    },
    [refreshFiled],
  );

  /**
   * Change a setting and bring games already added into line with it.
   *
   * Without this, renaming the collection or switching to per-platform naming
   * would only affect the next ROM added, leaving everything already in the
   * library under the old name.
   */
  const applyCollectionChange = useCallback(
    async (changes: Record<string, unknown>) => {
      setMigrating(true);
      try {
        // Captured before the patch: games added by an older build did not record
        // their collection, so the old name is only knowable from these.
        const previous = settings
          ? {
              // Including the switch matters: without it the backend derives
              // where an unrecorded game *was* as though collections had always
              // been on, decides it is already in the right place, and files
              // nothing when they are turned back on.
              add_to_collection: settings.add_to_collection,
              collection_name: settings.collection_name,
              collection_per_platform: settings.collection_per_platform,
              collection_template: settings.collection_template,
              platform_names: settings.platform_names,
            }
          : null;

        await patch(changes);
        const plan = await planCollectionMigration(previous);
        await applyMoves(plan.moves);
      } catch (error) {
        console.error("[deckyemu] collection migration failed", error);
        toaster.toast({
          title: "Could not update collections",
          body: "The setting was saved but existing games were not moved.",
        });
      } finally {
        setMigrating(false);
      }
    },
    [applyMoves, patch, settings],
  );

  /**
   * Write the setting off, then take the games out.
   *
   * In that order, and it is not cosmetic: the plan is computed from the stored
   * settings, so with collections still on it would produce no unfiling at all.
   */
  const turnOffAndUnfile = useCallback(async () => {
    await patch({ add_to_collection: false });
    try {
      // Built from what Steam reports rather than from a migration plan. The
      // plan can only move games whose entry recorded a collection, and the
      // ones stranded here are precisely those whose entry did not.
      const added = await listAdded();
      const titles = new Map(added.map((game) => [game.app_id, game.title]));
      const moves = findFiledGames(added.map((game) => game.app_id)).flatMap((group) =>
        group.appIds.map((appId) => ({
          app_id: appId,
          title: titles.get(appId) ?? "",
          from: group.tag,
          to: "",
        })),
      );
      await applyMoves(moves);
    } catch (error) {
      console.error("[deckyemu] could not take games out of their collections", error);
      toaster.toast({
        title: "Could not update collections",
        body: "Collections are off, but the games already added are still in them.",
      });
    }
    await refreshFiled();
  }, [applyMoves, patch, refreshFiled]);

  /**
   * Turn collections on or off. One press, and the label says which way.
   *
   * A button rather than a switch, because this control asks a question before
   * it does anything and a switch cannot survive the answer being no. Steam's
   * ToggleField keeps its own visual state and does not re-read `checked` when
   * the prop it was given has not changed, so a declined dialog left the switch
   * drawn in the position the user pressed it into while the setting said the
   * opposite -- and it stayed that way until the tab was left and re-entered.
   * Writing the setting first only moved the confusion: a switch you press and
   * then decline is a switch that looks like it did not take.
   *
   * A button has no position to be wrong about. Cancel means nothing happened,
   * which is the whole of what the user needs to know.
   *
   * Turning it on files everything, without asking -- adding games to a
   * collection destroys nothing and is the reason to turn it on.
   */
  const toggleEnabled = useCallback(async () => {
    if (!settings) return;

    if (!settings.add_to_collection) {
      await applyCollectionChange({ add_to_collection: true });
      return;
    }

    // Counted from the library rather than from a plan: the plan is computed
    // under the *current* settings, which still say collections are on, so it
    // would report nothing to do at the exact moment this asks.
    if (filed.games === 0) {
      await patch({ add_to_collection: false });
      return;
    }

    showModal(
      <ConfirmModal
        strTitle="Turn off collections?"
        strDescription={unfileWarning(filed.games, filed.shelves)}
        strOKButtonText="Turn off and take them out"
        onOK={() => void turnOffAndUnfile()}
      />,
    );
  }, [applyCollectionChange, filed, patch, settings, turnOffAndUnfile]);

  /** The row's action: take out whatever is still filed, asking first. */
  const unfileStranded = useCallback(async () => {
    if (filed.games === 0) return;
    showModal(
      <ConfirmModal
        strTitle="Take them out of their collections?"
        strDescription={unfileWarning(filed.games, filed.shelves)}
        strOKButtonText="Take them out"
        onOK={() => void turnOffAndUnfile()}
      />,
    );
  }, [filed, turnOffAndUnfile]);

  const saveCollectionName = useCallback(() => {
    const name = collectionInput.trim();
    if (!name || name === settings?.collection_name) {
      // Fall back to the stored value so the field never shows empty.
      setCollectionInput(settings?.collection_name ?? "DeckyEmu");
      return;
    }
    void applyCollectionChange({ collection_name: name });
  }, [collectionInput, settings?.collection_name, applyCollectionChange]);

  // Both sections are drawn while the settings load, with a Loading row each,
  // so the page does not reflow under the reader as they arrive.
  if (!settings) {
    return (
      <>
        <PanelSection>
          <PanelSectionRow>
            <Field label="Loading..." />
          </PanelSectionRow>
        </PanelSection>
        <PanelSection title="Naming">
          <PanelSectionRow>
            <Field label="Loading..." />
          </PanelSectionRow>
        </PanelSection>
      </>
    );
  }

  return (
    <>
      {/* First section untitled: the sidebar already labels this page
          "Collections", and a section title repeating it prints the word twice.
          What belongs here is the one decision the tab is about -- whether games
          are grouped at all -- and anything that follows from it. */}
      <PanelSection>
        <PanelSectionRow>
          {/* A button, not a switch. Turning collections off asks a question,
              and a switch cannot survive that answer being no -- see
              toggleEnabled. */}
          <ButtonItem
            layout="below"
            label="Add to a collection"
            description={
              settings.add_to_collection
                ? "Added games are grouped together in Big Picture."
                : "Added games are not grouped. They still appear in the library."
            }
            disabled={migrating}
            onClick={() => void toggleEnabled()}
          >
            {settings.add_to_collection ? "Turn off" : "Turn on"}
          </ButtonItem>
        </PanelSectionRow>

        {/* Collections are off, but games added while they were on are still in
            them. Directly under the control that explains why, rather than in
            the naming group, which has nothing to do with it. It is the retry
            for a removal that only partly succeeded, and the way back for an
            install where the setting was changed elsewhere. */}
        {!settings.add_to_collection && filed.games > 0 && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={migrating}
              description={strandedSummary(filed.games, filed.shelves)}
              onClick={() => void unfileStranded()}
            >
              {migrating ? "Working..." : "Take them out of their collections"}
            </ButtonItem>
          </PanelSectionRow>
        )}

        {/* Here rather than at the foot of the naming group: a migration runs
            for unfiling too, which happens while that group is not on screen. */}
        {migrating && (
          <PanelSectionRow>
            <Field label="Working on collections..." />
          </PanelSectionRow>
        )}
      </PanelSection>

      {/* Its own titled group, and only when there is something to name. Every
          row in it answers the same question -- what the collections are
          called -- which is a different question from whether to have them. */}
      {settings.add_to_collection && (
        <PanelSection title="Naming">
          <PanelSectionRow>
            <TextField
              label="Collection name"
              value={collectionInput}
              onChange={(event) => setCollectionInput(event.target.value)}
              onBlur={saveCollectionName}
              disabled={migrating}
            />
          </PanelSectionRow>

          <PanelSectionRow>
            <ToggleField
              label="One collection per system"
              // States what it does. The example that was here duplicated the
              // format dropdown's own labels, which are previews of the same
              // string -- two rows showing the same text, one of them stale
              // whenever the other was being changed.
              description={
                settings.collection_per_platform
                  ? "Each system gets its own shelf."
                  : "Every system shares one collection."
              }
              checked={settings.collection_per_platform}
              onChange={(value) => void applyCollectionChange({ collection_per_platform: value })}
              disabled={migrating}
            />
          </PanelSectionRow>

          {settings.collection_per_platform && (
            <>
              <PanelSectionRow>
                <DropdownItem
                  // "System", not "Platform": the toggle above says system and
                  // so does the rest of the plugin.
                  label="System names"
                  rgOptions={PLATFORM_NAME_OPTIONS}
                  selectedOption={settings.platform_names}
                  onChange={(option) =>
                    void applyCollectionChange({ platform_names: String(option.data) })
                  }
                  disabled={migrating}
                />
              </PanelSectionRow>

              <PanelSectionRow>
                <DropdownItem
                  label="Name format"
                  description="Each option shows how it would read. ⏎ marks a newline, which Steam will probably show as a space."
                  rgOptions={templates.map((option) => ({
                    data: option.template,
                    label: showNewlines(option.preview),
                  }))}
                  selectedOption={settings.collection_template}
                  onChange={(option) =>
                    void applyCollectionChange({ collection_template: String(option.data) })
                  }
                  disabled={migrating}
                />
              </PanelSectionRow>
            </>
          )}

          {/* Last, because it is the note you read after making a change rather
              than a control. The two repair buttons that used to sit here are
              findings in the library check now: they were checks wearing the
              clothes of settings, and both asked to be pressed on suspicion
              with no way to see whether anything was wrong first. */}
          <PanelSectionRow>
            <Field description="Games are filed as they are added, and moved when this naming changes. If any end up on the wrong shelf, Library → Check the library finds and fixes them." />
          </PanelSectionRow>
        </PanelSection>
      )}
    </>
  );
}
