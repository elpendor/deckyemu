import {
  ConfirmModal,
  DialogButton,
  Field,
  PanelSection,
  PanelSectionRow,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import { callable } from "@decky/api";

import { getSettings, listAdded, type AddedGame } from "./backend";
import { removeShortcut } from "./steam";
import { sweepEmptyCollections, unfileGames } from "./collections";
import { humanSize } from "./TransferModal";
import { callWithRetry } from "./timeout";
import { openModal } from "./modalStack";

/**
 * Declared here rather than in backend.ts, deliberately.
 *
 * `callable(...)` runs at module scope, so rollup treats it as a side effect
 * and keeps it however unreachable it is. Left in backend.ts, three RPC stubs
 * for the reset endpoints survived into release bundles that contained no way
 * to call them. Beside their only caller, they are dropped with it.
 */
interface ResetTarget {
  label: string;
  path: string;
  items: number;
  bytes: number;
}
const devResetInventory = callable<
  [],
  { ok: boolean; error?: string; groups?: Record<string, ResetTarget[]> }
>("dev_reset_inventory");
const devReset = callable<
  [action: string],
  { ok: boolean; error?: string; freed?: number; removed?: string[]; failed?: string[] }
>("dev_reset");

/**
 * Putting the Deck back to before the plugin touched it. Development only.
 *
 * Testing a first-run path needs a first run, and by the second week of work no
 * machine has one left. This is not shipped: `IS_DEV_BUILD` is a build-time
 * constant, so a release bundle does not contain this component at all, and the
 * backend refuses the calls independently.
 *
 * One action per press, each naming what it destroys and what that costs to
 * undo. Deliberately no "reset everything": the cheapest of these is rebuilt by
 * using the plugin for a minute and the dearest means fetching dumps from
 * another machine again, and one button would hide the second behind the first.
 */
const ACTIONS: {
  id: string;
  group: string;
  title: string;
  what: string;
  cost: string;
}[] = [
  {
    id: "state",
    group: "state",
    title: "Forget everything the plugin knows",
    what:
      "The record of games added, registered emulators, which config version each " +
      "has had applied, what firmware was installed, and cached artwork. The Steam " +
      "shortcuts for those games go too — their launcher scripts are deleted here, " +
      "so leaving the shortcuts behind would leave entries that start nothing.",
    cost:
      "Cheapest of these to undo — nothing on disk is lost, and re-scanning rebuilds " +
      "most of it. This is the one that makes a clean run actually clean: leave the " +
      "setup record behind and a reinstalled emulator is never reconfigured, silently.",
  },
  {
    id: "transfers",
    group: "transfers",
    title: "Delete every ROM and dump",
    what:
      "The transfer folder, the ROMs filed under each system — which is every " +
      "game you have added — and every BIOS, key and firmware archive sent here.",
    cost: "Expensive. These come from another machine and have to be sent again.",
  },
  {
    id: "downloads",
    group: "downloads",
    title: "Delete downloaded builds and tools",
    what: "Emulator AppImages, the PS4 package extractor, and unpacked PS4 games.",
    cost: "A download each, no worse.",
  },
  {
    id: "emulators",
    group: "emulators",
    title: "Uninstall every emulator",
    what:
      "Each one this plugin installed, its registration, and everything that " +
      "emulator owns — its configuration, the firmware it unpacked, games " +
      "installed into it, and save games. An emulator that comes back still " +
      "configured is the state this exists to get rid of, so the data goes with it.",
    cost:
      "A download each, and the data is not recoverable — save games are not " +
      "stored anywhere else. Anything installed system-wide is refused, and its " +
      "data is left alone with it: removing that needs root, which the plugin has " +
      "not got.",
  },
  {
    id: "emulator_data",
    group: "emulator_data",
    title: "Delete emulator data",
    what:
      "Everything the emulators own: installed games, firmware they unpacked, their " +
      "configuration — and save games.",
    cost: "Irreversible. Save games are not stored anywhere else.",
  },
  {
    id: "retroarch",
    group: "retroarch",
    title: "Remove RetroArch",
    what: "RetroArch itself, every core, its system folder and all its configuration.",
    cost: "A download and a re-scan.",
  },
];

interface Props {
  /**
   * Raised after a reset finishes, so the panels holding a picture of what is
   * installed go and look again. Without it the RetroArch tab still listed
   * RetroArch after it had been uninstalled, and the core list still offered to
   * remove a core that had been deleted — both correct at the moment they were
   * read and both read before any of this happened.
   */
  onChanged?: () => void;
}

export function DevPanel({ onChanged }: Props) {
  const [groups, setGroups] = useState<Record<string, ResetTarget[]> | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  // Failure is reported, never rendered as emptiness. The first version put
  // `?? {}` here and swallowed both a backend refusal and an outright crash,
  // so every row read "Nothing to remove" -- which is precisely what a clean
  // machine looks like. The panel claimed there was nothing to do while the
  // call behind it was raising AttributeError.
  const load = useCallback(() => {
    setError("");
    callWithRetry(devResetInventory)
      .then((result) => {
        if (!result.ok || !result.groups) {
          setError(result.error || "The backend would not answer.");
          return;
        }
        setGroups(result.groups);
      })
      .catch((loadError) => {
        console.error("[deckyemu] could not read reset inventory", loadError);
        setError(String(loadError));
      });
  }, []);

  useEffect(load, [load]);

  const run = useCallback(
    (action: (typeof ACTIONS)[number], targets: ResetTarget[]) => {
      const total = targets.reduce((sum, item) => sum + item.bytes, 0);
      openModal(
        <ConfirmModal
          strTitle={action.title}
          strOKButtonText="Delete"
          bDestructiveWarning
          strDescription={
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div>{action.what}</div>
              <div>{action.cost}</div>
              {/* The list, not just a total: "3.1 GB" is easy to press past and
                  a line naming somebody's save directory is not. */}
              <div style={{ opacity: 0.75, fontSize: "13px" }}>
                {targets.map((item) => (
                  <div key={item.path}>
                    {item.label}
                    {item.bytes > 0 ? ` — ${humanSize(item.bytes)}` : ""}
                  </div>
                ))}
                {total > 0 && <div style={{ marginTop: "6px" }}>{humanSize(total)} in total.</div>}
              </div>
            </div>
          }
          onOK={() => {
            setBusy(action.id);
            void (async () => {
              try {
                /*
                 * Read before the reset, acted on after it.
                 *
                 * This action deletes the registry and the whole launcher
                 * directory, and the backend cannot touch Steam -- so without
                 * this every game added was left as a shortcut running a script
                 * that no longer existed. Twenty of them, in the library,
                 * starting nothing, and invisible to the audit because every
                 * check it makes begins from a registry entry that has just
                 * been deleted.
                 *
                 * Gathered first because the registry is about to go, and
                 * removed only once the reset has actually succeeded: deleting
                 * somebody's shortcuts and then failing to reset would be the
                 * worst of both.
                 */
                const stranded =
                  action.id === "state"
                    ? await listAdded().catch((listError) => {
                        console.error("[deckyemu] could not read the library", listError);
                        return [] as AddedGame[];
                      })
                    : [];

                /*
                 * The setup shortcut, read for the same reason and at the same
                 * moment: its id lives in settings.json, which this action is
                 * about to delete.
                 *
                 * It is not in the library and never was -- it is one hidden
                 * shortcut repointed at whichever emulator is being opened -- so
                 * `stranded` does not cover it. Left behind, it is a Steam entry
                 * pointing at a launcher directory that no longer exists: it
                 * starts nothing, the library check reports it as dead, and the
                 * next emulator window makes a second one beside it because the
                 * id it would have reused is gone.
                 */
                const setupAppId =
                  action.id === "state"
                    ? await getSettings()
                        .then((settings) => settings.setup_app_id ?? 0)
                        .catch((settingsError) => {
                          console.error(
                            "[deckyemu] could not read the setup shortcut id",
                            settingsError,
                          );
                          return 0;
                        })
                    : 0;

                const result = await devReset(action.id);
                if (!result.ok) {
                  toaster.toast({ title: "Reset failed", body: result.error ?? "" });
                  return;
                }

                // Out of their collections before their shortcuts go -- the
                // ordering is load-bearing, and `unfileGames` says why. A reset
                // that left twenty dead shortcuts also left the shelves they
                // sat on.
                await unfileGames(stranded);

                let unshortcut = 0;
                for (const game of stranded) {
                  if (removeShortcut(game.app_id)) unshortcut += 1;
                }
                // Counted with them: to the person pressing this it is one more
                // entry that was in their library and now is not.
                if (setupAppId && removeShortcut(setupAppId)) unshortcut += 1;

                // And whatever earlier resets left standing, since this is the
                // action that made them.
                const emptied = await sweepEmptyCollections();
                const failed = result.failed?.length
                  ? ` ${result.failed.length} could not be removed.`
                  : "";
                toaster.toast({
                  title: action.title,
                  body:
                    (result.removed
                      ? `${result.removed.length} removed.` +
                        // The data half, said separately: "3 removed" is the
                        // uninstall and gives no hint that gigabytes of saves
                        // went with it.
                        (result.freed ? ` ${humanSize(result.freed)} of data deleted.` : "")
                      : `${humanSize(result.freed ?? 0)} recovered.`) +
                    (unshortcut ? ` ${unshortcut} Steam shortcut(s) removed.` : "") +
                    (emptied ? ` ${emptied} empty collection(s) deleted.` : "") +
                    failed,
                });
                load();
                onChanged?.();
              } finally {
                setBusy("");
              }
            })();
          }}
        />,
      );
    },
    [load, onChanged],
  );

  return (
    <PanelSection title="Reset">
      <PanelSectionRow>
        <Field description="Development build only. None of this exists in a release — the tab is compiled out and the backend refuses the calls." />
      </PanelSectionRow>

      {error && (
        <PanelSectionRow>
          <Field label="Could not read what is on disk" description={error} />
        </PanelSectionRow>
      )}

      {ACTIONS.map((action) => {
        const targets = groups?.[action.group] ?? [];
        const total = targets.reduce((sum, item) => sum + item.bytes, 0);
        return (
          <PanelSectionRow key={action.id}>
            <Field
              label={action.title}
              // What is actually there right now, so a button that would do
              // nothing says so instead of asking for confirmation first.
              // "Nothing to remove" is only said once the inventory has
              // actually been read. Until then it is unknown, and the two must
              // not look the same.
              description={
                groups === null
                  ? error
                    ? "Unknown — the inventory could not be read."
                    : "Reading..."
                  : targets.length === 0
                    ? "Nothing to remove."
                    : total > 0
                      ? `${targets.length} item(s), ${humanSize(total)}.`
                      : `${targets.length} item(s).`
              }
              childrenContainerWidth="min"
            >
              <DialogButton
                disabled={busy === action.id || targets.length === 0}
                onClick={() => run(action, targets)}
                style={{ minWidth: "auto", width: "auto", padding: "6px 16px" }}
              >
                {busy === action.id ? "Working..." : "Reset"}
              </DialogButton>
            </Field>
          </PanelSectionRow>
        );
      })}
    </PanelSection>
  );
}
