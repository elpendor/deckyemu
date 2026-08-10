/**
 * A date somebody can read, out of what flatpak prints.
 *
 * `2026-07-26 20:53:49 +0000` is accurate and unreadable at a glance. The day is
 * what distinguishes one build from another when choosing which to go back to;
 * the seconds never are.
 *
 * Its own module rather than living beside the dialog that uses it, because
 * anything importing `@decky/ui` cannot be imported under Node -- Steam's
 * components are resolved by sniffing webpack modules at import time -- so a
 * helper kept in the .tsx is a helper with no tests.
 */
export function buildDate(raw: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw.trim());
  // Shown as it came when the shape is not the one flatpak prints. The rollback
  // list is chosen from by date, so a blank row is one nobody can tell from its
  // neighbour -- ugly beats absent when the alternative is picking at random.
  return match ? `${match[3]}/${match[2]}/${match[1]}` : raw.trim();
}
