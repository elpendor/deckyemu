import { makeDiscPlaylist, prepareShortcut, type ResolvedGame, type RomProbe } from "./backend";
import { addPreparedGame } from "./addGame";
import { coreById, readsPlaylist } from "./discSet";
import { installWaitingContent } from "./installContent";

/**
 * One game, decided: everything the add needs, whoever worked it out.
 *
 * The panel fills it from the draft and a batch fills one per row, so both end
 * in the same steps in the same order.
 */
export interface GamePlan {
  romPath: string;
  coreId: string;
  /** The system row's answer; "" lets the lookup's answer stand. */
  systemId: string;
  title: string;
  /** Vita3K starts a title id rather than a file. */
  titleId: string;
  /** Two or more makes a playlist; see `RomDraft.discs`. */
  discs: string[];
  probe: RomProbe | null;
  resolved: ResolvedGame | null;
}

export type AddOutcome =
  | {
    ok: true; appId: number; title: string; notes: string[]; romPath: string;
    /** File names of the updates and DLC that went in with it. */
    contentInstalled: string[];
  }
  | { ok: false; error: string };

/**
 * Playlist, launcher, shortcut, artwork, collection, record, then any updates
 * and DLC sent with it. A refusal comes back as `ok: false`; a step that throws
 * still throws, after `addPreparedGame` has rolled back what it made.
 */
export async function addGameToSteam(
  plan: GamePlan,
  onContentStep?: (label: string, index: number, total: number, measured: boolean) => void,
): Promise<AddOutcome> {
  const { romPath, coreId, discs, probe } = plan;
  // The system row decides the collection; the lookup's answer is the fallback
  // for a core covering one system, which is never asked.
  const system = plan.systemId || plan.resolved?.system || "";

  // The playlist is written here and nowhere earlier, so backing out before
  // this leaves the folder as it was found.
  let addPath = romPath;
  // What the shortcut starts when that is not what the game is: PCSX2 cannot
  // read a playlist, so it starts the first disc and swaps from its own menu.
  let launchName = "";
  if (discs.length >= 2) {
    const playlist = await makeDiscPlaylist(romPath, discs);
    if (!playlist.ok) return { ok: false, error: playlist.error };
    addPath = playlist.path;
    if (!readsPlaylist(coreById(probe, coreId))) launchName = discs[0];
  }

  const prepared = await prepareShortcut(
    plan.title, coreId, addPath, system, plan.titleId, launchName,
  );
  if (!prepared.ok) return { ok: false, error: prepared.error ?? "Could not prepare the shortcut." };

  const added = await addPreparedGame({
    prepared,
    romPath: addPath,
    coreId,
    system,
    art: plan.resolved?.art,
    // What boots an installed PS3, PS4 or Vita game is eboot.bin, so
    // remembering its emulator for `.bin` would suggest it for the next PS1
    // disc.
    rememberCore: !(plan.titleId || /(^|\/)eboot\.bin$/i.test(addPath)),
  });

  const notes: string[] = [
    added.artApplied > 0 ? `${added.artApplied} artwork image(s) applied` : "no artwork found",
  ];
  if (prepared.collection_name && !added.collection) {
    notes.push("could not add it to its collection");
  }
  if (prepared.warn_flatpak_sdcard) {
    notes.push("SD card access granted to the RetroArch flatpak");
  }

  // After the record exists, because installing one is matched against it.
  const waiting = probe?.content_waiting ?? [];
  const installed = waiting.length
    ? await installWaitingContent(added.appId, waiting, (one, index) => {
      onContentStep?.(one.label, index, waiting.length, one.name.toLowerCase().endsWith(".nsz"));
    })
    : [];
  if (installed.length) notes.push(`${installed.map((one) => one.label).join(", ")} installed`);

  return {
    ok: true, appId: added.appId, title: prepared.title, notes,
    romPath: prepared.rom_path || addPath,
    contentInstalled: installed.map((one) => one.name),
  };
}
