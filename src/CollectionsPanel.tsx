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
  getSettings,
  listAdded,
  planCollectionMigration,
  recordCollections,
  setSettings,
  type PluginSettings,
} from "./backend";
import { migrateCollections, type CollectionMove } from "./steam";
import { callWithRetry } from "./timeout";
import { countFiled, strandedSummary, unfileWarning } from "./unfileWarning";

/**
 * Naming formats for per-platform collections.
 *
 * The two-line option is offered because it was asked for, but Steam renders
 * collection titles as single-line text and CSS collapses whitespace, so the
 * newline will most likely show as a space rather than a break.
 */
const COLLECTION_TEMPLATES = [
  "[{name}] {platform}",
  "{platform}",
  "{name}: {platform}",
  "{name} · {platform}",
  "{name} - {platform}",
  "{platform} ({name})",
  "{name}\\n{platform}",
];

const PLATFORM_NAME_OPTIONS: SingleDropdownOption[] = [
  { data: "short", label: "Short (SNES, N64, GBA)" },
  { data: "full", label: "Full (Super Nintendo Entertainment System)" },
];

/** Render a template the way the backend will, for the dropdown labels. */
function previewTemplate(template: string, name: string, platform: string): string {
  return template
    .replace("\\n", " ⏎ ")
    .replace("{name}", name || "Collection")
    .replace("{platform}", platform)
    .replace(/[ \t]+/g, " ")
    .trim();
}

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
      setFiled(countFiled(added.map((game) => game.collection)));
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
      })
      .catch(() => undefined);
  }, [refreshFiled]);

  const patch = useCallback(async (changes: Record<string, unknown>) => {
    try {
      setLocalSettings(await setSettings(changes));
    } catch (error) {
      console.error("[deckyemu] failed to save settings", error);
    }
  }, []);

  /** Carry out a plan that has already been made. Returns how many landed. */
  const applyMoves = useCallback(
    async (moves: CollectionMove[]) => {
      if (moves.length === 0) return 0;
      setMigrating(true);
      try {
        const { moved, assignments } = await migrateCollections(moves);
        if (Object.keys(assignments).length > 0) {
          await recordCollections(assignments);
        }

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
      const moves = (await planCollectionMigration(null)).moves.filter((move) => !move.to);
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

  if (!settings) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Field label="Loading..." />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    // No title: the sidebar already labels this page "Collections", and a
    // PanelSection title that repeats its tab prints the heading twice.
    <PanelSection>
      <PanelSectionRow>
        {/* A button, not a switch. Turning collections off asks a question, and
            a switch cannot survive that answer being no -- see toggleEnabled. */}
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
          them. Switching the setting says nothing about those -- this is where
          they are dealt with, and it is also the retry for a removal that only
          partly succeeded. */}
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

      {settings.add_to_collection && (
        <>
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
              description={
                settings.collection_per_platform
                  ? `e.g. "${previewTemplate(
                      settings.collection_template,
                      settings.collection_name,
                      "Nintendo 64",
                    )}"`
                  : "All systems share a single collection"
              }
              checked={settings.collection_per_platform}
              onChange={(value) => void applyCollectionChange({ collection_per_platform: value })}
              disabled={migrating}
            />
          </PanelSectionRow>

          {settings.collection_per_platform && (
            <PanelSectionRow>
              <DropdownItem
                label="Platform names"
                rgOptions={PLATFORM_NAME_OPTIONS}
                selectedOption={settings.platform_names}
                onChange={(option) =>
                  void applyCollectionChange({ platform_names: String(option.data) })
                }
                disabled={migrating}
              />
            </PanelSectionRow>
          )}

          {settings.collection_per_platform && (
            <PanelSectionRow>
              <DropdownItem
                label="Naming format"
                description="⏎ marks a newline, which Steam will probably show as a space."
                rgOptions={COLLECTION_TEMPLATES.map((template) => ({
                  data: template,
                  label: previewTemplate(template, settings.collection_name, "Nintendo 64"),
                }))}
                selectedOption={settings.collection_template}
                onChange={(option) =>
                  void applyCollectionChange({ collection_template: String(option.data) })
                }
                disabled={migrating}
              />
            </PanelSectionRow>
          )}

          {/* The two repair buttons that were here are findings in the library
              check now. They were checks wearing the clothes of settings:
              nothing about "are my games on the right shelf" belongs beside the
              naming format, and both asked to be pressed on suspicion, with no
              way to see whether anything was wrong first. */}
          <PanelSectionRow>
            <Field description="Games are filed as they are added, and moved when this naming changes. If any end up on the wrong shelf, Library → Check the library finds and fixes them." />
          </PanelSectionRow>

          {migrating && (
            <PanelSectionRow>
              <Field label="Working on collections..." />
            </PanelSectionRow>
          )}
        </>
      )}
    </PanelSection>
  );
}
