import { DialogButton, Focusable, ModalRoot, Spinner } from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  adoptPreviousInstall,
  auditLibrary,
  collectionShape,
  deleteRom,
  deleteStrayLaunchers,
  discardPreviousInstall,
  forgetGames,
  type AuditReport,
} from "./backend";
import {
  addAppsToCollection,
  deleteCollections,
  findEmptyCollections,
  removeAppsFromCollection,
  removeShortcut,
  repointShortcut,
  shortcutExists,
} from "./steam";
import { humanSize } from "./TransferModal";
import { emptyCollectionMatcher } from "./collectionMatch";
import { callWithRetry } from "./timeout";

interface Props {
  onChanged: () => void;
  closeModal?: () => void;
}

interface Finding {
  key: string;
  title: string;
  detail: string;
  action: string;
  run: () => Promise<string>;
  destructive?: boolean;
}

/**
 * Forget entries and empty the collections they were filed into.
 *
 * Forgetting only the record left the collection behind holding nothing, which is
 * exactly the "orphaned collections" this dialog is supposed to clear. A collection
 * is deleted only once it is empty, so one holding games added by hand survives.
 */
async function forgetAndUnfile(appIds: number[]): Promise<string> {
  const result = await forgetGames(appIds);

  const byCollection = new Map<string, number[]>();
  for (const game of result.games ?? []) {
    if (!game.collection) continue;
    byCollection.set(game.collection, [
      ...(byCollection.get(game.collection) ?? []),
      game.app_id,
    ]);
  }
  for (const [tag, ids] of byCollection) {
    await removeAppsFromCollection(tag, ids);
  }

  const emptied = byCollection.size;
  return (
    `${result.removed.length} forgotten` +
    (emptied ? `, ${emptied} collection(s) tidied` : "") +
    "."
  );
}

const SECTION: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "4px",
  padding: "10px 0",
  borderBottom: "1px solid rgba(255,255,255,0.08)",
};

/**
 * Reports everything that has drifted out of sync and offers to fix each one.
 *
 * Called "orphaned entries" while it only found records with nothing behind
 * them. It also reports collections left holding nothing, which are not
 * entries and are not orphans, so both it and its button are named for the job
 * rather than for one of the findings.
 *
 * Five things can disagree: this plugin's registry, the launcher scripts, the
 * ROM files, Steam's own shortcuts, and Steam's collections. The backend can see the first three; whether
 * a shortcut still exists is only knowable here, so that check happens in the
 * frontend against the registry the backend returns.
 */
