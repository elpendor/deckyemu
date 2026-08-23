import { type UpdateCheck } from "./backend";

/**
 * Whether a newer DeckyEmu exists, held where anything can read it.
 *
 * Module scope rather than component state because the two things that show it
 * live in different places: the row is inside the panel's `Content`, which only
 * exists while the panel is open, and the dot is on the plugin's Quick Access
 * icon, which is rendered once when the plugin loads and outlives every panel.
 * Neither can be the other's parent, so the answer belongs to neither.
 *
 * Two things write here. The backend's timer, through decky's event channel,
 * which is what makes the dot right before anybody opens anything; and the
 * panel's own check on open, which is the one that governs what a user sees:
 * the timer is a floor for a device nobody opens the panel on, and it counts
 * awake time rather than clock time (see `_UPDATE_INTERVAL`). Opening the panel
 * checks, at most hourly.
 *
 * The same pattern and the same reasoning as `addedGames.ts`, which keeps the
 * library list here for a context menu that cannot await.
 */
export interface UpdateSignal {
  available: boolean;
  /** Empty unless `available`. The row needs it; the dot does not. */
  version: string;
}

let signal: UpdateSignal = { available: false, version: "" };

/**
 * Whether the dot is wanted at all.
 *
 * Kept beside the answer rather than read where it is drawn: the icon is
 * created once when the plugin loads and the switch is in the Updates tab, two
 * trees that never meet, so flipping it has to reach the icon through here or
 * the dot stays put until something reloads.
 *
 * Assumed on until told otherwise, which matches the stored default. The
 * alternative -- start off, turn on once the setting has been read -- makes the
 * dot flicker in a moment after every load.
 */
let dotEnabled = true;

const listeners = new Set<() => void>();

function notify(): void {
  // Over a copy: a listener that unsubscribes in response would otherwise be
  // mutating the set being iterated.
  for (const listener of [...listeners]) listener();
}

/** What is known right now. Safe to call while rendering. */
export function currentUpdate(): UpdateSignal {
  return signal;
}

/**
 * Record what a check found.
 *
 * Both directions, because "no longer available" is a real transition -- the
 * user installed it -- and a signal that only ever says yes can light the dot
 * but never put it out.
 */
export function noteUpdate(available: boolean, version: string): void {
  const next = { available: available && Boolean(version), version: available ? version : "" };
  // Unchanged means nobody is told. Otherwise every check on every panel open
  // re-renders the icon to redraw the same dot.
  if (next.available === signal.available && next.version === signal.version) return;

  signal = next;
  notify();
}

/** Follow the stored setting. Called at load, and again when it is changed. */
export function setUpdateDotEnabled(on: boolean): void {
  if (on === dotEnabled) return;
  dotEnabled = on;
  notify();
}

/**
 * Whether to draw the dot: an update exists *and* the user wants to hear it.
 *
 * Only the dot is gated. The row inside the panel and the Updates tab both stay
 * as they are -- turning off an unsolicited notification is not a request to be
 * refused the information when you go looking for it.
 */
export function updateDotVisible(): boolean {
  return dotEnabled && signal.available;
}

/**
 * Record what a check came back with, which is not the same as what it found.
 *
 * A check that could not reach GitHub says nothing about whether an update
 * exists -- but it reports `available: false`, which is indistinguishable from
 * "you are up to date" unless `checked` is read as well. Taking it at face
 * value puts out a dot a working check had lit: one panel open on a train and
 * the update is forgotten until the timer comes round hours later.
 *
 * The backend's watch already had this rule. Both frontend callers were written
 * without it, which is why it is here now rather than at each of them.
 */
export function noteCheck(check: UpdateCheck | null | undefined): void {
  if (!check?.checked) return;
  noteUpdate(Boolean(check.available), check.latest?.version ?? "");
}

/** Subscribe. The returned function unsubscribes, and must be called. */
export function watchUpdates(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
