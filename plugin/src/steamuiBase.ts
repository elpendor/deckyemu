/**
 * The plugin build's copy of src/steamui/base.ts: the Steam pieces the UI kit
 * is built on, as the loader's library finds them. Named exports only; see
 * steamui.ts.
 */

export {
  DialogButton,
  DialogButtonPrimary,
  DialogButtonSecondary,
  Focusable,
  GamepadButton,
  Navigation,
  showModal,
} from "@decky/ui";
export type { GamepadEvent, ShowModalResult } from "@decky/ui";
export type { FocusableProps } from "../../src/steamui/components";