export function OrphanModal({ onChanged, closeModal }: Props) {
  const [report, setReport] = useState<AuditReport | null>(null);
  const [missingShortcuts, setMissingShortcuts] = useState<AuditReport["registry"]>([]);
  const [busy, setBusy] = useState("");
  const [emptyCollections, setEmptyCollections] = useState<string[]>([]);
  const [done, setDone] = useState<string[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const result = await callWithRetry(auditLibrary);
      setReport(result);
      // A shortcut deleted directly in Steam leaves our registry entry behind.
      setMissingShortcuts(result.registry.filter((entry) => !shortcutExists(entry.app_id)));
      // Shelves with nothing left on them. Not derivable from the registry --
      // an empty collection is one no registered game names any more.
      setEmptyCollections(findEmptyCollections(emptyCollectionMatcher(await collectionShape())));
    } catch (loadError) {
      console.error("[retroarch] audit failed", loadError);
      setError("Could not check the library.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const perform = useCallback(
    async (finding: Finding) => {
      setBusy(finding.key);
      setError("");
      try {
        const message = await finding.run();
        setDone((previous) => [...previous, finding.key]);
        toaster.toast({ title: finding.title, body: message });
        onChanged();
        await load();
      } catch (runError) {
        console.error("[retroarch] fix failed", runError);
        setError("That could not be completed — see the plugin log.");
      } finally {
        setBusy("");
      }
    },
    [onChanged, load],
  );

  const findings: Finding[] = [];

  for (const install of report?.previous_installs ?? []) {
    // Adopting a game whose shortcut is gone just manufactures a fresh orphan to
    // forget, which is how this dialog started going round in circles. Only the
    // frontend can see Steam, so the filter has to happen here.
    const adoptable = install.games.filter(
      (game) => game.rom_exists && shortcutExists(game.app_id),
    );
    const noShortcut = install.games.filter((game) => !shortcutExists(game.app_id)).length;
    const noRom = install.games.filter((game) => !game.rom_exists).length;

    if (adoptable.length > 0) {
      findings.push({
        key: `previous-${install.path}`,
        title: `Games from a previous install (${install.name})`,
        detail:
          `${adoptable.length} of ${install.games.length} game(s) added under the old name can be ` +
          `taken over. Their Steam shortcuts still work; adopting rebuilds each launcher here and ` +
          `repoints the shortcut at it.` +
          (noRom ? ` ${noRom} cannot be adopted because their ROM is missing.` : "") +
          (noShortcut ? ` ${noShortcut} no longer have a Steam shortcut.` : ""),
        action: `Adopt ${adoptable.length}`,
        run: async () => {
        const result = await adoptPreviousInstall(install.path);
        if (!result.ok) throw new Error(result.error);

        const adopted = result.adopted ?? [];
        let repointed = 0;
        // Point each shortcut at its rebuilt launcher, or it keeps running the
        // old install's script.
        for (const game of adopted) {
          if (repointShortcut(game.app_id, game.exe)) repointed += 1;
        }

        // Filing into collections is a Steam-side operation, so the backend can
        // only say where each game belongs -- it cannot put it there.
        const byCollection = new Map<string, number[]>();
        for (const game of adopted) {
          if (!game.collection) continue;
          byCollection.set(game.collection, [
            ...(byCollection.get(game.collection) ?? []),
            game.app_id,
          ]);
        }
        let filed = 0;
        for (const [tag, appIds] of byCollection) {
          if (await addAppsToCollection(tag, appIds)) filed += appIds.length;
        }

          const skipped = result.skipped?.length ?? 0;
          return (
            `${repointed} adopted` +
            (filed ? `, ${filed} added to collections` : "") +
            (skipped ? `, ${skipped} skipped` : "") +
            "."
          );
        },
      });
    }

    // The other half of the choice. Without it the old registry stays on disk and
    // the same games are offered again after every adopt-then-forget cycle.
    findings.push({
      key: `discard-${install.path}`,
      title: `Forget the previous install (${install.name})`,
      detail:
        adoptable.length > 0
          ? `Stop offering these ${install.games.length} game(s). Their launcher scripts are kept, ` +
            `so any shortcut that still works keeps working — this only deletes the old record.`
          : `None of its ${install.games.length} game(s) can be taken over` +
            (noShortcut ? ` — Steam has no shortcut for ${noShortcut} of them` : "") +
            `. Deleting the old record stops it being offered every time. Launcher scripts are kept.`,
      action: "Discard the old record",
      destructive: true,
      run: async () => {
        const result = await discardPreviousInstall(install.path);
        if (!result.ok) throw new Error(result.error);
        return `${result.discarded ?? 0} old record(s) discarded.`;
      },
    });
  }

  if ((report?.broken.length ?? 0) > 0) {
    const broken = report!.broken;
    findings.push({
      key: "broken",
      title: "Games that can no longer launch",
      detail: broken
        .map((entry) => `${entry.title || entry.app_id} — ${entry.reasons.join(" and ")}`)
        .join("\n"),
      action: `Remove ${broken.length} from Steam`,
      destructive: true,
      run: async () => {
        for (const entry of broken) removeShortcut(entry.app_id);
        return forgetAndUnfile(broken.map((entry) => entry.app_id));
      },
    });
  }

  if (missingShortcuts.length > 0) {
    findings.push({
      key: "missing-shortcuts",
      title: "Entries with no Steam shortcut",
      detail:
        `${missingShortcuts.length} game(s) are tracked here but Steam has no shortcut for them, ` +
        `which happens when a shortcut is deleted directly in Steam. Forgetting them removes the ` +
        `leftover record and its launcher script; no Steam entry is touched.`,
      action: `Forget ${missingShortcuts.length}`,
      run: async () => forgetAndUnfile(missingShortcuts.map((entry) => entry.app_id)),
    });
  }

  if ((report?.unused_roms.length ?? 0) > 0) {
    const unused = report!.unused_roms;
    const bytes = unused.reduce((sum, rom) => sum + rom.bytes, 0);
    findings.push({
      key: "unused-roms",
      title: "ROMs no game uses",
      detail:
        `${unused.length} file(s) filed under a system, totalling ${humanSize(bytes)}, ` +
        `that nothing in your library points at. Removing a game leaves its ROM by ` +
        `default, and a shortcut deleted in Steam itself never asks at all. Only the ` +
        `plugin's own roms folder is counted — anything you keep elsewhere is untouched.` +
        "\n\n" +
        unused.map((rom) => `${rom.system}/${rom.name}`).join("\n"),
      action: `Delete ${unused.length}`,
      destructive: true,
      run: async () => {
        let freed = 0;
        let failed = 0;
        for (const rom of unused) {
          const result = await deleteRom(rom.path);
          if (result.ok) freed += result.freed ?? 0;
          else failed += 1;
        }
        return (
          `${humanSize(freed)} freed` + (failed ? `, ${failed} could not be deleted.` : ".")
        );
      },
    });
  }

  if (emptyCollections.length > 0) {
    findings.push({
      key: "empty-collections",
      title: "Collections with nothing in them",
      detail:
        `${emptyCollections.join(", ")} — made by this plugin and now empty. ` +
        `A collection is deleted as its last game leaves, so these are left over ` +
        `from a shortcut deleted in Steam itself, or from before removal did that. ` +
        `Only collections matching the naming this plugin uses are listed, and only ` +
        `while they hold nothing.`,
      action: `Delete ${emptyCollections.length}`,
      destructive: true,
      run: async () => {
        const deleted = await deleteCollections(emptyCollections);
        return `${deleted} collection(s) deleted.`;
      },
    });
  }

  if ((report?.strays.length ?? 0) > 0) {
    const strays = report!.strays;
    findings.push({
      key: "strays",
      title: "Launcher scripts with no game",
      detail: `${strays.length} script(s) in the launcher folder are not referenced by any tracked game.`,
      action: `Delete ${strays.length}`,
      destructive: true,
      run: async () => {
        const result = await deleteStrayLaunchers(strays);
        return `${result.deleted} deleted.`;
      },
    });
  }

  const pending = findings.filter((finding) => !done.includes(finding.key));

  return (
    <ModalRoot closeModal={closeModal} bAllowFullSize>
      <div style={{ fontSize: "20px", fontWeight: 600, marginBottom: "4px" }}>
        Library check
      </div>
      <div style={{ opacity: 0.7, fontSize: "13px", marginBottom: "8px" }}>
        Games, launcher scripts and Steam shortcuts that no longer line up.
      </div>

      {error && (
        <div style={{ color: "#e35d5d", fontSize: "13px", marginBottom: "8px" }}>{error}</div>
      )}

      {!report && (
        <div style={{ display: "flex", justifyContent: "center", padding: "24px" }}>
          <Spinner style={{ height: "32px" }} />
        </div>
      )}

      {report && pending.length === 0 && (
        <div style={{ padding: "14px 0", opacity: 0.8 }}>
          Nothing is out of place — every tracked game has its ROM, its launcher and a Steam
          shortcut.
        </div>
      )}

      {report && pending.length > 0 && (
        <Focusable
          style={{
            display: "flex",
            flexDirection: "column",
            maxHeight: "50vh",
            overflowY: "auto",
          }}
        >
          {pending.map((finding) => (
            <div key={finding.key} style={SECTION}>
              <div style={{ fontWeight: 500 }}>{finding.title}</div>
              <div style={{ fontSize: "12px", opacity: 0.7, whiteSpace: "pre-wrap" }}>
                {finding.detail}
              </div>
              <DialogButton
                onClick={() => void perform(finding)}
                disabled={Boolean(busy)}
                style={{ width: "auto", minWidth: "200px", marginTop: "6px" }}
              >
                {busy === finding.key ? "Working..." : finding.action}
              </DialogButton>
            </div>
          ))}
        </Focusable>
      )}

      <Focusable style={{ display: "flex", gap: "8px", marginTop: "14px" }}>
        <DialogButton onClick={() => void load()} disabled={Boolean(busy)}>
          Re-check
        </DialogButton>
        <DialogButton onClick={() => closeModal?.()} disabled={Boolean(busy)}>
          Close
        </DialogButton>
      </Focusable>
    </ModalRoot>
  );
}
