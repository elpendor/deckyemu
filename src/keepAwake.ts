import { addEventListener, removeEventListener } from "./host";

type Store = { BlockSuspendAction?: () => () => void };

/**
 * Keep Steam from going to sleep until `event` fires.
 *
 * Steam's own blocker, the one its downloads use. The service also holds a
 * system inhibitor, but that alone only refuses the sleep: Steam has already
 * blanked the screen by then and stays black until woken by hand.
 *
 * Module-level rather than in a dialog, so closing the dialog mid-copy does
 * not let the Deck sleep.
 */
export function keepAwakeUntil(event: string): () => void {
  const release = keepAwake();
  const stop = () => {
    removeEventListener(event, listener);
    release();
  };
  const listener = addEventListener(event, stop);
  return stop;
}

/** Keep Steam awake until the returned function is called (once is enough). */
export function keepAwake(): () => void {
  const store = (window as unknown as { SuspendResumeStore?: Store }).SuspendResumeStore;
  const release = store?.BlockSuspendAction?.();
  let held = Boolean(release);
  return () => {
    if (held) release?.();
    held = false;
  };
}
