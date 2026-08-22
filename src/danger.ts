/**
 * Red for controls that destroy work.
 *
 * `ButtonItem` accepts no style prop -- it is Steam's own component, found by
 * signature at runtime -- so the colour has to reach the button it renders
 * through a class on a wrapper. Keeping ButtonItem rather than swapping in a
 * DialogButton preserves the description text and focus behaviour of every other
 * row beside it; only the colour changes.
 *
 * `!important` because Steam's own class sets the background and wins on
 * specificity otherwise. `gpfocus` is the class Steam puts on the focused
 * element under gamepad navigation.
 *
 * Shared rather than copied: it is used by "Remove all DeckyEmu games" and by
 * "Uninstall RetroArch", and two drifting copies of a colour that means "this
 * one is dangerous" would be worse than one import.
 */
export const DANGER_CLASS = "deckyemu-danger";

export const DANGER_CSS = `
.${DANGER_CLASS} button {
  background: rgba(176, 44, 44, 0.9) !important;
  color: #fff !important;
}
.${DANGER_CLASS} button:hover,
.${DANGER_CLASS} button:focus,
.${DANGER_CLASS} button.gpfocus,
.${DANGER_CLASS} .gpfocus button {
  background: rgb(214, 58, 58) !important;
}
.${DANGER_CLASS} button[disabled] {
  background: rgba(176, 44, 44, 0.45) !important;
}
`;

/**
 * The same red, for a paragraph rather than a button.
 *
 * `DANGER_CSS` styles `button` elements *inside* the class and nothing else, so
 * putting `DANGER_CLASS` on a div of text does nothing at all -- which is what
 * the import warning did for as long as it has existed. Inline, so it needs no
 * stylesheet injected into whichever modal happens to be rendering it: a
 * ConfirmModal opened from a panel is its own tree, and the `<style>` tag a
 * panel injects is not always in the document when the dialog is up.
 *
 * A left bar rather than red text, matching the paused-transfer notice: at this
 * size a block of coloured prose reads as decoration, and the bar makes it a
 * different kind of thing before any of it has been read.
 */
export const DANGER_TEXT = {
  padding: "8px 10px",
  borderLeft: "4px solid rgb(214, 58, 58)",
  borderRadius: "4px",
  background: "rgba(176, 44, 44, 0.15)",
};
