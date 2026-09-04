import type { CSSProperties } from "react";

/**
 * The two measurements every dialog in this plugin was making up for itself.
 *
 * Written down for the same reason `iconButton.ts` was: four modals had their
 * own copy, and the copies had drifted -- the transfer dialog's secondary text
 * was 13px at 0.7 opacity, and the three dialogs that borrowed its shape wrote
 * the same two numbers in the other order under a different name. Nothing was
 * wrong with either, which is exactly the problem: a reader moving between
 * them could not tell whether a difference was deliberate.
 */

/** Secondary text. Everything that is not a heading, a value or an error. */
export const MUTED: CSSProperties = { fontSize: "13px", opacity: 0.7 };

/**
 * A stack of sections.
 *
 * 8px rather than 10: this gap is paid between every section of a dialog, so it
 * is one of the cheapest places to reclaim height without changing what is
 * shown.
 */
export const COLUMN: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
};
