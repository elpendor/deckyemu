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
  planCollectionMigration,
  recordCollections,
  setSettings,
  type PluginSettings,
} from "./backend";
import { migrateCollections, type CollectionMove } from "./steam";
import { callWithRetry } from "./timeout";
import { countStranded, strandedSummary, unfileWarning } from "./unfileWarning";

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
  const [stranded, setStranded] = useState({ games: 0, shelves: 0 });

  /**
   * Recount what is still filed. Cheap, and the plan is the honest source: with
   * collections off every move it produces is an unfiling, which is exactly the
   * question being asked.
   */
  const refreshPending = useCallback(async () => {
    try {
      setStranded(countStranded((await planCollectionMigration(null)).moves));
    } catch (error) {
      console.error("[deckyemu] could not count filed games", error);
    }
  }, []);

  useEffect(() => {
    callWithRetry(getSettings)
      .then((loaded) => {
        setLocalSettings(loaded);
        setCollectionInput(loaded.collection_name);
        if (!loaded.add_to_collection) void refreshPending();
      })
      .catch(() => undefined);
  }, [refreshPending]);

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
        void refreshPending();
      }
    },
    [refreshPending],
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
   * The master switch, and nothing more than a switch.
   *
   * It says where games go from now on, so pressing it only writes the setting.
   * Taking games that are already filed back out is a separate act with its own
   * button below, and keeping the two apart is what this control is for.
   *
   * Two attempts got that wrong before landing here, both by hanging a dialog
   * off the toggle. Asking *before* writing the setting left the switch drawn
   * as off with the setting still on when the dialog was cancelled -- Steam's
   * ToggleField keeps its own visual state and does not re-read `checked` when
   * the prop it is given has not changed, so it stayed wrong until the tab was
   * left and re-entered. Writing the setting first fixed that and was still
   * wrong: pressing a switch and being asked a question you can decline leaves
   * a switch that looks like it did not take, whatever the setting underneath
   * says. A toggle should toggle.
   *
   * Switching it on files everything, without asking -- adding games to a
   * collection destroys nothing and is the whole reason to turn it on.
   */
  const setEnabled = useCallback(
    async (value: boolean) => {
      if (value) {
        await applyCollectionChange({ add_to_collection: true });
        return;
      }
      await patch({ add_to_collection: false });
      await refreshPending();
    },
    [applyCollectionChange, patch, refreshPending],
  );

  /** The row's action: take out whatever is still filed, asking first. */
  const unfileStranded = useCallback(async () => {
    const moves = (await planCollectionMigration(null)).moves.filter((move) => !move.to);
    const { games, shelves } = countStranded(moves);
    if (games === 0) {
      setStranded({ games: 0, shelves: 0 });
      return;
    }
    showModal(
      <ConfirmModal
        strTitle="Take them out of their collections?"
        strDescription={unfileWarning(games, shelves)}
        strOKButtonText="Take them out"
        strCancelButtonText="Leave them"
        onOK={() => void applyMoves(moves)}
      />,
    );
  }, [applyMoves]);

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
        <ToggleField
          label="Add to a collection"
          description="Groups added games together in Big Picture"
          checked={settings.add_to_collection}
          onChange={(value) => void setEnabled(value)}
          disabled={migrating}
        />
      </PanelSectionRow>

      {/* Collections are off, but games added while they were on are still in
          them. Switching the setting says nothing about those -- this is where
          they are dealt with, and it is also the retry for a removal that only
          partly succeeded. */}
      {!settings.add_to_collection && stranded.games > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={migrating}
            description={strandedSummary(stranded.games, stranded.shelves)}
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
