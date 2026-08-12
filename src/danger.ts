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
