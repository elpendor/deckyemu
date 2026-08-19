import { toaster } from "@decky/api";

import { prepareFirmwareGui } from "./backend";
import { openSetupShortcut } from "./setupShortcut";
import { logError } from "./logError";

/**
 * Install a requirement the emulator will only take through its own window.
 *
 * Ryujinx's Switch firmware is the case: `--install-firmware` is read inside
 * the main window and then waits on a Yes/No dialog, so there is no headless
 * route. A window is only ever composited if Steam launched the process, which
 * is why this goes out through the one hidden setup shortcut rather than being
 * run from the plugin.
 *
 * Shared rather than written twice. The settings page had it and the transfer
 * dialog did not, so pressing Install there fell through to the copy path --
 * which has no destination for this requirement and returned its `manual` text
 * as an error. The user saw "Press Install: Ryujinx opens with the file already
 * chosen" *as the reason it had failed*, which reads as the plugin telling them
 * to do the thing they had just done.
 *
 * Returns whether the emulator was actually started, so a caller can decide
 * what to re-read; every failure is reported here as a toast, because both
 * callers would otherwise say the same three things in the same three ways.
 */
export async function installThroughEmulator(
  entryId: string,
  emulatorName: string,
  requirement: string,
  prompt?: string,
): Promise<boolean> {
  try {
    const prepared = await prepareFirmwareGui(entryId, requirement);
    if (!prepared.ok || !prepared.exe) {
      toaster.toast({ title: "Could not open", body: prepared.error ?? "" });
      return false;
    }

    // The one setup shortcut, repointed at the script just written to carry
    // the install argument.
    const appId = await openSetupShortcut({
      title: prepared.title ?? emulatorName,
      exe: prepared.exe,
      start_dir: prepared.start_dir,
      app_id: prepared.app_id,
    });
    if (!appId) {
      toaster.toast({
        title: `Could not open ${emulatorName}`,
        // Hidden, so pointing at "your library" would send somebody looking
        // where it does not appear.
        body: `Steam would not start it. "${prepared.title}" is in your hidden games if you want to run it yourself.`,
      });
      return false;
    }

    toaster.toast({
      title: `${emulatorName} is opening`,
      body: prompt || `${prepared.file} is ready to install.`,
    });
    return true;
  } catch (error) {
    logError("could not open the emulator to install firmware", error);
    toaster.toast({ title: "Could not open", body: `${error}` });
    return false;
  }
}
