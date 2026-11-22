import * as batch from "./batchImport";
import {
  firmwareMatches, fileServerStatus, forgetGames, forgetTakenLicences, uninstallCore, unfileRoms,
} from "./backend";
import { unfileGames } from "./collections";
import { batchInputs, groupReceived } from "./receivedGroups";
import { removeShortcut } from "./steam";

/**
 * Development builds only: the batch store on `window.__deckyemu.batchTest`,
 * for the on-device scenarios in scripts/deck/batch_e2e.py. They drive the
 * same functions the dialog calls, with no dialog open.
 */
export function exposeBatchForTests(): void {
  const w = window as unknown as { __deckyemu?: Record<string, unknown> };
  (w.__deckyemu ??= {}).batchTest = {
    ...batch, transferInputs, takeBack, uninstallCore, forgetTakenLicences,
    marker: "deckyemu batch test hook",
  };
}

/** What Add all… hands the review: the transfer folder, grouped and typed. */
async function transferInputs(): Promise<batch.BatchFile[]> {
  const status = await fileServerStatus();
  const received = status.received ?? [];
  const matches = received.length ? await firmwareMatches(received.map((file) => file.name)) : {};
  return batchInputs(groupReceived(received), "roms", (name) => Boolean(matches?.[name]));
}

/** Take back every game this batch added: Steam, the library, its files. */
async function takeBack(): Promise<number> {
  const added = batch.getBatch().rows.flatMap((row) => (row.outcome === "added" ? row.added : []));
  if (!added.length) return 0;
  const forgotten = await forgetGames(added.map((one) => one.appId));
  await unfileGames(forgotten.games);
  for (const one of added) removeShortcut(one.appId);
  await unfileRoms(added.map((one) => one.filedPath).filter(Boolean));
  return added.length;
}
