import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  showModal,
  TextField,
  ToggleField,
  type SingleDropdownOption,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  collectionTargets,
  getSettings,
  planCollectionMigration,
  recordCollections,
  setSettings,
  type PluginSettings,
} from "./backend";
import {
  addAppsToCollection,
  findStaleCollections,
  migrateCollections,
  pruneStaleCollections,
} from "./steam";
import { callWithRetry } from "./timeout";

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

  useEffect(() => {
    callWithRetry(getSettings)
      .then((loaded) => {
        setLocalSettings(loaded);
        setCollectionInput(loaded.collection_name);
      })
      .catch(() => undefined);
  }, []);

  const patch = useCallback(async (changes: Record<string, unknown>) => {
    try {
      setLocalSettings(await setSettings(changes));
    } catch (error) {
      console.error("[retroarch] failed to save settings", error);
    }
  }, []);

  /**
   * Move games that were already added into their new collection.
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
        if (plan.moves.length === 0) return;

        const { moved, assignments } = await migrateCollections(plan.moves);
        if (Object.keys(assignments).length > 0) {
          await recordCollections(assignments);
        }

        const failed = plan.moves.length - moved;
        toaster.toast({
          title: moved > 0 ? "Collections updated" : "Could not update collections",
          body:
            failed > 0
              ? `${moved} of ${plan.moves.length} game(s) moved; ${failed} could not be.`
              : `${moved} game(s) moved.`,
        });
      } catch (error) {
        console.error("[retroarch] collection migration failed", error);
        toaster.toast({
          title: "Could not update collections",
          body: "The setting was saved but existing games were not moved.",
        });
      } finally {
        setMigrating(false);
      }
    },
    [patch, settings],
  );

  /**
   * Put every tracked game into the collection it should be in.
   *
   * The migration only moves games whose target differs from what was recorded,
   * so it cannot repair a game that was recorded as filed but never actually
   * added -- the two agree, and nothing moves. This ignores the recorded value
   * and files everything, which is safe because adding a game already present is
   * a no-op.
   */
  const refileCollections = useCallback(async () => {
    setMigrating(true);
    try {
      const { targets } = await collectionTargets();

      const byCollection = new Map<string, number[]>();
      for (const [appIdText, tag] of Object.entries(targets)) {
        const appId = Number(appIdText);
        if (!appId || !tag) continue;
        byCollection.set(tag, [...(byCollection.get(tag) ?? []), appId]);
      }

      if (byCollection.size === 0) {
        toaster.toast({
          title: "Nothing to file",
          body: "No tracked games, or collections are turned off.",
        });
        return;
      }

      let filed = 0;
      const failed: string[] = [];
      for (const [tag, appIds] of byCollection) {
        if (await addAppsToCollection(tag, appIds)) filed += appIds.length;
        else failed.push(tag);
      }

      toaster.toast({
        title: failed.length ? "Some collections failed" : "Games filed",
        body: failed.length
          ? `${filed} filed; could not update ${failed.join(", ")}.`
          : `${filed} game(s) across ${byCollection.size} collection(s).`,
      });
    } catch (error) {
      console.error("[retroarch] refile failed", error);
      toaster.toast({ title: "Could not file games", body: "See the plugin log." });
    } finally {
      setMigrating(false);
    }
  }, []);

  /**
   * Remove our games from collections they no longer belong to.
   *
   * Separate from the migration because the old collection cannot always be
   * derived -- games added by an older build recorded nothing. This looks at
   * what Steam actually contains instead, and always confirms first, since one
   * of these could be a collection the user curates by hand.
   */
  const tidyCollections = useCallback(async () => {
    setMigrating(true);
    try {
      const { targets } = await collectionTargets();
      const stale = findStaleCollections(targets);

      if (stale.length === 0) {
        toaster.toast({
          title: "Nothing to tidy",
          body: "No games are in collections they should not be.",
        });
        return;
      }

      const summary = stale
        .map((entry) => `"${entry.tag}" (${entry.appIds.length} game(s))`)
        .join(", ");

      showModal(
        <ConfirmModal
          strTitle="Tidy up collections?"
          strDescription={`These collections hold games that now belong elsewhere: ${summary}. They will be removed from those collections, and any collection left empty will be deleted. Your games and ROMs are not affected.`}
          strOKButtonText="Tidy up"
          bDestructiveWarning
          onOK={() => {
            void (async () => {
              const pruned = await pruneStaleCollections(stale);
              toaster.toast({
                title: pruned > 0 ? "Collections tidied" : "Could not tidy collections",
                body: `${pruned} entry(s) removed.`,
              });
            })();
          }}
        />,
      );
    } catch (error) {
      console.error("[retroarch] tidy failed", error);
      toaster.toast({ title: "Could not check collections", body: "See the log for details." });
    } finally {
      setMigrating(false);
    }
  }, []);

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
          onChange={(value) => void patch({ add_to_collection: value })}
        />
      </PanelSectionRow>

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

          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={refileCollections}
              disabled={migrating}
              description="Adds every tracked game to the collection it belongs to. Useful if games are missing from a collection; adding one that is already there does nothing."
            >
              Re-file games into collections
            </ButtonItem>
          </PanelSectionRow>

          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={tidyCollections}
              disabled={migrating}
              description="Removes your games from collections they no longer belong to, and deletes any left empty. Asks first."
            >
              Tidy up old collections
            </ButtonItem>
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
