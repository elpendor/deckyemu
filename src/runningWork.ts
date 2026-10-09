import { type RunningWork } from "./backend";

/**
 * Reading what the backend is still doing, for a panel that has just opened.
 *
 * Pure and apart from the components, because "which row is busy" is the part
 * worth being sure of and there is no DOM here to test a component with.
 */

/** Whether `event` has anything running, whatever it was started for. */
export function isRunning(work: RunningWork[], event: string): boolean {
  return work.some((item) => item.event === event);
}

/**
 * The id the running `event` was started for, or "" when it is not running.
 *
 * The first argument is the id by the convention every `*_done` event with one
 * follows (`emulator_install_done(id, ok, message)`). Anything else -- no
 * arguments, or one that is not a string -- reads as no id rather than being
 * guessed at, so a row is never marked busy for something it did not start.
 */
export function runningId(work: RunningWork[], event: string): string {
  const found = work.find((item) => item.event === event);
  const id = found?.args?.[0];
  return typeof id === "string" ? id : "";
}
