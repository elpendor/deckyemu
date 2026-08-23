/**
 * Selecting a ROM, shared by the file picker and the received-files list.
 *
 * Both entry points need the identical sequence -- probe the file, remember the
 * folder, pick a core, look up name and artwork -- and both write into the same
 * draft, so the work lives here rather than being duplicated per caller.
 */

import { addEventListener, removeEventListener, toaster } from "@decky/api";

import {
  installEmulator,
  installPs3Package,
  installPs4Package,
  installVitaPackage,
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
import { chooseSystem } from "./corePicker";
import { pendingPackage as pendingPackageOf } from "./packageState";
import {
  draftGeneration,
  getDraft,
  newDraftGeneration,
  updateDraft,
} from "./romDraft";
import { logError } from "./logError";

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
  system = "",
): Promise<void> {
  if (!romPath || !coreId) return;
  // Which draft this answer belongs to. Nothing here is awaited by its callers,
  // so the panel can be finished with this game -- added, or replaced by
  // another ROM -- long before the backend answers.
  const asked = draftGeneration();
  updateDraft({ looking: true, error: "" });
  try {
    // `system` decides which of a multi-system core's thumbnail directories is
    // searched first, so the cover matches the shelf the game is going on --
    // a Mega Drive ROM used to come back with a Game Gear cover.
    const result = await resolveGame(romPath, coreId, title, system);
    if (draftGeneration() !== asked) return;
    updateDraft({ resolved: result, title: result.title || title, looking: false });
  } catch (error) {
    logError("lookup failed", error);
    if (draftGeneration() !== asked) return;
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
    logError("could not select the installed game", error);
    updateDraft({ error: `Could not read the game ${name} installed.` });
    return false;
  }
}

/**
 * Make `romPath` the game being added: probe it, choose a core, resolve artwork.
 *
 * Errors land in the draft rather than throwing, because both callers are UI
 * handlers with nowhere useful to send an exception.
 */
export async function selectRom(romPath: string): Promise<void> {
  // A different game, so anything still in flight for the last one is no longer
  // an answer to anything -- see `newDraftGeneration`. Bumped before the first
  // write, so a lookup that returns during this function is already stale.
  newDraftGeneration();
  // `titleId` cleared with the rest: a file picked from disk is launched as a
  // file, and a leftover id from a previous selection would send the launcher
  // at the wrong game entirely.
  //
  // The unpack state goes too, and it is the one that outlives its own draft: a
  // package can still be extracting while this runs, and the progress bar it
  // owns belongs to the file the user has just moved on from. The extraction
  // finishes on its own and its own writes are dropped as stale.
  updateDraft({
    romPath,
    titleId: "",
    resolved: null,
    installable: [],
    unpacking: false,
    unpackPercent: 0,
    unpackStatus: "",
    error: "",
  });

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
      updateDraft({ coreId: "", systemId: "" });
      return;
    }

    if (info.suggested_core_id) {
      // The system comes with the core, because the file is what answers it:
      // the same `.md` that picks Genesis Plus GX also says it is a Mega Drive
      // cartridge rather than one of the five other systems that core covers.
      const system = chooseSystem(info, info.suggested_core_id);
      updateDraft({ coreId: info.suggested_core_id, systemId: system });
      await lookupArtwork(romPath, info.suggested_core_id, "", system);
      return;
    }

    // Nothing installed can run this, so offer the cores that could.
    updateDraft({ coreId: "", systemId: "" });
    // Except when the file is an archive whose contents nothing can run from
    // inside it. `match_extension` is "zip" there, and suggesting the cores that
    // claim `.zip` would offer to install an Amstrad CPC core to open an Xbox
    // 360 title -- the same wrong answer the matching list was just stopped from
    // giving, one step further on. The panel's Unpack button is the only route,
    // and it is already on screen.
    if (info.archived_content) return;
    try {
      // The selection goes with the list it belonged to: a core chosen for the
      // last ROM is not a choice anyone made about this one.
      updateDraft({
        installable: await suggestCoresForExtension(info.match_extension),
        installableId: "",
      });
    } catch (suggestError) {
      logError("could not fetch core suggestions", suggestError);
    }
  } catch (probeError) {
    logError("could not inspect the ROM", probeError);
    updateDraft({
      error: `Could not inspect that file: ${
        probeError instanceof Error ? probeError.message : String(probeError)
      }`,
    });
  }
}


/**
 * Unpack the package the draft is pointing at, then carry on from the game.
 *
 * Here rather than in `AddGamePanel` for the same reason the flags it sets live
 * in the draft: this outlasts the panel by minutes. A PS4 package is a long job
 * and the user will open the ROM picker, look at their library or close Quick
 * Access while it runs -- all of which unmount the panel. Anything owned by the
 * component stops existing at that moment.
 *
 * `romPath` is read from the draft rather than passed, so there is one answer to
 * which file this is about and it is the same one the rest of the flow uses.
 */
