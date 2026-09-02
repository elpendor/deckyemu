import type { CatalogEmulator } from "./backend/firmware";

/**
 * What to say about the motion server.
 *
 * **It says so when it is working too**, unlike the version line above, and the
 * first version of this did not -- which made it useless for the question it
 * was built to answer. "How do I know it is installed?" cannot be answered by a
 * row that stays quiet when it is: silence and success looked identical, so the
 * only way to check remained reading a log over SSH.
 *
 * The noise argument does not apply here the way it does to versions. Two
 * entries in the catalog declare motion; every other row is unchanged, so this
 * is two short words on two rows rather than a line per emulator.
 *
 * Only an installed emulator. Before that the server has not been fetched and
 * saying anything would report a step that has not been reached.
 */
export function motion(entry: CatalogEmulator): string {
  if (!entry.motion?.declared || !entry.present) return "";
  if (entry.motion.ready && entry.motion.configured) return "motion ready";
  // The binary is here and the emulator is not using it, because its own
  // controller config is the user's and this plugin will not overwrite it.
  // Named rather than shown as ready: "ready" and "does nothing" looking
  // the same is the fault this whole line exists to remove.
  if (entry.motion.ready) return "motion server installed, but this emulator's own controller settings are not using it";
  // A wait is not a failure, and the difference matters: a rate-limited address
  // fixes itself, so naming the wait turns "gyro is broken" into "gyro shortly".
  if (entry.motion.waiting > 0) {
    const minutes = Math.ceil(entry.motion.waiting / 60);
    return `motion server retrying in ${minutes} min`;
  }
  return "motion server not downloaded yet";
}
