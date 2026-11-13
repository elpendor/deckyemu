/**
 * The kit's stylesheet: Steam's own values, measured from its rules on the
 * Deck (Nov 2026), under class names of ours. Steam's hashed class names
 * change with its builds; these never do.
 *
 * Global Steam classes that have not changed in years (DialogButton,
 * DialogHeader, GenericConfirmDialog...) are used as they are instead.
 */

const CSS = `
.dek-section { padding: 0 16px; margin: 0 0 24px; }
.dek-section-title {
  display: flex; padding: 0 0 8px; font-family: "Motiva Sans", Helvetica, sans-serif;
  font-size: 16px; font-weight: 600; line-height: 22px; letter-spacing: 0.5px;
  text-transform: uppercase; color: rgba(255, 255, 255, 0.7);
}
.dek-section-title > div { flex-grow: 1; }
.dek-row { --dek-gutter: 16px; }

/* Steam's Field has two looks. Away from Quick Access each row is a filled
   box with gaps between; in Quick Access ("classic") rows bleed to the panel
   edges and separators divide them. */
.dek-field {
  position: relative; display: flex; flex-direction: row; gap: 0 12px;
  border-radius: 2px; color: rgb(150, 150, 150); font-size: 16px;
  padding: 12px; background: rgb(35, 38, 46);
}
.dek-field + .dek-field, .dek-row + .dek-row > .dek-field { margin-top: 6px; }
.dek-field.dek-highlight.gpfocus, .dek-field.dek-highlight.gpfocuswithin {
  background: rgb(61, 68, 80); color: #fff; z-index: 1;
}
#QuickAccess-Menu .dek-field {
  background: none; padding: 10px var(--dek-gutter, 16px);
  margin: 0 calc(-1 * var(--dek-gutter, 16px));
}
#QuickAccess-Menu .dek-field.dek-highlight.gpfocus,
#QuickAccess-Menu .dek-field.dek-highlight.gpfocuswithin {
  background: rgb(61, 68, 80);
}
#QuickAccess-Menu .dek-field.dek-sep::after,
#QuickAccess-Menu .dek-field.dek-sep-thick::after {
  content: ""; position: absolute; left: var(--dek-gutter, 16px);
  right: var(--dek-gutter, 16px); background: rgba(255, 255, 255, 0.1);
}
#QuickAccess-Menu .dek-field.dek-sep::after { bottom: -0.5px; height: 1px; }
#QuickAccess-Menu .dek-field.dek-sep-thick::after {
  bottom: -0.75px; height: 1.5px;
}
.dek-field.dek-highlight.gpfocus::after,
.dek-field.dek-highlight.gpfocuswithin::after { display: none; }
.dek-field.dek-disabled, .dek-field.dek-disabled .dek-label,
.dek-field.dek-disabled .dek-desc { color: rgb(103, 112, 123); }
.dek-field-body { flex-grow: 1; min-width: 0; }
.dek-label-row {
  display: flex; flex-direction: row; column-gap: 10px;
  justify-content: flex-end; align-items: center;
}
.dek-field.dek-below .dek-label-row { margin-bottom: 6px; }
.dek-label-row { column-gap: 12px; }
#QuickAccess-Menu .dek-label-row { column-gap: 10px; }
.dek-label {
  flex-grow: 1; display: flex; flex-direction: row; max-width: 100%;
  word-break: break-word; font-size: 16px; line-height: 20px; color: rgb(220, 222, 223);
}
.dek-label > svg { position: relative; top: 2px; margin-inline-end: 12px; }
.dek-field.dek-highlight.gpfocus .dek-label,
.dek-field.dek-highlight.gpfocuswithin .dek-label { color: #fff; }
.dek-children { display: flex; flex-flow: row; }
.dek-children > div { flex-grow: 1; min-width: 0; }
.dek-field { align-items: flex-start; }
#QuickAccess-Menu .dek-field { align-items: center; }
.dek-inline-children { flex-shrink: 0; min-width: 0; max-width: 50%; display: flex; }
.dek-field:not(:has(.dek-desc)) { align-items: center; }
.dek-desc {
  margin-top: 4px; font-size: 12px; line-height: 16px; color: rgb(184, 188, 191);
}
.dek-children + .dek-desc { margin-top: 6px; }
.dek-field.dek-highlight.gpfocus .dek-desc,
.dek-field.dek-highlight.gpfocuswithin .dek-desc { color: rgb(220, 222, 223); }
.dek-children .DialogButton { width: 100%; min-width: 160px; padding: 10px 24px; }
/* Steam's own: a control scrolled into view stops 55px above the bottom, so
   the button bar does not cover it. */
.dek-field.Focusable, .dek-field :is(.Focusable, input, textarea, button),
.dek-page-content :is(.Focusable, input, textarea, button),
.dek-modal :is(.Focusable, input, textarea, button) { scroll-margin: 20px 0 55px; }

.dek-spinner {
  display: inline-block; aspect-ratio: 1; height: 24px; box-sizing: border-box;
  border: 3px solid rgba(255, 255, 255, 0.2); border-top-color: #fff;
  border-radius: 50%; animation: dek-spin 0.9s linear infinite;
}
@keyframes dek-spin { to { transform: rotate(360deg); } }

.dek-modal {
  display: flex; position: absolute; left: 0; right: 0;
  top: var(--basicui-header-height, 0px);
  bottom: var(--gamepadui-current-footer-height, 0px);
  overflow: hidden auto; scroll-padding: 80px 0; flex-direction: column; padding: 24px;
}
.dek-modal.gpfocus { outline: none; }
.dek-modal-backdrop { position: absolute; inset: 0; }
.dek-modal > .DialogContent {
  margin: auto; background-color: rgb(14, 20, 27); border: 2px solid rgb(35, 38, 46);
  padding: calc(12px + 2.25vh) 2.8vw; width: 660px; box-sizing: border-box;
  position: relative; animation: dek-fade 0.5s cubic-bezier(0.17, 0.45, 0.14, 0.83);
}
/* Fixed, not sized to content: a tabbed dialog would change width per tab.
   77vw is what Steam's measured on the Deck. */
.dek-modal > .DialogContent.DialogContentFullSize { width: 77vw; }
.dek-modal .DialogContentFullSize .DialogContent_InnerWidth { max-width: calc(88vw - 48px); }
@keyframes dek-fade { from { opacity: 0; } to { opacity: 1; } }

.dek-tabs { display: flex; flex-direction: column; min-height: 0; flex: 1; }
.dek-tab-bar {
  display: flex; flex-direction: row; align-items: center; height: 58px;
  padding: 0 24px; flex-shrink: 0;
}
.dek-bumper { width: 32px; height: 32px; display: flex; }
.dek-bumper img { width: 100%; height: 100%; }
/* "safe": centred while the tabs fit; past that, plain center pushed the
   overflow off the left edge, where no scroll reaches, under the L1 glyph. */
.dek-tab-list {
  flex: 1; display: flex; flex-direction: row; justify-content: safe center; gap: 8px;
  overflow: hidden; position: relative; margin: 0 8px;
}
.dek-tab {
  display: flex; align-items: center; padding: 6px 16px; border-radius: 64px;
  font-size: 12px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase;
  color: rgb(220, 222, 223); white-space: nowrap; cursor: pointer;
}
.dek-tab.dek-active { color: #fff; background: rgba(255, 255, 255, 0.15); }
.dek-tab.gpfocus { color: #fff; background: rgba(255, 255, 255, 0.3); outline: none; }
.dek-tab-content { flex: 1; min-height: 0; overflow: hidden auto; }
.dek-slide-right { animation: dek-slide-right 0.25s cubic-bezier(0.17, 0.45, 0.14, 0.83); }
.dek-slide-left { animation: dek-slide-left 0.25s cubic-bezier(0.17, 0.45, 0.14, 0.83); }
@keyframes dek-slide-right { from { opacity: 0; transform: translateX(48px); } }
@keyframes dek-slide-left { from { opacity: 0; transform: translateX(-48px); } }

.dek-pages { display: flex; flex-direction: row; height: 100%; flex-grow: 1; background: rgb(14, 20, 27); }
.dek-page-list {
  background: rgb(43, 45, 51); flex: 1 1 0%; min-width: 240px; max-width: 20%;
  display: flex; flex-direction: column; position: relative;
  padding-bottom: var(--gamepadui-current-footer-height, 0px);
}
.dek-page-items {
  line-height: 16px; white-space: nowrap; overflow: hidden auto;
  padding: var(--basicui-header-height, 0px) 0 16px;
  flex: 1 1 auto; display: flex; flex-direction: column;
}
.dek-page-item {
  font-family: "Motiva Sans", Helvetica, sans-serif; font-size: 16px; line-height: 22px;
  padding: 10px calc(12px + 1.4vw); color: rgb(184, 188, 191); cursor: pointer;
  border-left: 2px solid transparent; scroll-margin: 2.5em 0;
}
.dek-page-item > div { display: flex; flex-direction: row; transition: transform 0.32s cubic-bezier(0.17, 0.45, 0.14, 0.83); transform-origin: 12% 50%; }
.dek-page-item.dek-active {
  color: #fff; background: linear-gradient(90deg, rgba(26, 159, 255, 0.22) 0%, rgba(26, 159, 255, 0) 100%);
}
.dek-page-item.dek-active > div, .dek-page-item.gpfocus > div { transform: scale(1.1); }
.dek-page-item.gpfocus {
  outline: none; color: #fff; border-left-color: rgb(26, 159, 255);
  background: linear-gradient(90deg, rgba(26, 159, 255, 0.4) 0%, rgba(26, 159, 255, 0) 100%);
}
.dek-page-icon { height: 20px; width: 20px; margin: auto 16px auto 0; }
.dek-page-icon svg { width: 100%; height: 100%; }
.dek-page-title { flex-grow: 1; margin: auto 0; }
.dek-page-content {
  flex: 1; min-width: 0; overflow: hidden auto; background: rgb(26, 28, 33);
  padding-bottom: var(--gamepadui-current-footer-height, 0px);
  /* For the browser's own focus scrolling, which a text field gets and which
     ignores scroll-margin. */
  scroll-padding: 20px 0 55px;
}
.dek-page-body.DialogContent { background: none; }
.dek-page-body { padding: calc(12px + 2.25vh) 2.8vw; padding-top: calc(12px + 2.25vh + var(--basicui-header-height, 0px)); }

.dek-option-list { display: flex; flex-direction: column; max-height: 60vh; overflow: hidden auto; }
.dek-option-group { padding: 12px 16px 4px; font-size: 12px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; color: rgba(255, 255, 255, 0.7); }
.dek-dropdown { display: flex; min-width: 0; max-width: 100%; }
.dek-dropdown .DialogButton {
  display: flex; justify-content: space-between; align-items: center; text-align: start;
  gap: 8px; min-width: 0; max-width: 100%; padding: 10px 16px;
}
.dek-dropdown .DialogButton > span:last-child { flex-shrink: 0; }
.dek-dropdown .DialogButton > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
`;

const ID = "deckyemu-ui-kit";

function ensure(doc: Document): void {
  // Replaced when it differs: Steam's documents outlive an update of ours,
  // and the sheet the previous version put there would otherwise stay.
  const found = doc.getElementById(ID);
  if (found) {
    if (found.textContent !== CSS) found.textContent = CSS;
    return;
  }
  const style = doc.createElement("style");
  style.id = ID;
  style.textContent = CSS;
  (doc.head ?? doc.documentElement).appendChild(style);
}

/**
 * A ref callback that puts the stylesheet into the document the element is in.
 * Quick Access is a separate window with a document of its own.
 */
export function styled(element: Element | null): void {
  if (element?.ownerDocument) ensure(element.ownerDocument);
}

/** For tests and for anything rendered before a ref fires. */
export const KIT_CSS = CSS;
