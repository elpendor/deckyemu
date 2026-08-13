/**
 * The one-glance state of a firmware requirement.
 *
 * The panel already says all of this in prose, and prose is what gets skimmed:
 * a row reading "Cemu cannot decrypt a WUD or WUX disc image without the key"
 * looks the same at arm's length as one reading "In place: keys.txt". A symbol
 * per row answers "is this fine?" without reading anything, and the words stay
 * for when the answer is no.
 *
 * Three states rather than two, because "the file is in the transfer folder but
 * not installed yet" is neither fine nor missing -- it is the one state where
 * the fix is a single press, and collapsing it into either of the others hides
 * the cheapest thing the user could do.
 */

export type FirmwareRowState = "installed" | "waiting" | "missing";

/** Only the parts of a requirement this needs, so tests need not build one. */
export interface FirmwareCounts {
  installed: string[];
  waiting: string[];
}

/**
 * Which state a requirement is in.
 *
 * Installed wins over waiting: a spare copy still sitting in the transfer
 * folder is housekeeping, not an outstanding task, and the row says so in its
 * own words. Ordering it the other way would flag a satisfied requirement as
 * needing attention for as long as the source file was left lying about.
 */
export function firmwareState(requirement: FirmwareCounts): FirmwareRowState {
  if (requirement.installed.length > 0) return "installed";
  if (requirement.waiting.length > 0) return "waiting";
  return "missing";
}

/** The worst state among a set, for a summary beside the emulator's name. */
export function worstState(requirements: FirmwareCounts[]): FirmwareRowState {
  const states = requirements.map(firmwareState);
  if (states.includes("missing")) return "missing";
  if (states.includes("waiting")) return "waiting";
  return "installed";
}

/**
 * Colours, deliberately not red for "missing".
 *
 * Missing firmware is a prerequisite nobody has met yet, not a fault: on a
 * fresh install every one of these is missing, and a column of red on first run
 * reads as a broken plugin. Amber says "your turn" -- red is kept for the
 * things that actually went wrong, matching the error text elsewhere.
 */
export const STATE_COLOR: Record<FirmwareRowState, string> = {
  installed: "#4ca94c",
  waiting: "#e0a33e",
  missing: "#e0a33e",
};

/** Read out by assistive tooling, and the answer to "what is that symbol". */
export const STATE_TITLE: Record<FirmwareRowState, string> = {
  installed: "In place",
  waiting: "Waiting to be installed",
  missing: "Not supplied yet",
};
