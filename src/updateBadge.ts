import { type UpdateCheck } from "./backend";

/**
 * Whether the panel should mention that a newer DeckyEmu exists, and how.
 *
 * A separate module from the panel for the same reason as `deviceGate`: the
 * decision is the part worth being sure about, and the panel is not where a
 * test can reach it.
 *
 * There is deliberately no toast. The alternative considered was a Steam
 * notification when a check finds something, and it was dropped: it would fire
 * on every panel open until the user gave in, there is no good moment for one
 * in Game Mode, and the thing it interrupts is a game. A row that is simply
 * there when you next open the panel says the same thing and costs nothing.
 */
export interface UpdateBadge {
  label: string;
  description: string;
}

/**
 * `null` whenever there is nothing certain to say.
 *
 * A failed check, a check that has not run yet, and a check that found nothing
 * all read the same way here -- as silence. The Updates tab is where a failure
 * is explained, because that is where somebody has gone to ask; putting "could
 * not reach GitHub" in front of somebody who opened the panel to launch a game
 * is noise about a thing they were not doing.
 */
export function updateBadge(check: UpdateCheck | null | undefined): UpdateBadge | null {
  if (!check?.available) return null;

  // `available` is computed against `latest` in the backend, so this cannot
  // normally be missing -- but the panel would render "undefined is out" if it
  // ever were, and a version number is the whole content of the row.
  const version = check.latest?.version;
  if (!version) return null;

  return {
    // No plugin name: this row is inside DeckyEmu's own panel, under a header
    // that says DeckyEmu. The Updates tab has said "Version X is available."
    // since long before this row existed, and two wordings for one fact read as
    // two different facts.
    label: `Version ${version} is available`,
    // Naming what is installed as well: the useful question on seeing this is
    // "how far behind am I", and the answer is otherwise two screens away.
    description: check.current
      ? `You are running ${check.current}.`
      : "Open the Updates tab to install it.",
  };
}
