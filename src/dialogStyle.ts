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

/**
 * A bounded list, with a scrollbar that says it is one.
 *
 * Steam's CEF shows no scrollbar by default, so a list that scrolls looks
 * exactly like a list that ends -- and the only way to find out is to push a
 * stick at it. `overflow-y: auto` means the bar appears only when there is
 * something below the fold, which makes its presence the affordance.
 *
 * A class and a rule rather than an inline style, because `::-webkit-scrollbar`
 * is a pseudo-element and cannot be written inline. Scoped to the class, and
 * the modal that uses it renders `<style>{SCROLLER_CSS}</style>` in its own
 * tree -- the same arrangement as `DANGER_CSS`, for the same reason: a dialog
 * is not inside whichever panel opened it.
 *
 * `display: block` is not redundant, and neither is `!important` on every
 * declaration: Steam hides scrollbars globally, and the first version of this
 * rule reached the device, applied to the right element, and showed nothing --
 * a width alone does not undo a `display: none` that wins on specificity.
 * `scrollbar-width` is there for the same belt-and-braces reason; CEF honours
 * the standard property in newer builds and the pseudo-element in all of them.
 */
export const SCROLLER_CLASS = "deckyemu-scroller";

export const SCROLLER_CSS = `
.${SCROLLER_CLASS} {
  scrollbar-width: thin !important;
  scrollbar-color: rgba(255, 255, 255, 0.35) transparent !important;
}
.${SCROLLER_CLASS}::-webkit-scrollbar {
  display: block !important;
  width: 6px !important;
}
.${SCROLLER_CLASS}::-webkit-scrollbar-track {
  background: transparent !important;
}
.${SCROLLER_CLASS}::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.35) !important;
  border-radius: 3px !important;
  min-height: 24px !important;
}
`;

/**
 * A row in a `SCROLLER_CLASS` list, and the highlight that says it has focus.
 *
 * **Steam's own focus ring is drawn outside the element's box**, so a clipped
 * scroll container cannot contain it: the ring for the first and last rows
 * appears above and below the list, over whatever is there. `noFocusRing` on
 * the row turns it off, and this draws the highlight with a background and an
 * *inset* shadow instead -- inset paints within the element, and the element is
 * inside the clip, so nothing can escape it.
 *
 * A class of our own rather than Steam's `gpfocuswithin`: that one is Steam's
 * to define, and styling it here would reach every row in the dialog that
 * happens to carry it.
 */
export const SCROLLER_ROW_CLASS = "deckyemu-scroller-row";

export const SCROLLER_ROW_FOCUS_CLASS = "deckyemu-scroller-row-focus";

export const SCROLLER_ROW_CSS = `
.${SCROLLER_ROW_CLASS} {
  border-radius: 4px;
  padding: 4px 6px;
}
.${SCROLLER_ROW_CLASS}.${SCROLLER_ROW_FOCUS_CLASS} {
  background: rgba(255, 255, 255, 0.12);
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.55);
}
`;
