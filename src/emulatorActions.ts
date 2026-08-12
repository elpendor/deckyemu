import type { CatalogEmulator } from "./backend";

/**
 * Which buttons a catalog row offers.
 *
 * Extracted because getting it wrong is invisible. A row with a missing button
 * does not throw and does not log -- the emulator simply looks like it cannot be
 * installed, with nothing saying why. That shipped once: install and forget were
 * decided by one `imported ? … : …` chain, which was correct only while an
 * imported entry was always bring-your-own. The moment an imported definition
 * could name a source, the chain reached Forget first and the download button
 * became unreachable.
 *
 * So the rule is stated once, as data, over independent facts:
 *
 * * `kind` decides how the emulator is obtained -- and `byo` means the plugin
 *   never obtains it, so there is nothing to install or remove.
 * * `present` decides install versus remove.
 * * `imported` decides only whether the *definition* can be forgotten. It says
 *   where the entry came from, not how the emulator is obtained.
 */
export interface RowActions {
  /** Point a bring-your-own entry at a binary the user already has. */
  locate: boolean;
  /** Download or install it. */
  install: boolean;
  /** Uninstall what the plugin installed. */
  remove: boolean;
  /** Forget an imported definition. Never removes the emulator itself. */
  forget: boolean;
  /** Register something already on the device but unknown to the plugin. */
  register: boolean;
  /** Open the emulator's own window. */
  gui: boolean;
}

export function emulatorRowActions(entry: CatalogEmulator): RowActions {
  const obtainable = entry.kind !== "byo";
  return {
    locate: entry.kind === "byo",
    install: obtainable && !entry.present,
    remove: obtainable && entry.present,
    forget: Boolean(entry.imported),
    // Present but not registered is a real state: Discover and the usual
    // emulation setups install these same flatpaks, and one that arrived that
    // way has no extensions and never appears when adding a game.
    register: entry.present && !entry.registered,
    // Opening the interface of an emulator the plugin knows nothing about would
    // give a window with nothing behind it.
    gui: entry.present && entry.registered,
  };
}
