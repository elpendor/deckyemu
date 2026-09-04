/**
 * How long ago something happened, said the way a person would say it.
 *
 * A clock time would be more precise and less useful. What somebody is asking
 * when they read this is "did the thing I just did get copied?", and "16:04"
 * only answers that if they also know what time it is now. "just now" answers
 * it directly.
 *
 * Rounded rather than exact for the same reason: a save copied 91 seconds ago
 * and one copied 89 seconds ago are the same event to whoever is reading, and a
 * line that ticks over from "just now" to "1 minutes ago" is worse at its job
 * than one that does not.
 */
export function ago(seconds: number, now: number = Date.now()): string {
  // Unix seconds in, milliseconds for the clock: the backend records
  // `time.time()` and JS counts in milliseconds, and mixing the two silently
  // produces "20 thousand days ago".
  const past = Math.max(0, Math.floor(now / 1000) - Math.floor(seconds));
  if (past < 90) return "just now";
  if (past < 3600) return `${Math.round(past / 60)} minutes ago`;
  if (past < 86400) {
    const hours = Math.round(past / 3600);
    return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  }
  const days = Math.round(past / 86400);
  return days === 1 ? "yesterday" : `${days} days ago`;
}
