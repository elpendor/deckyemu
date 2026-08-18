/**
 * The in-progress "add a game" selection, held outside React.
 *
 * Steam unmounts a Quick Access panel's content when a modal opens over it, so
 * the file picker destroys the panel that launched it. Anything kept in
 * component state is lost, and worse, the artwork lookup that was already in
 * flight resolves into a component that no longer exists -- the ROM is picked,
 * the backend does all the work, and the UI shows nothing.
 *
 * Keeping the draft in module scope fixes both halves: state survives the
 * remount, and late-arriving async results are stored and broadcast to whatever
 * instance is mounted at the time.
 */

import type { InstallableCore, ResolvedGame, RomProbe } from "./backend";

export interface RomDraft {
  romPath: string;
  /**
   * The installed title this game is, for emulators that start a title id
   * rather than a file. Vita3K only — everything else ignores it, and a ROM
   * picked from disk clears it.
   */
  titleId: string;
  probe: RomProbe | null;
  coreId: string;
  showAllCores: boolean;
  /**
   * Which of a multi-system core's systems this game is, or "" when the core
   * covers one and there is nothing to ask.
   *
   * Here rather than in component state for the reason `installableId` is: the
   * row is a dropdown, a dropdown opens a ContextMenu, and that unmounts the
   * panel behind it exactly as a modal does -- so a choice held in `useState`
   * is discarded on the way back and the row snaps to its first entry, which
   * for Genesis Plus GX is Game Gear.
   */
  systemId: string;
  resolved: ResolvedGame | null;
  title: string;
  installable: InstallableCore[];
  /**
   * Which of `installable` the install button would install. "" means the first.
   *
   * Here rather than in component state because a Steam dropdown opens a
   * ContextMenu, and that unmounts the panel behind it exactly as a modal does
   * -- so a selection held in `useState` is discarded on the way back and the
   * list snaps to its first entry. Picking anything but the default was
   * impossible until this moved.
   */
  installableId: string;
  /**
   * Which licence key the user said belongs to a Vita package, or "".
   *
   * Here for the same reason as `installableId`, and it matters more: the wrong
   * key installs the game and then fails to decrypt it, so a choice that
   * silently reverts to the first candidate is a choice the user made and did
   * not get. Resolved against the candidate list, so a stale name from another
   * ROM falls back rather than reaching the backend.
   */
  keyChoice: string;
  looking: boolean;
  adding: boolean;
  installingCore: string;
  error: string;
}

export const EMPTY_DRAFT: RomDraft = {
  romPath: "",
  titleId: "",
  probe: null,
  coreId: "",
  showAllCores: false,
  systemId: "",
  resolved: null,
  title: "",
  installable: [],
  installableId: "",
  keyChoice: "",
  looking: false,
  adding: false,
  installingCore: "",
  error: "",
};

let draft: RomDraft = EMPTY_DRAFT;

type Listener = (next: RomDraft) => void;
const listeners = new Set<Listener>();

export function getDraft(): RomDraft {
  return draft;
}

/** Merge a patch into the draft and notify any mounted panel. */
export function updateDraft(patch: Partial<RomDraft>): RomDraft {
  draft = { ...draft, ...patch };
  for (const listener of listeners) {
    listener(draft);
  }
  return draft;
}

export function resetDraft(): RomDraft {
  return updateDraft(EMPTY_DRAFT);
}

export function subscribeDraft(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
