/**
 * The plugin build's `src/host`: the loader's API, under the names the shared
 * panel imports. The build puts this module in place of `src/host/index.ts`.
 */

import { Navigation, QuickAccessTab } from "./steamui";
import { canInstallUpdates, installUpdate } from "./updater";
import type { Staged } from "../../src/host/updates";

export * from "@decky/api";
export type { Staged };

/**
 * A real enum, beside the loader's `const enum` of the same values. The shared
 * panel is compiled against the service's host, where it is a value, so it
 * imports one; a `const enum` has nothing to import at runtime.
 */
export enum FileSelectionType {
  FILE = 0,
  FOLDER = 1,
}

/** See src/host/updates.ts. The loader installs, after its own confirmation. */
export const updates = {
  available: canInstallUpdates,
  how: "The loader downloads and installs it, then reloads the plugin.",
  unavailable: "The loader's installer is not reachable from this window.",
  noAnswer: "The loader did not accept the request.",
  // Our icon shows in the loader's plugin list, beside the name, where a badge
  // sits just outside the button's corner.
  dotOffset: "-5px",
  async finish(staged: Staged, version: string): Promise<{ title: string; body: string }> {
    if (!staged.url) throw new Error("The update was not offered to the loader.");
    await installUpdate(staged.url, staged.version ?? version, staged.sha256 ?? "");
    return { title: `Installing ${staged.version ?? version}`, body: "The loader will confirm and show progress." };
  },
};

/** Open the Quick Access menu on the loader's tab, where ours is. */
export function openPanel(): void {
  Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
}