export function unpackPendingPackage(system: Console, keyName = ""): void {
  const romPath = getDraft().romPath;
  if (!romPath) return;
  // Which draft this install belongs to. Nothing awaits it, so the user can
  // pick another ROM while it runs -- and then the answer is about a file they
  // have moved on from. Written in anyway, it replaced their new selection with
  // the game that came out of the package. See `newDraftGeneration`.
  const asked = draftGeneration();
  const stale = () => draftGeneration() !== asked;
  updateDraft({
    error: "",
    unpacking: true,
    unpackPercent: 0,
    unpackStatus: "Starting...",
  });
  void (async () => {
    try {
      const result =
        system === "ps4"
          ? await installPs4Package(romPath)
          : system === "vita"
            ? // `keyName` is only set when the user picked a key that is not
              // named for this game. Without it the backend uses the one named
              // after the package, and refuses rather than guessing.
              await installVitaPackage(romPath, keyName)
            : await installPs3Package(romPath);
      if (!result.ok || !result.title_id) {
        // A failure still has to reach somebody. The error row is the right
        // place for it only while this is still the game on screen; after that
        // it would be an error about a file the panel is not showing.
        if (stale()) {
          toaster.toast({
            title: "That package did not install",
            body: result.error ?? "",
          });
        } else {
          updateDraft({ error: result.error ?? "The package did not install." });
        }
        return;
      }
      toaster.toast({
        title: `${result.title} installed`,
        // Worth saying: a licence going in without being asked for is the
        // difference between a game that boots and one that does not.
        body:
          ("licence" in result && result.licence ? "Its licence was installed too. " : "") +
          // The install happened either way; only the flow into the panel is
          // abandoned, and the game is still reachable from the list of what
          // the emulator has installed.
          (stale()
            ? "Choose a game to add it from the installed list."
            : "Finding its artwork."),
      });
      if (stale()) return;
      await selectPackagedGame(system, result.title_id);
    } catch (installError) {
      logError("package install failed", installError);
      if (stale()) return;
      updateDraft({
        error:
          installError instanceof Error
            ? installError.message
            : "The package did not install.",
      });
    } finally {
      // In a finally, so no path out of here can leave the panel claiming to
      // still be unpacking. Not once the draft has moved on: the flag there
      // belongs to whatever is being added now.
      if (!stale()) updateDraft({ unpacking: false, unpackPercent: 0, unpackStatus: "" });
    }
  })();
}

/**
 * Install the emulator a package needs, then unpack the package.
 *
 * One press for two steps because they are one intention: a `.pkg` is only ever
 * installed *into* an emulator, so with that emulator missing there is nothing
 * else the user could want here.
 *
 * **The listeners are registered here, at module scope, and that is the whole
 * point of this living in `addFlow`.** They were an effect inside the panel
 * first, and it did not work: installing an emulator takes half a minute and
 * launches it headless in gamescope, so the Quick Access panel is unmounted for
 * most of it. `emulator_install_done` then fired with nothing subscribed, the
 * unpack never followed, and the row sat on "Installing..." forever. Measured
 * on a device -- shadPS4 installed at 18:12:37 and the package it was installed
 * for was still sitting in the transfer folder.
 *
 * The draft already held the *flag* across that unmount. Holding the flag and
 * not the listener is the shape of the bug: half the state survived and the
 * thing that would act on it did not.
 *
 * `installEmulator` starts the install and reports the end by event, unlike
 * `installCore` which resolves -- which is why there is a subscription at all.
 */
export async function installEmulatorAndUnpack(emulatorId: string): Promise<void> {
  updateDraft({
    error: "",
    installingEmulator: emulatorId,
    emulatorPercent: 0,
    emulatorStatus: "Starting...",
  });

  // Only this emulator: an install started from the Emulators tab emits the
  // same events and must not drive this bar or trigger an unpack nobody asked
  // for.
  const onProgress = (id: string, text: string, percent: number) => {
    if (id !== emulatorId) return;
    updateDraft({ emulatorStatus: text, emulatorPercent: percent });
  };

  const stop = () => {
    removeEventListener("emulator_install_progress", progress);
    removeEventListener("emulator_install_done", done);
  };

  const onDone = (id: string, ok: boolean, message: string) => {
    if (id !== emulatorId) return;
    stop();
    updateDraft({ installingEmulator: "", emulatorPercent: 0, emulatorStatus: "" });
    if (!ok) {
      updateDraft({ error: message || "The install did not complete." });
      return;
    }
    void continueAfterEmulator();
  };

  const progress = addEventListener<[id: string, text: string, percent: number]>(
    "emulator_install_progress",
    onProgress,
  );
  const done = addEventListener<[id: string, ok: boolean, message: string]>(
    "emulator_install_done",
    onDone,
  );

  try {
    const result = await installEmulator(emulatorId);
    if (!result.ok) {
      stop();
      updateDraft({
        error: result.error ?? "Could not start the install.",
        installingEmulator: "",
      });
    }
  } catch (startError) {
    logError("emulator install could not start", startError);
    stop();
    updateDraft({ error: "Could not start the install.", installingEmulator: "" });
  }
}

/**
 * Re-read the package now the emulator is there, and unpack it.
 *
 * The re-probe is what takes the offer off screen: `emulator_ready` came from
 * the probe, so without it the row would still be offering an install while the
 * unpack ran behind it.
 *
 * Exported because it is also the recovery path. If the done event is missed
 * entirely -- the plugin reloading mid-install would do it -- the panel asks on
 * its next mount whether the emulator arrived, and this is what it calls.
 */
export async function continueAfterEmulator(): Promise<boolean> {
  const romPath = getDraft().romPath;
  if (!romPath) return false;
  try {
    const info = await probeRom(romPath);
    updateDraft({ probe: info });
    const nowPending = pendingPackageOf(info);
    // Gone means the package installed itself somehow, or the file moved.
    // Either way there is nothing left here to unpack.
    if (!nowPending || !nowPending.state.emulator_ready) return false;
    unpackPendingPackage(nowPending.system, getDraft().keyChoice);
    return true;
  } catch (probeError) {
    logError("could not re-read the package after installing", probeError);
    updateDraft({
      error: "The emulator is installed. Press install again to unpack the game.",
    });
    return false;
  }
}
