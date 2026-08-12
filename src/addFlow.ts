/**
 * Selecting a ROM, shared by the file picker and the received-files list.
 *
 * Both entry points need the identical sequence -- probe the file, remember the
 * folder, pick a core, look up name and artwork -- and both write into the same
 * draft, so the work lives here rather than being duplicated per caller.
 */

import {
  listInstalledPs3Games,
  listInstalledPs4Games,
  listInstalledVitaGames,
  probeRom,
  ps3CoreId,
  ps4CoreId,
  vitaCoreId,
  resolveGame,
  setSettings,
  suggestCoresForExtension,
} from "./backend";
import { updateDraft } from "./romDraft";

/**
 * The two consoles whose games arrive as packages rather than as ROMs.
 *
 * Identical from here on — unpack, then carry on from the eboot inside — so the
 * difference is only which backend answers. `.pkg` does not say which console
 * it is for; the backend decides that from the file's magic and the probe says
 * which one it found.
 */
export type Console = "ps3" | "ps4" | "vita";

const CONSOLES = {
  ps3: { games: listInstalledPs3Games, core: ps3CoreId, name: "RPCS3" },
  ps4: { games: listInstalledPs4Games, core: ps4CoreId, name: "shadPS4" },
  vita: { games: listInstalledVitaGames, core: vitaCoreId, name: "Vita3K" },
} as const;

export const SYSTEM_NAME: Record<Console, string> = {
  ps3: "Sony - PlayStation 3",
  ps4: "Sony - PlayStation 4",
  vita: "Sony - PlayStation Vita",
};

/**
 * What the draft's error says when the lookup itself did not complete.
 *
 * Exported so the panel can recognise this one failure rather than guess at it
 * from the absence of a result -- "no artwork" is also the state of a ROM whose
 * core has not been chosen yet, and those two want different offers.
 */
export const LOOKUP_FAILED = "Lookup failed. You can still set a name manually and add the game.";

/**
 * Look up name and artwork for a ROM/core pair, writing into the draft.
 *
 * `title` overrides the name taken from the filename. Only PS3 games need it so
 * far, and they need it badly: every one of them boots `USRDIR/EBOOT.BIN`, so
 * the search would otherwise go looking for a game called "EBOOT".
 */
export async function lookupArtwork(
  romPath: string,
  coreId: string,
  title = "",
): Promise<void> {
  if (!romPath || !coreId) return;
  updateDraft({ looking: true, error: "" });
  try {
    const result = await resolveGame(romPath, coreId, title);
    updateDraft({ resolved: result, title: result.title || title, looking: false });
  } catch (error) {
    console.error("[deckyemu] lookup failed", error);
    updateDraft({
      resolved: null,
      looking: false,
      // A PS3 game's name comes from its PARAM.SFO, not from the lookup, so a
      // failed lookup must not drop it back to "EBOOT".
      ...(title ? { title } : {}),
      error: LOOKUP_FAILED,
    });
  }
}

/**
 * Make an installed PS3 or PS4 game the game being added.
 *
 * The path here is one nobody would ever pick by hand, which is the point: the
 * user chose a `.pkg`, it was unpacked, and this carries on from the eboot that
 * came out — under the name in the game's own param.sfo, so SteamGridDB is
 * asked about "Braid" rather than about a filename.
 */
export async function selectPackagedGame(
  system: Console,
  titleId: string,
): Promise<boolean> {
  const { games: listGames, core: coreId, name } = CONSOLES[system];
  try {
    const [games, core] = await Promise.all([listGames(), coreId()]);
    const game = games.games.find((item) => item.title_id === titleId);
    if (!game || !core.ok || !core.core_id) {
      updateDraft({
        error:
          core.error || `${name} unpacked the package but the game did not appear.`,
      });
      return false;
    }

    updateDraft({
      romPath: game.eboot,
      // Carried so the ordinary Add button builds the right launcher. Vita3K
      // starts a title id, not a path, and without this the generic add path
      // wrote a shortcut pointing at eboot.bin -- which opens Vita3K's app
      // list instead of the game.
      titleId: game.title_id,
      // Cleared so the panel stops offering to install a package that is now a
      // game, and so the core dropdown reflects the EBOOT rather than the .pkg.
      probe: null,
      coreId: core.core_id,
      title: game.title,
      resolved: null,
      installable: [],
      error: "",
    });
    await lookupArtwork(game.eboot, core.core_id, game.title);
    return true;
  } catch (error) {
    console.error("[deckyemu] could not select the installed game", error);
    updateDraft({ error: `Could not read the game ${name} installed.` });
    return false;
  }
}

/** Kept for the PS3 games picker, which only ever lists one console's games. */
export const selectPs3Game = (titleId: string) => selectPackagedGame("ps3", titleId);

/**
 * Make `romPath` the game being added: probe it, choose a core, resolve artwork.
 *
 * Errors land in the draft rather than throwing, because both callers are UI
 * handlers with nowhere useful to send an exception.
 */
export async function selectRom(romPath: string): Promise<void> {
  // `titleId` cleared with the rest: a file picked from disk is launched as a
  // file, and a leftover id from a previous selection would send the launcher
  // at the wrong game entirely.
  updateDraft({ romPath, titleId: "", resolved: null, installable: [], error: "" });

  try {
    const info = await probeRom(romPath);
    updateDraft({
      probe: info,
      title: info.provisional_title,
      showAllCores: info.matching_cores.length === 0,
    });

    const directory = romPath.slice(0, Math.max(0, romPath.lastIndexOf("/")));
    if (directory) {
      // Reopens the picker where the user last was.
      setSettings({ last_rom_dir: directory }).catch(() => undefined);
    }

    // A package already unpacked is not a package any more: carry straight on
    // from the game inside it, so picking the same .pkg twice does not offer to
    // install what is already installed.
    const packaged = info.ps4_package
      ? (["ps4", info.ps4_package] as const)
      : info.vita_package
        ? (["vita", info.vita_package] as const)
        : info.ps3_package
          ? (["ps3", info.ps3_package] as const)
          : null;
    if (packaged) {
      const [system, state] = packaged;
      if (state.installed) {
        await selectPackagedGame(system, state.title_id);
        return;
      }
      // Not installed, so this stops here. The panel shows an Unpack step,
      // because unpacking takes real time and consumes the file, and neither is
      // something to do behind a file picker closing. The core is cleared with
      // it: a package cannot be launched by anything, and leaving whatever was
      // selected for the last ROM would let Add build a launcher pointing at it.
      updateDraft({ coreId: "" });
      return;
    }

    if (info.suggested_core_id) {
      updateDraft({ coreId: info.suggested_core_id });
      await lookupArtwork(romPath, info.suggested_core_id);
      return;
    }

    // Nothing installed can run this, so offer the cores that could.
    updateDraft({ coreId: "" });
    try {
      updateDraft({ installable: await suggestCoresForExtension(info.match_extension) });
    } catch (suggestError) {
      console.error("[deckyemu] could not fetch core suggestions", suggestError);
    }
  } catch (probeError) {
    console.error("[deckyemu] could not inspect the ROM", probeError);
    updateDraft({
      error: `Could not inspect that file: ${
        probeError instanceof Error ? probeError.message : String(probeError)
      }`,
    });
  }
}
