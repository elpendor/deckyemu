import { recordSetupShortcut, staleSetupShortcuts } from "./backend";
import { createShortcut, launchApp, removeShortcut, repointShortcut, setAppHidden, shortcutExists } from "./steam";

/**
 * The one Steam shortcut that opens an emulator's own window.
 *
 * Several emulators will only do certain jobs through their own UI — installing
 * PS3 firmware, importing Switch firmware — and there is no command-line
 * equivalent. gamescope composites nothing Steam did not launch, so running the
 * emulator from the plugin shows nothing at all: a Steam shortcut is the only
 * door.
 *
 * It used to be one shortcut per emulator, created on first use and kept
 * forever, which put a permanent library entry there for something opened once.
 * Now there is one, repointed at whichever emulator is being opened, and hidden
 * from the library.
 *
 * Shared by the Emulators tab and the firmware rows, which were doing the same
 * six steps separately.
 */

export interface SetupTarget {
  title: string;
  exe: string;
  start_dir?: string;
  /** The recorded shortcut, or 0 when there is not one yet. */
  app_id?: number;
}

/**
 * Point the setup shortcut at `target` and start it.
 *
 * Returns the appId on success, or 0 when Steam would not launch it — the
 * caller says so, because it can name what the user was trying to do.
 */
export async function openSetupShortcut(target: SetupTarget): Promise<number> {
  let appId = target.app_id ?? 0;

  // Steam reuses the ids of deleted shortcuts, so a remembered id is only good
  // if something still answers to it.
  if (!appId || !shortcutExists(appId)) {
    appId = await createShortcut({
      title: target.title,
      exe: target.exe,
      startDir: target.start_dir ?? "",
      launchOptions: "",
    });
    await recordSetupShortcut(appId);
    // Hidden once, when it is made. A failure is untidy rather than broken, so
    // nothing here depends on it having worked.
    setAppHidden(appId, true);
  } else {
    // The whole point of keeping one: it is pointed at a different emulator
    // rather than joined by another shortcut.
    repointShortcut(appId, target.exe);
  }

  return launchApp(appId) ? appId : 0;
}

/**
 * Delete the per-emulator shortcuts an older build left in the library.
 *
 * Handed over once by the backend, which forgets them as it returns them — so
 * this runs on a panel opening and does nothing at all from the second time on.
 */
export async function removeStaleSetupShortcuts(): Promise<number> {
  try {
    const stale = await staleSetupShortcuts();
    const ids = stale.app_ids ?? [];
    for (const appId of ids) {
      // No existence check: removing an id Steam no longer knows is a no-op,
      // and skipping one it does know would leave the entry there forever.
      removeShortcut(appId);
    }
    return ids.length;
  } catch (error) {
    console.error("[deckyemu] could not clear old setup shortcuts", error);
    return 0;
  }
}
