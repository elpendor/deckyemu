import { registerGame, type ArtImage } from "./backend";
import { createOrReuseShortcut } from "./reuseShortcut";
import { addToCollection, applyArtwork, removeShortcut } from "./steam";

/**
 * Putting a prepared game into Steam: the five steps, in the one order.
 *
 * The backend writes the launcher and says what Steam needs; everything after
 * that is Steam-side and therefore only doable from here. Two panels did these
 * five steps separately -- the add flow and the Vita list -- and they had
 * already drifted: one rolled the shortcut back when a later step threw and the
 * other left it standing, so a failed add from the Vita list put an entry in the
 * library that nothing tracked.
 *
 * One step of the order is load-bearing: filing comes before registering,
 * because what gets registered is *where the game went*, and that is not known
 * until the attempt has been made.
 */

interface Prepared {
  title: string;
  exe: string;
  start_dir: string;
  launch_options: string;
  launcher_path: string;
  collection_name: string;
  rom_path?: string;
}

export interface AddGameArgs {
  prepared: Prepared;
  /** The ROM the caller picked, for the case where the backend did not move it. */
  romPath: string;
  coreId: string;
  /** The database resolveGame settled on; decides the collection for a multi-system core. */
  system?: string;
  art?: Partial<Record<"capsule" | "header" | "hero" | "logo", ArtImage>>;
  /** False for a game whose boot file is not named after it -- see registerGame. */
  rememberCore?: boolean;
}

export interface AddGameResult {
  appId: number;
  /** Whether a shortcut that was already there was taken over rather than made. */
  reused: boolean;
  /** How many artwork slots stuck. */
  artApplied: number;
  /** The collection the game actually went into, which is "" when it did not. */
  collection: string;
}

/**
 * Create or reuse the shortcut, dress it, file it, and record it.
 *
 * Throws whatever any step throws, having first undone the shortcut *if this
 * call is what made it*. That condition is the part worth keeping: rolling back
 * unconditionally deleted a shortcut that existed before the add started, which
 * is somebody's working game removed because an unrelated step failed.
 */
export async function addPreparedGame(args: AddGameArgs): Promise<AddGameResult> {
  const { prepared } = args;

  const { appId, reused } = await createOrReuseShortcut({
    title: prepared.title,
    exe: prepared.exe,
    startDir: prepared.start_dir,
    launchOptions: prepared.launch_options,
  });

  try {
    const artApplied = args.art ? await applyArtwork(appId, args.art) : 0;

    /*
     * Recorded from the attempt, not assumed from the settings.
     *
     * The registry's `collection` is what a later rename moves the game out of
     * and what removing it empties, so it has to mean "where this game went" --
     * and filing can fail while everything else succeeds, if Steam is mid-update
     * or the collection cannot be created. The backend used to compute the name
     * a second time and record that, which said the game was on a shelf it had
     * never reached: the rename then moved it from a collection it was not in,
     * and removing it emptied nothing.
     */
    const wanted = prepared.collection_name;
    const collection = wanted && (await addToCollection(appId, wanted)) ? wanted : "";

    await registerGame(
      appId,
      prepared.title,
      // Where the ROM ended up, not where it was picked from: adding a game
      // files it out of the transfer folder and into one named after its
      // system, and the library has to record the path the launcher runs or
      // every filed game reads as an orphan.
      prepared.rom_path || args.romPath,
      args.coreId,
      prepared.launcher_path,
      args.system ?? "",
      args.rememberCore ?? true,
      collection,
    );

    return { appId, reused, artApplied, collection };
  } catch (error) {
    // Only what this call created. A reused shortcut was there before and is
    // not ours to withdraw over a failure further down.
    if (!reused) removeShortcut(appId);
    throw error;
  }
}
