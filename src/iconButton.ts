import type { CSSProperties } from "react";

/**
 * The shape of every icon-only button in the plugin.
 *
 * Written down because it was previously copied inline at thirty-four call
 * sites across ten files, and both of the things it now states were wrong
 * everywhere at once.
 *
 * **The icon has to be centred by the button, not by a line box.** A
 * `react-icons` glyph is an inline SVG, so it sits on the text baseline;
 * `DialogButton` centres the line box it sits in, which left every icon in the
 * plugin exactly 3px high. Measured, not guessed: the plate ran 438-485 and the
 * glyph 447-470. Flex centring is what actually centres a glyph.
 *
 * **And the height has to be stated.** Before flex centring, the button was 48px
 * tall by accident -- the line box was providing the height. Centring properly
 * removed that and the button fell to 42px, which is under every published
 * minimum for something a finger has to hit: 44 in Apple's guidance and in
 * WCAG's AAA target size, 48 in Material's. On this screen -- 1280x800 across
 * about six and a quarter inches, so roughly 204ppi -- 48px is about 6mm, which
 * is a floor rather than a generous size.
 *
 * That matters less here than on a phone, because the panel is driven by a
 * controller. It does not stop mattering: the Quick Access panel takes touch,
 * and on the added-games rows these four buttons are the most tapped controls
 * in the plugin.
 */
export const ICON_BUTTON: CSSProperties = {
  minWidth: "auto",
  // `height` with `border-box`, not `minHeight`. The first attempt at this said
  // `minHeight: 48px`, which sizes the *content* box -- the padding and border
  // then sat outside it and the button came out 72px, measured. Stating the
  // outer size keeps the number in this file the number on the screen, which is
  // also the number the touch-target guidance in the docstring is about.
  boxSizing: "border-box",
  // **Square, and the same square Steam uses.** The gear and controller buttons
  // on a game's own page are 48x48 with a 24x24 glyph inside, read off the live
  // computed style. Ours were 40x48 with a 16px glyph: right height, too narrow,
  // and a smaller icon than everything beside them.
  //
  // Width stated rather than left to `auto` and padding, which is what made
  // them narrow -- and made them *different widths from each other*, since the
  // play triangle and the pencil are not the same width.
  height: "48px",
  width: "48px",
  // The glyph. `react-icons` renders at `1em`, so the button's font size is
  // what sizes it.
  //
  // **20 rather than 24, and the difference is ink and not box.** Steam's own
  // icon element is 24x24, but its gear only inks about 20 of that. A Font
  // Awesome glyph fills its viewBox far more completely -- the play triangle
  // spans the full 24 -- so matching Steam's box size overshot its ink by a
  // fifth and read as noticeably bigger beside it. Measured: Steam's glyph is
  // 42% of its button, ours was 51%.
  fontSize: "20px",
  padding: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

/**
 * A compact button holding **text** rather than an icon -- "Cancel" and its
 * like. Same height and centring, but the width has to follow the words, so it
 * takes neither the square nor the icon-sized font.
 *
 * Named for where it is used rather than for what it is, which is a wart: it
 * sits beside icon buttons in the same rows.
 */
export const ICON_BUTTON_WIDE: CSSProperties = {
  ...ICON_BUTTON,
  width: "auto",
  minWidth: "auto",
  fontSize: "inherit",
  padding: "6px 16px",
};
